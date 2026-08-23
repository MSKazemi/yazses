"""The diarization harness's arithmetic (`paper/benchmark/`).

Same reason `test_bench_throughput.py` exists: a harness that reports a wrong number
is worse than none, because the number gets quoted. This one is more exposed than
most -- `score()` is a reimplementation of md-eval's frame-based DER with a Hungarian
one-to-one speaker mapping, chosen over `pyannote.metrics` because that would drag
pyannote.audio into the benchmark group and undo the point of a sherpa backend that
needs no torch. A bug in a reimplemented metric is invisible from the outside: every
number moves together and nothing looks wrong.

So the scorer is pinned against cases whose DER is known by construction, the corpus
builder against the selection bias it is supposed to avoid, and the WER interval
against the degenerate inputs that would otherwise produce a confident zero.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "paper" / "benchmark"


def _load(name: str):
    # The bench scripts are run with `paper/benchmark` as the script directory, so
    # they import each other by bare name (`from _common import ...`). Loading one
    # from a test has to reproduce that, or the import fails inside the module and
    # surfaces as a collection error naming `_common` rather than the module asked for.
    if str(BENCH) not in sys.path:
        sys.path.insert(0, str(BENCH))
    spec = importlib.util.spec_from_file_location(name, BENCH / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def diar():
    pytest.importorskip("scipy")
    return _load("bench_diarization")


@pytest.fixture(scope="module")
def corpus_mod():
    return _load("make_corpus")


# --------------------------------------------------------------------------- #
# score()
# --------------------------------------------------------------------------- #
def test_a_perfect_hypothesis_scores_zero(diar):
    ref = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
    got = diar.score(ref, list(ref), 0.0)
    assert got["der"] == 0.0
    assert got["speaker_count_error"] == 0


def test_renaming_every_speaker_still_scores_zero(diar):
    """DER is invariant to speaker labels -- that is what the mapping is for."""
    ref = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
    hyp = [(0.0, 5.0, "speaker_7"), (5.0, 10.0, "speaker_3")]
    assert diar.score(ref, hyp, 0.0)["der"] == 0.0


def test_two_speakers_swapped_is_not_forgiven(diar):
    """The optimal mapping must not be free to swap when swapping is the error."""
    ref = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
    hyp = [(0.0, 5.0, "X"), (5.0, 10.0, "X")]   # both turns given to one speaker
    got = diar.score(ref, hyp, 0.0)
    assert got["der"] == pytest.approx(50.0, abs=1.0)
    assert got["speaker_count_error"] == -1


def test_an_empty_hypothesis_misses_everything(diar):
    got = diar.score([(0.0, 10.0, "A")], [], 0.0)
    assert got["der"] == pytest.approx(100.0, abs=0.5)
    assert got["missed_pct"] == pytest.approx(100.0, abs=0.5)
    assert got["false_alarm_pct"] == 0.0


def test_speech_where_there_is_none_is_false_alarm_not_confusion(diar):
    """The three error terms have to stay distinct; they are read separately."""
    ref = [(0.0, 10.0, "A")]
    hyp = [(0.0, 10.0, "A"), (10.0, 15.0, "B")]  # 5s invented after the reference ends
    got = diar.score(ref, hyp, 0.0)
    assert got["false_alarm_pct"] == pytest.approx(50.0, abs=1.0)
    assert got["confusion_pct"] == 0.0
    assert got["missed_pct"] == 0.0


def test_over_splitting_one_speaker_is_charged_as_confusion(diar):
    """The failure this harness was built to see: one person, many clusters.

    Every frame is speech in both reference and hypothesis, so nothing is missed and
    nothing is invented -- the whole penalty has to land on confusion, because only
    one hypothesis cluster can be mapped to the single reference speaker.
    """
    ref = [(0.0, 10.0, "A")]
    hyp = [(float(i), float(i + 1), f"spk{i}") for i in range(10)]
    got = diar.score(ref, hyp, 0.0)
    assert got["n_hyp_speakers"] == 10
    assert got["speaker_count_error"] == 9
    assert got["missed_pct"] == 0.0
    assert got["false_alarm_pct"] == 0.0
    assert got["confusion_pct"] == pytest.approx(90.0, abs=1.0)


def test_a_collar_forgives_boundaries_and_only_boundaries(diar):
    """A collar must reduce a boundary error and leave a whole-segment error alone."""
    ref = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
    off_by_a_bit = [(0.0, 5.2, "A"), (5.2, 10.0, "B")]
    assert diar.score(ref, off_by_a_bit, 0.0)["der"] > 0
    assert diar.score(ref, off_by_a_bit, 0.25)["der"] == 0.0


# --------------------------------------------------------------------------- #
# _read_manifest -- provenance is published, so it cannot be inherited
# --------------------------------------------------------------------------- #
def test_a_corpus_that_does_not_declare_its_provenance_is_refused(diar, tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"meetings": []}), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        diar._read_manifest(tmp_path)
    assert "ground_truth" in str(exc.value) and "caveat" in str(exc.value)


def test_a_declared_corpus_is_accepted_and_its_strings_survive(diar, tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"ground_truth": "gt text", "caveat": "cv text", "meetings": []}),
        encoding="utf-8",
    )
    got = diar._read_manifest(tmp_path)
    assert got["ground_truth"] == "gt text" and got["caveat"] == "cv text"


# --------------------------------------------------------------------------- #
# make_corpus subset selection
# --------------------------------------------------------------------------- #
def _fake_tree(root: Path, spec: dict[str, list[tuple[str, int]]]) -> tuple[Path, Path]:
    """spec: bucket -> [(file_id, duration_s)]. Four speakers in every file."""
    wav, rttm = root / "wav", root / "rttm"
    wav.mkdir(parents=True); rttm.mkdir(parents=True)
    for files in spec.values():
        for fid, dur in files:
            with wave.open(str(wav / f"{fid}.wav"), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes(b"\x00\x00" * (16000 * dur))
            lines = [f"SPEAKER {fid} 1 {i * 5}.00 4.00 <NA> <NA> spk{i % 4} <NA> <NA>"
                     for i in range(8)]
            (rttm / f"{fid}.rttm").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return wav, rttm


def test_every_bucket_contributes_the_same_number_of_recordings(corpus_mod, tmp_path):
    """The bias that shipped in the first draft of this selector.

    Durations ascend with session, so a selector that skips an over-budget file
    instead of stopping keeps drawing from the short-file bucket after the others are
    shut out -- it gave one session three of six recordings. `run()` averages DER
    across meetings without weighting by duration, so a bucket's influence is its
    file count, and equal count is what has to hold.
    """
    spec = {s: [(f"{s}{p}", 60 + (si * 4 + pi) * 30) for pi, p in enumerate("abcd")]
            for si, s in enumerate(["EN2002", "ES2004", "IS1009", "TS3003"])}
    wav, rttm = _fake_tree(tmp_path, spec)
    manifest = corpus_mod.build("ami", wav, rttm, tmp_path / "out", 20)

    counts: dict[str, int] = {}
    for m in manifest["meetings"]:
        counts[m["id"][:-1]] = counts.get(m["id"][:-1], 0) + 1
    assert set(counts) == set(spec), "a bucket was left unrepresented"
    assert len(set(counts.values())) == 1, f"unequal contribution: {counts}"


def test_selection_is_deterministic(corpus_mod, tmp_path):
    spec = {s: [(f"{s}{p}", 60 + i * 20) for i, p in enumerate("abc")]
            for s in ["AA1111", "BB2222"]}
    wav, rttm = _fake_tree(tmp_path, spec)
    first = corpus_mod.build("ami", wav, rttm, tmp_path / "o1", 15)
    second = corpus_mod.build("ami", wav, rttm, tmp_path / "o2", 15)
    assert [m["id"] for m in first["meetings"]] == [m["id"] for m in second["meetings"]]


def test_at_least_one_recording_per_bucket_even_on_an_impossible_budget(corpus_mod, tmp_path):
    """A budget smaller than a single recording must not yield an empty corpus."""
    spec = {s: [(f"{s}a", 600)] for s in ["AA1111", "BB2222"]}
    wav, rttm = _fake_tree(tmp_path, spec)
    manifest = corpus_mod.build("ami", wav, rttm, tmp_path / "out", 1)
    assert len(manifest["meetings"]) == 2


def test_the_manifest_names_the_recordings_behind_the_number(corpus_mod, tmp_path):
    spec = {s: [(f"{s}a", 60)] for s in ["AA1111", "BB2222"]}
    wav, rttm = _fake_tree(tmp_path, spec)
    manifest = corpus_mod.build("ami", wav, rttm, tmp_path / "out", 90)
    assert [m["id"] for m in manifest["meetings"]] == ["AA1111a", "BB2222a"]
    assert manifest["ground_truth"] and manifest["caveat"]
    assert "duration" in manifest["selection"]


def test_an_unknown_source_is_refused_rather_than_defaulted(corpus_mod, tmp_path):
    wav, rttm = _fake_tree(tmp_path, {"AA1111": [("AA1111a", 60)]})
    with pytest.raises(SystemExit):
        corpus_mod.build("not-a-dataset", wav, rttm, tmp_path / "out", 90)


# --------------------------------------------------------------------------- #
# bench_wer bootstrap interval
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def wer_mod():
    pytest.importorskip("jiwer")
    pytest.importorskip("whisper_normalizer")
    return _load("bench_wer")


def test_the_interval_brackets_the_observed_wer(wer_mod):
    per_utt = [(1, 10)] * 30 + [(0, 10)] * 70   # 30 errors / 1000 words = 3.0%
    lo, hi = wer_mod._bootstrap_wer_ci(per_utt)
    assert lo < 3.0 < hi


def test_a_flawless_corpus_gets_a_zero_width_interval(wer_mod):
    assert wer_mod._bootstrap_wer_ci([(0, 10)] * 50) == (0.0, 0.0)


def test_the_interval_is_deterministic(wer_mod):
    per_utt = [(i % 3, 10 + i % 7) for i in range(120)]
    assert wer_mod._bootstrap_wer_ci(per_utt) == wer_mod._bootstrap_wer_ci(per_utt)


def test_an_empty_corpus_does_not_raise(wer_mod):
    assert wer_mod._bootstrap_wer_ci([]) == (0.0, 0.0)


def test_resampling_is_by_utterance_not_by_word(wer_mod):
    """A word-level bootstrap would report a far narrower interval than is honest.

    Same total words and same total errors, but concentrated in few utterances: the
    utterance-level interval must widen, because the sampled unit is the utterance.
    """
    spread = [(1, 10)] * 40 + [(0, 10)] * 60
    clumped = [(10, 10)] * 4 + [(0, 10)] * 96
    lo_s, hi_s = wer_mod._bootstrap_wer_ci(spread)
    lo_c, hi_c = wer_mod._bootstrap_wer_ci(clumped)
    assert (hi_c - lo_c) > (hi_s - lo_s)
