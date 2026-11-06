"""scripts/bench-stt.py integrity: resolved-engine check, file accounting, JSON, p95 floor.

These are tooling tests for the *proposed* evaluation protocol (ADR-033, not accepted);
they are protocol-agnostic and need no model, no audio hardware and no network. The
engine and the audio decoder are replaced through the script's two seams
(`_build_engine`, `_load_audio`), so nothing here measures anything real.

The failures they guard against are the ones a benchmark makes silently:
* the factory falls back to faster-whisper and the row is published as "parakeet";
* a file with no reference or undecodable audio drops out of the denominator.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# The script imports jiwer at top level and exits without it. jiwer is a dev dependency,
# not guaranteed on every leg, so skip rather than let the import call sys.exit.
pytest.importorskip("jiwer")
np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def bench():
    name = "bench_stt_night_n13"
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "bench-stt.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # @dataclass resolves its module through sys.modules
    spec.loader.exec_module(mod)
    return mod


class FakeEngine:
    engine_name = "faster-whisper"
    model_name = "base.en"

    def __init__(self, text: str = "the cat sat", fail_on: int | None = None) -> None:
        self.text = text
        self.fail_on = fail_on  # audio length (samples) whose decode raises

    def transcribe(self, audio, sr):
        if self.fail_on is not None and len(audio) == self.fail_on:
            raise RuntimeError("decoder blew up")
        return self.text


def _patch(monkeypatch, bench, engine, *, unreadable: set[str] = frozenset(), lengths=None):
    monkeypatch.setattr(bench, "_build_engine", lambda cfg: engine)
    monkeypatch.setattr(bench, "_build_normalizer", lambda: ((lambda t: t.lower().strip()), "lower"))
    monkeypatch.setattr(bench, "get_peak_rss_mb", lambda: 123.0)
    lengths = lengths or {}

    def load(path, rate):
        if path.name in unreadable:
            raise RuntimeError("not audio")
        return np.zeros(lengths.get(path.name, 16000), dtype=np.float32), rate

    monkeypatch.setattr(bench, "_load_audio", load)


def _corpus(tmp_path: Path, refs: dict[str, str | None]) -> Path:
    for stem, ref in refs.items():
        (tmp_path / f"{stem}.wav").write_bytes(b"")
        if ref is not None:
            (tmp_path / f"{stem}.txt").write_text(ref, encoding="utf-8")
    return tmp_path


# --- resolved-engine check ----------------------------------------------------------


def test_check_engine_flags_a_recorded_factory_fallback(bench) -> None:
    check = bench.check_engine("parakeet", "", {
        "engine": "faster-whisper", "model": "base.en",
        "fallback_from": "parakeet", "fallback_reason": "it failed to load (ImportError)"})
    assert check.is_fallback
    assert check.resolved_engine == "faster-whisper"
    assert "parakeet" in check.problems[0]


def test_check_engine_flags_a_name_mismatch_without_fallback_marker(bench) -> None:
    check = bench.check_engine("moonshine", "", {"engine": "faster-whisper", "model": "base.en"})
    assert check.is_fallback


def test_check_engine_model_rename_is_a_warning_not_a_fallback(bench) -> None:
    check = bench.check_engine("moonshine", "base", {"engine": "moonshine", "model": "moonshine/base"})
    assert not check.is_fallback
    assert check.warnings


def test_check_engine_unidentified_engine_is_unverified_not_fallback(bench) -> None:
    check = bench.check_engine("faster-whisper", "base.en", None)
    assert not check.verified
    assert not check.is_fallback


def test_main_refuses_a_fallback_engine_by_default(bench, monkeypatch, tmp_path) -> None:
    engine = FakeEngine()
    engine.fallback_from = "parakeet"
    engine.fallback_reason = "it failed to load (ImportError; see `yazses logs`)"
    _patch(monkeypatch, bench, engine)
    data = _corpus(tmp_path, {"a": "the cat sat"})
    assert bench.main([str(data), "--engine", "parakeet"]) == bench.EXIT_FALLBACK == 2


def test_main_labels_the_row_when_fallback_is_allowed(bench, monkeypatch, tmp_path, capsys) -> None:
    engine = FakeEngine()
    engine.fallback_from = "parakeet"
    _patch(monkeypatch, bench, engine)
    data = _corpus(tmp_path, {"a": "the cat sat"})
    assert bench.main([str(data), "--engine", "parakeet", "--allow-fallback"]) == 0
    row = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("| CPU/GPU")][0]
    assert "FALLBACK" in row
    assert "faster-whisper (requested parakeet)" in row


# --- failure accounting -------------------------------------------------------------


def test_every_file_is_accounted_for_and_partial_coverage_exits_3(bench, monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, bench, FakeEngine(fail_on=32000), unreadable={"b.wav"},
           lengths={"d.wav": 32000})
    data = _corpus(tmp_path, {"a": "the cat sat", "b": "x", "c": None, "d": "y"})
    out = tmp_path / "run.json"
    assert bench.main([str(data), "--json-out", str(out)]) == bench.EXIT_PARTIAL == 3
    cov = json.loads(out.read_text(encoding="utf-8"))["summary"]["coverage"]
    assert (cov["n_total"], cov["n_scored"], cov["n_failed"]) == (4, 1, 3)
    reasons = {f["file"]: f["reason"] for f in cov["failed"]}
    assert set(reasons) == {"b.wav", "c.wav", "d.wav"}
    assert "missing reference" in reasons["c.wav"]


def test_allow_partial_exits_0_but_the_row_still_states_coverage(bench, monkeypatch, tmp_path, capsys) -> None:
    _patch(monkeypatch, bench, FakeEngine())
    data = _corpus(tmp_path, {"a": "the cat sat", "b": None})
    assert bench.main([str(data), "--allow-partial"]) == 0
    row = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("| CPU/GPU")][0]
    assert "PARTIAL coverage 1/2" in row


def test_full_coverage_exits_0_and_the_row_names_normaliser_and_process_peak(
        bench, monkeypatch, tmp_path, capsys) -> None:
    _patch(monkeypatch, bench, FakeEngine())
    data = _corpus(tmp_path, {"a": "the cat sat"})
    assert bench.main([str(data)]) == 0
    row = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("| CPU/GPU")][0]
    assert "norm: lower" in row
    assert "process peak" in row
    assert "PARTIAL" not in row and "FALLBACK" not in row


# --- JSON output ----------------------------------------------------------------------


def test_json_out_header_and_per_sample_word_ops(bench, monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, bench, FakeEngine(text="the cat sat"))
    data = _corpus(tmp_path, {"a": "the cat sat", "b": "the dog sat down"})
    out = tmp_path / "run.json"
    assert bench.main([str(data), "--json-out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))

    header = doc["header"]
    for key in ("schema", "protocol", "commit", "subject", "engine", "normalizer",
                "versions", "cpu", "os", "cold_load_s", "warmup_s", "rss_note"):
        assert key in header, key
    assert "PROPOSED" in header["protocol"]
    assert header["engine"]["resolved_engine"] == "faster-whisper"
    assert header["engine"]["fallback"] is False
    assert header["normalizer"] == "lower"
    assert isinstance(header["cold_load_s"], float)

    by_file = {s["file"]: s for s in doc["samples"]}
    assert set(by_file) == {"a.wav", "b.wav"}
    for s in by_file.values():
        for key in ("duration_s", "decode_s", "ref", "hyp",
                    "hits", "substitutions", "deletions", "insertions"):
            assert key in s, key
    assert (by_file["a.wav"]["substitutions"], by_file["a.wav"]["deletions"],
            by_file["a.wav"]["insertions"]) == (0, 0, 0)
    # "the dog sat down" -> "the cat sat": dog->cat substituted, "down" deleted.
    assert (by_file["b.wav"]["hits"], by_file["b.wav"]["substitutions"],
            by_file["b.wav"]["deletions"], by_file["b.wav"]["insertions"]) == (2, 1, 1, 0)
    assert doc["summary"]["decode"]["n"] == 2


# --- percentiles ----------------------------------------------------------------------


def test_p95_floor_matches_the_live_latency_summary(bench) -> None:
    from yazses.stt.latency import MIN_SAMPLES_FOR_P95

    assert bench.MIN_SAMPLES_FOR_P95 == MIN_SAMPLES_FOR_P95


def test_p95_is_withheld_below_the_floor_and_reported_at_it(bench) -> None:
    n = bench.MIN_SAMPLES_FOR_P95
    below = bench.decode_percentiles([0.1] * (n - 1))
    assert below["p95_ms"] is None and below["p50_ms"] == 100.0
    at = bench.decode_percentiles([i / 1000 for i in range(1, n + 1)])
    assert at["p95_ms"] == 19.0          # nearest rank ceil(0.95 * 20) = 19
    assert at["p50_ms"] == 10.0


def test_p95_uses_the_same_nearest_rank_as_latency(bench) -> None:
    from yazses.stt.latency import percentile

    values = [float(v) for v in (7, 3, 11, 5, 2, 13, 17, 19, 23, 29, 31, 37,
                                 41, 43, 47, 53, 59, 61, 67, 71, 73, 79)]
    got = bench.decode_percentiles([v / 1000 for v in values])
    assert got["p95_ms"] == round(percentile(values, 0.95), 1)
    assert got["p50_ms"] == round(percentile(values, 0.50), 1)


def test_no_samples_reports_no_percentiles(bench) -> None:
    assert bench.decode_percentiles([]) == {
        "n": 0, "p50_ms": None, "p95_ms": None, "p95_min_n": bench.MIN_SAMPLES_FOR_P95}
