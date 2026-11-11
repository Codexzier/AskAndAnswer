"""Offline-Spracherkennung mit Vosk (Echtzeit, deutsches Modell).

Vosk erkennt Sprache waehrend sie gesprochen wird: vorlaeufige Ergebnisse
("partial") kommen nach wenigen hundert Millisekunden, endgueltige Saetze
("final") nach einer kurzen Sprechpause. Das kleine deutsche Modell
(vosk-model-small-de, ca. 45 MB) braucht nur ca. 200-300 MB RAM und laeuft
auf einem Kern des UNO Q schneller als Echtzeit.
"""

from __future__ import annotations

import json
import logging
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from commands import COMMAND_PHRASES

log = logging.getLogger("aouda.speech")


def ensure_vosk_model(models_dir: Path, name: str, base_url: str,
                      progress: Callable[[str], None] | None = None) -> Path:
    """Laedt das Vosk-Modell beim ersten Start herunter und entpackt es."""
    target = models_dir / name
    if (target / "am").exists() or (target / "conf").exists():
        return target

    models_dir.mkdir(parents=True, exist_ok=True)
    url = base_url.rstrip("/") + "/" + name + ".zip"
    archive = models_dir / (name + ".zip.part")
    log.info("Lade Vosk-Modell %s", url)

    request = urllib.request.Request(url, headers={"User-Agent": "aouda-uno-q/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response, open(archive, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        last_percent = -1
        while True:
            block = response.read(256 * 1024)
            if not block:
                break
            out.write(block)
            done += len(block)
            if progress and total:
                percent = done * 100 // total
                if percent != last_percent and percent % 5 == 0:
                    progress(f"Lade Sprachmodell {percent}%")
                    last_percent = percent

    if progress:
        progress("Entpacke Sprachmodell...")
    tmp_dir = models_dir / (name + ".tmp")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(tmp_dir)
    # Das Archiv enthaelt einen Ordner mit dem Modellnamen
    inner = tmp_dir / name
    shutil.rmtree(target, ignore_errors=True)
    (inner if inner.exists() else tmp_dir).rename(target)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    archive.unlink(missing_ok=True)
    return target


@dataclass
class RecognitionEvent:
    final: str | None = None        # abgeschlossener Satz
    partial: str | None = None      # vorlaeufiger Text (kann sich noch aendern)
    confidence: float = 1.0         # mittlere Wort-Konfidenz des finalen Satzes


class Recognizer:
    """Duenne Huelle um vosk.KaldiRecognizer."""

    def __init__(self, model, sample_rate: int, grammar: list[str] | None = None):
        import vosk

        if grammar:
            self._rec = vosk.KaldiRecognizer(model, sample_rate, json.dumps(grammar, ensure_ascii=False))
        else:
            self._rec = vosk.KaldiRecognizer(model, sample_rate)
        self._rec.SetWords(True)
        self._last_partial = ""

    def feed(self, pcm16: bytes) -> RecognitionEvent | None:
        """Audio (16 bit mono) einspeisen; liefert ein Ereignis, wenn sich etwas aendert."""
        if self._rec.AcceptWaveform(pcm16):
            return self._final_event(self._rec.Result())
        partial = json.loads(self._rec.PartialResult()).get("partial", "")
        if partial != self._last_partial:
            self._last_partial = partial
            return RecognitionEvent(partial=partial)
        return None

    def flush(self) -> RecognitionEvent:
        """Restliches Audio auswerten (z. B. am Ende einer Aufnahme)."""
        return self._final_event(self._rec.FinalResult())

    def reset(self) -> None:
        self._rec.Reset()
        self._last_partial = ""

    def _final_event(self, raw: str) -> RecognitionEvent:
        self._last_partial = ""
        data = json.loads(raw)
        text = data.get("text", "").replace("[unk]", "").strip()
        words = [w for w in data.get("result", []) if w.get("word") != "[unk]"]
        conf = sum(w.get("conf", 1.0) for w in words) / len(words) if words else 0.0
        return RecognitionEvent(final=text, confidence=conf)


class SpeechEngine:
    """Laedt das Vosk-Modell und erzeugt Erkenner."""

    def __init__(self, model_path: Path, sample_rate: int):
        import vosk

        vosk.SetLogLevel(-1)
        self.sample_rate = sample_rate
        self.model = vosk.Model(str(model_path))

    def knows(self, word: str) -> bool:
        try:
            return self.model.vosk_model_find_word(word) >= 0
        except Exception:
            return False

    def free(self) -> Recognizer:
        return Recognizer(self.model, self.sample_rate)

    def wake_grammar(self, wake_words: list[str]) -> list[str]:
        """Grammatik aus Weckwort-Schreibweisen x Befehlssaetzen.

        Es werden nur Woerter verwendet, die das Modell kennt; unbekannte
        Woerter wuerden von Vosk sonst einfach verworfen.
        """
        wake = []
        for spelling in wake_words:
            words = normalize_vosk(spelling).split()
            if words and all(self.knows(w) for w in words):
                wake.append(" ".join(words))
        phrases_ok = []
        for phrases in COMMAND_PHRASES.values():
            for phrase in phrases:
                words = normalize_vosk(phrase).split()
                if all(self.knows(w) for w in words):
                    phrases_ok.append(" ".join(words))
        grammar = sorted({f"{w} {p}" for w in wake for p in phrases_ok})
        log.info("Weckwort-Varianten im Wortschatz: %s", ", ".join(wake) or "-")
        if not grammar:
            return []
        return grammar + ["[unk]"]

    def grammar_recognizer(self, grammar: list[str]) -> Recognizer:
        return Recognizer(self.model, self.sample_rate, grammar)


def normalize_vosk(text: str) -> str:
    """Wie commands.normalize, aber mit Umlauten (Vosk-Wortschatz nutzt Umlaute)."""
    text = text.lower()
    keep = "".join(c if (c.isalpha() or c == " ") else " " for c in text)
    return " ".join(keep.split())


def to_pcm16_mono(chunk: np.ndarray, src_rate: int, channels: int, dst_rate: int = 16000) -> np.ndarray:
    """Wandelt einen Mikrofon-Block in 16 kHz / mono / int16 um."""
    data = np.asarray(chunk)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if data.dtype.kind == "f":
        data = np.clip(data, -1.0, 1.0) * 32767.0
    elif data.dtype == np.int32:
        data = data / 65536.0
    if src_rate != dst_rate and len(data) > 1:
        count = max(1, int(round(len(data) * dst_rate / src_rate)))
        positions = np.linspace(0, len(data) - 1, count)
        data = np.interp(positions, np.arange(len(data)), data.astype(np.float32))
    return np.asarray(data).astype(np.int16, copy=False)

