"""KI-Chat: lokales Sprachmodell mit Internetsuche als Rueckfallebene.

Ablauf einer Frage:
  1. Braucht die Frage offensichtlich aktuelle Daten (Wetter, Nachrichten,
     "heute", Jahreszahlen ...), wird zuerst im Internet gesucht.
  2. Sonst antwortet das lokale Modell (Qwen3.5 0.8B ueber die arduino:llm Brick).
  3. Antwortet das Modell mit "SUCHE: ..." oder ist es erkennbar unsicher
     ("weiss ich nicht", "keine aktuellen Informationen" ...), wird im Internet
     gesucht und das Modell beantwortet die Frage mit den Suchergebnissen.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable, Protocol

from websearch import SearchResult, format_context, web_search

log = logging.getLogger("aouda.assistant")

SYSTEM_PROMPT = (
    "Du bist AOUDA, ein freundlicher Sprachassistent auf einem Arduino UNO Q. "
    "Antworte immer auf Deutsch, kurz und sachlich in hoechstens drei Saetzen. "
    "Benutze kein Markdown, keine Aufzaehlungen und keine Emojis, denn die Antwort "
    "erscheint auf einem kleinen Display. Die Fragen stammen aus einer "
    "Spracherkennung und koennen Erkennungsfehler enthalten. "
    "Wenn du die Antwort nicht sicher weisst oder die Frage aktuelle Informationen "
    "braucht (Nachrichten, Wetter, Preise, Sportergebnisse, Ereignisse nach 2024), "
    "antworte ausschliesslich mit: SUCHE: <kurze Suchanfrage>"
)

WEB_PROMPT = (
    "Beantworte die Frage auf Deutsch in hoechstens drei kurzen Saetzen und nur mit "
    "Hilfe der folgenden Suchergebnisse. Antworte nicht mit SUCHE. Wenn die "
    "Suchergebnisse die Antwort nicht enthalten, sage das ehrlich.\n\n"
    "Heutiges Datum: {today}\n\nSuchergebnisse:\n{context}\n\nFrage: {question}"
)

# Hinweise, dass die Frage aktuelle Informationen braucht
_CURRENT_PATTERNS = [
    r"\bheute\b", r"\bmorgen\b", r"\bgestern\b", r"\baktuell", r"\bgerade\b", r"\bjetzt\b",
    r"\bneueste", r"\bneuste", r"\bletzte[nrs]?\b", r"\bdiese[nrs]? (woche|monat|jahr)",
    r"\bwetter", r"\btemperatur", r"\bnachrichten\b", r"\bnews\b", r"\bschlagzeile",
    r"\bpreis", r"\bkostet\b", r"\bkurs\b", r"\baktie", r"\bbitcoin", r"\bboerse", r"\bbörse",
    r"\bspielstand", r"\bergebnis", r"\btabelle\b", r"\bgewonnen\b", r"\bwahl", r"\bumfrage",
    r"\bwann (spielt|kommt|beginnt|startet|ist das naechste|ist das nächste)",
    r"\bwer ist (der|die) (aktuelle|neue|jetzige)", r"\bsonnenaufgang", r"\bsonnenuntergang",
    r"\bverkehr", r"\bstau\b", r"\bfahrplan", r"\böffnungszeit", r"\boeffnungszeit",
]

# Hinweise in der Antwort, dass das Modell es nicht weiss
_UNSURE_PATTERNS = [
    r"\bsuche\s*:", r"wei(ß|ss) ich (es )?(leider )?nicht", r"ich wei(ß|ss) (es |das )?(leider )?nicht",
    r"leider nicht", r"keine (aktuellen )?informationen", r"kann ich (dir )?(leider )?nicht (sagen|beantworten)",
    r"nicht (sicher|bekannt)", r"keinen zugriff", r"keine echtzeit", r"nicht in der lage",
    r"mein(em)? wissensstand", r"stand meines wissens", r"trainingsdaten",
    r"als (ki|künstliche intelligenz|sprachmodell)", r"i don't know", r"i do not know",
    r"tut mir leid", r"leider (kann|habe|wei(ß|ss))", r"keine daten",
]


def needs_current_info(question: str) -> bool:
    q = question.lower()
    if any(re.search(p, q) for p in _CURRENT_PATTERNS):
        return True
    # Jahreszahlen ab dem letzten Jahr deuten auf aktuelle Ereignisse
    this_year = date.today().year
    for year in re.findall(r"\b(20\d\d)\b", q):
        if int(year) >= this_year - 1:
            return True
    return False


def is_unsure(answer: str) -> bool:
    a = answer.lower()
    if not a.strip():
        return True
    return any(re.search(p, a) for p in _UNSURE_PATTERNS)


def extract_search_query(answer: str, question: str) -> str:
    m = re.search(r"suche\s*:\s*(.+)", answer, flags=re.IGNORECASE)
    if m:
        query = m.group(1).strip().strip("\"'<>.").splitlines()[0].strip()
        if len(query) >= 3:
            return query
    return question


def clean_answer(text: str) -> str:
    """Entfernt Denk-Bloecke, Markdown und ueberfluessige Leerzeichen."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"</?think>", "", text)
    text = re.sub(r"[*_`#]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    return " ".join(text.split())


class ChatModel(Protocol):
    def chat_stream(self, message: str) -> Iterable[str]: ...


@dataclass
class Answer:
    text: str
    sources: list[str] = field(default_factory=list)
    searched: bool = False
    seconds: float = 0.0


class Assistant:
    def __init__(self, llm: ChatModel, web_enabled: bool = True, web_results: int = 4,
                 web_region: str = "de-de", web_timeout: float = 10.0,
                 search: Callable[..., list[SearchResult]] = web_search):
        self.llm = llm
        self.web_enabled = web_enabled
        self.web_results = web_results
        self.web_region = web_region
        self.web_timeout = web_timeout
        self._search = search

    def answer(self, question: str,
               on_status: Callable[[str], None] = lambda s: None,
               on_partial: Callable[[str], None] = lambda s: None) -> Answer:
        start = time.monotonic()

        if self.web_enabled and needs_current_info(question):
            on_status("Suche im Internet...")
            result = self._answer_with_web(question, question, on_status, on_partial)
            if result:
                result.seconds = time.monotonic() - start
                return result

        on_status("Denke nach...")
        text = self._stream(question, on_partial, hide_search=True)
        if self.web_enabled and is_unsure(text):
            query = extract_search_query(text, question)
            log.info("Modell unsicher (%r) -> Websuche: %s", text[:80], query)
            on_status("Suche im Internet...")
            result = self._answer_with_web(question, query, on_status, on_partial)
            if result:
                result.seconds = time.monotonic() - start
                return result

        if re.match(r"\s*suche\s*:", text, flags=re.IGNORECASE):
            text = "Das weiß ich leider nicht, und die Internetsuche war nicht erfolgreich."
        return Answer(text=text, seconds=time.monotonic() - start)

    def _answer_with_web(self, question: str, query: str,
                         on_status: Callable[[str], None],
                         on_partial: Callable[[str], None]) -> Answer | None:
        try:
            results = self._search(query, max_results=self.web_results,
                                   region=self.web_region, timeout=self.web_timeout)
        except Exception as exc:
            log.warning("Websuche fehlgeschlagen: %s", exc)
            results = []
        if not results:
            return None
        on_status("Lese Suchergebnisse...")
        prompt = WEB_PROMPT.format(today=date.today().strftime("%d.%m.%Y"),
                                   context=format_context(results), question=question)
        text = self._stream(prompt, on_partial, hide_search=False)
        sources = []
        for r in results:
            if r.source and r.source not in sources:
                sources.append(r.source)
        return Answer(text=text, sources=sources[:2], searched=True)

    def _stream(self, message: str, on_partial: Callable[[str], None], hide_search: bool) -> str:
        """Fragt das Modell und meldet den wachsenden Text (gedrosselt) weiter."""
        raw = ""
        last_update = 0.0
        for token in self.llm.chat_stream(message):
            raw += token
            now = time.monotonic()
            if now - last_update >= 0.4:
                shown = clean_answer(raw)
                # "SUCHE: ..." nicht als Antwort anzeigen
                if not (hide_search and shown.upper().startswith("SUCH")):
                    on_partial(shown)
                last_update = now
        return clean_answer(raw)
