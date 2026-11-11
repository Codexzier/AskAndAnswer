"""Aufnahme (max. 10 Minuten) und Transkription.

Waehrend der Aufnahme wird das Audio als WAV gespeichert und gleichzeitig von
Vosk in Echtzeit erkannt (Live-Text auf dem TFT). Nach dem Ende wird das
Transkript zusammengesetzt und als .txt neben der WAV-Datei gespeichert.

Optional (AOUDA_TRANSCRIBE=whisper) wird die WAV-Datei nach der Aufnahme mit
faster-whisper ein zweites Mal transkribiert. Das ist genauer, dauert auf dem
UNO Q aber ungefaehr so lange wie die Aufnahme selbst (Modell "base").
"""

from __future__ import annotations

import logging
import wave
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger("aouda.recorder")


class Recording:
    """Schreibt 16-kHz-Mono-Audio in eine WAV-Datei und sammelt den Live-Text."""

    def __init__(self, directory: Path, sample_rate: int, max_seconds: float):
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.wav_path = directory / f"aufnahme_{stamp}.wav"
        self.txt_path = directory / f"aufnahme_{stamp}.txt"
        self.sample_rate = sample_rate
        self.max_samples = int(max_seconds * sample_rate)
        self.samples = 0
        self.sentences: list[str] = []
        self._wav = wave.open(str(self.wav_path), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)

    @property
    def seconds(self) -> float:
        return self.samples / self.sample_rate

    @property
    def full(self) -> bool:
        return self.samples >= self.max_samples

    @property
    def fraction(self) -> float:
        return min(1.0, self.samples / self.max_samples) if self.max_samples else 1.0

    def write(self, pcm16: np.ndarray) -> np.ndarray:
        """Schreibt Audio bis zum Zeitlimit; liefert den tatsaechlich geschriebenen Teil."""
        room = self.max_samples - self.samples
        if room <= 0:
            return pcm16[:0]
        part = pcm16[:room]
        self._wav.writeframes(part.astype("<i2").tobytes())
        self.samples += len(part)
        return part

    def add_sentence(self, text: str) -> None:
        text = text.strip()
        if text:
            self.sentences.append(text)

    @property
    def live_text(self) -> str:
        return format_transcript(self.sentences)

    def close(self) -> None:
        try:
            self._wav.close()
        except Exception:
            pass

    def save_text(self, text: str) -> None:
        header = (f"Aufnahme vom {datetime.now():%d.%m.%Y %H:%M}, "
                  f"Dauer {format_duration(self.seconds)}\n\n")
        self.txt_path.write_text(header + text + "\n", encoding="utf-8")


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def format_transcript(sentences: list[str]) -> str:
    """Saetze von Vosk (klein, ohne Satzzeichen) lesbar zusammensetzen."""
    out = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        s = s[0].upper() + s[1:]
        if s[-1] not in ".!?":
            s += "."
        out.append(s)
    return " ".join(out)


def transcribe_whisper(wav_path: Path, model_name: str, models_dir: Path,
                       progress: Callable[[float, str], None] | None = None) -> str:
    """Transkribiert eine WAV-Datei mit faster-whisper (CPU, int8)."""
    from faster_whisper import WhisperModel  # optionales Paket

    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=4,
                         download_root=str(models_dir / "whisper"))
    segments, info = model.transcribe(str(wav_path), language="de", beam_size=1, vad_filter=True)
    duration = info.duration or 1.0
    texts = []
    for segment in segments:
        texts.append(segment.text.strip())
        if progress:
            progress(min(1.0, segment.end / duration), " ".join(texts))
    return " ".join(t for t in texts if t)
