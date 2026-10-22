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


def test_with_the_written_config_a_blink_does_not_dictate_and_a_held_closure_does(tmp_path):
    """The end of the GUI path: the config the two Sets wrote, through the real face-switch backend
    and the real global stop. A blink-length closure must not open the microphone; a held one must,
    and opening the eyes must close it. Scores are a synthetic fixture (0.85 shut, 0.08 open), not
    evidence about a real face."""
    from yazses.config import load_config
    from yazses.facegesture.backend import FaceGestureBackend
    from yazses.handsfree.panel_io import perform_action
    from yazses.handsfree.safety import HandsFreeSafety
    from yazses.perception import FaceSignal, PerceptionSample
    from yazses.system.configedit import set_config_key, set_config_table_array

    path = tmp_path / "config.toml"
    path.write_text("[facegesture]\nenabled = true\n[handsfree_safety]\nenabled = true\n", encoding="utf-8")
    for gesture, action in (("eyes_closed", "hold_to_talk"), ("jaw_open", "none")):
        face = load_config(path).facegesture
        inputs = _inputs(switches=tuple(dict(s) for s in face.switches),
                         min_hold_frames=face.min_hold_frames, fps=face.fps)
        perform_action(plan_mapping(inputs, gesture, action).action, ipc=None,
                       write_key=lambda s, k, v, q: set_config_key(path, s, k, v, quote=q),
                       write_table=lambda n, e: set_config_table_array(path, n, e))
    face = load_config(path).facegesture

    class Lease:
        name = "scripted"
        sample = None

        def start(self): ...

        def stop(self): ...

        def latest(self):
            return self.sample

    def run(face_cfg, closed_spans):
        clock = [100.0]
        events = []
        gate = HandsFreeSafety(("facegesture",), clock=lambda: clock[0] * 1000.0)
        lease = Lease()
        backend = FaceGestureBackend(face_cfg, lambda n: events.append(("open", clock[0] - 100)),
                                     lambda: events.append(("close", clock[0] - 100)),
                                     safety=gate, perception=lease, clock=lambda: clock[0])
        for i in range(int(6 * face_cfg.fps)):
            t = i / face_cfg.fps
            clock[0] = 100.0 + t
            s = 0.85 if any(a <= t < b for a, b in closed_spans) else 0.08
            lease.sample = PerceptionSample(clock[0], face=FaceSignal(
                clock[0], 0.95, {"eyeBlinkLeft": s, "eyeBlinkRight": s, "jawOpen": 0.9 if t > 5 else 0.0}))
            gate.sample("facegesture")
            if i == 1:
                assert gate.resume().ok
            backend._shared_step()
        return [e for e, _t in events if e == "open"], events

    blink = [(1.0, 1.2), (2.0, 2.33)]                  # 0.2 s and 0.33 s
    opens, _ = run(face, blink)
    assert opens == [], "a blink opened the microphone under the config the panel wrote"
    opens, events = run(face, [(1.0, 3.0)])            # held 2 s, then opened
    assert opens == ["open"]
    (_, t_open), = [e for e in events if e[0] == "open"]
    assert 1.0 + 0.7 <= t_open <= 1.0 + 0.9            # ~0.8 s after closing
    assert any(e == "close" and 3.0 <= t <= 3.3 for e, t in events)
    # jaw open was unmapped by the second Set: opening the mouth at t > 5 s did nothing above
    # The same blinks under the shipped 3-frame hold used to open it twice -- the defect the
    # panel's frame floor guarded. Since #406 the detector itself needs EYES_CLOSED_MIN_HOLD_S
    # of sample time for eyes_closed, so the frame count is no longer what stands between a
    # blink and the microphone: a config the panel never wrote is protected too.
    opens, _ = run(replace(face, min_hold_frames=3), blink)
    assert opens == [], "a blink opened the microphone under a 3-frame hold"
