"""Polyglot Switch P0 — LID routing scaffolding (design/v2-cognitive-layer §3.4).

The dependency-free scaffolding for code-switch transcription: parse the configured
language pair, pick the dominant language of a span, and detect whether an utterance
is code-switched. The CS-adapted model itself needs training and is gated; this is the
routing plumbing that slots it in.
"""
from __future__ import annotations

import pytest

from yazses.polyglot.lid import dominant_language, is_code_switched, parse_pair

# ---- parse_pair ------------------------------------------------------------

def test_parse_valid_pair():
    assert parse_pair("fa-en") == ("fa", "en")


def test_parse_pair_rejects_garbage():
    for bad in ("", "english", "fa_en", "fa-en-de"):
        with pytest.raises(ValueError):
            parse_pair(bad)


# ---- dominant_language -----------------------------------------------------

def test_dominant_language_picks_argmax():
    assert dominant_language({"fa": 0.7, "en": 0.3}) == "fa"
    assert dominant_language({"fa": 0.2, "en": 0.8}) == "en"


def test_dominant_language_empty_is_none():
    assert dominant_language({}) is None


# ---- is_code_switched ------------------------------------------------------

def test_monolingual_spans_are_not_code_switched():
    assert is_code_switched(["en", "en", "en"], ("fa", "en")) is False


def test_mixed_pair_spans_are_code_switched():
    assert is_code_switched(["en", "fa", "en"], ("fa", "en")) is True


def test_languages_outside_the_pair_are_ignored():
    # A stray 'de' span isn't part of the configured pair → not a CS event for it.
    assert is_code_switched(["en", "de", "en"], ("fa", "en")) is False
