"""scripts/bench-pyannote-pipelines.py: pure helpers and the accounting loop (N2).

No model, no torch, no network: the pipeline, the audio decoder and the scorer are the
script's injected seams, so nothing here measures anything real. The real scorer is
``pyannote.metrics``; one test binds against it where it is installed.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def bench():
    name = "bench_pyannote_pipelines_n2"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "bench-pyannote-pipelines.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # @dataclass resolves its module through sys.modules
    spec.loader.exec_module(mod)
    return mod


class _Segment:
    def __init__(self, start, end):
        self.start, self.end = start, end


class _Annotation:
    def __init__(self, tracks):
        self._tracks = tracks

    def itertracks(self, yield_label=False):
        for start, end, label in self._tracks:
            yield _Segment(start, end), None, label


@dataclass
class _DiarizeOutput:
    speaker_diarization: object
    exclusive_speaker_diarization: object


def _fake_score(reference, hypothesis, duration_s):
    return {"der": 0.1, "jer": 0.2, "miss": 0.1, "false_alarm": 0.0,
            "confusion": 0.0, "total": 1.0}


def test_only_the_two_pinned_candidates_are_accepted(bench):
    assert bench.CANDIDATES == (
        "pyannote/speaker-diarization-3.1",
        "pyannote/speaker-diarization-community-1",
    )
    with pytest.raises(SystemExit):
        bench.main(["x", "--evidence-class", "synthetic", "--corpus-label", "c",
                    "--pipelines", "someone/else"])


def test_parse_rttm(bench):
    text = (
        "SPEAKER f 1 1.50 1.00 <NA> <NA> B <NA> <NA>\n"
        "# comment\n"
        "SPEAKER f 1 0.00 1.00 <NA> <NA> A <NA> <NA>\n"
        "SPEAKER f 1 3.00 0.00 <NA> <NA> A <NA> <NA>\n"
        "SPKR-INFO f 1 <NA> <NA> <NA> unknown A <NA> <NA>\n"
    )
    assert bench.parse_rttm(text) == [(0.0, 1.0, "A"), (1.5, 2.5, "B")]


def test_parse_rttm_rejects_a_malformed_line(bench):
    with pytest.raises(ValueError, match="line 1"):
        bench.parse_rttm("SPEAKER f 1 x 1.0 <NA> <NA> A <NA> <NA>\n")


def test_speaker_count_error_is_signed(bench):
    ref = [(0, 1, "A"), (1, 2, "B")]
    assert bench.speaker_count_error(ref, [(0, 2, "s0")]) == -1
    assert bench.speaker_count_error(ref, [(0, 1, "a"), (1, 2, "b"), (2, 3, "c")]) == 1
    assert bench.speaker_count_error(ref, [(0, 1, "x"), (1, 2, "y")]) == 0


def test_overlapping_speech_seconds(bench):
    assert bench.overlapping_speech_seconds([(0, 2.5, "a"), (1.5, 4, "b")]) == 1.0
    assert bench.overlapping_speech_seconds([(0, 2, "a"), (2, 4, "b")]) == 0.0


def test_every_fixture_is_accounted_for(bench, tmp_path):
    (tmp_path / "good.wav").write_bytes(b"")
    (tmp_path / "good.rttm").write_text("SPEAKER good 1 0 4 <NA> <NA> A <NA> <NA>\n", encoding="utf-8")
    (tmp_path / "norttm.wav").write_bytes(b"")
    (tmp_path / "broken.wav").write_bytes(b"")
    (tmp_path / "broken.rttm").write_text("SPEAKER broken 1 0 1 <NA> <NA> A <NA> <NA>\n", encoding="utf-8")
    fixtures = bench.discover_fixtures(tmp_path)
    assert [f[0] for f in fixtures] == ["broken", "good", "norttm"]

    def load_audio(path):
        if path.stem == "broken":
            raise RuntimeError("undecodable")
        return [0.0] * 64000, 16000

    output = _DiarizeOutput(
        speaker_diarization=_Annotation([(0.0, 2.5, "S0"), (1.5, 4.0, "S1")]),
        exclusive_speaker_diarization=_Annotation([(0.0, 2.0, "S0"), (2.0, 4.0, "S1")]),
    )
    ticks = iter(range(100))
    run = bench.run_pipeline(
        "pyannote/speaker-diarization-community-1", fixtures,
        load_pipeline=lambda pid: (lambda audio, sr: output),
        load_audio=load_audio, score=_fake_score,
        provenance=lambda pid: {"repo": pid, "revision": "abc", "sha256": "0" * 64},
        clock=lambda: float(next(ticks)),
    )
    assert [r.fixture for r in run.results] == ["good"]
    assert {f["fixture"] for f in run.failures} == {"broken", "norttm"}

    views = {v.view: v for v in run.results[0].views}
    assert set(views) == {"exclusive", "regular"}
    assert views["exclusive"].shipped and not views["regular"].shipped
    assert views["exclusive"].overlap_s == 0.0
    assert views["regular"].overlap_s == 1.0
    assert views["exclusive"].speaker_count_error == 1  # 2 hyp vs 1 ref

    rows = bench.summarise(run, len(fixtures))
    assert {r["view"] for r in rows} == {"exclusive", "regular"}
    assert all(r["n_scored"] == 1 and r["n_total"] == 3 for r in rows)
    table = bench.render_table(rows)
    assert "exclusive (shipped)" in table
    assert "1/3" in table


def test_a_legacy_annotation_is_scored_as_one_view(bench, tmp_path):
    (tmp_path / "a.wav").write_bytes(b"")
    (tmp_path / "a.rttm").write_text("SPEAKER a 1 0 1 <NA> <NA> A <NA> <NA>\n", encoding="utf-8")
    run = bench.run_pipeline(
        "pyannote/speaker-diarization-3.1", bench.discover_fixtures(tmp_path),
        load_pipeline=lambda pid: (lambda audio, sr: _Annotation([(0.0, 1.0, "S")])),
        load_audio=lambda p: ([0.0] * 16000, 16000), score=_fake_score,
        provenance=lambda pid: {},
    )
    assert [(v.view, v.shipped) for v in run.results[0].views] == [("legacy", True)]


def test_a_pipeline_that_does_not_load_is_a_recorded_result(bench, tmp_path):
    (tmp_path / "a.wav").write_bytes(b"")

    def refuse(pid):
        raise RuntimeError("gated")

    run = bench.run_pipeline(
        "pyannote/speaker-diarization-community-1", bench.discover_fixtures(tmp_path),
        load_pipeline=refuse, load_audio=lambda p: ([], 16000), score=_fake_score,
        provenance=lambda pid: {},
    )
    assert run.load_error and "gated" in run.load_error
    assert run.failures == [{"fixture": "a", "reason": "pipeline did not load"}]
    assert bench.summarise(run, 1) == []


def test_time_weighted_and_mean_der_are_both_reported(bench):
    def vs(der, miss, total):
        return bench.ViewScore("exclusive", True, der, 0.0, miss, 0.0, 0.0, total, 0, 1, 0.0)

    run = bench.PipelineRun("p", {}, 1.0, results=[
        bench.FixtureResult("short", 10.0, 1, 1.0, [vs(0.5, 5.0, 10.0)]),
        bench.FixtureResult("long", 90.0, 1, 9.0, [vs(0.1, 9.0, 90.0)]),
    ])
    (row,) = bench.summarise(run, 2)
    assert row["der_mean"] == pytest.approx(0.3)
    assert row["der_time_weighted"] == pytest.approx(14.0 / 100.0)
    assert row["rtf"] == pytest.approx(0.1)


def test_sha256_tree_depends_on_names_and_content(bench, tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "config.yaml").write_text("x", encoding="utf-8")
    first = bench.sha256_tree(a)
    (a / "config.yaml").write_text("y", encoding="utf-8")
    assert bench.sha256_tree(a) != first


def test_the_real_scorer_binds_against_pyannote_metrics(bench):
    pytest.importorskip("pyannote.metrics")
    score = bench._real_scorer(collar=0.0, skip_overlap=False)
    ref = [(0.0, 2.0, "A"), (2.0, 4.0, "B")]
    perfect = score(ref, [(0.0, 2.0, "x"), (2.0, 4.0, "y")], 4.0)
    assert perfect["der"] == pytest.approx(0.0)
    half = score(ref, [(0.0, 4.0, "x")], 4.0)
    assert half["der"] == pytest.approx(0.5)
    assert half["confusion"] == pytest.approx(2.0)
