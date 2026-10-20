"""The face-switch mapping is validated when the config is LOADED (EYE-FACE-002).

``parse_bindings`` has always skipped, never coerced, a mapping it could not honour -- but only
the camera backend asked it, so the answer reached a log line when the daemon built the switch.
A typo in ``intent`` loaded clean, ``yazses doctor`` said every setting was usable, and the user
was left with a facial movement bound to nothing. These tests pin the load-time report, and the
one bound the freeze-the-pointer request needs when the gesture it belongs to cannot let go.

The traces and files are synthetic; nothing here is evidence for a threshold.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from yazses.config import FacegestureConfig, load_config_checked
from yazses.facegesture.detector import GestureSwitch
from yazses.facegesture.switches import (
    ACTIONS,
    COMMIT_ACTIONS,
    HOLD_ACTIONS,
    SwitchAction,
    SwitchIntent,
    SwitchMapper,
    stuck_consequence,
)


def _load(tmp_path: Path, body: str):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return load_config_checked(path)


def _face_problems(loaded) -> list[str]:
    return [str(p) for p in loaded.problems if p.section == "facegesture"]


_HEADER = "[facegesture]\nenabled = true\n"


def _entry(gesture: str, intent: str) -> str:
    return f'[[facegesture.switches]]\ngesture = "{gesture}"\nintent = "{intent}"\n'


# ----------------------------------------------------------------------------- a clean file


def test_a_file_with_no_switches_reports_nothing(tmp_path):
    assert _face_problems(_load(tmp_path, _HEADER)) == []


def test_every_valid_action_and_the_explicit_unmap_load_clean(tmp_path):
    body = _HEADER + _entry("brow_raise", "select") + _entry("smile", "none") + _entry("Mouth_Pucker", "CONFIRM")
    loaded = _load(tmp_path, body)
    assert loaded.problems == []
    assert len(loaded.config.facegesture.switches) == 3


@pytest.mark.parametrize("action", [pytest.param(a, id=a) for a in ACTIONS])
def test_each_published_action_is_accepted_at_load(tmp_path, action):
    assert _face_problems(_load(tmp_path, _HEADER + _entry("brow_raise", action))) == []


# --------------------------------------------------------- a bad mapping is named at load time


def test_an_unknown_action_is_rejected_at_load_with_the_valid_names(tmp_path):
    loaded = _load(tmp_path, _HEADER + _entry("brow_raise", "selct"))
    (problem,) = _face_problems(loaded)
    assert "selct" in problem and "not an action" in problem
    assert all(name in problem for name in ("select", "confirm", "cancel", "hold_to_talk"))
    assert problem.startswith("[facegesture] switches:")


def test_an_unknown_gesture_is_rejected_at_load_with_the_valid_names(tmp_path):
    (problem,) = _face_problems(_load(tmp_path, _HEADER + _entry("smyle", "select")))
    assert "smyle" in problem and "not a gesture" in problem and "smile" in problem


def test_one_bad_entry_does_not_cost_its_good_neighbours(tmp_path):
    body = _HEADER + _entry("brow_raise", "selct") + _entry("smile", "select")
    loaded = _load(tmp_path, body)
    assert len(_face_problems(loaded)) == 1
    assert len(loaded.config.facegesture.switches) == 2  # the table is kept; the backend skips the bad one


def test_two_switches_on_the_same_expression_are_reported_and_the_first_wins(tmp_path):
    body = _HEADER + _entry("brow_raise", "select") + _entry("brow_raise", "cancel")
    (problem,) = _face_problems(_load(tmp_path, body))
    assert "switches[1]" in problem and "already mapped" in problem


def test_a_switch_entry_that_is_not_a_table_is_reported(tmp_path):
    loaded = _load(tmp_path, _HEADER + 'switches = ["brow_raise"]\n')
    assert any("should be a table" in p or "list" in p for p in _face_problems(loaded)), loaded.problems


def test_a_bad_primary_gesture_does_not_stop_the_mapping_being_checked(tmp_path):
    body = '[facegesture]\ngesture = "wink"\n' + _entry("brow_raise", "selct")
    problems = [str(p) for p in _load(tmp_path, body).problems]
    assert any("'wink'" in p or "wink" in p for p in problems)          # the key's own problem
    assert any("selct" in p and "not an action" in p for p in problems)  # and the mapping's


def test_the_report_reaches_doctor_as_a_failing_config_row(tmp_path):
    from yazses.system.doctor import _config_validity

    path = tmp_path / "config.toml"
    path.write_text(_HEADER + _entry("brow_raise", "selct"), encoding="utf-8")
    rows = _config_validity(path)
    assert rows[0][0] == "Config validity" and rows[0][1] == "FAIL"
    assert any("selct" in row[2] for row in rows[1:])


def test_a_file_of_valid_switches_is_ok_in_doctor(tmp_path):
    from yazses.system.doctor import _config_validity

    path = tmp_path / "config.toml"
    path.write_text(_HEADER + _entry("brow_raise", "select"), encoding="utf-8")
    assert _config_validity(path)[0][1] == "OK"


# ------------------------------- a commit gesture that cannot let go freezes the pointer for ever


def test_stuck_consequence_names_what_each_action_leaves_held():
    assert {a: stuck_consequence(a) for a in ACTIONS} == {
        "hold_to_talk": "microphone",
        "hold_to_command": "microphone",
        "select": "pointer",
        "confirm": "pointer",
        "cancel": None,
        "pause_pointer": None,
    }
    assert stuck_consequence("none") is None and stuck_consequence(None) is None
    assert {a for a in ACTIONS if stuck_consequence(a) == "microphone"} == set(HOLD_ACTIONS)
    assert {a for a in ACTIONS if stuck_consequence(a) == "pointer"} == set(COMMIT_ACTIONS)


def _stuck_rig(max_hold_s: float):
    """A select-bound switch fed a face that fires and never relaxes, through the real mapper."""
    freezes: list[bool] = []
    clicks: list[int] = []
    mapper = SwitchMapper(
        {"jaw_open": "select"},
        {"select": SwitchAction(press=lambda: clicks.append(1))},
        on_freeze=freezes.append,
    )
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=2, max_hold_s=max_hold_s)

    def step(score: float, t: float) -> None:
        event = sw.update(score, 1.0, now_s=t)
        if event is not None:
            phase = "press" if event == "start" else "release"
            mapper.handle(SwitchIntent("jaw_open", phase, t))

    return mapper, sw, step, freezes, clicks


def test_a_select_gesture_that_never_relaxes_keeps_the_pointer_frozen_and_clicks_only_once():
    mapper, _sw, step, freezes, clicks = _stuck_rig(max_hold_s=0.0)  # the shipped state: guard off
    for i in range(5000):
        step(0.9, i * 0.1)
    # Characterisation of the hazard `restcheck` now names for commit actions too.
    assert mapper.freeze_pointer and freezes == [True] and clicks == [1]


def test_the_opt_in_max_hold_releases_the_freeze_and_a_relaxed_face_rearms_the_switch():
    mapper, sw, step, freezes, clicks = _stuck_rig(max_hold_s=5.0)
    for i in range(200):  # 20 s at 10 Hz
        step(0.9, i * 0.1)
    assert not mapper.freeze_pointer and freezes == [True, False] and sw.latched
    step(0.0, 21.0)  # a real reading below release re-arms
    for i in range(3):
        step(0.9, 22.0 + i * 0.1)
    assert clicks == [1, 1] and mapper.freeze_pointer


# ------------------------------------------------ the shipped config stays dormant (rule 2)


def test_the_shipped_defaults_are_dormant():
    cfg = FacegestureConfig()
    assert cfg.enabled is False and cfg.switches == []
    assert replace(cfg, enabled=True).switches == []
