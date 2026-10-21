"""Vocal Morse core (ADR-v2-105) — `morsevox/decode.py` on its own.

The happy-path checks for this module live in `test_morsevox_checkdigit.py`, which shares
a file with an unrelated feature. This file pins the edges that file does not: every code
in the table, the threshold boundaries (inclusive on which side), unknown codes, and what
`adapt_dot_threshold` keeps and ignores. Pure module, no mocks.
"""
from __future__ import annotations

import string

import pytest

from yazses.morsevox.decode import (
    _MORSE,
    MorseCalib,
    MorseDecoder,
    adapt_dot_threshold,
    classify_gap,
    classify_pulse,
)


def _feed_code(dec: MorseDecoder, code: str, gap: str = "gap_letter"):
    for ch in code:
        assert dec.feed("dot" if ch == "." else "dash") is None
    return dec.feed(gap)


def test_table_covers_letters_and_digits_once_each():
    assert sorted(_MORSE.values()) == sorted(string.ascii_lowercase + string.digits)
    assert len(set(_MORSE)) == len(_MORSE) == 36
    # A few anchors from the ITU table, so the table is not only checked against itself.
    assert {_MORSE[".-"], _MORSE["-..."], _MORSE["..."], _MORSE["---"], _MORSE["-----"]} == {
        "a", "b", "s", "o", "0"}


@pytest.mark.parametrize("code,char", sorted(_MORSE.items()))
def test_every_code_decodes(code, char):
    assert _feed_code(MorseDecoder(), code) == char


def test_pulse_boundary_is_inclusive_for_dot():
    c = MorseCalib(dot_max_ms=200.0)
    assert classify_pulse(200.0, c) == "dot"
    assert classify_pulse(200.001, c) == "dash"
    assert classify_pulse(0.0, c) == "dot"


def test_gap_boundaries_are_inclusive_for_the_longer_gap():
    c = MorseCalib(letter_gap_ms=600.0, word_gap_ms=1400.0)
    assert classify_gap(599.9, c) == "gap_symbol"
    assert classify_gap(600.0, c) == "gap_letter"
    assert classify_gap(1399.9, c) == "gap_letter"
    assert classify_gap(1400.0, c) == "gap_word"


def test_unknown_code_is_dropped_at_letter_gap_and_still_spaces_at_word_gap():
    assert _feed_code(MorseDecoder(), "......") is None          # six dots: not a code
    assert _feed_code(MorseDecoder(), "......", "gap_word") == " "


def test_decoder_resets_between_letters():
    dec = MorseDecoder()
    assert _feed_code(dec, ".-") == "a"
    assert _feed_code(dec, "-...") == "b"        # not ".--..." carried over
    assert dec.feed("gap_symbol") is None        # symbol gaps are not boundaries


def test_adapt_keeps_gap_thresholds_and_respects_alpha():
    c = MorseCalib(dot_max_ms=200.0, letter_gap_ms=700.0, word_gap_ms=1500.0)
    d = [100, 100, 100, 500, 500, 500]           # boundary exactly 300
    full = adapt_dot_threshold(d, c, alpha=1.0)
    assert full.dot_max_ms == pytest.approx(300.0)
    assert (full.letter_gap_ms, full.word_gap_ms) == (700.0, 1500.0)
    assert adapt_dot_threshold(d, c, alpha=0.0).dot_max_ms == pytest.approx(200.0)
    assert adapt_dot_threshold(d, c, alpha=0.5).dot_max_ms == pytest.approx(250.0)


def test_adapt_ignores_non_positive_durations_and_none():
    c = MorseCalib()
    assert adapt_dot_threshold(None, c) is c
    assert adapt_dot_threshold([0, -5, 120], c) is c              # one usable value
    with_junk = adapt_dot_threshold([0, -1, 100, 500], c, alpha=1.0)
    assert with_junk.dot_max_ms == pytest.approx(300.0)
