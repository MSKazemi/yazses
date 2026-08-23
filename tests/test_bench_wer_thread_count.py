"""A WER quoted without its thread count is not a number two hosts can compare.

CTranslate2 owns the int8 kernels and the order their partial sums are reduced in,
and that order depends on how many threads the GEMM was split across. Measured on
one laptop, one set of library versions and one byte-identical 200-utterance
LibriSpeech subset, `tiny.en` scored **4.78%** with the thread count left to
CTranslate2, **4.88%** at one thread and **4.95%** at four. `base.en` and `small.en`
did not move, which is the part that makes this easy to miss: the harness looks
reproducible right up until the smallest model is the one under discussion.

So `bench_wer` takes the thread count as an argument and writes it into the result.
Two things are guarded here, both of which were absent and neither of which review
would reliably catch:

* the value reaches `SttConfig`, rather than being accepted and dropped -- a flag
  that silently does nothing is worse than no flag, because the result file then
  carries a `cpu_threads` that did not decode anything;
* the value is recorded in the result even when it is the default `0`, since `0`
  means "CTranslate2 chose", and a reader cannot tell that from "nobody asked".

The engine is a stub. Nothing here needs a model on disk, which is the point: the
guard has to run in CI, where the benchmark itself cannot.
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


class _StubEngine:
    """Named for the class `bench_wer` demands back, so the fallback guard passes."""

    __name__ = "FasterWhisperEngine"


def _install_stub(monkeypatch, seen: dict):
    import yazses.stt.factory as factory

    def fake_build_engine(cfg):
        seen["cpu_threads"] = cfg.cpu_threads
        engine = _StubEngine()
        type(engine).__name__ = "FasterWhisperEngine"
        return engine

    monkeypatch.setattr(factory, "build_engine", fake_build_engine)


@pytest.mark.parametrize("threads", [0, 1, 4])
def test_the_thread_count_reaches_the_engine_config(bench_wer, monkeypatch, threads):
    seen: dict = {}
    _install_stub(monkeypatch, seen)
    bench_wer._build("faster-whisper", "tiny.en", threads)
    assert seen["cpu_threads"] == threads, (
        "bench_wer accepted a thread count and did not pass it to SttConfig, so the "
        "result file would report a pinning that never happened"
    )


def test_the_default_is_the_shipping_default_not_a_bench_specific_pin(
    bench_wer, monkeypatch
):
    """`0` is what the daemon uses, so it is what the published number must describe."""
    seen: dict = {}
    _install_stub(monkeypatch, seen)
    bench_wer._build("faster-whisper", "tiny.en")
    assert seen["cpu_threads"] == 0


def test_the_result_records_the_thread_count_even_when_it_is_the_default(
    bench_wer, monkeypatch
):
    """`0` and "unrecorded" are different claims and must not render identically."""
    monkeypatch.setattr(
        bench_wer, "librispeech_subset", lambda n, stratified, split="test-clean": []
    )
    out = bench_wer.run(0, [], cpu_threads=0)
    assert "cpu_threads" in out["config"], (
        "a result whose config omits cpu_threads cannot be compared with one from "
        "another host, because the reader cannot tell which of them pinned it"
    )
    assert out["config"]["cpu_threads"] == 0

    out4 = bench_wer.run(0, [], cpu_threads=4)
    assert out4["config"]["cpu_threads"] == 4
