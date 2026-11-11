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
from typing import Callable

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
from sysstats import LevelMeter, SystemStats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
log = logging.getLogger("aouda")

IDLE = "idle"
QUESTION_LISTEN = "question"
BUSY = "busy"
RECORDING = "recording"

HINT = "Sag: AOUDA, ..."
STOP_SENTENCE = "AOUDA, stoppe Aufnahme"

# Befehlsuebersicht auf dem TFT: (Befehl, Zeile). Ein erkannter Befehl wird gruen.
COMMAND_OVERVIEW = [
    (None, "Sprachbefehle:"),
    (QUESTION, "AOUDA, ich habe eine"),
    (QUESTION, "  Frage"),
    (None, ""),
    (RECORD_START, "AOUDA, starte Aufnahme"),
    (None, ""),
    (RECORD_STOP, STOP_SENTENCE),
    (RECORD_STOP, "  (nur während Aufnahme)"),
]
COMMAND_NAMES = {QUESTION: "Frage", RECORD_START: "Aufnahme starten", RECORD_STOP: "Aufnahme stoppen"}


def command_overview(highlight: str | None = None) -> tuple[list[str], list[int]]:
    """Zeilen und Farben der Befehlsuebersicht (aktive Befehle weiss, erkannter gruen)."""
    lines, colors = [], []
    for command, line in COMMAND_OVERVIEW:
        lines.append(line)
        if command is None:
            colors.append(tft.GRAY)
        elif command == highlight:
            colors.append(tft.GREEN)
        elif command == RECORD_STOP:
            colors.append(tft.DARKGRAY)       # nur waehrend einer Aufnahme gueltig
        else:
            colors.append(tft.WHITE)
    return lines, colors

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
        # verzoegerter Bildschirmwechsel: (Zeitpunkt, Zeichenfunktion)
        self._deferred: tuple[float, Callable[[], None]] | None = None
        self._idle_heard = False
        self._idle_feedback_at = 0.0

        # Statuszeile
        self.meter = LevelMeter()
        self.stats = SystemStats()
        self._level_at = 0.0
        self._stats_at = 0.0

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
            self._screen = "error"
            self._deferred = None
            display.new_screen("Fehler", tft.RED, "Neustart in 5 s", tft.RED)
            display.text(str(exc), tft.WHITE, tail=False)
            if self.mic is not None:
                try:
                    self.mic.stop()
                except Exception:
                    pass
            time.sleep(5)

    def process(self, pcm: np.ndarray) -> None:
        now = time.monotonic()
        self.update_status(pcm, now)

        if self.state == IDLE:
            self.handle_idle(pcm)
        elif self.state == QUESTION_LISTEN:
            self.handle_question(pcm)
        elif self.state == RECORDING:
            self.handle_recording(pcm)
        # BUSY: Audio verwerfen, waehrend die KI antwortet / transkribiert wird

        if self._deferred is not None and now >= self._deferred[0]:
            draw = self._deferred[1]
            self._deferred = None
            draw()

    def update_status(self, pcm: np.ndarray, now: float) -> None:
        """Mikrofonpegel (mehrmals pro Sekunde) und CPU/RAM (jede Sekunde)."""
        self.meter.add(pcm)
        if now - self._level_at >= self.cfg.level_interval_s:
            self._level_at = now
            display.mic_level(self.meter.take())
        if now - self._stats_at >= self.cfg.stats_interval_s:
            self._stats_at = now
            display.system(self.stats.cpu_percent(), self.stats.ram_percent())

    def confirm(self, command: str, then: Callable[[], None] | None = None) -> None:
        """Zeigt den erkannten Befehl gruen an; `then` zeichnet nach confirm_s den naechsten Bildschirm."""
        log.info("Befehl erkannt: %s", COMMAND_NAMES[command])
        self.show_idle(highlight=command)
        if then is not None:
            self._deferred = (time.monotonic() + self.cfg.confirm_s, then)

    # ------------------------------------------------------------------
    # Bereit: auf "AOUDA, ..." warten
    # ------------------------------------------------------------------
    def show_idle(self, footer: str = "", footer_color: int = tft.GRAY,
                  highlight: str | None = None, expect_generation: int | None = None) -> None:
        """Befehlsuebersicht; ist sie schon zu sehen, werden nur Aenderungen gezeichnet."""
        lines, colors = command_overview(highlight)
        if highlight:
            footer, footer_color = "Erkannt: " + COMMAND_NAMES[highlight], tft.GREEN
        elif not footer:
            footer = "Warte auf Weckwort..."

        if self._screen == "idle" and expect_generation is None:
            display.header("AOUDA ist bereit", tft.GREEN)
            display.lines(lines, tft.WHITE, colors)
            display.footer(footer, footer_color)
            return
        if display.new_screen("AOUDA ist bereit", tft.GREEN, footer, footer_color,
                              expect_generation=expect_generation) is None:
            return   # inzwischen wird etwas anderes angezeigt
        self._screen = "idle"
        display.lines(lines, tft.WHITE, colors)

    def handle_idle(self, pcm: np.ndarray) -> None:
        if self._reset_wake:
            self.wake_rec.reset()
            self._reset_wake = False
        event = self.wake_rec.feed(pcm.tobytes())
        if event is None or self._deferred is not None:
            return

        if event.final is None:
            # Rueckmeldung, dass gerade etwas gehoert wird
            now = time.monotonic()
            if event.partial and now - self._idle_feedback_at > 0.3:
                self._idle_feedback_at = now
                self._idle_heard = True
                display.footer("> " + event.partial, tft.GRAY)
            return

        text = event.final
        if not text:
            if self._idle_heard:
                display.footer("? nicht verstanden", tft.DARKGRAY)
            self._idle_heard = False
            return
        self._idle_heard = False

        match = find_command(text, [QUESTION, RECORD_START, RECORD_STOP],
                             require_wake=self.cfg.wake_required,
                             threshold=self.cfg.match_threshold,
                             wake_spellings=self.cfg.wake_words)
        log.info("Gehoert: '%s' (Konfidenz %.2f) -> %s", text, event.confidence,
                 match.command if match else "-")

        if match and self.grammar_mode and event.confidence < self.cfg.min_confidence:
            log.info("Konfidenz zu niedrig, ignoriert")
            display.footer(f"? {text} ({event.confidence:.2f})", tft.DARKGRAY)
            return

        if not match:
            display.footer(f"? {text}", tft.DARKGRAY)
            return

        self.wake_rec.reset()
        if match.command == QUESTION:
            words = match.after.split()
            if not self.grammar_mode and len(words) >= 3:
                self.confirm(QUESTION)
                self.ask(match.after, delay=self.cfg.confirm_s)   # Frage direkt im selben Satz
            else:
                self.start_question()
        elif match.command == RECORD_START:
            self.start_recording()
        else:
            self.show_idle("Keine Aufnahme aktiv", tft.ORANGE)

    # ------------------------------------------------------------------
    # Frage
    # ------------------------------------------------------------------
    def start_question(self) -> None:
        self.state = QUESTION_LISTEN
        self.free_rec.reset()
        now = time.monotonic()
        self._q_start = now
        self._q_last_voice = now
        self._q_final = ""
        self._q_partial = ""
        self._q_draw = 0.0
        self.confirm(QUESTION, self._draw_question_screen)

    def _draw_question_screen(self) -> None:
        self._screen = "question"
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

        if (self._q_final or self._q_partial) and now - self._q_draw > 0.25 and self._deferred is None:
            display.live(self._q_final, self._q_partial)
            self._q_draw = now

        has_text = bool(self._q_final or self._q_partial)
        if not has_text and now - self._q_start > self.cfg.question_timeout_s:
            self.state = IDLE
            self._reset_wake = True
            self._deferred = None
            self.show_idle("Keine Frage gehört", tft.ORANGE)
            return

        if has_text and (now - self._q_last_voice > self.cfg.question_pause_s
                         or now - self._q_start > self.cfg.question_max_s):
            rest = self.free_rec.flush()
            question = (self._q_final + " " + (rest.final or "")).strip()
            if not question:
                question = self._q_partial
            self.ask(question)

    def ask(self, question: str, delay: float = 0.0) -> None:
        self.state = BUSY
        self._deferred = None
        threading.Thread(target=self._answer_worker, args=(question, delay), daemon=True).start()

    def _answer_worker(self, question: str, delay: float = 0.0) -> None:
        time.sleep(delay)
        self._screen = "answer"
        question = question.strip()
        if question:
            question = question[0].upper() + question[1:] + ("" if question.endswith("?") else "?")
        log.info("Frage: %s", question)
        generation = display.new_screen("Frage", tft.CYAN, "Denke nach...", tft.YELLOW)
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
            time.sleep(10)
            self.show_idle(expect_generation=generation)
            return

        log.info("Antwort (%.1f s%s): %s", answer.seconds,
                 ", Web: " + ", ".join(answer.sources) if answer.searched else "", answer.text)
        display.header("Antwort (Web)" if answer.searched else "Antwort", tft.GREEN)
        footer = ("Quelle: " + answer.sources[0]) if answer.sources else HINT
        self._back_to_idle()
        text = answer.text or "Darauf habe ich leider keine Antwort."
        if display.show_paged(text, tft.WHITE, self.cfg.page_seconds, footer, tft.GRAY,
                              max_seconds=self.cfg.result_hold_s):
            self.show_idle(expect_generation=generation)

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
        log.info("Aufnahme gestartet: %s", self.recording.wav_path)
        self.confirm(RECORD_START, self._draw_recording_screen)

    def _draw_recording_screen(self) -> None:
        self._screen = "recording"
        self._rec_second = -1
        display.new_screen(self._rec_title(), tft.RED, STOP_SENTENCE, tft.WHITE)
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
                    if self._deferred is None:
                        display.footer(STOP_SENTENCE, tft.GREEN)   # erkannt -> gruen
                    self.stop_recording("Aufnahme beendet")
                    return
                if event.final is not None:
                    rec.add_sentence(event.final)
                    self._rec_partial = ""
                else:
                    self._rec_partial = event.partial or ""

        if self._deferred is None:   # sonst steht noch die Befehlsuebersicht da
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
            if self._deferred is None:
                display.footer("Zeitlimit erreicht", tft.ORANGE)
            self.stop_recording("10 Minuten erreicht")

    def stop_recording(self, reason: str) -> None:
        rec = self.recording
        rec.close()
        self.state = BUSY
        self._deferred = None
        log.info("%s nach %s: %s", reason, format_duration(rec.seconds), rec.wav_path)
        threading.Thread(target=self._transcribe_worker, args=(rec, reason), daemon=True).start()

    def _transcribe_worker(self, rec: Recording, reason: str) -> None:
        time.sleep(self.cfg.confirm_s)   # gruene Bestaetigung kurz stehen lassen
        self._screen = "transcript"
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

        generation = display.new_screen(f"Transkript {duration}", tft.MAGENTA, saved, tft.GRAY)
        self._back_to_idle()
        if display.show_paged(text, tft.WHITE, self.cfg.page_seconds, saved, tft.GRAY,
                              max_seconds=self.cfg.result_hold_s):
            self.show_idle(expect_generation=generation)


aouda = Aouda(cfg)
App.run(user_loop=aouda.run_once)
