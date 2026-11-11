"""Erkennung der Sprachbefehle "AOUDA, ich habe eine Frage" usw.

"AOUDA" ist kein deutsches Wort. Die Spracherkennung schreibt es deshalb
unterschiedlich ("auda", "outa", "auto", "au da", ...). Damit der Befehl
trotzdem erkannt wird, werden zwei Verfahren kombiniert:

* Koelner Phonetik: klingt das Wort vor dem Befehl wie "Auda" (Code "02")?
* Unscharfer Textvergleich (difflib) gegen bekannte Schreibweisen.

Die Befehlssaetze selbst werden ebenfalls unscharf verglichen, damit kleine
Erkennungsfehler ("ich hab ne frage") nicht stoeren.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

QUESTION = "question"
RECORD_START = "record_start"
RECORD_STOP = "record_stop"

COMMAND_PHRASES: dict[str, list[str]] = {
    QUESTION: [
        "ich habe eine frage",
        "ich hab eine frage",
        "ich habe ne frage",
        "ich hab ne frage",
        "ich habe da eine frage",
        "ich hätte eine frage",
    ],
    RECORD_START: [
        "starte aufnahme",
        "starte die aufnahme",
        "starte eine aufnahme",
        "start aufnahme",
        "aufnahme starten",
        "aufnahme start",
    ],
    RECORD_STOP: [
        "stoppe aufnahme",
        "stoppe die aufnahme",
        "stopp aufnahme",
        "stop aufnahme",
        "stopp die aufnahme",
        "beende aufnahme",
        "beende die aufnahme",
        "aufnahme beenden",
        "aufnahme stoppen",
    ],
}

WAKE_CANONICAL = ["aouda", "auda"]


@dataclass
class CommandMatch:
    command: str
    score: float          # Aehnlichkeit des Befehlssatzes 0..1
    wake: bool            # Weckwort vor dem Befehl erkannt?
    wake_text: str        # erkannte Woerter vor dem Befehl
    before: str           # Text vor dem Weckwort / Befehl
    after: str            # Text nach dem Befehl (z. B. die Frage selbst)


# ---------------------------------------------------------------------------
# Text normalisieren
# ---------------------------------------------------------------------------
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def normalize(text: str) -> str:
    """Kleinbuchstaben, Umlaute ausgeschrieben, nur a-z und Leerzeichen."""
    text = text.lower().translate(_UMLAUTS)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z]+", " ", text)
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Koelner Phonetik
# ---------------------------------------------------------------------------
def koelner_phonetik(word: str) -> str:
    """Phonetischer Code nach der Koelner Phonetik (fuer deutsche Woerter)."""
    w = normalize(word).replace(" ", "")
    if not w:
        return ""
    w = w.upper()
    codes: list[str] = []
    for i, ch in enumerate(w):
        prev = w[i - 1] if i > 0 else ""
        nxt = w[i + 1] if i + 1 < len(w) else ""
        if ch in "AEIJOUY":
            code = "0"
        elif ch == "H":
            code = ""
        elif ch == "B":
            code = "1"
        elif ch == "P":
            code = "3" if nxt == "H" else "1"
        elif ch in "DT":
            code = "8" if nxt in ("C", "S", "Z") else "2"
        elif ch in "FVW":
            code = "3"
        elif ch in "GKQ":
            code = "4"
        elif ch == "C":
            if i == 0:
                code = "4" if nxt in tuple("AHKLOQRUX") else "8"
            elif prev in ("S", "Z"):
                code = "8"
            else:
                code = "4" if nxt in tuple("AHKOQUX") else "8"
        elif ch == "X":
            code = "8" if prev in ("C", "K", "Q") else "48"
        elif ch == "L":
            code = "5"
        elif ch in "MN":
            code = "6"
        elif ch == "R":
            code = "7"
        elif ch in "SZ":
            code = "8"
        else:
            code = ""
        codes.append(code)

    raw = "".join(codes)
    collapsed = ""
    for digit in raw:
        if not collapsed or collapsed[-1] != digit:
            collapsed += digit
    if not collapsed:
        return ""
    return collapsed[0] + collapsed[1:].replace("0", "")


WAKE_CODE = koelner_phonetik("auda")   # "02"


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def is_wake_word(text: str, extra_spellings: list[str] | None = None) -> bool:
    """Prueft, ob ein (kurzer) Text wie "AOUDA" klingt."""
    t = normalize(text)
    if not t:
        return False
    joined = t.replace(" ", "")
    spellings = [normalize(s).replace(" ", "") for s in (extra_spellings or [])] + WAKE_CANONICAL
    if joined in spellings:
        return True
    if koelner_phonetik(joined) == WAKE_CODE:
        return True
    return any(_similar(joined, s) >= 0.75 for s in WAKE_CANONICAL)


# ---------------------------------------------------------------------------
# Befehle suchen
# ---------------------------------------------------------------------------
def find_command(
    text: str,
    commands: list[str] | None = None,
    require_wake: bool = True,
    threshold: float = 0.78,
    wake_spellings: list[str] | None = None,
) -> CommandMatch | None:
    """Sucht einen Befehl im erkannten Text.

    Args:
        text: erkannter Text (beliebige Schreibweise)
        commands: erlaubte Befehle (Standard: alle)
        require_wake: Weckwort muss direkt vor dem Befehl stehen
        threshold: Mindest-Aehnlichkeit des Befehlssatzes
        wake_spellings: zusaetzliche bekannte Schreibweisen des Weckworts
    """
    words = normalize(text).split()
    if not words:
        return None

    best: tuple[tuple, CommandMatch] | None = None
    for command in commands or list(COMMAND_PHRASES):
        for phrase in COMMAND_PHRASES[command]:
            target = normalize(phrase)
            n = len(target.split())
            for size in {max(1, n - 1), n, n + 1}:
                for start in range(0, len(words) - size + 1):
                    candidate = " ".join(words[start:start + size])
                    score = _similar(candidate, target)
                    if score < threshold:
                        continue

                    wake, wake_text, wake_start = _wake_before(words, start, wake_spellings)
                    if require_wake and not wake:
                        continue

                    match = CommandMatch(
                        command=command,
                        score=score,
                        wake=wake,
                        wake_text=wake_text,
                        before=" ".join(words[:wake_start]),
                        after=" ".join(words[start + size:]),
                    )
                    # Rangfolge: Weckwort vorhanden, Aehnlichkeit, laengeres Fenster
                    rank = (wake, round(score, 3), size)
                    if best is None or rank > best[0]:
                        best = (rank, match)
    return best[1] if best else None


def _wake_before(words: list[str], start: int, spellings: list[str] | None) -> tuple[bool, str, int]:
    """Prueft die ein bis zwei Woerter vor dem Befehl auf das Weckwort."""
    for count in (1, 2):
        if start - count < 0:
            break
        candidate = " ".join(words[start - count:start])
        if is_wake_word(candidate, spellings):
            return True, candidate, start - count
    return False, "", start

