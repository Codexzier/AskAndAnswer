import pytest

from commands import (QUESTION, RECORD_START, RECORD_STOP, find_command, is_wake_word,
                      koelner_phonetik, normalize)


def test_normalize():
    assert normalize("AOUDA, ich hätte eine Frage!") == "aouda ich haette eine frage"


@pytest.mark.parametrize("word,code", [
    ("Müller-Lüdenscheidt", "65752682"),   # Referenzbeispiel der Koelner Phonetik
    ("Wikipedia", "3412"),
    ("auda", "02"),
    ("aouda", "02"),
])
def test_koelner_phonetik(word, code):
    assert koelner_phonetik(word) == code


@pytest.mark.parametrize("text", ["auda", "aouda", "outa", "auto", "au da", "audi", "oda"])
def test_wake_word_variants(text):
    assert is_wake_word(text)


@pytest.mark.parametrize("text", ["hallo", "frage", "oder", "ich", "danke"])
def test_not_wake_word(text):
    assert not is_wake_word(text)


def test_custom_wake_spelling():
    assert not is_wake_word("oder")
    assert is_wake_word("oder", ["oder"])


@pytest.mark.parametrize("text,command", [
    ("Auda, ich habe eine Frage", QUESTION),
    ("outa ich hab ne frage", QUESTION),
    ("aouda starte aufnahme", RECORD_START),
    ("auto starte die aufnahme", RECORD_START),
    ("au da stoppe die aufnahme", RECORD_STOP),
    ("auda stop aufnahme", RECORD_STOP),
])
def test_commands(text, command):
    match = find_command(text)
    assert match is not None
    assert match.command == command
    assert match.wake


def test_command_requires_wake_word():
    assert find_command("ich habe eine frage") is None
    match = find_command("ich habe eine frage", require_wake=False)
    assert match.command == QUESTION and not match.wake


def test_question_in_same_sentence():
    match = find_command("auda ich habe eine frage wie hoch ist der eiffelturm")
    assert match.command == QUESTION
    assert match.after == "wie hoch ist der eiffelturm"


def test_stop_inside_dictation_keeps_text_before():
    match = find_command("das war der letzte punkt auda stoppe aufnahme", [RECORD_STOP])
    assert match.command == RECORD_STOP
    assert match.before == "das war der letzte punkt"


def test_no_command_in_normal_speech():
    assert find_command("heute ist ein schoener tag und wir gehen spazieren") is None
