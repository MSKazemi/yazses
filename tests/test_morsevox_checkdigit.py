"""Vocal Morse (ADR-v2-105) + Checksum-Validated Entry (ADR-v2-106) — pure cores."""
from __future__ import annotations

import pytest

from yazses.checkdigit.validate import suggest_fix, validate
from yazses.morsevox.decode import (
    MorseCalib,
    MorseDecoder,
    adapt_dot_threshold,
    classify_gap,
    classify_pulse,
)

# ---- vocal morse -----------------------------------------------------------

def test_classify_pulse_and_gap():
    c = MorseCalib()
    assert classify_pulse(100, c) == "dot"
    assert classify_pulse(400, c) == "dash"
    assert classify_gap(300, c) == "gap_symbol"
    assert classify_gap(700, c) == "gap_letter"
    assert classify_gap(1500, c) == "gap_word"


def test_morse_decoder_spells_word():
    d = MorseDecoder()
    # "sos" = ... --- ...
    for sym in ["dot", "dot", "dot"]:
        assert d.feed(sym) is None
    assert d.feed("gap_letter") == "s"
    for sym in ["dash", "dash", "dash"]:
        d.feed(sym)
    assert d.feed("gap_letter") == "o"
    for sym in ["dot", "dot", "dot"]:
        d.feed(sym)
    assert d.feed("gap_word") == "s "        # word gap → char + space
    assert d.feed("nonsense") is None         # unknown token
    assert d.feed("gap_letter") is None       # empty buffer → None


def test_adapt_dot_threshold():
    c = MorseCalib(dot_max_ms=200.0)
    adapted = adapt_dot_threshold([90, 100, 110, 500, 520, 540], c, alpha=1.0)
    # boundary ≈ (100 + 520)/2 = 310 → dot_max moves toward it
    assert 250 < adapted.dot_max_ms < 360
    assert adapt_dot_threshold([100], c) is c        # too few → unchanged
    assert adapt_dot_threshold([], c) is c


# ---- checksum-validated entry ----------------------------------------------

def test_validate_luhn_and_isbn():
    assert validate("4539 1488 0343 6467", "luhn")[0] is True    # valid test Visa
    assert validate("4539 1488 0343 6468", "luhn")[0] is False
    assert validate("0-306-40615-2", "isbn10")[0] is True
    assert validate("978-0-306-40615-7", "isbn13")[0] is True
    assert validate("2363", "verhoeff")[0] is True
    ok, norm = validate("4539-1488", "luhn")
    assert norm == "45391488"


def test_validate_unknown_scheme_raises():
    with pytest.raises(ValueError):
        validate("123", "mystery")


def test_validate_length_and_char_guards():
    assert validate("123", "isbn13")[0] is False        # wrong length
    assert validate("123", "isbn10")[0] is False        # wrong length
    assert validate("030640615Q", "isbn10")[0] is False  # invalid char in body
    assert validate("", "verhoeff")[0] is False          # empty


def test_suggest_fix_skips_nondigit_position():
    # ISBN-10 ending in 'X' — the X position is skipped, no crash
    assert isinstance(suggest_fix("030640615X", "isbn10"), list)


def test_suggest_fix():
    fixes = suggest_fix("4539 1488 0343 6468", "luhn")   # off-by-one last digit
    assert "4539148803436467" in fixes                    # the true value is proposed
    assert isinstance(fixes, list)
    assert all(validate(f, "luhn")[0] for f in fixes)     # every suggestion actually validates


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "morsevox" in slugs and "checkdigit" in slugs
    assert Config().morsevox.enabled is False and Config().checkdigit.enabled is False
