"""`scripts/bench-decode-latency.py`: the pure parts of the release-to-transcript harness.

The measurements need a model and are not run here. What is pinned is what the numbers
in `docs/benchmarks.md` depend on: the percentile definition (shared with
`stt.latency.percentile`), the lead-in the daemon prepends, the fixture reader, and that
the variant grid's first entry is the shipped baseline the others are compared with.
"""
from __future__ import annotations

import importlib.util
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def bench():
    spec = importlib.util.spec_from_file_location(
        "bench_decode_latency", ROOT / "scripts" / "bench-decode-latency.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


def test_percentiles_match_the_daemon_definition(bench) -> None:
    from yazses.stt.latency import percentile

    values = [float(v) for v in (5, 1, 9, 3, 7, 2, 8, 4, 6, 10, 12, 11, 15, 14, 13)]
    for q in (0.5, 0.95):
        assert bench.nearest_rank(values, q) == percentile(values, q)
    s = bench.summarise(values)
    assert s == {"n": 15, "p50_ms": 8.0, "p95_ms": 15.0, "min_ms": 1.0}
    assert bench.summarise([]) == {"n": 0}


def test_the_lead_in_is_the_daemons_default_of_zeros(bench) -> None:
    from yazses.config import AccessibilityConfig

    assert bench.LEAD_MS == AccessibilityConfig().pre_speech_padding_ms
    burst = np.ones(100, dtype=np.float32)
    led = bench.with_lead(burst)
    assert led.size == 100 + bench.LEAD_MS * 16 and not led[: bench.LEAD_MS * 16].any()
    assert bench.with_lead(burst, 0) is burst


def test_the_default_prompt_is_the_one_a_default_install_decodes_with(bench) -> None:
    from yazses.stt.vocabulary import merge_initial_prompt

    assert bench.DEFAULT_PROMPT == merge_initial_prompt("", language="en")


def test_the_grid_starts_with_the_shipped_baseline(bench) -> None:
    name, threads, kwargs, lead = bench._variants(bench.DEFAULT_PROMPT)[0]
    assert (name, threads, lead) == ("baseline", 0, bench.LEAD_MS)
    assert kwargs == {"language": "en", "initial_prompt": bench.DEFAULT_PROMPT}


def test_load_wav_reads_16k_mono_pcm_and_refuses_anything_else(bench, tmp_path) -> None:
    good = tmp_path / "good.wav"
    with wave.open(str(good), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.array([0, 16384, -32768], dtype=np.int16).tobytes())
    assert bench.load_wav(good).tolist() == [0.0, 0.5, -1.0]
    bad = tmp_path / "bad.wav"
    with wave.open(str(bad), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0")
    with pytest.raises(SystemExit):
        bench.load_wav(bad)
