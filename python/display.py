"""Ansteuerung des TFT (160x128) ueber die Bridge zum Mikrocontroller.

Der Sketch stellt nur einfache Zeichenbefehle bereit (ui_clear, ui_rect,
ui_text). Layout, Zeilenumbruch, Seiten und Laufschrift werden hier in Python
berechnet. Ist der Sketch nicht erreichbar, wird alles nur auf der Konsole
ausgegeben, damit die App trotzdem funktioniert.

Bildschirmaufteilung (Querformat):

    y   0..11   Kopfzeile  (Modus, farbiger Balken)
    y  12..13   Fortschrittsbalken (z. B. Aufnahmezeit)
    y  15..114  Textbereich: 10 Zeilen a 26 Zeichen
    y 117..127  Fusszeile  (Status / Hinweis)
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata

log = logging.getLogger("aouda.display")

WIDTH = 160
HEIGHT = 128
CHAR_W = 6
CHAR_H = 8

HEADER_H = 12
PROGRESS_Y = 12
PROGRESS_H = 2
BODY_X = 2
BODY_Y = 15
LINE_H = 10
BODY_ROWS = 10
FOOTER_Y = 117
FOOTER_H = 11
COLS = (WIDTH - BODY_X) // CHAR_W   # 26

# RGB565
BLACK = 0x0000
WHITE = 0xFFFF
GRAY = 0x8410
DARKGRAY = 0x31A6
RED = 0xF800
GREEN = 0x07E0
BLUE = 0x001F
CYAN = 0x07FF
YELLOW = 0xFFE0
ORANGE = 0xFD20
MAGENTA = 0xF81F
NAVY = 0x000F
DARKGREEN = 0x03E0
MAROON = 0x7800
PURPLE = 0x780F

_KEEP = set("äöüÄÖÜß°")
_REPLACE = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "–": "-", "—": "-", "−": "-", "•": "-", "·": "-",
    "…": "...", " ": " ", "€": "EUR", "²": "2", "³": "3",
    "½": "1/2", "¼": "1/4", "×": "x", "\t": " ",
}


def sanitize(text: str) -> str:
    """Bringt Text auf den Zeichensatz des Displays (ASCII + Umlaute + Grad).

    Jedes Zeichen des Ergebnisses belegt genau eine Zeichenzelle auf dem TFT.
    """
    out: list[str] = []
    for ch in text:
        if ch == "\n" or (" " <= ch <= "~") or ch in _KEEP:
            out.append(ch)
        elif ch in _REPLACE:
            out.append(_REPLACE[ch])
        elif unicodedata.category(ch).startswith("C"):
            continue   # Steuerzeichen
        else:
            base = unicodedata.normalize("NFKD", ch)
            base = "".join(c for c in base if " " <= c <= "~")
            out.append(base or "?")
    text = "".join(out)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text


def wrap(text: str, cols: int = COLS) -> list[str]:
    """Zeilenumbruch an Wortgrenzen; zu lange Woerter werden getrennt."""
    lines: list[str] = []
    for paragraph in sanitize(text).split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        line = ""
        for word in words:
            while len(word) > cols:
                if line:
                    lines.append(line)
                    line = ""
                lines.append(word[:cols - 1] + "-")
                word = word[cols - 1:]
            if not line:
                line = word
            elif len(line) + 1 + len(word) <= cols:
                line += " " + word
            else:
                lines.append(line)
                line = word
        lines.append(line)
    # Leerzeilen am Ende entfernen
    while lines and not lines[-1]:
        lines.pop()
    return lines


def paginate(lines: list[str], rows: int = BODY_ROWS) -> list[list[str]]:
    if not lines:
        return [[]]
    return [lines[i:i + rows] for i in range(0, len(lines), rows)]


def fit(text: str, cols: int) -> str:
    text = sanitize(text).replace("\n", " ")
    return text if len(text) <= cols else text[:cols - 1] + "~"


class Display:
    """TFT-Ausgabe mit Schattenpuffer, damit nur geaenderte Zeilen gesendet werden."""

    RETRY_S = 10.0

    def __init__(self, bridge=None, console: bool = True):
        self._bridge = bridge
        self._console = console
        self._lock = threading.RLock()
        self._available = bridge is not None
        self._retry_at = 0.0
        self._rows: list[tuple[str, int] | None] = [None] * BODY_ROWS
        self._header: tuple[str, int, int] | None = None
        self._footer: tuple[str, int] | None = None
        self._progress: int | None = None
        self._generation = 0

    # ------------------------------------------------------------------
    # Bridge
    # ------------------------------------------------------------------
    def _call(self, method: str, *args) -> object:
        if self._bridge is None:
            return None
        now = time.monotonic()
        if not self._available and now < self._retry_at:
            return None
        try:
            result = self._bridge.call(method, *args, timeout=5)
            if not self._available:
                log.info("TFT wieder erreichbar")
            self._available = True
            return result
        except Exception as exc:  # Sketch nicht geladen, Timeout, ...
            if self._available:
                log.warning("TFT nicht erreichbar (%s): %s", method, exc)
            self._available = False
            self._retry_at = now + self.RETRY_S
            return None

    def ping(self) -> str | None:
        with self._lock:
            self._available = True
            result = self._call("ui_ping")
            return str(result) if result is not None else None

    @property
    def available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    # Bildschirme
    # ------------------------------------------------------------------
    def new_screen(self, title: str, color: int, footer: str = "", footer_color: int = GRAY) -> int:
        """Loescht den Bildschirm und zeichnet Kopf- und Fusszeile.

        Liefert eine Generation-Nummer. Laufende Seiten-Anzeigen einer aelteren
        Generation beenden sich dann selbst.
        """
        with self._lock:
            self._generation += 1
            self._call("ui_clear", BLACK)
            self._rows = [None] * BODY_ROWS
            self._header = None
            self._footer = None
            self._progress = None
            self.header(title, color)
            self.footer(footer, footer_color)
            if self._console:
                print(f"\n=== {title} ===", flush=True)
            return self._generation

    @property
    def generation(self) -> int:
        return self._generation

    def header(self, title: str, color: int, text_color: int = BLACK) -> None:
        title = fit(title, COLS)
        with self._lock:
            if self._header == (title, color, text_color):
                return
            self._header = (title, color, text_color)
            self._call("ui_rect", 0, 0, WIDTH, 2, color)
            self._call("ui_text", 0, 2, " " + title, text_color, color, 1, WIDTH)
            self._call("ui_rect", 0, 2 + CHAR_H, WIDTH, HEADER_H - 2 - CHAR_H, color)

    def footer(self, text: str, color: int = GRAY) -> None:
        text = fit(text, COLS)
        with self._lock:
            if self._footer == (text, color):
                return
            self._footer = (text, color)
            self._call("ui_text", BODY_X, FOOTER_Y + 2, text, color, BLACK, 1, WIDTH - BODY_X)
            if self._console and text:
                print(f"[{text}]", flush=True)

    def progress(self, fraction: float, color: int = RED) -> None:
        width = max(0, min(WIDTH, int(round(WIDTH * fraction))))
        with self._lock:
            if self._progress == width:
                return
            old = self._progress or 0
            if width > old:
                self._call("ui_rect", old, PROGRESS_Y, width - old, PROGRESS_H, color)
            elif width < old:
                self._call("ui_rect", width, PROGRESS_Y, old - width, PROGRESS_H, BLACK)
            self._progress = width

    def lines(self, lines: list[str], color: int = WHITE, colors: list[int] | None = None) -> None:
        """Zeigt bis zu BODY_ROWS Zeilen; nur geaenderte Zeilen werden gezeichnet."""
        with self._lock:
            for row in range(BODY_ROWS):
                text = fit(lines[row], COLS) if row < len(lines) else ""
                c = colors[row] if colors and row < len(colors) else color
                if self._rows[row] == (text, c):
                    continue
                self._rows[row] = (text, c)
                y = BODY_Y + row * LINE_H
                self._call("ui_text", BODY_X, y, text, c, BLACK, 1, WIDTH - BODY_X)

    def text(self, text: str, color: int = WHITE, tail: bool = True) -> list[str]:
        """Zeigt Text; bei tail=True die letzten Zeilen (Live-Text scrollt mit)."""
        wrapped = wrap(text)
        view = wrapped[-BODY_ROWS:] if tail else wrapped[:BODY_ROWS]
        self.lines(view, color)
        return wrapped

    def live(self, final_text: str, partial: str, color: int = WHITE, partial_color: int = YELLOW) -> None:
        """Live-Transkript: bestaetigter Text weiss, vorlaeufiger Text gelb."""
        final_lines = wrap(final_text) if final_text else []
        combined = (final_text + " " + partial).strip() if partial else final_text
        all_lines = wrap(combined) if combined else []
        view = all_lines[-BODY_ROWS:]
        offset = len(all_lines) - len(view)
        colors = []
        for i in range(len(view)):
            idx = offset + i
            is_final = idx < len(final_lines) - 1 or (
                idx == len(final_lines) - 1 and all_lines[idx] == final_lines[idx])
            colors.append(color if is_final else partial_color)
        self.lines(view, color, colors)

    def show_paged(self, text: str, color: int = WHITE, seconds: float = 7.0,
                   footer: str = "", footer_color: int = GRAY, loop: bool = True) -> None:
        """Blaettert langen Text seitenweise durch.

        Laeuft (blockierend), bis ein neuer Bildschirm aufgebaut wird
        (andere Generation) oder - bei loop=False - einmal alle Seiten gezeigt sind.
        """
        generation = self._generation
        pages = paginate(wrap(text))
        if self._console:
            print(sanitize(text), flush=True)
        if len(pages) == 1:
            self.lines(pages[0], color)
            if footer:
                self.footer(footer, footer_color)
            return

        index = 0
        while self._generation == generation:
            self.lines(pages[index], color)
            label = f"{index + 1}/{len(pages)}"
            info = f"{label} {footer}".strip() if footer else f"Seite {label}"
            self.footer(info, footer_color)
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if self._generation != generation:
                    return
                time.sleep(0.1)
            index += 1
            if index >= len(pages):
                if not loop:
                    return
                index = 0

    def splash(self, title: str, subtitle: str, info: str = "") -> None:
        with self._lock:
            self._generation += 1
            self._rows = [None] * BODY_ROWS
            self._header = None
            self._footer = None
            self._progress = None
            self._call("ui_clear", BLACK)
            title = fit(title, 8)
            x = max(0, (WIDTH - len(title) * CHAR_W * 3) // 2)
            self._call("ui_text", x, 30, title, CYAN, BLACK, 3, 0)
            sub = fit(subtitle, COLS)
            x = max(0, (WIDTH - len(sub) * CHAR_W) // 2)
            self._call("ui_text", x, 66, sub, WHITE, BLACK, 1, 0)
            if info:
                self._call("ui_text", BODY_X, 100, fit(info, COLS), GRAY, BLACK, 1, WIDTH - BODY_X)
            if self._console:
                print(f"{title} - {subtitle} {info}", flush=True)

    def status(self, info: str, color: int = GRAY) -> None:
        """Statuszeile im Splash-Bildschirm (z. B. Download-Fortschritt)."""
        with self._lock:
            self._call("ui_text", BODY_X, 100, fit(info, COLS), color, BLACK, 1, WIDTH - BODY_X)
            if self._console:
                print(info, flush=True)
