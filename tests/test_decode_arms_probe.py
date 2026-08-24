"""Guards for the paired per-utterance arm comparison.

The probe's whole value is that it makes a decode-setting change *decidable*: a corpus
WER cannot say whether a gain is broad or comes from two clips that ran away, and a
number without an interval cannot say whether it is a gain at all. These tests pin the
statistics rather than the decoding -- the arithmetic is what the decision rests on, and
it is also the only part that can be wrong silently.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "paper" / "benchmark"
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "probes"))

jiwer = pytest.importorskip("jiwer")
mod = pytest.importorskip("decode_arms_per_utterance")


def _row(utt_id, ref_words, errors):
    return {"id": utt_id, "ref_words": ref_words, "insertions": errors,
            "substitutions": 0, "deletions": 0, "errors": errors}


# --- the sign test -----------------------------------------------------------------

def test_the_sign_test_matches_the_closed_form():
    # Five wins and no losses is 2 * (1/2)**5 two-sided.
    assert mod.exact_sign_test(5, 0) == pytest.approx(2 * 0.5 ** 5)
    assert mod.exact_sign_test(0, 5) == pytest.approx(2 * 0.5 ** 5)


def test_an_even_split_is_as_unsurprising_as_it_gets():
    assert mod.exact_sign_test(10, 10) == pytest.approx(1.0)


def test_no_discordant_pairs_is_not_evidence():
    """Every utterance unchanged must not read as a significant result."""
    assert mod.exact_sign_test(0, 0) == 1.0


def test_the_p_value_is_never_above_one():
    """The doubling of the one-sided tail can overshoot; it must be clamped."""
    for better in range(0, 12):
        for worse in range(0, 12):
            assert 0.0 <= mod.exact_sign_test(better, worse) <= 1.0


def test_ties_do_not_dilute_the_evidence():
    """A tie carries no directional information, so 5-0 stays 5-0 among 200 unchanged."""
    base = [_row(f"u{i}", 10, 5) for i in range(200)]
    arm = [dict(r) for r in base]
    for i in range(5):
        arm[i] = {**arm[i], "errors": 0, "insertions": 0}
    out = mod.compare(base, arm)
    assert (out["utterances_better"], out["utterances_worse"]) == (5, 0)
    assert out["utterances_unchanged"] == 195
    assert out["sign_test_p"] == pytest.approx(2 * 0.5 ** 5, abs=1e-4)


# --- corpus WER --------------------------------------------------------------------

def test_corpus_wer_weights_by_reference_length():
    """Not the mean of per-utterance WERs -- a one-word utterance would then outweigh a
    fifty-word one, which is how a corpus figure ends up describing its shortest clips."""
    rows = [_row("a", 1, 1), _row("b", 99, 0)]
    assert mod._corpus_wer(rows) == pytest.approx(1 / 100 * 100)


def test_an_empty_corpus_does_not_divide_by_zero():
    assert mod._corpus_wer([]) == 0.0


# --- per-utterance scoring ---------------------------------------------------------

def test_each_utterance_is_aligned_on_its_own():
    """A word that could be charged to either neighbour must not migrate across the
    boundary: concatenating first is what makes an insertion ambiguous."""
    ids = ["a", "b"]
    refs = ["the cat sat", "on the mat"]
    hyps = ["the cat sat on", "the mat"]
    rows = mod._per_utterance(ids, refs, hyps)
    assert [r["id"] for r in rows] == ["a", "b"]
    assert rows[0]["insertions"] == 1  # charged to the utterance that emitted it
    assert rows[1]["deletions"] == 1


def test_an_unscorable_utterance_does_not_shift_every_later_id():
    """The regression this file exists for.

    An empty reference is dropped, so the surviving rows no longer line up with the
    subset list. Carrying the id positionally would have named `b`'s audio for `c`'s
    errors -- a mislabel that reads as a finding and points at the wrong clip.
    """
    ids = ["a", "b", "c"]
    refs = ["hello world", "", "goodbye now"]
    hyps = ["hello world", "spurious", "goodbye then"]
    rows = mod._per_utterance(ids, refs, hyps)
    assert [r["id"] for r in rows] == ["a", "c"]
    assert rows[1]["substitutions"] == 1  # "now" -> "then", and it belongs to c


# --- the pairing --------------------------------------------------------------------

def test_pairing_refuses_arms_that_scored_different_utterances():
    base = [_row("a", 10, 1), _row("b", 10, 1)]
    arm = [_row("a", 10, 1), _row("z", 10, 1)]
    with pytest.raises(ValueError, match="different utterances"):
        mod.compare(base, arm)


def test_the_baseline_is_the_median_run_not_the_best():
    runs = [
        [_row("a", 10, 9)],  # worst
        [_row("a", 10, 1)],  # best
        [_row("a", 10, 5)],  # median
    ]
    assert mod.median_run(runs)[0]["errors"] == 5


def test_a_real_difference_is_called_and_signed():
    base = [_row(f"u{i}", 10, 4) for i in range(60)]
    arm = [_row(f"u{i}", 10, 1) for i in range(60)]
    out = mod.compare(base, arm)
    assert out["delta_wer"] < 0
    lo, hi = out["delta_wer_ci95"]
    assert hi < 0, "a uniform three-error-per-utterance win must resolve"
    assert out["verdict"] == "arm is better"


def test_no_difference_is_reported_as_no_difference():
    """Half better by one, half worse by one: the honest answer is 'cannot resolve'."""
    base = [_row(f"u{i}", 10, 3) for i in range(60)]
    arm = [{**r, "errors": 3 + (1 if i % 2 else -1)} for i, r in enumerate(base)]
    out = mod.compare(base, arm)
    lo, hi = out["delta_wer_ci95"]
    assert lo <= 0 <= hi
    assert out["verdict"] == "no resolvable difference"


def test_the_interval_is_reproducible():
    base = [_row(f"u{i}", 10, 4) for i in range(40)]
    arm = [_row(f"u{i}", 10, 2) for i in range(40)]
    assert mod.compare(base, arm) == mod.compare(base, arm)


# --- concentration ------------------------------------------------------------------

def test_a_gain_carried_by_one_clip_is_reported_as_such():
    """The question in the probe's title, as a number."""
    base = [_row(f"u{i}", 10, 1) for i in range(20)]
    base[7] = _row("u7", 10, 100)
    arm = [_row(f"u{i}", 10, 1) for i in range(20)]
    out = mod.compare(base, arm)
    assert out["gain_concentration"]["top_1"]["share_of_gain"] == pytest.approx(1.0)
    assert out["gain_concentration"]["top_1"]["utterances"] == ["u7"]


def test_a_broad_gain_is_not_reported_as_concentrated():
    base = [_row(f"u{i}", 10, 3) for i in range(20)]
    arm = [_row(f"u{i}", 10, 2) for i in range(20)]
    out = mod.compare(base, arm)
    assert out["gain_concentration"]["top_1"]["share_of_gain"] == pytest.approx(1 / 20)
    assert out["total_errors_removed"] == 20


def test_concentration_does_not_divide_by_zero_when_nothing_improved():
    base = [_row(f"u{i}", 10, 2) for i in range(10)]
    arm = [_row(f"u{i}", 10, 5) for i in range(10)]
    out = mod.compare(base, arm)
    assert out["total_errors_removed"] == 0
    assert out["verdict"] == "arm is worse"


def test_the_arms_are_the_ones_the_determinism_probe_settled():
    """The comparison is only meaningful against the arms already shown deterministic."""
    assert set(mod.ARMS) == {"baseline", "greedy", "greedy_no_context"}
