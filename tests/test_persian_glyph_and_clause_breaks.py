"""SafeGlyph and the semantic-break splitter, on Persian (follow-up to the preservation sweep).

SafeGlyph is opt-in and only logs, so the cost of the old behaviour was a false "hidden
character" warning on every Persian dictation that contained a half-space, which teaches people
to ignore the guard. The splitter treated the ASCII semicolon as a clause end but not the Arabic
one (U+061B), though the Arabic question mark was already a sentence end.
"""

from __future__ import annotations

import pytest

from yazses.safeglyph.confusables import scan_confusables
from yazses.sembr.breaks import semantic_breaks

ZWNJ = "‌"
ZWJ = "‍"


@pytest.mark.parametrize(
    "text",
    ["می‌خواهم کتاب‌ها را بخوانم.", "خانه‌های بزرگ", "کتاب‌خانه"],
)
def test_a_half_space_between_persian_letters_is_not_a_hidden_character(text):
    assert scan_confusables(text) == []


def test_a_joiner_between_other_non_ascii_letters_is_not_flagged_either():
    assert scan_confusables("क" + ZWJ + "ष") == []            # Devanagari: ZWJ is spelling there too


@pytest.mark.parametrize(
    "text",
    [
        "pay" + ZWNJ + "pal",                 # hidden between ASCII letters: the attack
        "pay" + ZWJ + "pal",
        ZWNJ + "سلام",                        # at the start: no letter before it
        "سلام" + ZWNJ,                        # at the end: no letter after it
        "سلام" + ZWNJ + "1",                  # next to a digit
        "a" + ZWNJ + "سلام",                  # ASCII on one side
    ],
)
def test_a_joiner_anywhere_else_is_still_flagged(text):
    kinds = [f["kind"] for f in scan_confusables(text)]
    assert "invisible" in kinds


@pytest.mark.parametrize("char", ["​", "⁠", "﻿", "­"])
def test_the_other_invisible_characters_are_flagged_even_between_persian_letters(char):
    assert [f["kind"] for f in scan_confusables("سلام" + char + "دنیا")] == ["invisible"]


def test_a_real_homoglyph_inside_persian_text_is_still_found():
    text = "می‌خواهم pаypal را"                      # the 'а' is Cyrillic
    found = scan_confusables(text)
    assert {f["kind"] for f in found} == {"confusable", "mixed-script"}
    assert not any(f["kind"] == "invisible" for f in found)


def test_the_english_findings_are_unchanged():
    assert [f["kind"] for f in scan_confusables("pay​pal")] == ["invisible"]
    assert scan_confusables("plain ascii text") == []


# -- Arabic semicolon ------------------------------------------------------------------------


def test_the_arabic_semicolon_ends_a_clause_like_the_ascii_one():
    assert semantic_breaks("اول رفتم؛ بعد برگشتم") == "اول رفتم؛\nبعد برگشتم"
    assert semantic_breaks("first; second") == "first;\nsecond"


def test_the_arabic_question_mark_still_ends_a_sentence():
    assert semantic_breaks("حال شما خوب است؟ بله") == "حال شما خوب است؟\nبله"


def test_english_text_breaks_exactly_as_before():
    text = "Wait: it works. Does it? Yes; it does, and then it stops."
    assert semantic_breaks(text) == "Wait:\nit works.\nDoes it?\nYes;\nit does,\nand then it stops."
