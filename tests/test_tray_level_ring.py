"""The tray's live input-level ring.

The badge has five colours and they all describe what YazSes is *doing*. None of
them describes whether the microphone is hearing anything, and those two come apart
exactly when it matters most: a muted mic, a USB-C monitor that stole capture, a VAD
threshold sitting above the user's voice. In every one of those cases the badge is
green for "recording" and nothing is ever typed — the symptom behind
`docs/how-to/silent-audio-discarding.md` and the silent-streak guard.

The ring closes that gap while the burst is happening rather than after it.

What is worth testing is the reasoning, not the pixels: that the gate lands in a
fixed place regardless of microphone, that the ring is hidden whenever showing it
would imply something false, and that a hostile status dict cannot crash the icon.
"""

from __future__ import annotations

import pytest

from yazses.tray.menu import level_ring


def _rec(level: float, threshold: float = 0.01, state: str = "recording") -> dict:
    return {"state": state, "audio_level": level, "vad_threshold": threshold}


# ---- the gate is anchored, which is the whole point ------------------------


@pytest.mark.parametrize("threshold", [0.001, 0.004, 0.01, 0.05, 0.2])
def test_the_gate_sits_in_the_same_place_on_every_microphone(threshold):
    """`audio_level` is mean(|samples|) — its useful range depends on the mic, the
    room and the threshold. Drawn linearly, a quiet setup would sit invisibly near
    zero and a loud one would peg. Anchoring the gate is what makes "past the notch"
    mean the same thing everywhere."""
    at_gate = level_ring(_rec(threshold, threshold))
    assert at_gate.fraction == pytest.approx(at_gate.gate_fraction), (
        f"a level exactly at the threshold must land on the notch (threshold={threshold})"
    )


def test_below_the_gate_reads_as_below():
    ring = level_ring(_rec(0.005, 0.01))
    assert ring.show and not ring.above_gate
    assert ring.fraction < ring.gate_fraction


def test_above_the_gate_reads_as_above():
    ring = level_ring(_rec(0.02, 0.01))
    assert ring.show and ring.above_gate
    assert ring.fraction > ring.gate_fraction


def test_approaching_the_gate_is_visible_rather_than_all_or_nothing():
    """A user who is too quiet should see themselves getting closer, not a dead ring."""
    quiet, louder = level_ring(_rec(0.002)), level_ring(_rec(0.006))
    assert quiet.fraction < louder.fraction < louder.gate_fraction


def test_a_shout_does_not_peg_the_ring_at_the_gate():
    assert level_ring(_rec(0.05)).fraction == 1.0


def test_the_ring_is_monotonic_in_level():
    fractions = [level_ring(_rec(lv)).fraction for lv in (0.0, 0.003, 0.01, 0.02, 0.05)]
    assert fractions == sorted(fractions)


def test_a_live_but_silent_microphone_still_shows_a_ring():
    """Zero sweep would look identical to "not recording", which is the one thing
    this must never be confused with."""
    assert level_ring(_rec(0.0)).fraction > 0


# ---- hidden whenever drawing it would say something untrue -----------------


@pytest.mark.parametrize("state", ["idle", "loading", "error", "enrolling", ""])
def test_no_ring_when_not_recording(state):
    """A ring on an idle badge implies YazSes is listening. It is not, and implying
    otherwise on a tool whose promise is 'it only listens while you hold the key'
    would be the worst possible thing for this icon to say."""
    assert level_ring(_rec(0.05, state=state)).show is False


@pytest.mark.parametrize("threshold", [0.0, -1.0, None])
def test_no_ring_without_a_usable_threshold(threshold):
    """With no gate the notch is meaningless, and a ring with no reference point is
    decoration pretending to be information."""
    assert level_ring({"state": "recording", "audio_level": 0.02,
                       "vad_threshold": threshold}).show is False


def test_no_ring_on_a_missing_status():
    assert level_ring({}).show is False


@pytest.mark.parametrize(
    "status",
    [
        {"state": "recording", "audio_level": "loud", "vad_threshold": 0.01},
        {"state": "recording", "audio_level": None, "vad_threshold": "x"},
        {"state": "recording", "audio_level": -1.0, "vad_threshold": 0.01},
    ],
)
def test_a_malformed_status_hides_the_ring_rather_than_raising(status):
    """This runs inside the icon paint path — an exception here loses the tray."""
    assert level_ring(status).show is False


# ---- the numbers actually reach the tray -----------------------------------


def test_the_tray_model_carries_what_the_ring_needs():
    """`set_state` builds its status dict from a TrayModel, so a field absent there
    can never reach the painter no matter how correct the pure function is."""
    from yazses.platform.base import TrayModel

    model = TrayModel()
    assert hasattr(model, "audio_level") and hasattr(model, "vad_threshold")


def test_the_poller_fills_them_from_the_daemon_status():
    """Guards the wiring end to end: daemon status key -> TrayModel field."""
    import ast
    import inspect

    from yazses.tray import app

    source = inspect.getsource(app)
    tree = ast.parse(source)
    filled = {
        kw.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "TrayModel"
        for kw in node.keywords
    }
    assert {"audio_level", "vad_threshold"} <= filled, (
        f"tray/app.py builds TrayModel without the level fields ({sorted(filled)}), so "
        f"the ring would always draw a silent microphone"
    )
