"""One engine's exception cost five completed models their results.

The `full` WER matrix runs eight checkpoints across three engines and writes its JSON
after the last one. On 2026-08-23 it scored tiny.en, base.en, small.en, medium.en,
large-v3 and Parakeet over roughly ninety minutes, then reached `moonshine/tiny`, which
raised `AssertionError: audio should be of shape [batch, samples]` on its first
utterance — and the run produced **nothing at all**. The engine bug is fixed; the
harness property that turned it into total loss is fixed here.

Two failure points, because they are different events:

* **load** — weights missing, an extra not installed, a converter that will not open the
  file. Nothing has been measured yet.
* **decode** — the engine loaded and then raised part-way through the subset. This one
  must *not* be scored on what it managed first: a WER computed over the utterances an
  engine survived is a number for an engine that does not work, and it would sit in the
  table looking exactly like a real one.

A failed engine is recorded in `results["failed"]` rather than dropped, so "absent from
the table" and "silently skipped" cannot be confused — a reader checks that key before
treating the matrix as complete.

No model is downloaded here. `_build` is replaced, which is the same seam
`test_bench_wer_thread_count.py` uses, so this runs in CI where the benchmark cannot.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1] / "paper" / "benchmark"


@pytest.fixture(scope="module")
def bench_wer():
    pytest.importorskip("jiwer")
    pytest.importorskip("whisper_normalizer")
    if str(BENCH) not in sys.path:
        sys.path.insert(0, str(BENCH))
    spec = importlib.util.spec_from_file_location("bench_wer", BENCH / "bench_wer.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_wer"] = module
    spec.loader.exec_module(module)
    return module


class _Engine:
    """Transcribes, or raises at a chosen utterance index."""

    def __init__(self, fail_at: int | None = None) -> None:
        self._fail_at, self._n = fail_at, 0

    def transcribe(self, audio, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        self._n += 1
        if self._fail_at is not None and self._n >= self._fail_at:
            raise RuntimeError("audio should be of shape [batch, samples]")
        return "the quick brown fox"


def _install(bench_wer, monkeypatch, behaviour: dict) -> None:
    def fake_build(engine_name, model_name, cpu_threads):  # noqa: ANN001
        what = behaviour[engine_name]
        if what == "raise-on-load":
            raise RuntimeError("weights not found")
        return _Engine(fail_at=what if isinstance(what, int) else None)

    monkeypatch.setattr(bench_wer, "_build", fake_build)
    monkeypatch.setattr(bench_wer, "load_audio", lambda _path: b"")


def _subset(bench_wer, monkeypatch, n: int = 4) -> None:
    """Fixed references, so no LibriSpeech checkout is needed."""
    rows = [(f"utt-{i}", Path(f"/nonexistent/{i}.flac"), "the quick brown fox", 1.0)
            for i in range(n)]
    monkeypatch.setattr(
        bench_wer,
        "librispeech_subset",
        lambda _n, stratified=True, split="test-clean": rows,
    )


def test_a_working_engine_still_reports_when_a_later_one_dies(bench_wer, monkeypatch):
    """The regression, in one sentence: the good result must survive the bad one."""
    _subset(bench_wer, monkeypatch)
    _install(bench_wer, monkeypatch, {"ok": None, "dies": 2})
    result = bench_wer.run(4, [("good", "ok", "m"), ("broken", "dies", "m")], cpu_threads=1)
    assert sorted(result["models"]) == ["good"], result["models"]
    assert "broken" in result["failed"]


def test_an_engine_that_cannot_load_is_recorded_not_dropped(bench_wer, monkeypatch):
    _subset(bench_wer, monkeypatch)
    _install(bench_wer, monkeypatch, {"ok": None, "noload": "raise-on-load"})
    result = bench_wer.run(4, [("good", "ok", "m"), ("absent", "noload", "m")], cpu_threads=1)
    assert "absent" not in result["models"]
    assert "weights not found" in result["failed"]["absent"]


def test_a_partly_decoded_engine_gets_no_wer(bench_wer, monkeypatch):
    """Scoring what it managed first would publish a number for a broken engine."""
    _subset(bench_wer, monkeypatch)
    _install(bench_wer, monkeypatch, {"dies": 3})
    result = bench_wer.run(4, [("broken", "dies", "m")], cpu_threads=1)
    assert result["models"] == {}, result["models"]
    assert "broken" in result["failed"]


def test_the_failed_key_exists_even_when_nothing_failed(bench_wer, monkeypatch):
    """A reader checks `failed` before trusting the table; it must never be absent."""
    _subset(bench_wer, monkeypatch)
    _install(bench_wer, monkeypatch, {"ok": None})
    result = bench_wer.run(4, [("good", "ok", "m")], cpu_threads=1)
    assert result["failed"] == {}
    assert "good" in result["models"]


def test_the_order_of_the_specs_does_not_matter(bench_wer, monkeypatch):
    """A failure first must not stop the ones behind it either."""
    _subset(bench_wer, monkeypatch)
    _install(bench_wer, monkeypatch, {"ok": None, "dies": 1})
    result = bench_wer.run(4, [("broken", "dies", "m"), ("good", "ok", "m")], cpu_threads=1)
    assert sorted(result["models"]) == ["good"]
    assert sorted(result["failed"]) == ["broken"]
