from conftest import FakeBridge

import display as tft


def test_sanitize_keeps_umlauts_and_replaces_typography():
    assert tft.sanitize("Grüße – „Test“ … 20 °C, café") == 'Grüße - "Test" ... 20 °C, cafe'


def test_wrap_respects_width_and_words():
    text = "Der Eiffelturm ist ein 330 Meter hoher Eisenfachwerkturm in Paris."
    lines = tft.wrap(text, 26)
    assert all(len(line) <= 26 for line in lines)
    assert " ".join(lines) == text


def test_wrap_splits_long_words():
    lines = tft.wrap("Donaudampfschifffahrtsgesellschaftskapitaensmuetze", 20)
    assert all(len(line) <= 20 for line in lines)
    assert "".join(line.rstrip("-") for line in lines) == "Donaudampfschifffahrtsgesellschaftskapitaensmuetze"


def test_paginate():
    lines = [str(i) for i in range(23)]
    pages = tft.paginate(lines, 10)
    assert [len(p) for p in pages] == [10, 10, 3]


def test_display_only_redraws_changed_lines():
    FakeBridge.calls.clear()
    d = tft.Display(FakeBridge, console=False)
    d.lines(["eins", "zwei"])
    first = len(FakeBridge.calls)
    d.lines(["eins", "drei"])
    changed = FakeBridge.calls[first:]
    assert [args[2] for _, args in changed] == ["drei"]


def test_text_fits_on_screen():
    FakeBridge.calls.clear()
    d = tft.Display(FakeBridge, console=False)
    d.new_screen("Antwort", tft.GREEN, "Fuss")
    d.text("Wort " * 100)
    for method, args in FakeBridge.calls:
        if method == "ui_text":
            x, y, text, fg, bg, scale, width = args
            assert x + len(text) * 6 * scale <= tft.WIDTH
            assert y + 8 * scale <= tft.HEIGHT


def test_display_without_sketch_does_not_raise():
    class Broken:
        @staticmethod
        def call(*args, **kwargs):
            raise TimeoutError("kein Sketch")

    d = tft.Display(Broken, console=False)
    d.new_screen("Test", tft.GREEN)
    d.text("Hallo")
    assert not d.available
