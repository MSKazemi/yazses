"""A non-finite level in the daemon's ``status`` reply must not poison the level displays.

The daemon encodes ``status`` with ``json.dumps``, whose default writes a non-finite float
as ``Infinity`` / ``NaN``, and the IPC client's ``json.loads`` reads it back as a float.
So ``audio_level`` (``mean(|chunk|)``) and ``vad_threshold`` can arrive non-finite.

Two displays read them:

* the overlay (``overlay/poller.py`` -> ``overlay/envelope.py``): one ``Infinity`` latched
  the envelope's adaptive peak at inf, and every later reading divided to 0 -- the sonar
  stayed dark for the rest of the overlay session;
* the tray's level ring (``tray/menu.level_ring``): a ``NaN`` level drew a *full* ring
  flagged as below the gate, a reading that contradicts itself.

Pure-logic tests, synthetic inputs, no display needed.
"""
from __future__ import annotations

import json
import math

import pytest

from yazses.overlay.envelope import EnvelopeFollower
from yazses.overlay.poller import parse_status
from yazses.tray.menu import level_ring


def _over_the_wire(payload: dict) -> dict:
    """Round-trip through the same json defaults the daemon and the client use."""
    return json.loads(json.dumps(payload))


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
@pytest.mark.parametrize("key", ["audio_level", "vad_threshold"])
def test_parse_status_never_returns_a_non_finite_level(key: str, bad: float) -> None:
    snap = parse_status(_over_the_wire({"state": "recording", key: bad}))
    assert math.isfinite(snap.audio_level)
    assert math.isfinite(snap.vad_threshold)


def test_one_infinite_reading_does_not_silence_the_sonar_for_the_session() -> None:
    envelope = EnvelopeFollower(threshold=0.01)
    bad = parse_status(_over_the_wire({"state": "recording", "audio_level": float("inf")}))
    envelope.update(bad.audio_level)

    speech = parse_status(_over_the_wire({"state": "recording", "audio_level": 0.2}))
    readings = [envelope.update(speech.audio_level) for _ in range(5)]
    assert readings[-1] > 0.5, readings


@pytest.mark.parametrize(
    "level, threshold",
    [
        (float("nan"), 0.01),
        (0.02, float("nan")),
        (float("inf"), 0.01),
        (0.02, float("inf")),
    ],
)
def test_level_ring_hides_on_a_non_finite_reading(level: float, threshold: float) -> None:
    status = _over_the_wire(
        {"state": "recording", "audio_level": level, "vad_threshold": threshold}
    )
    ring = level_ring(status)
    assert ring.show is False


def test_level_ring_still_draws_an_ordinary_reading() -> None:
    ring = level_ring({"state": "recording", "audio_level": 0.02, "vad_threshold": 0.01})
    assert ring.show is True
    assert ring.above_gate is True
