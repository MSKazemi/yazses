"""Tests for inter-utterance continuation spacing (root-cause fix for burst gluing).

The daemon injects each hold-to-talk burst independently. Without a separator,
the last word of one burst glues to the first word of the next:
"words together" + "I mean" -> "words togetherI mean". These tests pin the
smart-leading-space policy: prepend a space when continuing a recent dictation,
but suppress it before closing punctuation.

Since #551 the suppression set is script-aware (contract 7.0.0, MAJOR): the
Persian closing marks ، ؟ ؛ and the closing guillemet » suppress like their
Latin cousins, and the probe skips invisible format characters (ZWNJ, bidi
controls, BOM) before deciding.
"""
from yazses.postprocess.spacing import continuation_prefix

PERSIAN_COMMA = "\u060C"     # ،
PERSIAN_QUESTION = "\u061F"  # ؟
PERSIAN_SEMICOLON = "\u061B"  # ؛
CLOSING_GUILLEMET = "\u00BB"  # »
OPENING_GUILLEMET = "\u00AB"  # «
ZWNJ = "\u200C"
RLE = "\u202B"


def test_no_prefix_when_no_recent_injection():
    # First burst of a session — never prepend a space.
    assert continuation_prefix("hello world", had_recent_injection=False) == ""


def test_prepends_space_when_continuing():
    assert continuation_prefix("this is me", had_recent_injection=True) == " "


def test_suppresses_space_before_closing_punctuation():
    for punct in [".", ",", "!", "?", ";", ":", ")"]:
        assert continuation_prefix(punct + " done", had_recent_injection=True) == "", punct


def test_empty_text_gets_no_prefix():
    assert continuation_prefix("", had_recent_injection=True) == ""


def test_space_before_opening_quote_or_paren_is_kept():
    # A new clause that starts with an opening delimiter still wants a leading space.
    assert continuation_prefix('"quoted"', had_recent_injection=True) == " "
    assert continuation_prefix("(aside)", had_recent_injection=True) == " "


# ── #551: script-aware suppression (contract 7.0.0) ──────────────────────────


def test_suppresses_space_before_persian_closing_punctuation():
    # "word" + "، بعداً" must render "word، بعداً", not "word ، بعداً".
    for punct in [PERSIAN_COMMA, PERSIAN_QUESTION, PERSIAN_SEMICOLON,
                  CLOSING_GUILLEMET]:
        assert continuation_prefix(punct + " بعداً", had_recent_injection=True) == "", punct


def test_keeps_space_before_opening_guillemet():
    # U+00AB « opens; the deliberate asymmetry covers it like ASCII quotes.
    assert continuation_prefix(OPENING_GUILLEMET + "نقل قول", had_recent_injection=True) == " "


def test_probe_skips_leading_zwnj_to_find_persian_comma():
    # A ZWNJ leading the burst joins into the previous word; the visible
    # character behind it decides. The comma still suppresses the space.
    assert continuation_prefix(ZWNJ + PERSIAN_COMMA + " بعداً", had_recent_injection=True) == ""


def test_probe_skips_leading_bidi_control_to_find_ascii_comma():
    assert continuation_prefix(RLE + ", done", had_recent_injection=True) == ""


def test_leading_zwnj_before_a_word_still_gets_space():
    # Joining across a boundary ZWNJ is a normalization decision
    # (persian_text strips boundary ZWNJ), not a spacing one: the burst's
    # first visible character is a word, so the separator is kept.
    assert continuation_prefix(ZWNJ + "سلام", had_recent_injection=True) == " "


def test_leading_bidi_control_before_a_word_still_gets_space():
    assert continuation_prefix(RLE + "سلام", had_recent_injection=True) == " "


def test_all_invisible_burst_falls_back_to_space():
    # Only format characters: nothing visible to suppress on — keep the
    # ordinary separator rather than guessing.
    assert continuation_prefix(ZWNJ + RLE, had_recent_injection=True) == " "
