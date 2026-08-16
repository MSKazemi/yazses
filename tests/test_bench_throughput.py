"""The throughput harness's metrics (`paper/benchmark/bench_throughput.py`).

This is the instrument for the one comparison the project has always declined to
guess at — dictation against typing — and it is the reason the T11 spec puts a
*measurement* before any feature. So its arithmetic is worth pinning: a harness
that reports a wrong number is worse than none, because the number gets quoted.

The I/O is driven through injected `reader`/`clock`, so a session runs here with
no participant, no microphone and no terminal.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "paper" / "benchmark" / "bench_throughput.py"


@pytest.fixture(scope="module")
def bench():
    """Load the script as a module.

    Registered in `sys.modules` before executing: `@dataclass` resolves its own
    module by name at class-creation time, and without the entry it raises
    AttributeError on None — which surfaces as fifteen collection errors rather
    than anything resembling the cause.
    """
    import sys

    spec = importlib.util.spec_from_file_location("bench_throughput", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["bench_throughput"] = module
    spec.loader.exec_module(module)
    return module


def test_entry_rate_uses_the_five_character_word(bench) -> None:
    """The entry-rate literature counts a 'word' as five characters. Using
    whitespace-delimited words would make every comparison against a published
    typing figure wrong in a direction nobody would notice."""
    # 50 characters in 60 seconds = 10 five-char words per minute.
    assert bench.words_per_minute("x" * 50, 60.0) == pytest.approx(10.0)


def test_a_zero_duration_does_not_divide_by_zero(bench) -> None:
    assert bench.words_per_minute("hello", 0.0) == 0.0


def test_a_perfect_transcript_scores_no_error(bench) -> None:
    assert bench.error_rate_pct("the quick brown fox", "the quick brown fox") == 0.0


def test_surrounding_whitespace_is_not_an_error(bench) -> None:
    """Dictation injects a leading space between bursts by design; counting that
    as an error would penalise the feature that exists to be correct."""
    assert bench.error_rate_pct("hello world", "  hello world  ") == 0.0


def test_a_wrong_word_is_measured_not_rounded_away(bench) -> None:
    rate = bench.error_rate_pct("send it to Nadia", "send it to Nadya")
    assert 0 < rate < 20


def test_two_empty_strings_are_not_an_error(bench) -> None:
    assert bench.error_rate_pct("", "") == 0.0


def test_edit_distance_is_symmetric_and_zero_on_equality(bench) -> None:
    assert bench.levenshtein("abc", "abc") == 0
    assert bench.levenshtein("abc", "abd") == bench.levenshtein("abd", "abc") == 1
    assert bench.levenshtein("", "abc") == 3


def test_a_session_summarises_into_quotable_numbers(bench) -> None:
    session = bench.Session(mode="typing")
    session.trials = [
        bench.Trial("hello world", "hello world", 6.0),
        bench.Trial("goodbye now", "goodbye now", 6.0),
    ]
    out = bench.summarise(session)
    assert out["n_trials"] == 2
    assert out["mode"] == "typing"
    assert out["wpm_median"] > 0
    assert out["uncorrected_error_rate_pct_mean"] == 0.0


def test_the_result_records_that_one_person_is_a_pilot(bench) -> None:
    """The whole failure this project keeps correcting is a number quoted without
    its conditions. A single-participant figure must carry that fact in the file."""
    session = bench.Session(mode="dictation")
    session.trials = [bench.Trial("hello", "hello", 3.0)]
    assert bench.summarise(session)["n_participants"] == 1


def test_an_empty_session_reports_nothing_rather_than_zero(bench) -> None:
    """Zero WPM would read as a measurement. No trials is the absence of one."""
    out = bench.summarise(bench.Session(mode="typing"))
    assert out == {"n_trials": 0}


def test_a_typing_session_runs_without_a_participant(bench) -> None:
    answers = iter(["the quick brown fox jumps over the lazy dog", "please call me back"])
    ticks = iter([0.0, 5.0, 5.0, 9.0])
    session = bench.run_typing(
        bench.PHRASES[:2], reader=lambda _p: next(answers), clock=lambda: next(ticks)
    )
    assert len(session.trials) == 2
    assert session.trials[0].seconds == 5.0


def test_a_dictation_session_records_corrections(bench) -> None:
    replies = iter(["hello world", "2", "goodbye", "0"])
    ticks = iter([0.0, 4.0, 4.0, 7.0])
    session = bench.run_dictation(
        bench.PHRASES[:2], reader=lambda _p: next(replies), clock=lambda: next(ticks)
    )
    assert [t.corrections for t in session.trials] == [2, 0]


def test_a_non_numeric_correction_count_does_not_crash_the_run(bench) -> None:
    """Mid-study, a mistyped answer must not lose the trials already recorded."""
    replies = iter(["hello world", "dunno"])
    session = bench.run_dictation(
        bench.PHRASES[:1], reader=lambda _p: next(replies), clock=lambda: 0.0
    )
    assert session.trials[0].corrections == 0


def test_the_phrase_set_covers_what_actually_breaks(bench) -> None:
    """A phrase set of clean prose measures a tool nobody uses. Numbers, proper
    nouns, code and a bilingual line are where dictation is hard."""
    joined = " ".join(bench.PHRASES).lower()
    # Written out rather than as a clever comprehension: the first version of this
    # line iterated an empty string, so `any()` was always False — the vacuous
    # guard this repo keeps finding, in the test that checks for them.
    assert "four one nine" in joined, "no spoken-number phrase in the set"
    assert "sixty two euros" in joined, "no currency phrase in the set"
    assert "nadia" in joined, "no proper noun in the phrase set"
    assert "none" in joined and "function" in joined, "no code-shaped phrase"
    assert "salam" in joined, "no bilingual phrase"


def test_dry_run_needs_no_dependencies(bench) -> None:
    """It must run on a checkout that has not installed the benchmark group —
    otherwise the first thing a curious contributor tries fails."""
    assert bench.main(["--mode", "typing", "--dry-run"]) == 0
