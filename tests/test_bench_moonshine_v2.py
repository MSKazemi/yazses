"""scripts/bench-moonshine-v2.py: the M1 measurement tooling, with no model and no network.

The script compares the shipped Moonshine engine against `moonshine-voice` v2 under the
*proposed* ADR-033 protocol. `moonshine-voice` is not a YazSes dependency, so every test
here replaces it with a double through the script's `_import_moonshine_voice` seam, and
the audio decoder through `bench-stt.py`'s `_load_audio` seam. Nothing is measured.

What is guarded is what a comparison gets wrong silently: pairing two runs on different
files or normalisers, scoring a fallback, counting an append as a retraction, and a run
that would reach the network without `--fetch`.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("jiwer")
np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mv2():
    return _load("bench_moonshine_v2_under_test", "bench-moonshine-v2.py")


@pytest.fixture
def bench(monkeypatch):
    mod = _load("bench_stt_for_mv2_test", "bench-stt.py")
    monkeypatch.setattr(mod, "_build_normalizer", lambda: ((lambda t: t.lower().strip()), "lower"))
    monkeypatch.setattr(mod, "get_peak_rss_mb", lambda: 100.0)
    monkeypatch.setattr(mod, "_load_audio",
                        lambda path, rate: (np.zeros(16000, dtype=np.float32), rate))
    return mod


def _fake_mv(text: str = "the cat sat", partials: tuple[str, ...] = ("the", "the cat")):
    """A `moonshine_voice` double with the 0.1.6 surface the script touches."""
    mod = types.ModuleType("moonshine_voice")
    mod.__file__ = str(ROOT / "nonexistent" / "moonshine_voice" / "__init__.py")

    class Line:
        def __init__(self, t: str, line_id: int = 1) -> None:
            self.text, self.line_id = t, line_id

    class LineTextChanged:
        def __init__(self, line) -> None:
            self.line = line

    class Transcript:
        def __init__(self, lines) -> None:
            self.lines = lines

    class Stream:
        def __init__(self) -> None:
            self.listeners: list = []
            self.fed = 0

        def add_listener(self, fn) -> None:
            self.listeners.append(fn)

        def start(self) -> None:
            pass

        def add_audio(self, samples, rate) -> None:
            if self.fed < len(partials):
                for fn in self.listeners:
                    fn(LineTextChanged(Line(partials[self.fed])))
            self.fed += 1

        def stop(self):
            for fn in self.listeners:
                fn(LineTextChanged(Line(text)))
            return Transcript([Line(text)])

        def close(self) -> None:
            pass

    class Transcriber:
        def __init__(self, model_path, model_arch) -> None:
            self.model_path, self.model_arch = model_path, model_arch

        def transcribe_without_streaming(self, samples, sample_rate):
            assert isinstance(samples, list)          # the ctypes binding wants a list
            return Transcript([Line(text)])

        def create_stream(self, update_interval=None):
            return Stream()

    def get_model_for_language(*a, **k):  # pragma: no cover - must never be called
        raise AssertionError("the network fetch ran without --fetch")

    mod.Transcriber = Transcriber
    mod.LineTextChanged = LineTextChanged
    mod.string_to_model_arch = lambda s: s
    mod.get_model_for_language = get_model_for_language
    return mod


def _corpus(tmp_path: Path, refs: dict[str, str]) -> Path:
    data = tmp_path / "corpus"
    data.mkdir()
    for stem, ref in refs.items():
        (data / f"{stem}.wav").write_bytes(b"")
        (data / f"{stem}.txt").write_text(ref, encoding="utf-8")
    return data


# ---- pure helpers -------------------------------------------------------------------

def test_an_append_is_not_a_retraction(mv2) -> None:
    assert mv2.count_retractions(["the", "the cat", "the cat  sat"]) == 0


def test_a_rewrite_of_seen_text_is_a_retraction(mv2) -> None:
    assert mv2.count_retractions(["the cat", "a cat", "a cat sat", "a hat"]) == 2


def test_partial_stats_counts_retractions_per_line(mv2) -> None:
    stats = mv2.partial_stats([(1, "hi"), (2, "so"), (1, "hi there"), (2, "go")])
    assert stats == {"lines": 2, "text_changes": 4, "retractions": 1}


def test_sha256_manifest_is_order_independent_and_content_sensitive(mv2, tmp_path) -> None:
    (tmp_path / "b.ort").write_bytes(b"b")
    (tmp_path / "a.ort").write_bytes(b"a")
    first = mv2.sha256_manifest(tmp_path)
    assert list(first["files"]) == ["a.ort", "b.ort"]
    (tmp_path / "a.ort").write_bytes(b"A")
    assert mv2.sha256_manifest(tmp_path)["combined_sha256"] != first["combined_sha256"]


def test_paired_bootstrap_of_identical_runs_is_zero(mv2) -> None:
    errs = [(1, 10), (0, 8), (3, 12)]
    out = mv2.paired_bootstrap(errs, errs, n_resamples=200)
    assert out["delta_wer"] == 0.0 and out["ci95"] == [0.0, 0.0]
    assert out["unit"] == "file"


def test_paired_bootstrap_sign_follows_the_second_run(mv2) -> None:
    out = mv2.paired_bootstrap([(0, 10)] * 5, [(2, 10)] * 5, n_resamples=200)
    assert out["delta_wer"] == pytest.approx(0.2)
    assert out["ci95"][0] > 0


def _doc(files: dict[str, tuple[int, int, int, int]], *, engine="moonshine", model="base",
         normalizer="whisper", fallback=False, verified=True, n_total=None) -> dict:
    samples = [{"file": f, "hits": h, "substitutions": s, "deletions": d, "insertions": i}
               for f, (h, s, d, i) in files.items()]
    return {
        "header": {"normalizer": normalizer, "protocol": "p", "subject": engine, "model": model,
                   "engine": {"resolved_engine": engine, "resolved_model": model,
                              "fallback": fallback, "verified": verified}},
        "summary": {"rtf": 0.1, "decode": {"p50_ms": 10.0, "p95_ms": None},
                    "coverage": {"n_scored": len(files), "n_total": n_total or len(files)}},
        "samples": samples,
    }


def test_check_comparable_refuses_what_cannot_be_paired(mv2) -> None:
    a = _doc({"x.wav": (9, 1, 0, 0)})
    assert mv2.check_comparable([a])
    assert "normalisers" in " ".join(
        mv2.check_comparable([a, _doc({"x.wav": (9, 1, 0, 0)}, normalizer="lower")]).problems)
    assert "file sets" in " ".join(mv2.check_comparable([a, _doc({"y.wav": (9, 1, 0, 0)})]).problems)
    assert "fell back" in " ".join(
        mv2.check_comparable([a, _doc({"x.wav": (9, 1, 0, 0)}, fallback=True)]).problems)
    assert "coverage" in " ".join(
        mv2.check_comparable([a, _doc({"x.wav": (9, 1, 0, 0)}, n_total=2)]).problems)
    assert not mv2.check_comparable([a, _doc({"x.wav": (9, 1, 0, 0)}, n_total=2)],
                                    allow_partial=True)
    assert not mv2.check_comparable([a, _doc({"x.wav": (10, 0, 0, 0)}, engine="moonshine-voice")])


def test_compare_pairs_against_the_first_run(mv2) -> None:
    v1 = _doc({"a.wav": (9, 1, 0, 0), "b.wav": (10, 0, 0, 0)})
    v2 = _doc({"a.wav": (10, 0, 0, 0), "b.wav": (10, 0, 0, 0)},
              engine="moonshine-voice", model="small-streaming")
    result = mv2.compare([v1, v2], n_resamples=200)
    assert result["rows"][0]["wer"] == pytest.approx(0.05)
    assert "vs_baseline" not in result["rows"][0]
    assert result["rows"][1]["vs_baseline"]["delta_wer"] == pytest.approx(-0.05)
    table = mv2.markdown(result)
    assert "baseline" in table and "moonshine-voice:small-streaming" in table


# ---- the run subcommand, end to end against doubles ---------------------------------

def test_run_scores_through_bench_stt_and_adds_provenance(mv2, bench, monkeypatch, tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "encoder.ort").write_bytes(b"weights")
    monkeypatch.setattr(mv2, "_import_moonshine_voice", lambda: _fake_mv())
    monkeypatch.setattr(mv2, "_load_bench_stt", lambda: bench)
    data = _corpus(tmp_path, {"a": "the cat sat", "b": "the cat sat"})
    out = tmp_path / "run.json"

    code = mv2.main(["run", str(data), "--arch", "small-streaming", "--model-dir",
                     str(model_dir), "--json-out", str(out), "--streaming"])

    assert code == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["header"]["engine"]["resolved_engine"] == "moonshine-voice"
    assert doc["header"]["engine"]["fallback"] is False
    assert doc["summary"]["wer"] == 0.0
    assert "encoder.ort" in doc["header"]["weights"]["files"]
    assert set(doc["header"]["corpus"]["files"]) == {"a.wav", "a.txt", "b.wav", "b.txt"}
    assert "moonshine-voice" in doc["header"]["versions"]
    streaming = doc["streaming"]["summary"]
    assert streaming["n"] == 2 and streaming["retractions"] == 0
    assert streaming["wer_streamed_final"] == 0.0
    assert streaming["release_to_final_p95_ms"] is None   # n < bench-stt's p95 floor


def test_run_never_fetches_without_the_flag(mv2, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mv2, "_import_moonshine_voice", lambda: _fake_mv())
    data = _corpus(tmp_path, {"a": "x"})
    assert mv2.main(["run", str(data), "--arch", "tiny", "--json-out",
                     str(tmp_path / "o.json")]) == 1


def test_run_refuses_non_english(mv2, tmp_path) -> None:
    data = _corpus(tmp_path, {"a": "x"})
    assert mv2.main(["run", str(data), "--arch", "base", "--language", "ja",
                     "--model-dir", str(tmp_path), "--json-out", str(tmp_path / "o.json")]) == 1


def test_streaming_needs_a_streaming_arch(mv2, tmp_path) -> None:
    data = _corpus(tmp_path, {"a": "x"})
    assert mv2.main(["run", str(data), "--arch", "base", "--streaming", "--model-dir",
                     str(tmp_path), "--json-out", str(tmp_path / "o.json")]) == 1


def test_the_script_does_not_import_moonshine_voice_at_module_level() -> None:
    source = (ROOT / "scripts" / "bench-moonshine-v2.py").read_text(encoding="utf-8")
    top_level = [ln for ln in source.splitlines() if ln.startswith(("import ", "from "))]
    assert not any("moonshine_voice" in ln for ln in top_level)


def test_compare_cli_refuses_with_its_own_exit_code(mv2, tmp_path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(_doc({"x.wav": (9, 1, 0, 0)})), encoding="utf-8")
    b.write_text(json.dumps(_doc({"y.wav": (9, 1, 0, 0)})), encoding="utf-8")
    assert mv2.main(["compare", str(a), str(b)]) == mv2.EXIT_REFUSED


def test_digest_annotates_the_chosen_field(mv2, tmp_path) -> None:
    run = tmp_path / "v1.json"
    run.write_text(json.dumps(_doc({"x.wav": (1, 0, 0, 0)})), encoding="utf-8")
    weights = tmp_path / "w"
    weights.mkdir()
    (weights / "m.onnx").write_bytes(b"m")
    assert mv2.main(["digest", str(weights), "--into", str(run)]) == 0
    assert mv2.main(["digest", str(weights), "--field", "corpus", "--into", str(run)]) == 0
    header = json.loads(run.read_text(encoding="utf-8"))["header"]
    assert header["weights"] == header["corpus"]
    assert "m.onnx" in header["weights"]["files"]
