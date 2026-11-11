"""Internetsuche fuer Fragen, die das lokale Modell nicht beantworten kann.

1. DuckDuckGo & Co. ueber das Paket "ddgs" (kein API-Schluessel noetig)
2. Fallback: deutsche Wikipedia (MediaWiki-API)
"""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("aouda.web")

USER_AGENT = "aouda-uno-q/1.0 (voice assistant)"


@dataclass
class SearchResult:
    title: str
    snippet: str
    url: str

    @property
    def source(self) -> str:
        host = urllib.parse.urlparse(self.url).netloc
        return host[4:] if host.startswith("www.") else host


def _clean(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", text or ""))
    return " ".join(text.split())


def search_ddgs(query: str, max_results: int, region: str, timeout: float) -> list[SearchResult]:
    from ddgs import DDGS  # erst hier importieren: optional und etwas traege

    results = []
    raw = DDGS(timeout=int(timeout)).text(query, region=region, safesearch="moderate", max_results=max_results)
    for item in raw or []:
        snippet = _clean(item.get("body", ""))
        if snippet:
            results.append(SearchResult(_clean(item.get("title", "")), snippet, item.get("href", "")))
    return results[:max_results]


def _wiki_get(params: dict, timeout: float) -> dict:
    url = "https://de.wikipedia.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json", "utf8": 1})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def search_wikipedia(query: str, max_results: int, timeout: float) -> list[SearchResult]:
    found = _wiki_get({"action": "query", "list": "search", "srsearch": query, "srlimit": max_results}, timeout)
    titles = [hit["title"] for hit in found.get("query", {}).get("search", [])]
    if not titles:
        return []
    extracts = _wiki_get({
        "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
        "exsentences": 4, "redirects": 1, "titles": "|".join(titles[:max_results]),
    }, timeout)
    pages = extracts.get("query", {}).get("pages", {})
    by_title = {p.get("title"): _clean(p.get("extract", "")) for p in pages.values()}
    results = []
    for title in titles:
        snippet = by_title.get(title, "")
        if snippet:
            url = "https://de.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
            results.append(SearchResult(title, snippet, url))
    return results


def web_search(query: str, max_results: int = 4, region: str = "de-de", timeout: float = 10.0) -> list[SearchResult]:
    """Sucht im Internet und liefert kurze Textausschnitte."""
    for name, func in (
        ("ddgs", lambda: search_ddgs(query, max_results, region, timeout)),
        ("wikipedia", lambda: search_wikipedia(query, max_results, timeout)),
    ):
        try:
            results = func()
            if results:
                log.info("Websuche (%s): %d Treffer fuer '%s'", name, len(results), query)
                return results
        except Exception as exc:
            log.warning("Websuche %s fehlgeschlagen: %s", name, exc)
    return []


def format_context(results: list[SearchResult], max_chars: int = 1600) -> str:
    """Suchergebnisse kompakt fuer den Prompt des kleinen Modells."""
    parts = []
    used = 0
    for i, r in enumerate(results, 1):
        entry = f"[{i}] {r.title} ({r.source}): {r.snippet}"
        if used + len(entry) > max_chars:
            entry = entry[: max(0, max_chars - used)]
        if not entry:
            break
        parts.append(entry)
        used += len(entry)
    return "\n".join(parts)
