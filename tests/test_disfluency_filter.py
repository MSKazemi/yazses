"""Tests for the offline disfluency filter."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from yazses.config import DisfluencyConfig
from yazses.stt.filters.disfluency import filter_transcript

CORPUS_PATH = Path(__file__).parent / "fixtures" / "disfluency" / "corpus.json"


def load_corpus():
    with open(CORPUS_PATH) as f:
        return json.load(f)


@pytest.mark.parametrize("entry", load_corpus(), ids=lambda e: e["notes"][:40])
def test_corpus(entry):
    config = DisfluencyConfig()
    result = filter_transcript(entry["input"], config)
    assert result.text == entry["expected"], (
        f"Input: {entry['input']!r}\n"
        f"Expected: {entry['expected']!r}\n"
        f"Got: {result.text!r}"
    )


def test_runtime_under_10ms():
    config = DisfluencyConfig()
    text = "um so I uh need to basically uh you know delete last line uh right okay so"
    t0 = time.perf_counter()
    for _ in range(100):
        filter_transcript(text, config)
    elapsed_ms = (time.perf_counter() - t0) / 100 * 1000
    assert elapsed_ms < 10, f"filter_transcript took {elapsed_ms:.2f} ms (> 10 ms)"


def test_proper_nouns_unchanged():
    config = DisfluencyConfig()
    text = "Hello Python is great"
    result = filter_transcript(text, config)
    assert "Python" in result.text


def test_code_identifiers_unchanged():
    config = DisfluencyConfig()
    text = "call the function_name here"
    result = filter_transcript(text, config)
    assert "function_name" in result.text


def test_disabled_filter_passthrough():
    config = DisfluencyConfig(enabled=False)
    text = "um hello um world"
    result = filter_transcript(text, config)
    assert result.text == text
    assert result.chars_removed == 0


def test_chars_removed_counted():
    config = DisfluencyConfig()
    text = "um hello world"
    result = filter_transcript(text, config)
    assert result.chars_removed > 0


def test_empty_input():
    config = DisfluencyConfig()
    result = filter_transcript("", config)
    assert result.text == ""
    assert result.chars_removed == 0


def test_custom_filler_words():
    config = DisfluencyConfig(filler_words=["actually", "honestly"])
    text = "I actually honestly think this is good"
    result = filter_transcript(text, config)
    assert "actually" not in result.text
    assert "honestly" not in result.text
    assert "think this is good" in result.text


# ---- Dysfluency-Friendly Mode: collapse passes (ADR-015) ------------------

from yazses.stt.filters.disfluency import (  # noqa: E402
    _collapse_prolongations,
    _collapse_repetitions,
)


def test_collapse_prolongation_basic():
    assert _collapse_prolongations("sooo good", 3) == "so good"


def test_collapse_prolongation_leaves_double_letters():
    assert _collapse_prolongations("see the tree", 3) == "see the tree"


def test_collapse_prolongation_protects_caps_and_code():
    assert _collapse_prolongations("HELLOOO obj.attr", 3) == "HELLOOO obj.attr"


def test_collapse_prolongation_noop_below_min_run():
    assert _collapse_prolongations("soo good", 3) == "soo good"


def test_collapse_hyphen_false_start():
    assert _collapse_repetitions("b-b-because i can", 2) == "because i can"


def test_collapse_space_fragment_run():
    assert _collapse_repetitions("st st stop now", 2) == "stop now"


def test_collapse_unigram_triple():
    assert _collapse_repetitions("the the the cat", 2) == "the cat"


def test_repetition_preserves_intentional_hyphenation():
    assert _collapse_repetitions("re-read the co-op file", 2) == "re-read the co-op file"


def test_repetition_preserves_emphasis_pair():
    assert _collapse_repetitions("very very good", 2) == "very very good"


def test_repetition_protects_caps_and_code():
    assert _collapse_repetitions("I I think foo_bar", 2) == "I I think foo_bar"


# ---- Dysfluency collapse integrated into filter_transcript (ADR-015) ------

def test_filter_default_does_not_collapse():
    cfg = DisfluencyConfig()
    assert filter_transcript("b-b-because sooo good", cfg).text == "b-b-because sooo good"


def test_filter_collapses_when_enabled():
    cfg = DisfluencyConfig(collapse_repetitions=True, collapse_prolongations=True)
    assert filter_transcript("b-b-because it is sooo good", cfg).text == "because it is so good"


def test_filter_collapse_respects_protection_end_to_end():
    cfg = DisfluencyConfig(collapse_repetitions=True, collapse_prolongations=True)
    out = filter_transcript("call FooBar and re-read obj.attr", cfg).text
    assert "FooBar" in out and "re-read" in out and "obj.attr" in out
