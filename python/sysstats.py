"""Systemlast (CPU, RAM) und Mikrofonpegel fuer die Statuszeile.

/proc/stat und /proc/meminfo zeigen auch im App-Container die Werte des
ganzen Boards, also inklusive KI-Modell und Spracherkennung.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

SILENCE_DB = -90.0


class SystemStats:
    def __init__(self, proc: Path | str = "/proc"):
        self._proc = Path(proc)
        self._prev: tuple[int, int] | None = None

    def cpu_percent(self) -> int | None:
        """CPU-Auslastung aller Kerne seit dem letzten Aufruf (0..100)."""
        try:
            first = (self._proc / "stat").read_text().splitlines()[0].split()
            values = [int(v) for v in first[1:]]
        except (OSError, IndexError, ValueError):
            return None
        idle = values[3] + (values[4] if len(values) > 4 else 0)   # idle + iowait
        total = sum(values[:8])                                    # ohne guest-Zeiten
        prev, self._prev = self._prev, (idle, total)
        if prev is None or total <= prev[1]:
            return None
        busy = 1.0 - (idle - prev[0]) / (total - prev[1])
        return int(round(max(0.0, min(1.0, busy)) * 100))

    def ram_percent(self) -> int | None:
        """Belegter Arbeitsspeicher in Prozent (MemTotal - MemAvailable)."""
        try:
            info = {}
            for line in (self._proc / "meminfo").read_text().splitlines():
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0])
            total, available = info["MemTotal"], info["MemAvailable"]
        except (OSError, KeyError, ValueError, IndexError):
            return None
        if total <= 0:
            return None
        return int(round((total - available) * 100 / total))


def level_db(pcm16: np.ndarray) -> float:
    """RMS-Pegel eines 16-Bit-Audioblocks in dBFS (0 = Vollaussteuerung)."""
    if len(pcm16) == 0:
        return SILENCE_DB
    rms = math.sqrt(float(np.mean(np.square(pcm16.astype(np.float32)))))
    if rms < 1.0:
        return SILENCE_DB
    return max(SILENCE_DB, 20.0 * math.log10(rms / 32768.0))


class LevelMeter:
    """Merkt sich den lautesten Block seit der letzten Anzeige.

    So bleiben auch kurze Silben sichtbar, obwohl die Anzeige nur einige Male
    pro Sekunde aktualisiert wird.
    """

    def __init__(self):
        self._peak = SILENCE_DB

    def add(self, pcm16: np.ndarray) -> None:
        self._peak = max(self._peak, level_db(pcm16))

    def take(self) -> float:
        peak, self._peak = self._peak, SILENCE_DB
        return peak
