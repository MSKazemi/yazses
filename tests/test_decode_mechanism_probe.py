"""Guards for the decode-mechanism probe.

The probe exists to kill a plausible inference: `condition_on_previous_text` is read
only *after* a window is decoded, a window is 30 s, and a hold-to-talk burst is a few
seconds — therefore the flag cannot affect dictation. It can, because `seek` advances to
the model's last emitted timestamp rather than by a whole window, so a short clip can
take a second pass that is prompted with the first pass's text.

These pin the two things that make the artifact readable rather than the decoding: that
a *later* pass is what counts (pass one is prompted with the initial_prompt under either
setting, so counting it would report an effect on every utterance), and that the
conclusion is not gated on a condition the experiment never needed.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1] / "paper" / "benchmark"
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "probes"))

pytest.importorskip("jiwer")
mod = pytest.importorskip("decode_mechanism")


def _row(utt_id: str, dur: float, lens: list[int], fallbacks: int = 0) -> dict:
    """One utterance as `_measure` would record it, derived from its prompt lengths."""
    return {
        "utt_id": utt_id,
        "duration_s": dur,
        "passes": len(lens),
        "fallback_events": fallbacks,
        "prompt_lens": lens,
        "later_pass_prompted": any(n > 0 for n in lens[1:]),
    }


def test_the_fallback_markers_are_the_ones_faster_whisper_logs():
    """Both rejection paths must be counted, and a rename must fail here loudly.

    Counting only the compression-ratio gate would report zero fallbacks on a corpus
    that fell back on log-probability every time — i.e. would call a non-reproducible
    model reproducible, which is the claim this probe exists to support.
    """
    fw = pytest.importorskip("faster_whisper")
    source = (Path(fw.__file__).parent / "transcribe.py").read_text(encoding="utf-8")
    for marker in mod.FALLBACK_MARKERS:
        assert marker in source, marker
    assert len(mod.FALLBACK_MARKERS) == 2


def test_a_fallback_line_is_not_miscounted_as_a_decode_pass():
    c = mod._PassCounter()
    c.current = "u"
    for msg in ("Processing segment at 00:00.000",
                "Compression ratio threshold is not met with temperature 0.0 (2.9 > 2.4)",
                "Log probability threshold is not met with temperature 0.2 (-1.5 < -1.0)"):
        c.emit(logging.LogRecord("faster_whisper", logging.DEBUG, __file__, 1, msg, (), None))
    assert c.passes["u"] == 1
    assert c.fallbacks["u"] == 2


def test_a_model_that_never_reaches_the_sampled_step_is_reported_as_such(monkeypatch):
    """The base.en result: five identical baseline decodes, explained rather than
    inferred from equal hashes."""
    rows = [_row("a", 4.0, [0], fallbacks=0), _row("b", 12.0, [0, 30], fallbacks=0)]
    _stub(monkeypatch, rows, rows)
    f = mod.run("test-clean", "base.en", 2)["finding"]
    assert f["fallback_events"] == 0
    assert f["fallback_ever_fires"] is False
    assert "rejected no decode attempt at all" in f["reading"]


def test_a_model_that_does_reach_it_is_reported_as_such(monkeypatch):
    rows = [_row("a", 4.0, [0], fallbacks=3), _row("b", 12.0, [0, 30], fallbacks=0)]
    _stub(monkeypatch, rows, rows)
    f = mod.run("test-clean", "large-v3", 2)["finding"]
    assert f["fallback_events"] == 3
    assert f["fallback_ever_fires"] is True
    assert "does reach the sampled step" in f["reading"]
    assert "not the same as differing" in f["reading"], (
        "firing the fallback is not evidence the output moves — base.en fires six "
        "times on test-clean and is still bit-reproducible"
    )


def _stub(monkeypatch, conditioned: list[dict], no_context: list[dict]) -> None:
    """Drive `run()` with recorded rows instead of a decode."""
    subset = [(r["utt_id"], Path("x"), "ref", r["duration_s"]) for r in conditioned]
    monkeypatch.setattr(mod, "librispeech_subset", lambda *a, **k: subset)
    monkeypatch.setattr(mod, "load_audio", lambda p: None)
    monkeypatch.setattr(mod, "subset_digest", lambda ids: "deadbeef")
    monkeypatch.setattr(mod.bench_wer, "_build", lambda *a, **k: object())
    monkeypatch.setattr(mod, "_measure",
                        lambda eng, sub, aud, extra: no_context if extra else conditioned)


def test_the_two_arms_are_the_contrast_the_docstring_names():
    assert set(mod.ARMS) == {"conditioned", "no_context"}
    assert mod.ARMS["conditioned"] == {}, "the control must be faster-whisper's defaults"
    assert mod.ARMS["no_context"] == {"condition_on_previous_text": False}


def test_the_marker_it_counts_is_the_one_faster_whisper_logs():
    """A silent upstream rename would report every clip as zero-pass, not as an error."""
    fw = pytest.importorskip("faster_whisper")
    source = (Path(fw.__file__).parent / "transcribe.py").read_text(encoding="utf-8")
    assert mod.PASS_MARKER in source


def test_a_first_pass_prompt_is_not_counted_as_conditioning():
    """The regression that would make the probe claim an effect on every utterance.

    Pass one is handed the `initial_prompt` (or nothing) under both settings, so only
    passes after the first can show the flag acting.
    """
    assert _row("u", 5.0, [12])["later_pass_prompted"] is False
    assert _row("u", 5.0, [12, 0])["later_pass_prompted"] is False
    assert _row("u", 5.0, [0, 12])["later_pass_prompted"] is True


def test_summarise_counts_multi_pass_utterances_and_their_fraction():
    rows = [_row("a", 4.0, [0]), _row("b", 9.0, [0]), _row("c", 12.0, [0, 30]),
            _row("d", 20.0, [0, 8, 4])]
    s = mod.summarise(rows)
    assert s["n_utterances"] == 4
    assert s["pass_histogram"] == {"1": 2, "2": 1, "3": 1}
    assert s["multi_pass_utterances"] == 2
    assert s["multi_pass_fraction"] == 0.5
    assert s["later_pass_prompted_utterances"] == 2
    assert s["max_duration_s"] == 20.0


def test_the_histogram_is_ordered_numerically_not_lexically():
    """`{"10": ..., "2": ...}` reads as a mistake in an archived artifact."""
    rows = [_row(str(i), 5.0, [0] * n) for i, n in enumerate([1, 2, 10])]
    assert list(mod.summarise(rows)["pass_histogram"]) == ["1", "2", "10"]


def test_summarise_survives_a_corpus_with_no_multi_pass_clip():
    """A guard that iterates is green on an empty collection; this is that collection."""
    s = mod.summarise([_row("a", 3.0, [0]), _row("b", 4.0, [0])])
    assert s["multi_pass_utterances"] == 0
    assert s["multi_pass_fraction"] == 0.0
    assert s["multi_pass_median_duration_s"] is None


def test_the_counter_never_raises_into_the_decode_it_observes():
    """A probe that breaks the run it measures destroys the run, not just the probe."""
    c = mod._PassCounter()
    broken = logging.LogRecord("faster_whisper", logging.DEBUG, __file__, 1,
                               "Processing segment at %s", (), None)
    broken.args = ()  # getMessage() will raise on the unfilled placeholder
    c.emit(broken)  # must not propagate


def test_the_conclusion_is_not_gated_on_the_pass_counts_matching(monkeypatch):
    """The bug this test exists for.

    The first version required the two arms to produce identical pass histograms before
    it would state its conclusion. They do not: dropping the prompt changes what the
    model emits, so `seek` lands elsewhere and one clip went from two passes to three.
    The prompt evidence is counted per pass and is unaffected by that, so the run
    printed `conditioning_reaches_short_audio: True` next to a reading saying the arms
    did not separate.
    """
    conditioned = [_row("a", 4.0, [0]), _row("b", 12.0, [0, 30])]
    no_context = [_row("a", 4.0, [0]), _row("b", 12.0, [0, 0, 0])]
    by_arm = {"conditioned": conditioned, "no_context": no_context}

    monkeypatch.setattr(mod, "librispeech_subset",
                        lambda *a, **k: [("a", Path("x"), "r", 4.0), ("b", Path("y"), "r", 12.0)])
    monkeypatch.setattr(mod, "load_audio", lambda p: None)
    monkeypatch.setattr(mod, "subset_digest", lambda ids: "deadbeef")
    monkeypatch.setattr(mod.bench_wer, "_build", lambda *a, **k: object())
    monkeypatch.setattr(mod, "_measure", lambda eng, sub, aud, extra: by_arm[
        "no_context" if extra else "conditioned"])

    payload = mod.run("test-clean", "base.en", 2)
    f = payload["finding"]
    assert f["conditioning_reaches_short_audio"] is True
    assert f["pass_count_is_unchanged_by_the_flag"] is False
    assert "not confined to long files" in f["reading"]
    assert "do not separate" not in f["reading"]
    assert "consequence of the flag" in f["reading"], "the 2->3 change must be explained"


def test_it_says_so_when_the_arms_genuinely_do_not_separate(monkeypatch):
    """The permissive direction: an inconclusive sample must read as inconclusive."""
    flat = [_row("a", 4.0, [0]), _row("b", 12.0, [0, 0])]
    monkeypatch.setattr(mod, "librispeech_subset",
                        lambda *a, **k: [("a", Path("x"), "r", 4.0), ("b", Path("y"), "r", 12.0)])
    monkeypatch.setattr(mod, "load_audio", lambda p: None)
    monkeypatch.setattr(mod, "subset_digest", lambda ids: "deadbeef")
    monkeypatch.setattr(mod.bench_wer, "_build", lambda *a, **k: object())
    monkeypatch.setattr(mod, "_measure", lambda *a, **k: flat)

    f = mod.run("test-clean", "base.en", 2)["finding"]
    assert f["conditioning_reaches_short_audio"] is False
    assert "do not separate" in f["reading"]


def test_the_artifact_says_what_it_measured(monkeypatch):
    """`MANIFEST.md` describes an artifact from this block; a blank row passes every
    other check in the archive."""
    monkeypatch.setattr(mod, "librispeech_subset",
                        lambda *a, **k: [("a", Path("x"), "r", 4.0)])
    monkeypatch.setattr(mod, "load_audio", lambda p: None)
    monkeypatch.setattr(mod, "subset_digest", lambda ids: "deadbeef")
    monkeypatch.setattr(mod.bench_wer, "_build", lambda *a, **k: object())
    monkeypatch.setattr(mod, "_measure", lambda *a, **k: [_row("a", 4.0, [0])])

    payload = mod.run("test-clean", "base.en", 1)
    assert payload["probe"]["measured"].strip()
    assert payload["probe"]["produced_by"].endswith("decode_mechanism.py")
    assert payload["config"]["corpus_digest"] == "deadbeef"
