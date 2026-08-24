"""A pinned speaker count silently discards `cluster_threshold`, and now says so.

`sherpa_onnx.FastClusteringConfig` accepts a `num_clusters` **and** a `threshold` and
uses the threshold only when the count is unset. `recimport/diarizer.py` passes both,
with `num_clusters=max_speakers if max_speakers > 0 else -1` — so a user who supplies a
speaker count gets the agglomeration stopped at that many clusters and the threshold
ignored entirely.

That matters because `cluster_threshold` is the setting ADR-v2-133 changed. Moving it
from 0.5 to 1.2 took corpus DER on the whole AMI test split from 75.21 % to 26.71 %, the
largest single improvement on `docs/benchmarks.md`. **None of it reaches a user who
passes `--speakers` or sets `[meeting] max_speakers`,** and both settings sit in the same
config table with nothing to say that one silences the other.

It was found by measurement rather than by reading: `paper/results/probes/ami16-maxspk.json`
(threshold 0.5, cap 4) and `paper/results/diarization-ami16_corpus-maxspk4.json`
(threshold 1.2, cap 4) are **bit-identical on all sixteen recordings**. Two runs two
weeks and one config change apart, agreeing to the second decimal on every meeting, is
not a coincidence that needed a third explanation.

The artifact equality is asserted here too. It is the evidence for the claim in the
message, and if a future change makes the threshold matter under a pinned count, the
warning becomes false — which this notices, in the one place that can.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from yazses.recimport.diarizer import warn_pinned_count

ROOT = Path(__file__).resolve().parents[1]
FREE_THRESH = ROOT / "paper" / "results" / "probes" / "ami16-maxspk.json"
NEW_THRESH = ROOT / "paper" / "results" / "diarization-ami16_corpus-maxspk4.json"


@pytest.mark.parametrize("threshold", [0.5, 1.2, 2.0])
def test_no_warning_when_the_count_is_not_pinned(threshold: float) -> None:
    """`max_speakers = 0` is the shipped default and the threshold is live there.

    Guard the guard in the permissive direction: a warning that fires unconditionally
    would be dismissed within a week and would then be protecting nothing.
    """
    assert warn_pinned_count(0, threshold) == ""


@pytest.mark.parametrize("num", [1, 2, 4, 12])
def test_a_pinned_count_says_the_threshold_is_inert(num: int) -> None:
    msg = warn_pinned_count(num, 1.2)
    assert f"max_speakers={num}" in msg
    assert "cluster_threshold=1.2" in msg
    assert "no effect" in msg


def test_the_warning_reaches_a_log_handler(caplog) -> None:
    """It must be emitted, not merely returned. The caller is a constructor on the
    CLI-only transcribe path and the meeting post-pass; neither shows a return value."""
    with caplog.at_level(logging.WARNING, logger="yazses.recimport.diarizer"):
        warn_pinned_count(4, 1.2)
    assert any("no effect" in r.message for r in caplog.records)


def test_the_warning_does_not_promise_accuracy() -> None:
    """The paired result is "unresolvable", and the message must not round that up.

    Both directions are wrong here. Claiming a pinned count is *better* is the claim
    that was withdrawn from `docs/benchmarks.md` for being confounded; claiming it is
    *worse* is the same error with the sign flipped, and the deciding run split 7-7
    with a sign-test p of 1.0. So the message says the count gets fixed and the DER
    does not resolve, and names the swing.
    """
    msg = warn_pinned_count(4, 1.2)
    assert "not measurably more accurate" in msg
    assert "2.06 -> 0.06" in msg, "the one thing a pinned count reliably does"
    for overclaim in ("is worse", "is better", "improves", "degrades"):
        assert overclaim not in msg, f"the message overclaims: {overclaim!r}"


def _meetings(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data = data.get("result", data)
    return {m["id"]: m["strict"] for m in data["meetings"]}


def test_both_artifacts_are_present() -> None:
    """Guard the guard: the comparison below iterates and is vacuous on a missing file."""
    for p in (FREE_THRESH, NEW_THRESH):
        assert p.is_file(), f"{p} is the evidence for the warning's claim and is missing"


def test_the_threshold_provably_did_nothing_under_a_pinned_count() -> None:
    a, b = _meetings(FREE_THRESH), _meetings(NEW_THRESH)
    assert sorted(a) == sorted(b), "the two runs cover different recordings"
    assert len(a) == 16
    differing = {k: (a[k]["der"], b[k]["der"]) for k in a if a[k]["der"] != b[k]["der"]}
    assert not differing, (
        "threshold 0.5 and 1.2 under `max_speakers = 4` no longer agree on "
        f"{sorted(differing)}. If that is a real change, `cluster_threshold` now does "
        "something under a pinned count and `warn_pinned_count` is telling users "
        "something false — fix the message, do not delete this test."
    )


def test_the_two_runs_used_the_thresholds_they_claim() -> None:
    """Otherwise the equality above is proved by both runs having the same config,
    which would make it a tautology rather than a finding."""
    def cfg(path: Path) -> dict:
        d = json.loads(path.read_text(encoding="utf-8"))
        return (d.get("result", d))["config"]

    assert cfg(FREE_THRESH)["cluster_threshold"] == 0.5
    assert cfg(NEW_THRESH)["cluster_threshold"] == 1.2
    assert cfg(FREE_THRESH)["max_speakers"] == 4
    assert cfg(NEW_THRESH)["max_speakers"] == 4


def test_the_constructor_actually_calls_it() -> None:
    """A message nothing invokes is a comment.

    Read from the source rather than by constructing a `SherpaDiarizer`, which needs the
    optional `diarization` extra *and* two ONNX files on disk — so a behavioural test
    here would skip in every environment that does not have both, which is every
    environment except one rented box. That is the same hole this session found in
    `test_shipped_backends.py`, and reopening it to test a one-line call would be a poor
    trade.
    """
    import inspect

    from yazses.recimport.diarizer import SherpaDiarizer

    src = inspect.getsource(SherpaDiarizer.__init__)
    assert "warn_pinned_count(num, threshold)" in src, (
        "SherpaDiarizer no longer calls warn_pinned_count, so a pinned speaker count "
        "silently discards cluster_threshold again"
    )
