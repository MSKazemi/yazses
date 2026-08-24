"""Guards for the `initial_prompt` vs `condition_on_previous_text` probe.

The probe exists because a LibriSpeech WER win cannot see whether a decode change
disables YazSes's personal vocabulary — the benchmark decodes with no prompt at all.
Its first version answered the wrong question: it split the long clip at a fixed *word
count*, which sits deep inside the first 30 s window, so a prompt effect within window
one was reported as an effect after window one. The measurement contradicted the source
reading, and the probe was what was wrong.

These pin the split and the honesty of the conclusion, not the decoding.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1] / "paper" / "benchmark"
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "probes"))

pytest.importorskip("jiwer")
mod = pytest.importorskip("prompt_survives_no_context")


class W:
    def __init__(self, text, start):
        self.text, self.start = text, start
        self.end = start + 0.1
        self.probability = 1.0


def test_the_split_is_a_time_not_a_word_count():
    """The regression this file exists for.

    Eighty words inside the window and forty after it: a count-based split would put
    most of window one on the wrong side of the boundary.
    """
    words = [W(f"w{i}", i * 0.35) for i in range(80)] + [W(f"x{i}", 31.0 + i * 0.2) for i in range(40)]
    head, tail = mod._split_at_window(words)
    assert head.split()[0] == "w0" and head.split()[-1] == "w79"
    assert tail.split() == [f"x{i}" for i in range(40)]


def test_a_word_exactly_on_the_boundary_belongs_after_it():
    head, tail = mod._split_at_window([W("a", 29.999), W("b", 30.0)])
    assert head == "a" and tail == "b"


def test_a_single_window_clip_has_an_empty_tail():
    head, tail = mod._split_at_window([W("a", 1.0), W("b", 2.0)])
    assert head == "a b" and tail == ""


def test_the_boundary_is_the_whisper_window():
    assert mod.WINDOW_S == 30.0, (
        "the split must match Whisper's 30 s window; a different value silently "
        "compares the wrong halves"
    )


def test_the_bias_prompt_cannot_be_confused_with_the_audio():
    """A real English phrase could appear for acoustic reasons, making any change
    unattributable to the prompt."""
    import re
    assert not re.search(r"\b(the|and|of|to|a|in)\b", mod.BIAS.lower()), (
        "the bias prompt contains ordinary words, so a change in the output is no "
        "longer attributable to the prompt rather than to the speech"
    )


def test_the_archived_result_does_not_claim_more_than_it_measured():
    """The long-file half is only informative if the ON arm reaches past the boundary.

    If it does not, both arms look identical after the window for a reason unrelated to
    the setting, and the artifact must say so rather than crediting the arm.
    """
    import json
    art = (Path(__file__).resolve().parents[1] / "paper" / "results" / "probes"
           / "prompt-vs-no-context-small.en-test-clean.json")
    if not art.is_file():
        pytest.skip("artifact not present in this checkout")
    f = json.loads(art.read_text())["finding"]
    if not f["long_file_case_is_discriminating"]:
        assert "inconclusive" in f["reading"], (
            "the long-file case could not separate the two settings, but the recorded "
            "reading does not say so"
        )
    assert f["prompt_still_applies_to_a_single_window"] is True, (
        "if this is ever False, the decode change disables the personal dictionary on "
        "the dictation path and must not ship there"
    )


def test_the_tail_comparison_is_not_vacuous_in_the_archived_result():
    """`prompt_changed_after_first_window = False` means nothing over an empty tail."""
    import json
    art = (Path(__file__).resolve().parents[1] / "paper" / "results" / "probes"
           / "prompt-vs-no-context-small.en-test-clean.json")
    if not art.is_file():
        pytest.skip("artifact not present in this checkout")
    for name in ("long_condition_true", "long_condition_false"):
        case = json.loads(art.read_text())["cases"][name]
        assert case["words_after_first_window"] > 0, (
            f"{name} has no words past the 30 s boundary, so its "
            "'unchanged after the first window' result is vacuous"
        )
