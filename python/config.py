"""Einstellungen fuer AOUDA.

Alle Werte koennen ueber Umgebungsvariablen ueberschrieben werden
(z. B. in App Lab oder beim Start auf der Kommandozeile).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("AOUDA_DATA_DIR", APP_DIR / "data"))


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "ja", "on")


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return list(default)
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Config:
    # --- Mikrofon --------------------------------------------------------
    # 0 = erstes Mikrofon (USB vor Klinke), "jack:1" = Klinke am Media Carrier,
    # "usb:1" = erstes USB-Mikrofon oder ein ALSA-Name wie "hw:0,0"
    mic_device: str = field(default_factory=lambda: _env_str("AOUDA_MIC", "0"))
    sample_rate: int = 16000

    # --- Spracherkennung (Vosk, offline, Echtzeit) ----------------------
    vosk_model: str = field(default_factory=lambda: _env_str("AOUDA_VOSK_MODEL", "vosk-model-small-de-0.15"))
    vosk_url: str = field(default_factory=lambda: _env_str("AOUDA_VOSK_URL", "https://alphacephei.com/vosk/models/"))
    # "grammar": Weckwort-Erkennung mit festem Wortschatz (robuster),
    # "free": freie Erkennung + unscharfer Textvergleich
    wake_mode: str = field(default_factory=lambda: _env_str("AOUDA_WAKE_MODE", "grammar"))
    # Moegliche Schreibweisen, wie die Spracherkennung "AOUDA" verstehen kann.
    # Im Grammatik-Modus werden nur Woerter genutzt, die das Modell kennt.
    wake_words: list[str] = field(default_factory=lambda: _env_list(
        "AOUDA_WAKE_WORDS",
        ["aouda", "auda", "ouda", "outa", "auder", "oda", "ada", "auto", "audi",
         "aua", "gouda", "lauda", "au da", "o da", "a uda", "aus da"],
    ))
    # Wird das Weckwort zwingend vor dem Befehl benoetigt?
    wake_required: bool = field(default_factory=lambda: _env_bool("AOUDA_WAKE_REQUIRED", True))
    # Mindest-Konfidenz (0..1) der Vosk-Woerter fuer einen Befehl
    min_confidence: float = field(default_factory=lambda: _env_float("AOUDA_MIN_CONFIDENCE", 0.55))
    # Mindest-Aehnlichkeit (0..1) beim Textvergleich der Befehle
    match_threshold: float = field(default_factory=lambda: _env_float("AOUDA_MATCH_THRESHOLD", 0.78))

    # --- Frage ------------------------------------------------------------
    question_timeout_s: float = field(default_factory=lambda: _env_float("AOUDA_QUESTION_TIMEOUT", 10.0))
    question_pause_s: float = field(default_factory=lambda: _env_float("AOUDA_QUESTION_PAUSE", 1.5))
    question_max_s: float = field(default_factory=lambda: _env_float("AOUDA_QUESTION_MAX", 25.0))

    # --- KI-Chat (arduino:llm Brick, llama.cpp) ---------------------------
    llm_max_tokens: int = field(default_factory=lambda: _env_int("AOUDA_LLM_MAX_TOKENS", 220))
    llm_temperature: float = field(default_factory=lambda: _env_float("AOUDA_LLM_TEMPERATURE", 0.3))
    llm_timeout_s: int = field(default_factory=lambda: _env_int("AOUDA_LLM_TIMEOUT", 180))

    # --- Internetsuche -----------------------------------------------------
    web_search: bool = field(default_factory=lambda: _env_bool("AOUDA_WEB_SEARCH", True))
    web_results: int = field(default_factory=lambda: _env_int("AOUDA_WEB_RESULTS", 4))
    web_timeout_s: float = field(default_factory=lambda: _env_float("AOUDA_WEB_TIMEOUT", 10.0))
    web_region: str = field(default_factory=lambda: _env_str("AOUDA_WEB_REGION", "de-de"))

    # --- Aufnahme ------------------------------------------------------------
    record_max_s: int = field(default_factory=lambda: _env_int("AOUDA_RECORD_MAX", 600))   # 10 Minuten
    # "vosk": Text entsteht in Echtzeit waehrend der Aufnahme (sofort fertig)
    # "whisper": nach der Aufnahme mit faster-whisper neu transkribieren
    #            (genauer, aber langsamer; faster-whisper muss installiert sein)
    transcribe_engine: str = field(default_factory=lambda: _env_str("AOUDA_TRANSCRIBE", "vosk"))
    whisper_model: str = field(default_factory=lambda: _env_str("AOUDA_WHISPER_MODEL", "base"))

    # --- Anzeige -------------------------------------------------------------
    page_seconds: float = field(default_factory=lambda: _env_float("AOUDA_PAGE_SECONDS", 7.0))
    # So lange bleibt ein erkannter Befehl gruen markiert, bevor der Bildschirm wechselt
    confirm_s: float = field(default_factory=lambda: _env_float("AOUDA_CONFIRM_SECONDS", 0.8))
    # So lange werden Antwort/Transkript angezeigt, danach wieder die Befehlsuebersicht
    result_hold_s: float = field(default_factory=lambda: _env_float("AOUDA_RESULT_SECONDS", 60.0))
    # Aktualisierung der Statuszeile (Mikrofonpegel / CPU+RAM) in Sekunden
    level_interval_s: float = 0.2
    stats_interval_s: float = 1.0

    # --- Pfade -----------------------------------------------------------------
    data_dir: Path = DATA_DIR
    models_dir: Path = DATA_DIR / "models"
    recordings_dir: Path = DATA_DIR / "recordings"

    def mic_selector(self) -> int | str:
        """Mikrofonauswahl fuer arduino.app_peripherals.microphone.Microphone."""
        return int(self.mic_device) if self.mic_device.isdigit() else self.mic_device
