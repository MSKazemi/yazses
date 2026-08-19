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
    """The tail still ends somewhere — but 0.05 is not where.

    This used to assert `_rec(0.05).fraction == 1.0`, i.e. that 5x the gate is a shout.
    Measured over 1617 real recorded bursts the p90 level is 0.0786, so 0.05 is ordinary
    speech, and pegging there is what made the ring read full on 44% of bursts at the
    default threshold. The scale is logarithmic now; see
    tests/test_tray_level_ring_scale.py for the measurement.
    """
    assert level_ring(_rec(0.05)).fraction < 1.0
    assert level_ring(_rec(0.01 * 200)).fraction == 1.0


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


# --- the glyph must be legible on its own badge ------------------------------
#
# The mark was painted white on every state colour. Measured against
# settingsui/theme.py's contrast maths — the only such maths in the codebase, and
# used nowhere near the tray until now — that is:
#
#     yellow  1.71:1     green  3.06:1     red  4.23:1     blue  4.51:1
#
# WCAG AA asks 4.5:1. Three of five failed, and the worst by a distance is yellow,
# which is the state meaning "recording, but there is nowhere to type" — the one a
# user most needs to notice. An icon that says "your words are going nowhere" and
# cannot be read is not doing the job it exists for.


def test_the_glyph_colour_is_chosen_by_contrast() -> None:
    from yazses.settingsui.theme import contrast_ratio
    from yazses.tray.menu import glyph_for

    def _rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]

    for badge in ("#34a853", "#fbbc04", "#9c27b0", "#1a73e8", "#e53935"):
        glyph = glyph_for(badge)
        chosen = contrast_ratio(_rgb(glyph), _rgb(badge))
        other = contrast_ratio(_rgb("#000000" if glyph == "#ffffff" else "#ffffff"), _rgb(badge))
        assert chosen >= other, f"{badge}: picked the less legible glyph"


def test_the_worst_case_is_fixed() -> None:
    """Yellow with a white glyph was 1.71:1 — effectively unreadable at 16 px."""
    from yazses.settingsui.theme import contrast_ratio
    from yazses.tray.menu import glyph_for

    def _rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]

    ratio = contrast_ratio(_rgb(glyph_for("#fbbc04")), _rgb("#fbbc04"))
    assert ratio >= 4.5, f"the no-text-target badge is still only {ratio:.2f}:1"


def test_every_shipped_state_colour_clears_aa() -> None:
    """Not just the five: any colour the tray can paint has to be legible."""
    from yazses.settingsui.theme import AA_NORMAL, contrast_ratio
    from yazses.tray import menu as menu_mod

    def _rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]

    shipped = [v for k, v in vars(menu_mod).items()
               if k.startswith("_") and isinstance(v, str) and v.startswith("#") and len(v) == 7]
    assert shipped, "no state colours found — this guard is checking nothing"
    for badge in shipped:
        ratio = contrast_ratio(_rgb(menu_mod.glyph_for(badge)), _rgb(badge))
        assert ratio >= AA_NORMAL, f"{badge} glyph is {ratio:.2f}:1, below AA"


def test_an_unparseable_colour_falls_back_rather_than_raising() -> None:
    """A bad colour must not take the tray icon down — the paint path swallows
    exceptions, so raising here would mean no icon at all."""
    from yazses.tray.menu import glyph_for

    assert glyph_for("not-a-colour").startswith("#")
    assert glyph_for("").startswith("#")


def test_the_two_trays_agree_on_the_icon_size() -> None:
    """`_ICON_PX` is declared in both tray backends, kept equal by a comment.

    A comment is not a mechanism. The size decides which frame Windows picks for
    the display scaling and how the level ring's geometry lands, so a divergence
    would be visible on one platform and invisible to whoever caused it. The
    geometry and the glyph colour are already shared; this is the last constant
    that was not.
    """
    from yazses.platform.linux.tray import _ICON_PX as linux_px
    from yazses.platform.windows.tray import _ICON_PX as windows_px

    assert linux_px == windows_px, (
        f"the Linux tray draws at {linux_px}px and the Windows tray at {windows_px}px"
    )
