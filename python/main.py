"""AOUDA - Sprachassistent fuer den Arduino UNO Q.

Sprachbefehle:
  "AOUDA, ich habe eine Frage"  -> Frage stellen, die lokale KI antwortet
                                   (bei Bedarf mit Internetsuche)
  "AOUDA, starte Aufnahme"      -> Aufnahme (max. 10 Minuten) mit Live-Text,
                                   danach Transkript
  "AOUDA, stoppe Aufnahme"      -> Aufnahme vorzeitig beenden

Alle Texte erscheinen auf dem 1.8" TFT des Shields (gesteuert vom Sketch).
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from arduino.app_bricks.llm import LargeLanguageModel
from arduino.app_peripherals.microphone import Microphone
from arduino.app_utils import App, Bridge

import display as tft
from assistant import SYSTEM_PROMPT, Assistant
from commands import QUESTION, RECORD_START, RECORD_STOP, find_command
from config import Config
from recorder import Recording, format_duration, transcribe_whisper
from speech import Recognizer, SpeechEngine, ensure_vosk_model, to_pcm16_mono

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
log = logging.getLogger("aouda")

IDLE = "idle"
QUESTION_LISTEN = "question"
BUSY = "busy"
RECORDING = "recording"

HINT = "Sag: AOUDA, ..."

cfg = Config()
display = tft.Display(Bridge)
llm = LargeLanguageModel(
    system_prompt=SYSTEM_PROMPT,
    temperature=cfg.llm_temperature,
    max_tokens=cfg.llm_max_tokens,
    timeout=cfg.llm_timeout_s,
)
assistant = Assistant(
    llm,
    web_enabled=cfg.web_search,
    web_results=cfg.web_results,
    web_region=cfg.web_region,
    web_timeout=cfg.web_timeout_s,
)


class Aouda:
    def __init__(self, config: Config):
        self.cfg = config
        self.state = IDLE
        self.ready = False
        self.engine: SpeechEngine | None = None
        self.wake_rec: Recognizer | None = None
        self.free_rec: Recognizer | None = None
        self.grammar_mode = False
        self.mic = None
        self._reset_wake = False
        self._screen = ""

        # Frage
        self._q_start = 0.0
        self._q_last_voice = 0.0
        self._q_final = ""
        self._q_partial = ""
        self._q_draw = 0.0

        # Aufnahme
        self.recording: Recording | None = None
        self._rec_partial = ""
        self._rec_draw = 0.0
        self._rec_second = -1

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------
    def setup(self) -> None:
        display.splash("AOUDA", "Sprachassistent", "Starte...")
        info = display.ping()
        log.info("TFT: %s", info or "nicht erreichbar (Sketch geladen?)")

        model_path = ensure_vosk_model(self.cfg.models_dir, self.cfg.vosk_model, self.cfg.vosk_url,
                                       progress=display.status)
        display.status("Lade Sprachmodell...")
        self.engine = SpeechEngine(model_path, self.cfg.sample_rate)
        self.free_rec = self.engine.free()

        grammar = []
        if self.cfg.wake_mode == "grammar":
            grammar = self.engine.wake_grammar(self.cfg.wake_words)
            if not grammar:
                log.warning("Keine Weckwort-Variante im Wortschatz -> freie Erkennung")
        if grammar:
            self.wake_rec = self.engine.grammar_recognizer(grammar)
            self.grammar_mode = True
        else:
            self.wake_rec = self.engine.free()
            self.grammar_mode = False
        log.info("Weckwort-Modus: %s", "Grammatik" if self.grammar_mode else "frei")

        display.status("Starte Mikrofon...")
        self.mic = Microphone(
            device=self.cfg.mic_selector(),
            sample_rate=self.cfg.sample_rate,
            channels=Microphone.CHANNELS_MONO,
            format=np.int16,
            buffer_size=Microphone.BUFFER_SIZE_BALANCED,
        )
        self.ready = True

    # ------------------------------------------------------------------
    # Hauptschleife
    # ------------------------------------------------------------------
    def run_once(self) -> None:
        """Wird von App.run() immer wieder aufgerufen."""
        try:
            if not self.ready:
                self.setup()
            if not self.mic.is_started():
                self.mic.start()
                log.info("Mikrofon: %s, %d Hz, %d Kanal/Kanaele",
                         self.mic.name, self.mic.sample_rate, self.mic.channels)
            self.show_idle()
            for chunk in self.mic.stream():
                pcm = to_pcm16_mono(chunk, self.mic.sample_rate, self.mic.channels, self.cfg.sample_rate)
                self.process(pcm)
        except Exception as exc:
            log.exception("Fehler in der Hauptschleife")
            display.new_screen("Fehler", tft.RED, "Neustart in 5 s", tft.RED)
            display.text(str(exc), tft.WHITE, tail=False)
            if self.mic is not None:
                try:
                    self.mic.stop()
                except Exception:
                    pass
            time.sleep(5)

    def process(self, pcm: np.ndarray) -> None:
        if self.state == IDLE:
            self.handle_idle(pcm)
        elif self.state == QUESTION_LISTEN:
            self.handle_question(pcm)
        elif self.state == RECORDING:
            self.handle_recording(pcm)
        # BUSY: Audio verwerfen, waehrend die KI antwortet / transkribiert wird

    # ------------------------------------------------------------------
    # Bereit: auf "AOUDA, ..." warten
    # ------------------------------------------------------------------
    def show_idle(self, footer: str = "") -> None:
        self._screen = "idle"
        display.new_screen("AOUDA ist bereit", tft.GREEN, footer or "Warte auf Weckwort", tft.GRAY)
        display.lines([
            "Sage:",
            "",
            "AOUDA, ich habe eine",
            "       Frage",
            "",
            "AOUDA, starte Aufnahme",
            "",
            "(Aufnahme beenden:",
            " AOUDA, stoppe Aufnahme)",
        ], tft.WHITE, [tft.GRAY, tft.WHITE, tft.CYAN, tft.CYAN, tft.WHITE, tft.ORANGE,
                       tft.WHITE, tft.GRAY, tft.GRAY])

    def handle_idle(self, pcm: np.ndarray) -> None:
        if self._reset_wake:
            self.wake_rec.reset()
            self._reset_wake = False
        event = self.wake_rec.feed(pcm.tobytes())
        if event is None or not event.final:
            return

        text = event.final
        match = find_command(text, [QUESTION, RECORD_START, RECORD_STOP],
                             require_wake=self.cfg.wake_required,
                             threshold=self.cfg.match_threshold,
                             wake_spellings=self.cfg.wake_words)
        log.info("Gehoert: '%s' (Konfidenz %.2f) -> %s", text, event.confidence,
                 match.command if match else "-")

        if match and self.grammar_mode and event.confidence < self.cfg.min_confidence:
            log.info("Konfidenz zu niedrig, ignoriert")
            match = None

        if not match:
            if self._screen == "idle":
                display.footer(f"? {text}", tft.DARKGRAY)
            return

        self.wake_rec.reset()
        if match.command == QUESTION:
            words = match.after.split()
            if not self.grammar_mode and len(words) >= 3:
                self.ask(match.after)    # Frage direkt im selben Satz gestellt
            else:
                self.start_question()
        elif match.command == RECORD_START:
            self.start_recording()
        else:
            display.footer("Keine Aufnahme aktiv", tft.ORANGE)

    # ------------------------------------------------------------------
    # Frage
    # ------------------------------------------------------------------
    def start_question(self) -> None:
        self.state = QUESTION_LISTEN
        self._screen = "question"
        self.free_rec.reset()
        now = time.monotonic()
        self._q_start = now
        self._q_last_voice = now
        self._q_final = ""
        self._q_partial = ""
        display.new_screen("Deine Frage?", tft.CYAN, "Ich höre zu...", tft.CYAN)
        display.lines(["Stelle jetzt deine Frage."], tft.GRAY)

    def handle_question(self, pcm: np.ndarray) -> None:
        now = time.monotonic()
        event = self.free_rec.feed(pcm.tobytes())
        if event is not None:
            if event.final is not None:
                if event.final:
                    self._q_final = (self._q_final + " " + event.final).strip()
                    self._q_last_voice = now
                self._q_partial = ""
            elif event.partial is not None:
                if event.partial and event.partial != self._q_partial:
                    self._q_last_voice = now
                self._q_partial = event.partial

        if (self._q_final or self._q_partial) and now - self._q_draw > 0.25:
            display.live(self._q_final, self._q_partial)
            self._q_draw = now

        has_text = bool(self._q_final or self._q_partial)
        if not has_text and now - self._q_start > self.cfg.question_timeout_s:
            self.state = IDLE
            self._reset_wake = True
            self.show_idle("Keine Frage gehört")
            return

        if has_text and (now - self._q_last_voice > self.cfg.question_pause_s
                         or now - self._q_start > self.cfg.question_max_s):
            rest = self.free_rec.flush()
            question = (self._q_final + " " + (rest.final or "")).strip()
            if not question:
                question = self._q_partial
            self.ask(question)

    def ask(self, question: str) -> None:
        self.state = BUSY
        self._screen = "answer"
        threading.Thread(target=self._answer_worker, args=(question,), daemon=True).start()

    def _answer_worker(self, question: str) -> None:
        question = question.strip()
        if question:
            question = question[0].upper() + question[1:] + ("" if question.endswith("?") else "?")
        log.info("Frage: %s", question)
        display.new_screen("Frage", tft.CYAN, "Denke nach...", tft.YELLOW)
        display.text(question, tft.CYAN, tail=False)

        answer_started = [False]

        def on_status(status: str) -> None:
            display.footer(status, tft.YELLOW)

        def on_partial(text: str) -> None:
            if not answer_started[0]:
                answer_started[0] = True
                display.header("Antwort", tft.GREEN)
            display.text(text, tft.WHITE, tail=True)

        try:
            answer = assistant.answer(question, on_status=on_status, on_partial=on_partial)
        except Exception as exc:
            log.exception("KI-Chat fehlgeschlagen")
            display.header("Fehler", tft.RED)
            display.text(f"Die KI ist nicht erreichbar: {exc}", tft.WHITE, tail=False)
            display.footer(HINT, tft.GRAY)
            self._back_to_idle()
            return

        log.info("Antwort (%.1f s%s): %s", answer.seconds,
                 ", Web: " + ", ".join(answer.sources) if answer.searched else "", answer.text)
        display.header("Antwort (Web)" if answer.searched else "Antwort", tft.GREEN)
        footer = ("Quelle: " + answer.sources[0]) if answer.sources else HINT
        self._back_to_idle()
        text = answer.text or "Darauf habe ich leider keine Antwort."
        display.show_paged(text, tft.WHITE, self.cfg.page_seconds, footer, tft.GRAY)

    def _back_to_idle(self) -> None:
        self._reset_wake = True
        self.state = IDLE

    # ------------------------------------------------------------------
    # Aufnahme
    # ------------------------------------------------------------------
    def start_recording(self) -> None:
        self.recording = Recording(self.cfg.recordings_dir, self.cfg.sample_rate, self.cfg.record_max_s)
        self.free_rec.reset()
        self._rec_partial = ""
        self._rec_draw = 0.0
        self._rec_second = -1
        self.state = RECORDING
        self._screen = "recording"
        log.info("Aufnahme gestartet: %s", self.recording.wav_path)
        display.new_screen(self._rec_title(), tft.RED, "Stopp: AOUDA, stoppe Aufn.", tft.ORANGE)
        display.lines(["Aufnahme läuft..."], tft.GRAY)

    def _rec_title(self) -> str:
        r = self.recording
        return f"REC {format_duration(r.seconds)} / {format_duration(r.max_samples / r.sample_rate)}"

    def handle_recording(self, pcm: np.ndarray) -> None:
        rec = self.recording
        part = rec.write(pcm)
        now = time.monotonic()

        if len(part):
            event = self.free_rec.feed(part.tobytes())
            if event is not None:
                text = event.final if event.final is not None else event.partial
                match = find_command(text or "", [RECORD_STOP],
                                     require_wake=self.cfg.wake_required,
                                     threshold=self.cfg.match_threshold,
                                     wake_spellings=self.cfg.wake_words)
                if match:
                    if event.final is None:
                        self.free_rec.flush()   # Rest des Stopp-Satzes verwerfen
                    rec.add_sentence(match.before)
                    self._rec_partial = ""
                    self.stop_recording("Aufnahme beendet")
                    return
                if event.final is not None:
                    rec.add_sentence(event.final)
                    self._rec_partial = ""
                else:
                    self._rec_partial = event.partial or ""

        second = int(rec.seconds)
        if second != self._rec_second:
            self._rec_second = second
            display.header(self._rec_title(), tft.RED, tft.WHITE)
            display.progress(rec.fraction, tft.RED)
        if now - self._rec_draw > 0.3:
            self._rec_draw = now
            if rec.sentences or self._rec_partial:
                display.live(rec.live_text, self._rec_partial)

        if rec.full:
            rest = self.free_rec.flush()
            rec.add_sentence(rest.final or "")
            self.stop_recording("10 Minuten erreicht")

    def stop_recording(self, reason: str) -> None:
        rec = self.recording
        rec.close()
        self.state = BUSY
        self._screen = "transcript"
        log.info("%s nach %s: %s", reason, format_duration(rec.seconds), rec.wav_path)
        threading.Thread(target=self._transcribe_worker, args=(rec, reason), daemon=True).start()

    def _transcribe_worker(self, rec: Recording, reason: str) -> None:
        duration = format_duration(rec.seconds)
        text = rec.live_text
        if self.cfg.transcribe_engine.lower() == "whisper":
            display.new_screen(f"Transkribiere {duration}", tft.MAGENTA, reason, tft.GRAY)
            display.lines(["Whisper läuft...", "", "Das dauert etwa so lange", "wie die Aufnahme."], tft.GRAY)

            def progress(fraction: float, partial: str) -> None:
                display.progress(fraction, tft.MAGENTA)
                display.footer(f"Transkription {int(fraction * 100)}%", tft.MAGENTA)
                display.text(partial, tft.WHITE, tail=True)

            try:
                text = transcribe_whisper(rec.wav_path, self.cfg.whisper_model, self.cfg.models_dir, progress)
            except ImportError:
                log.warning("faster-whisper ist nicht installiert -> Vosk-Transkript")
            except Exception:
                log.exception("Whisper fehlgeschlagen -> Vosk-Transkript")

        text = text.strip() or "(Kein Text erkannt)"
        try:
            rec.save_text(text)
            saved = "Datei " + rec.txt_path.stem.replace("aufnahme_", "")
            log.info("Transkript gespeichert: %s", rec.txt_path)
        except Exception:
            log.exception("Transkript konnte nicht gespeichert werden")
            saved = "nicht gespeichert!"

        display.new_screen(f"Transkript {duration}", tft.MAGENTA, saved, tft.GRAY)
        self._back_to_idle()
        display.show_paged(text, tft.WHITE, self.cfg.page_seconds, HINT, tft.GRAY)


aouda = Aouda(cfg)
App.run(user_loop=aouda.run_once)
