"""The overlay's envelope follower must stay adaptive, not become a fixed span.

Two indicators read the same `audio_level`: the tray's level ring and the overlay's rings.
The ring mapped it against a fixed multiple of the gate and, measured over 1617 real bursts,
read **full on 44% of them at the default threshold** — a meter carrying about one bit
(fixed in the same sweep, see `tests/test_tray_level_ring_scale.py`).

The overlay does not have that problem, and this file exists so it cannot acquire it.

## Measured on a real 162-second recording

Chunking the audio the way the daemon does (`mean(|samples|)` per capture block) gives 2537
readings, p10/median/p90 = 0.0043 / 0.0216 / 0.0609. Through the follower:

    threshold 0.01     median intensity 0.35   sd 0.21   pegged 0.0%   at-zero 0.7%
    threshold 0.0005   median intensity 0.42   sd 0.20   pegged 0.0%   at-zero 0.1%

The two thresholds differ by 20x and the output barely moves. That is the property worth
protecting: brightness tracks *loud for this speaker* rather than an absolute level, so a
badly-set gate degrades the rings gently instead of pinning them.

## Why the tray needed a different answer

The ring has to put the gate at a **fixed point on its circumference** — "past the notch"
must mean the same thing on every microphone — so it cannot normalise adaptively. It got a
logarithmic absolute scale instead. Same signal, different constraint, different answer;
this note is here so the two are not "unified" into one broken shape later.

## The stimulus is synthetic on purpose

Bursts of speech separated by pauses, at the percentiles measured above. A test that needed
the learning corpus would only run on a machine that had one.
"""

from __future__ import annotations

import random
import statistics

import pytest

from yazses.overlay.envelope import EnvelopeFollower


def _speech(n: int = 2000, seed: int = 7) -> list[float]:
    """Bursts of speech separated by pauses, matching the measured real percentiles."""
    rng = random.Random(seed)
    out: list[float] = []
    while len(out) < n:
        loud = rng.uniform(0.015, 0.09)
        for _ in range(rng.randint(30, 120)):
            out.append(max(0.0, rng.gauss(loud, loud * 0.4)))
        for _ in range(rng.randint(5, 40)):
            out.append(rng.uniform(0.0, 0.004))
    return out[:n]


def _run(threshold: float) -> list[float]:
    follower = EnvelopeFollower(threshold=threshold)
    return [follower.update(level) for level in _speech()]


@pytest.mark.parametrize("threshold", [0.0005, 0.004, 0.01, 0.05])
def test_the_rings_never_peg_on_ordinary_speech(threshold: float) -> None:
    """The failure the tray ring had: full brightness for half of normal speech."""
    out = _run(threshold)
    pegged = sum(1 for v in out if v > 0.99) / len(out)
    assert pegged < 0.05, f"rings saturate on {pegged:.0%} of ordinary speech"


@pytest.mark.parametrize("threshold", [0.0005, 0.004, 0.01])
def test_the_rings_use_their_range(threshold: float) -> None:
    """Not pegging is not enough — a follower stuck near zero also carries nothing."""
    out = _run(threshold)
    assert statistics.pstdev(out) > 0.1, "brightness barely varies across speech"
    assert 0.15 < statistics.median(out) < 0.9


def test_a_twentyfold_change_in_the_gate_barely_moves_the_output() -> None:
    """The adaptive property, stated directly.

    On real audio, thresholds of 0.01 and 0.0005 gave median intensities of 0.35 and 0.42.
    A fixed-span follower would differ enormously here — that is exactly how the tray ring
    went from 44% pegged to 97% pegged over the same range.
    """
    low = statistics.median(_run(0.0005))
    high = statistics.median(_run(0.01))
    assert abs(low - high) < 0.25, (
        f"the gate now dominates the output ({low:.2f} vs {high:.2f}) — the follower has "
        f"stopped normalising against its own peak"
    )


def test_silence_produces_no_rings() -> None:
    """Everything at or below the gate is silence; rings while silent would imply
    YazSes is hearing something when it is not."""
    follower = EnvelopeFollower(threshold=0.01)
    for _ in range(50):
        follower.update(0.002)
    assert follower.value == pytest.approx(0.0, abs=0.01)


def test_it_rises_faster_than_it_falls() -> None:
    """Asymmetric attack/release is what makes it read as responsive rather than
    twitchy; a symmetric follower would pass every test above."""
    up = EnvelopeFollower(threshold=0.0)
    for _ in range(3):
        up.update(0.05)
    risen = up.value
    for _ in range(3):
        up.update(0.0)
    fallen_by = risen - up.value
    assert risen > 0.8, "attack is too slow to follow a voice onset"
    assert fallen_by < risen, "release is not slower than attack"


def test_a_whisper_after_a_shout_is_still_visible() -> None:
    """The adaptive ceiling decays; without that a loud burst blanks the next minute."""
    follower = EnvelopeFollower(threshold=0.001)
    for _ in range(20):
        follower.update(0.3)
    for _ in range(600):          # ~10 s at 60 fps
        follower.update(0.02)
    assert follower.value > 0.15, "quiet speech stays invisible long after a loud burst"


def test_the_follower_still_normalises_against_its_own_peak() -> None:
    """The mechanism, so replacing it with a constant fails here and not in the field."""
    import ast
    import inspect
    import textwrap

    from yazses.overlay import envelope

    # `getsource` of a method keeps its class indentation, which `ast.parse` rejects.
    src = textwrap.dedent(inspect.getsource(envelope.EnvelopeFollower.update))
    fn = ast.parse(src).body[0]
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body
    code = "\n".join(ast.unparse(node) for node in body)
    assert "_peak" in code, (
        "the envelope no longer tracks an adaptive peak — see the tray ring for what a "
        "fixed span does to real speech"
    )
