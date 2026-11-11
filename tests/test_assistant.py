from assistant import Assistant, clean_answer, extract_search_query, is_unsure, needs_current_info
from websearch import SearchResult, format_context


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def chat_stream(self, message):
        self.prompts.append(message)
        yield from self.replies.pop(0)


def fake_search(results):
    calls = []

    def search(query, **kwargs):
        calls.append(query)
        return results

    search.calls = calls
    return search


RESULTS = [SearchResult("Wetter Berlin", "Heute 12 Grad und Regen.", "https://www.wetter.de/berlin")]


def test_needs_current_info():
    assert needs_current_info("wie wird das wetter heute in berlin")
    assert needs_current_info("was kostet ein bitcoin")
    assert not needs_current_info("wie hoch ist der eiffelturm")


def test_is_unsure():
    assert is_unsure("SUCHE: Wetter Berlin")
    assert is_unsure("Das weiß ich leider nicht.")
    assert is_unsure("")
    assert not is_unsure("Der Eiffelturm ist 330 Meter hoch.")


def test_extract_search_query():
    assert extract_search_query("SUCHE: Bundeskanzler Deutschland", "wer ist kanzler") == "Bundeskanzler Deutschland"
    assert extract_search_query("weiss nicht", "wer ist kanzler") == "wer ist kanzler"


def test_clean_answer():
    assert clean_answer("<think>hmm</think>**Paris** ist  die Hauptstadt.") == "Paris ist die Hauptstadt."


def test_local_answer_without_search():
    llm = ScriptedLLM([["Der Eiffelturm ", "ist 330 Meter hoch."]])
    search = fake_search(RESULTS)
    answer = Assistant(llm, search=search).answer("wie hoch ist der eiffelturm")
    assert answer.text == "Der Eiffelturm ist 330 Meter hoch."
    assert not answer.searched
    assert search.calls == []


def test_model_requests_search():
    llm = ScriptedLLM([["SUCHE: ", "Fussball Ergebnis"], ["Bayern hat 2:1 gewonnen."]])
    search = fake_search(RESULTS)
    answer = Assistant(llm, search=search).answer("wie hat bayern gespielt")
    assert answer.searched
    assert search.calls == ["Fussball Ergebnis"]
    assert answer.text == "Bayern hat 2:1 gewonnen."
    assert "Suchergebnisse" in llm.prompts[1]
    assert answer.sources == ["wetter.de"]


def test_current_question_searches_first():
    llm = ScriptedLLM([["In Berlin sind es 12 Grad."]])
    search = fake_search(RESULTS)
    answer = Assistant(llm, search=search).answer("wie ist das wetter heute in berlin")
    assert answer.searched and len(llm.prompts) == 1
    assert search.calls == ["wie ist das wetter heute in berlin"]


def test_search_failure_falls_back_to_model():
    llm = ScriptedLLM([["Ich weiß es nicht."]])
    answer = Assistant(llm, search=fake_search([])).answer("wer gewann 1954 die wm")
    assert answer.text == "Ich weiß es nicht."
    assert not answer.searched


def test_search_marker_never_shown_as_answer():
    llm = ScriptedLLM([["SUCHE: irgendwas"]])
    answer = Assistant(llm, search=fake_search([])).answer("frage")
    assert not answer.text.upper().startswith("SUCHE")


def test_web_disabled():
    llm = ScriptedLLM([["Weiß ich nicht."]])
    search = fake_search(RESULTS)
    Assistant(llm, web_enabled=False, search=search).answer("wetter heute")
    assert search.calls == []


def test_format_context_is_limited():
    many = [SearchResult(f"T{i}", "x" * 500, f"https://e{i}.de") for i in range(10)]
    assert len(format_context(many, max_chars=1000)) <= 1000 + 10
