"""Spielt die Ablaeufe aus main.py mit Attrappen durch (ohne Hardware)."""

import time
import wave

import numpy as np
import pytest
from conftest import FakeBridge, FakeLLM

import main
from config import Config
from speech import RecognitionEvent


class ScriptedRecognizer:
    """Liefert pro feed()-Aufruf das naechste vorbereitete Ereignis."""

    def __init__(self, events=()):
        self.events = list(events)
        self.resets = 0

    def feed(self, pcm):
        return self.events.pop(0) if self.events else None

    def flush(self):
        return RecognitionEvent(final="")

    def reset(self):
        self.resets += 1


def make_aouda(tmp_path, wake_events, free_events, **overrides):
    cfg = Config()
    cfg.recordings_dir = tmp_path / "recordings"
    cfg.question_pause_s = 0.0
    cfg.page_seconds = 0.01
    for key, value in overrides.items():
        setattr(cfg, key, value)
    aouda = main.Aouda(cfg)
    aouda.grammar_mode = True
    aouda.wake_rec = ScriptedRecognizer(wake_events)
    aouda.free_rec = ScriptedRecognizer(free_events)
    aouda.ready = True
    return aouda


def chunk(samples=1024):
    return np.zeros(samples, dtype=np.int16)


def wait_idle(aouda, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if aouda.state == main.IDLE:
            return
        time.sleep(0.02)
    pytest.fail(f"Zustand blieb {aouda.state}")


@pytest.fixture(autouse=True)
def clear_fakes():
    FakeBridge.calls.clear()
    FakeLLM.replies.clear()
    FakeLLM.prompts.clear()


def test_question_flow(tmp_path):
    FakeLLM.replies[:] = ["Der Eiffelturm ist 330 Meter hoch."]
    aouda = make_aouda(
        tmp_path,
        wake_events=[RecognitionEvent(final="auda ich habe eine frage", confidence=0.9)],
        free_events=[RecognitionEvent(partial="wie hoch"),
                     RecognitionEvent(final="wie hoch ist der eiffelturm")],
    )
    aouda.process(chunk())
    assert aouda.state == main.QUESTION_LISTEN
    for _ in range(4):
        aouda.process(chunk())
    assert aouda.state in (main.BUSY, main.IDLE)
    wait_idle(aouda)
    time.sleep(0.1)
    assert FakeLLM.prompts == ["wie hoch ist der eiffelturm?".capitalize()]
    shown = " ".join(FakeBridge.texts())
    assert "Der Eiffelturm ist 330 Meter hoch." in shown
    assert "Wie hoch ist der eiffelturm?" in shown


def test_low_confidence_is_ignored(tmp_path):
    aouda = make_aouda(
        tmp_path,
        wake_events=[RecognitionEvent(final="auda ich habe eine frage", confidence=0.2)],
        free_events=[],
    )
    aouda.process(chunk())
    assert aouda.state == main.IDLE


def test_question_timeout(tmp_path):
    aouda = make_aouda(
        tmp_path,
        wake_events=[RecognitionEvent(final="auda ich habe eine frage", confidence=0.9)],
        free_events=[],
        question_timeout_s=0.0,
    )
    aouda.process(chunk())
    aouda.process(chunk())
    assert aouda.state == main.IDLE
    assert any("Keine Frage" in t for t in FakeBridge.texts())


def test_recording_with_stop_command(tmp_path):
    aouda = make_aouda(
        tmp_path,
        wake_events=[RecognitionEvent(final="auto starte aufnahme", confidence=0.9)],
        free_events=[RecognitionEvent(final="das ist ein test"),
                     RecognitionEvent(partial="und fertig auda stoppe aufnahme")],
    )
    aouda.process(chunk())
    assert aouda.state == main.RECORDING
    rec = aouda.recording
    aouda.process(chunk())
    aouda.process(chunk())
    wait_idle(aouda)

    assert rec.wav_path.exists()
    with wave.open(str(rec.wav_path)) as wav:
        assert wav.getframerate() == 16000
        assert wav.getnframes() == 2 * 1024    # der Startbefehl selbst wird nicht aufgenommen
    content = rec.txt_path.read_text(encoding="utf-8")
    assert "Das ist ein test. Und fertig." in content
    assert "stoppe" not in content


def test_recording_time_limit(tmp_path):
    aouda = make_aouda(
        tmp_path,
        wake_events=[RecognitionEvent(final="auda starte aufnahme", confidence=0.9)],
        free_events=[RecognitionEvent(final="erster satz")],
        record_max_s=1,
    )
    aouda.process(chunk())
    rec = aouda.recording
    for _ in range(20):
        if aouda.state != main.RECORDING:
            break
        aouda.process(chunk(4000))
    wait_idle(aouda)
    with wave.open(str(rec.wav_path)) as wav:
        assert wav.getnframes() == 16000          # genau 1 s, nicht mehr
    assert "Erster satz." in rec.txt_path.read_text(encoding="utf-8")


def test_stop_without_recording(tmp_path):
    aouda = make_aouda(
        tmp_path,
        wake_events=[RecognitionEvent(final="auda stoppe aufnahme", confidence=0.9)],
        free_events=[],
    )
    aouda.process(chunk())
    assert aouda.state == main.IDLE
    assert any("Keine Aufnahme" in t for t in FakeBridge.texts())
