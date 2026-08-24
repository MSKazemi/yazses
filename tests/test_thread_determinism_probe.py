"""Guards for the thread-determinism probe.

The probe exists because two facts did not fit "sampling is the cause": `base.en` is
bit-identical across five baseline decodes yet does reach the temperature fallback, and
running the mechanism probe twice unchanged counted six rejected decode attempts and
then four. Rejection happens on the *greedy* first attempt, before anything is sampled,
so a deterministic decode cannot produce both numbers.

These pin the conclusions, which is where a probe like this goes wrong: it is very easy
to write one that reports a cause when the corpus simply never showed the effect.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1] / "paper" / "benchmark"
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "probes"))

pytest.importorskip("jiwer")
mod = pytest.importorskip("thread_determinism")


def _run(sha: str, fallbacks: int = 0, wer: float = 9.0, secs: float = 100.0) -> dict:
    return {
        "wer": wer,
        "hypothesis_sha256_16": sha,
        "fallback_events": fallbacks,
        "decode_seconds_total": secs,
    }


def test_the_arms_are_the_shipping_default_against_one_thread():
    assert mod.THREAD_ARMS == {"default": 0, "single": 1}, (
        "0 is CTranslate2's own choice and is what [stt] cpu_threads ships as; the "
        "comparison is only meaningful against what users actually run"
    )


def test_summarise_counts_distinct_hypotheses_not_equal_wers():
    """Two runs can share a WER and differ in text — the earlier large-v3 work turned
    on exactly that, so reproducibility must be judged on the hash."""
    runs = [_run("aaaa", wer=9.46), _run("bbbb", wer=9.46)]
    s = mod.summarise(runs)
    assert s["distinct_hypotheses"] == 2
    assert s["reproducible"] is False


def test_summarise_reports_a_varying_rejection_count():
    s = mod.summarise([_run("a", 6), _run("a", 4), _run("a", 4)])
    assert s["fallback_events_range"] == [4, 6]
    assert s["fallback_events_vary"] is True
    assert s["reproducible"] is True, "the text can be stable while the path to it is not"


def test_a_stable_rejection_count_is_not_reported_as_varying():
    s = mod.summarise([_run("a", 2), _run("a", 2)])
    assert s["fallback_events_vary"] is False
    assert s["fallback_events_range"] == [2, 2]


def _stub(monkeypatch, default_runs: list[dict], single_runs: list[dict]) -> None:
    monkeypatch.setattr(mod, "librispeech_subset",
                        lambda *a, **k: [("u1", Path("x"), "hello world", 4.0)])
    monkeypatch.setattr(mod, "load_audio", lambda p: None)
    monkeypatch.setattr(mod, "subset_digest", lambda ids: "deadbeef")
    seq = {"default": list(default_runs), "single": list(single_runs)}
    monkeypatch.setattr(mod, "_one_run",
                        lambda model, threads, subset, audio, refs:
                        seq["single" if threads == 1 else "default"].pop(0))


def test_pinning_is_only_credited_when_the_default_actually_moved(monkeypatch):
    """The failure mode this file exists for.

    If the default arm is already reproducible, a stable single-thread arm shows
    nothing — the corpus never exhibited the instability. Reporting "pinning fixes it"
    there would be a cause invented from an absence.
    """
    stable = [_run("aaaa"), _run("aaaa")]
    _stub(monkeypatch, list(stable), list(stable))
    f = mod.run("test-clean", "base.en", 1, 2)["finding"]
    assert f["pinning_threads_fixes_it"] is False
    assert "cannot separate the two causes" in f["reading"]


def test_pinning_is_credited_when_it_does_fix_a_moving_default(monkeypatch):
    _stub(monkeypatch,
          [_run("aaaa", 6), _run("bbbb", 4)],
          [_run("cccc", 3, secs=400.0), _run("cccc", 3, secs=400.0)])
    f = mod.run("test-clean", "base.en", 1, 2)["finding"]
    assert f["pinning_threads_fixes_it"] is True
    assert f["single_thread_slowdown"] == 4.0
    assert "thread-scheduling order in the CPU kernels" in f["reading"]
    assert "not a default" in f["reading"], "the slowdown must not be buried"
    assert "varies across identical" in f["reading"]


def test_it_says_so_when_one_thread_is_still_not_reproducible(monkeypatch):
    """The hypothesis losing must read as the hypothesis losing."""
    _stub(monkeypatch,
          [_run("aaaa"), _run("bbbb")],
          [_run("cccc"), _run("dddd")])
    f = mod.run("test-clean", "base.en", 1, 2)["finding"]
    assert f["pinning_threads_fixes_it"] is False
    assert "not the whole cause" in f["reading"]


def test_the_artifact_says_what_it_measured(monkeypatch):
    _stub(monkeypatch, [_run("aaaa")], [_run("aaaa")])
    payload = mod.run("test-clean", "base.en", 1, 1)
    assert payload["probe"]["measured"].strip()
    assert payload["probe"]["produced_by"].endswith("thread_determinism.py")
    assert payload["config"]["arms"] == {"default": "cpu_threads=0", "single": "cpu_threads=1"}
