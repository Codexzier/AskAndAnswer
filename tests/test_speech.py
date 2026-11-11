import numpy as np

from speech import SpeechEngine, normalize_vosk, to_pcm16_mono


def test_pcm_passthrough():
    data = np.arange(-5, 5, dtype=np.int16)
    out = to_pcm16_mono(data, 16000, 1)
    assert out.dtype == np.int16
    assert np.array_equal(out, data)


def test_pcm_stereo_float_resampled():
    t = np.linspace(0, 1, 48000, endpoint=False)
    mono = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    stereo = np.repeat(mono, 2)
    out = to_pcm16_mono(stereo, 48000, 2)
    assert out.dtype == np.int16
    assert len(out) == 16000
    assert 15000 < np.abs(out).max() <= 16384


def test_normalize_vosk_keeps_umlauts():
    assert normalize_vosk("Ich hätte eine Frage!") == "ich hätte eine frage"


def test_wake_grammar_uses_only_known_words():
    engine = SpeechEngine.__new__(SpeechEngine)
    vocabulary = {"auto", "audi", "ich", "habe", "eine", "frage", "starte", "aufnahme",
                  "die", "stoppe", "stopp"}
    engine.knows = lambda word: word in vocabulary
    grammar = engine.wake_grammar(["auda", "auto", "audi", "au da"])
    assert grammar[-1] == "[unk]"
    assert "auto ich habe eine frage" in grammar
    assert "audi starte aufnahme" in grammar
    assert "auto stoppe die aufnahme" in grammar
    assert not any(p.startswith("auda ") or p.startswith("au da ") for p in grammar)
    # Saetze mit unbekannten Woertern (z. B. "hab", "ne") fehlen
    assert not any(" ne " in p for p in grammar)


def test_wake_grammar_empty_when_no_wake_word_known():
    engine = SpeechEngine.__new__(SpeechEngine)
    engine.knows = lambda word: word in {"ich", "habe", "eine", "frage"}
    assert engine.wake_grammar(["auda"]) == []
