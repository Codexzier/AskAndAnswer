"""Testumgebung: python/ in den Suchpfad, Arduino-Module durch Attrappen ersetzen.

Die Tests laufen auf jedem PC (ohne UNO Q, ohne Mikrofon, ohne Modelle):
    pip install pytest numpy
    python -m pytest tests
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))


class FakeBridge:
    """Merkt sich alle Bridge-Aufrufe an den Sketch."""

    calls: list = []

    @classmethod
    def call(cls, method, *args, timeout=10):
        cls.calls.append((method, args))
        if method == "ui_ping":
            return "AOUDA-TFT 160x128"
        return None

    @classmethod
    def texts(cls):
        return [args[2] for method, args in cls.calls if method == "ui_text"]


class FakeApp:
    @staticmethod
    def run(user_loop=None):
        pass   # main.py ruft App.run() beim Import auf - im Test nichts tun


class FakeLLM:
    replies: list = []
    prompts: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def chat_stream(self, message):
        FakeLLM.prompts.append(message)
        reply = FakeLLM.replies.pop(0) if FakeLLM.replies else "Keine Antwort."
        for i in range(0, len(reply), 4):
            yield reply[i:i + 4]


class FakeMicrophone:
    CHANNELS_MONO = 1
    BUFFER_SIZE_BALANCED = 1024

    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _install_fakes():
    arduino = types.ModuleType("arduino")
    app_utils = types.ModuleType("arduino.app_utils")
    app_utils.App = FakeApp
    app_utils.Bridge = FakeBridge
    bricks = types.ModuleType("arduino.app_bricks")
    llm = types.ModuleType("arduino.app_bricks.llm")
    llm.LargeLanguageModel = FakeLLM
    peripherals = types.ModuleType("arduino.app_peripherals")
    microphone = types.ModuleType("arduino.app_peripherals.microphone")
    microphone.Microphone = FakeMicrophone
    for name, module in {
        "arduino": arduino,
        "arduino.app_utils": app_utils,
        "arduino.app_bricks": bricks,
        "arduino.app_bricks.llm": llm,
        "arduino.app_peripherals": peripherals,
        "arduino.app_peripherals.microphone": microphone,
    }.items():
        sys.modules.setdefault(name, module)


_install_fakes()
