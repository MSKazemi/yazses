"""Binding eyes-closed from the hands-free panel must not dictate on every blink.

`facegesture/detector.py` says the gesture "needs a long `min_hold_frames`", but the shipped
default is 3 frames (0.2 s at 15 fps) and the panel -- the only path a GUI user has -- never
shows that key. So the mapping write raises it in the same action, and the row says so before
the person presses Set. Pure view-model tests, plus one round trip through the real config
writer and loader, which is what the daemon will read after a restart.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from yazses.facegesture.switches import parse_bindings
from yazses.handsfree.panel import (
    EYES_CLOSED_MIN_HOLD_S,
    ConfigSet,
    ConfigTableArray,
    FeatureFact,
    PanelInputs,
    build_panel,
    eyes_closed_min_hold_frames,
    plan_mapping,
)


def _inputs(**kw) -> PanelInputs:
    base = PanelInputs(
        features=(FeatureFact("facegesture", "Face switch", True),),
        safety_configured=True,
    )
    return replace(base, **kw)


def _raises(plan) -> list[ConfigSet]:
    return [c for c in plan.action.config if isinstance(c, ConfigSet)]


@pytest.mark.parametrize(("fps", "frames"), [(15, 12), (30, 24), (10, 8), (1, 1), (60, 48),
                                              (0, 1), (999, 48)])
def test_the_floor_is_the_hold_time_in_frames_at_the_saved_rate(fps, frames):
    assert eyes_closed_min_hold_frames(fps) == frames


def test_the_hold_time_sits_above_a_blink():
    # Spontaneous blinks are commonly reported at roughly 0.1-0.4 s; the floor must clear that.
    assert EYES_CLOSED_MIN_HOLD_S >= 0.5


def test_mapping_eyes_closed_at_the_default_hold_raises_it_in_the_same_write():
    plan = plan_mapping(_inputs(), "eyes_closed", "hold_to_talk")
    assert plan.ok
    assert _raises(plan) == [ConfigSet("facegesture", "min_hold_frames", 12)]
    assert "0.2 s" in plan.note and "0.8 s" in plan.note and "blink" in plan.note


def test_a_longer_hold_is_never_lowered():
    plan = plan_mapping(_inputs(min_hold_frames=20), "eyes_closed", "hold_to_talk")
    assert plan.ok and _raises(plan) == [] and plan.note == ""


def test_mapping_another_gesture_or_unmapping_eyes_closed_changes_no_hold():
    assert _raises(plan_mapping(_inputs(), "smile", "hold_to_talk")) == []
    switches = ({"gesture": "eyes_closed", "intent": "hold_to_talk"},)
    plan = plan_mapping(_inputs(switches=switches), "eyes_closed", "none")
    assert plan.ok and _raises(plan) == []


def test_any_write_that_leaves_eyes_closed_bound_carries_the_floor():
    # Eyes closed already bound (here as the primary gesture); mapping a different gesture
    # rewrites the table that keeps it bound, so the same protection rides along.
    inputs = _inputs(primary_gesture="eyes_closed")
    plan = plan_mapping(inputs, "brow_raise", "hold_to_command")
    assert plan.ok and _raises(plan) == [ConfigSet("facegesture", "min_hold_frames", 12)]


def test_the_row_warns_before_set_is_pressed_and_only_when_it_applies():
    switches = ({"gesture": "eyes_closed", "intent": "hold_to_talk"},)
    rows = {r.gesture: r for r in build_panel(_inputs(switches=switches)).mapping.rows}
    assert "blink" in rows["eyes_closed"].note and "0.8 s" in rows["eyes_closed"].note
    assert rows["jaw_open"].note == ""  # the shipped primary: not this rule's business
    safe = {r.gesture: r for r in build_panel(
        _inputs(switches=switches, min_hold_frames=12)).mapping.rows}
    assert safe["eyes_closed"].note == ""


def test_the_table_still_round_trips_through_the_daemons_parser():
    plan = plan_mapping(_inputs(), "eyes_closed", "hold_to_talk")
    (table,) = [c for c in plan.action.config if isinstance(c, ConfigTableArray)]
    got, problems = parse_bindings([dict(e) for e in table.entries], "jaw_open", "full_text")
    assert problems == [] and got == {"jaw_open": "hold_to_talk", "eyes_closed": "hold_to_talk"}


def test_the_gui_path_produces_a_config_the_daemon_reads_back(tmp_path):
    """Map eyes closed, then unmap jaw open -- the two Sets a person presses in the panel --
    through the real writers, then load the file the way the daemon does."""
    from yazses.config import load_config
    from yazses.handsfree.panel_io import perform_action
    from yazses.system.configedit import set_config_key, set_config_table_array

    path = tmp_path / "config.toml"
    path.write_text("[facegesture]\nenabled = true\n", encoding="utf-8")

    def write_key(section, key, value, quote):
        set_config_key(path, section, key, value, quote=quote)

    def write_table(name, entries):
        set_config_table_array(path, name, entries)

    def current() -> PanelInputs:
        face = load_config(path).facegesture
        return _inputs(switches=tuple(dict(s) for s in face.switches),
                       min_hold_frames=face.min_hold_frames, fps=face.fps)

    for gesture, action in (("eyes_closed", "hold_to_talk"), ("jaw_open", "none")):
        plan = plan_mapping(current(), gesture, action)
        result = perform_action(plan.action, ipc=None, write_key=write_key, write_table=write_table)
        assert result.ok, result.message

    face = load_config(path).facegesture
    assert face.min_hold_frames == 12
    bindings, problems = parse_bindings(face.switches, face.gesture, face.mode)
    assert problems == [] and bindings == {"eyes_closed": "hold_to_talk"}
