"""The hands-free control panel's view-model (EYE-SETTINGS-001, #420).

The panel is for somebody who cannot use a keyboard or mouse reliably, so the properties held
here are the ones that fail that person first:

* nothing is on by default, and a panel that is merely displayed asks for nothing;
* a FAULTED state always offers a way out, and stopping is never harder than starting;
* a state that nobody determined, or a backend that does not exist, never reads as healthy;
* state is carried by a word, never by colour alone;
* no action takes a pointer position;
* the actions offered are the ones that do something in this build (guarded against the
  daemon, not against a hand-written copy of it).

Pure: no Qt, no camera, no daemon, no socket.
"""
from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from yazses.facegesture.detector import GESTURES
from yazses.facegesture.switches import ACTIONS, parse_bindings
from yazses.handsfree.observability import HandsFreeFacts
from yazses.handsfree.panel import (
    STATUS_WORDS,
    ConfigTableArray,
    FeatureFact,
    Overall,
    PanelInputs,
    build_panel,
    merge_facts,
    plan_mapping,
    render_text,
    wired_switch_actions,
)
from yazses.handsfree.safety import SafetyState, SafetyStatus, SourceHealth

WAYLAND = (
    "no pointer output: PointerUnsupportedError: native Wayland session: the X11 pointer "
    "backend only reaches XWayland, and the portal pointer backend is not selected for "
    "this platform yet"
)


def _features(**on: bool) -> tuple[FeatureFact, ...]:
    return tuple(
        FeatureFact(slug, slug, enabled=on.get(slug, False))
        for slug in ("headpointer", "facegesture", "gaze")
    )


def _safety(state: SafetyState, reason: str = "", *, sources=()) -> SafetyStatus:
    return SafetyStatus(
        state=state, reason=reason, terminal=False,
        user_paused=state is SafetyState.PAUSED, epoch=1, sources=tuple(sources),
    )


def _source(name="headpointer", *, armed=True, stale=False, faulted=False, reason="", age=40.0):
    return SourceHealth(name, armed, stale, faulted, reason, age, 1)


def _hp(**kw):
    base = {
        "ok": True, "active": True, "state": "tracking", "reason": "", "paused": False,
        "clutched": False, "calibrated": True, "dwell_enabled": False, "fault": "",
        "backend": "x11",
    }
    base.update(kw)
    return base


def _inputs(*, safety=None, hp=None, reachable=True, safety_cfg=True, **features) -> PanelInputs:
    facts = HandsFreeFacts(
        features_requested=tuple(k for k, v in features.items() if v),
        camera_ready=True,
        safety_configured=safety_cfg,
        safety=safety,
        head_wired=True,
        face_wired=True,
    )
    return PanelInputs(
        daemon_reachable=reachable,
        features=_features(**features),
        safety_configured=safety_cfg,
        facts=facts,
        headpointer=hp,
    )


def _all_rows(model):
    return [*model.health, *model.features]


# ------------------------------------------------------------------ a default install


def test_a_default_install_is_off_and_offers_to_turn_nothing_on_by_itself():
    model = build_panel(PanelInputs(features=_features()))
    assert model.banner.state is Overall.OFF
    assert "Nothing" in model.banner.detail
    assert all(f.status == "off" and f.desired is True for f in model.features)
    assert model.health == ()
    # Nothing is running, so nothing can be paused, resumed or recentred — and each says why.
    for spec in model.actions:
        assert not spec.enabled and spec.why_disabled


def test_displaying_the_panel_is_documented_as_not_opening_the_camera():
    model = build_panel(PanelInputs(features=_features()))
    assert any("does not open the camera" in n for n in model.notes)


# ------------------------------------------------------------------ the three states


def test_active_offers_pause_as_the_primary_action_and_nothing_to_resume():
    model = build_panel(_inputs(safety=_safety(SafetyState.ACTIVE), headpointer=True, hp=_hp()))
    assert model.banner.state is Overall.ACTIVE
    assert model.primary is model.action("pause")
    assert model.action("pause").enabled
    assert not model.action("resume").enabled
    assert model.action("resume").why_disabled == "Already active."


def test_paused_offers_resume_and_says_nothing_restarts_by_itself():
    model = build_panel(
        _inputs(safety=_safety(SafetyState.PAUSED, "paused by the user"), headpointer=True, hp=_hp())
    )
    assert model.banner.state is Overall.PAUSED
    assert "paused by the user" in model.banner.headline
    assert model.primary is model.action("resume")
    assert model.action("resume").enabled and not model.action("pause").enabled
    assert "by itself" in model.banner.detail


@pytest.mark.parametrize(
    "inputs",
    [
        # the global gate says FAULTED
        _inputs(
            safety=_safety(
                SafetyState.FAULTED, "headpointer: signal is stale (900 ms old)",
                sources=[_source(stale=True, age=900.0)],
            ),
            headpointer=True, hp=_hp(state="suppressed"),
        ),
        # the global stop is off and the Head-Pointer itself is faulted
        _inputs(
            safety=None, safety_cfg=False, headpointer=True,
            hp=_hp(state="faulted", fault="pointer backend failed"),
        ),
    ],
    ids=["gate faulted", "head-pointer faulted, no gate"],
)
def test_a_faulted_state_always_offers_recovery(inputs):
    model = build_panel(inputs)
    assert model.banner.state is Overall.FAULTED
    recover = model.action("resume")
    assert recover.enabled, "FAULTED must never leave the user without a way out"
    assert recover.label.startswith("Recover") and recover.kind == "recover"
    assert model.primary is recover
    assert "never replays" in model.banner.detail
    # and stopping is still possible while faulted
    assert model.action("pause").enabled


def test_stopping_is_never_gated_on_a_healthy_camera():
    inputs = replace(
        _inputs(safety=_safety(SafetyState.ACTIVE), headpointer=True, hp=_hp()),
        facts=HandsFreeFacts(
            features_requested=("headpointer",), camera_ready=False,
            safety_configured=True, safety=_safety(SafetyState.ACTIVE),
        ),
    )
    assert build_panel(inputs).action("pause").enabled


def test_running_without_the_global_stop_is_not_called_active():
    model = build_panel(_inputs(safety=None, safety_cfg=False, headpointer=True, hp=_hp()))
    assert model.banner.state is Overall.UNGATED
    assert "without a global stop" in model.banner.headline
    pause = model.action("pause")
    assert pause.enabled and "Head-Pointer" in pause.help and "does not reach" in pause.help
    assert any("global stop is off" in n for n in model.notes)


def test_a_daemon_that_is_not_running_says_so_and_still_lets_you_change_settings():
    model = build_panel(_inputs(reachable=False, headpointer=True))
    assert model.banner.state is Overall.NOT_RUNNING
    assert "not running" in model.banner.headline
    assert not model.action("pause").enabled
    assert model.action("pause").why_disabled == "YazSes is not running."
    # settings are saved to config and apply at start, so the toggles stay usable
    assert any(f.desired is not None for f in model.features)


def test_switched_on_but_nothing_running_does_not_claim_a_state():
    model = build_panel(
        _inputs(safety=None, safety_cfg=False, headpointer=True,
                hp={"ok": True, "active": False, "reason": WAYLAND})
    )
    assert model.banner.state is Overall.NOT_RUNNING
    assert "none is running" in model.banner.headline and "Wayland" in model.banner.headline
    assert not model.action("pause").enabled


# ------------------------------------------------------------------ honesty of the rows


def test_an_unsupported_pointer_backend_never_reads_as_healthy():
    model = build_panel(
        _inputs(safety=None, safety_cfg=False, headpointer=True,
                hp={"ok": True, "active": False, "reason": WAYLAND})
    )
    rows = {r.label: r for r in model.health}
    for label in ("Head-Pointer", "Pointer output"):
        assert rows[label].status == "unavailable", label
        assert "native Wayland" in rows[label].text  # the platform's own words, verbatim
    assert not any(r.status == "ok" for r in model.health if "ointer" in r.label)


def test_when_the_daemon_cannot_be_asked_the_pointer_is_unknown_not_ok():
    model = build_panel(_inputs(reachable=False, headpointer=True, hp=None))
    rows = {r.label: r for r in model.health}
    assert rows["Pointer output"].status == "unknown"
    assert rows["Head-Pointer"].status == "unknown"


def test_a_running_pointer_names_its_backend_and_its_controls():
    model = build_panel(
        _inputs(safety=_safety(SafetyState.ACTIVE), headpointer=True,
                hp=_hp(calibrated=False, clutched=True, dwell_enabled=True))
    )
    rows = {r.label: r for r in model.health}
    assert rows["Pointer output"].status == "ok" and "x11" in rows["Pointer output"].text
    text = rows["Head-Pointer"].text
    assert "not centred yet" in text and "clutch held" in text and "dwell-click on" in text


def test_a_pointer_fault_is_a_problem_with_a_way_out():
    model = build_panel(
        _inputs(safety=None, safety_cfg=False, headpointer=True,
                hp=_hp(state="faulted", fault="the X server went away"))
    )
    row = next(r for r in model.health if r.label == "Head-Pointer")
    assert row.status == "problem" and "X server" in row.text and "Recover" in row.remedy


@pytest.mark.parametrize(
    ("validity", "status", "mentions"),
    [
        ("valid", "ok", ""),
        ("stale", "attention", "yazses gaze calibrate"),
        ("missing", "attention", "yazses gaze calibrate"),
        ("unverified", "unknown", "yazses gaze calibrate"),
        ("unknown", "unknown", "yazses gaze calibrate"),
    ],
)
def test_gaze_calibration_state_is_visible_and_stale_offers_the_recalibrate_path(
    validity, status, mentions
):
    facts = HandsFreeFacts(
        features_requested=("gaze",), camera_ready=True,
        calibration_validity=validity, calibration_reason="the monitor layout changed",
    )
    model = build_panel(PanelInputs(features=_features(gaze=True), facts=facts))
    row = next(r for r in model.health if r.label == "Gaze calibration")
    assert row.status == status
    assert mentions in row.remedy


@pytest.mark.parametrize(
    ("use_baseline", "baseline", "status"),
    [(False, "", "off"), (True, "stored", "ok"), (True, "missing", "attention"), (True, "", "unknown")],
)
def test_the_face_switch_baseline_is_reported_in_each_of_its_states(use_baseline, baseline, status):
    inputs = replace(
        _inputs(facegesture=True), use_baseline=use_baseline, baseline=baseline
    )
    row = next(r for r in build_panel(inputs).health if r.label == "Face switch baseline")
    assert row.status == status
    if status == "attention":
        assert "yazses facegesture calibrate" in row.remedy


def test_the_camera_row_distinguishes_ready_blocked_and_undetermined():
    def row(ready, reason="r", remedy=""):
        facts = HandsFreeFacts(features_requested=("headpointer",), camera_ready=ready)
        inputs = PanelInputs(
            features=_features(headpointer=True), facts=facts,
            camera_reason=reason, camera_remedy=remedy,
        )
        return next(r for r in build_panel(inputs).health if r.label == "Camera")

    assert row(True).status == "ok"
    blocked = row(False, "no camera device", "plug one in")
    assert blocked.status == "problem" and blocked.remedy == "plug one in"
    assert row(None).status == "unknown"


def test_every_row_carries_a_state_word_so_colour_is_never_the_only_signal():
    states = [
        _inputs(safety=_safety(SafetyState.FAULTED, "x", sources=[_source(faulted=True, reason="b")]),
                headpointer=True, facegesture=True, gaze=True, hp=_hp(fault="b")),
        _inputs(safety=None, safety_cfg=False, headpointer=True,
                hp={"ok": True, "active": False, "reason": WAYLAND}),
        _inputs(reachable=False, headpointer=True, facegesture=True),
    ]
    words = set(STATUS_WORDS.values())
    for inputs in states:
        model = build_panel(inputs)
        for row in _all_rows(model):
            assert row.word in words
        for line in render_text(model):
            if line.startswith("  ["):
                assert line[3:].split("]")[0] in words


# ------------------------------------------------------------------ the actions


def test_no_action_takes_a_pointer_position():
    """ADR-v2-148: each action must be reachable by someone who cannot aim."""
    states = [
        _inputs(safety=_safety(SafetyState.ACTIVE), headpointer=True, hp=_hp()),
        _inputs(safety=_safety(SafetyState.PAUSED), headpointer=True, hp=_hp()),
        _inputs(safety=None, safety_cfg=False, headpointer=True, hp=_hp(dwell_enabled=True)),
    ]
    for inputs in states:
        model = build_panel(inputs)
        for spec in (*model.actions, *model.dwell, model.safety_toggle):
            if spec.ipc is None:
                continue
            for key, value in spec.ipc.params:
                assert key in {"action", "enabled"}, key
                assert isinstance(value, (bool, str)), (spec.id, key, value)
            assert spec.cli.startswith("yazses "), spec.id


def test_recenter_needs_a_running_head_pointer_and_nothing_else():
    on = build_panel(_inputs(safety=_safety(SafetyState.ACTIVE), headpointer=True, hp=_hp()))
    recenter = on.action("recenter")
    assert recenter.enabled
    assert recenter.ipc.method == "headpointer" and dict(recenter.ipc.params) == {"action": "recenter"}
    off = build_panel(_inputs(facegesture=True))
    assert not off.action("recenter").enabled
    assert "not running" in off.action("recenter").why_disabled


def test_dwell_can_be_turned_off_on_its_own_and_the_choice_is_saved_whatever_the_daemon_says():
    model = build_panel(
        _inputs(safety=_safety(SafetyState.ACTIVE), headpointer=True, hp=_hp(dwell_enabled=True))
    )
    off, on = model.dwell
    assert off.id == "dwell_off" and off.enabled and not on.enabled
    assert dict(off.ipc.params) == {"action": "dwell", "enabled": False}
    assert off.config[0].key == "dwell_enabled" and off.config[0].value is False
    assert off.config_always, "the safe direction must stick even if the daemon declines"


def test_dwell_on_is_refused_with_the_reason_the_daemon_gave():
    notice = "dwell-click is held off: it needs the overlay to show its progress"
    model = build_panel(
        _inputs(safety=_safety(SafetyState.ACTIVE), headpointer=True, hp=_hp(notice=notice))
    )
    on = model.action("dwell_on")
    assert not on.enabled and on.why_disabled == notice
    assert not on.config_always


def test_dwell_on_needs_the_head_pointer_switched_on_first():
    model = build_panel(_inputs(facegesture=True))
    assert not model.action("dwell_on").enabled
    assert "Head-Pointer on first" in model.action("dwell_on").why_disabled


def test_the_global_stop_toggle_is_a_config_write_that_says_it_needs_a_restart():
    on = build_panel(_inputs(headpointer=True, safety_cfg=False)).safety_toggle
    assert on.id == "safety_on" and on.needs_restart
    assert (on.config[0].section, on.config[0].key, on.config[0].value) == (
        "handsfree_safety", "enabled", True,
    )
    off = build_panel(_inputs(headpointer=True, safety_cfg=True)).safety_toggle
    assert off.id == "safety_off" and off.config[0].value is False


# ------------------------------------------------------------------ the feature rows


def test_feature_rows_report_dependency_state_truthfully():
    inputs = PanelInputs(features=(
        FeatureFact("headpointer", "Head-Pointer", True, missing_packages=("mediapipe", "opencv-python")),
        FeatureFact("facegesture", "Face switch", False, wired=False),
        FeatureFact("gaze", "Gaze", False, blocked="a strict snap cannot install packages"),
    ))
    rows = {f.slug: f for f in build_panel(inputs).features}
    assert rows["headpointer"].status == "attention"
    assert "mediapipe" in rows["headpointer"].text and "Apply" in rows["headpointer"].text
    assert rows["facegesture"].status == "unavailable" and rows["facegesture"].desired is None
    assert rows["gaze"].status == "unavailable" and "strict snap" in rows["gaze"].text
    assert rows["gaze"].desired is None


def test_a_staged_change_is_visible_before_it_is_applied():
    inputs = PanelInputs(features=(
        FeatureFact("headpointer", "Head-Pointer", False, staged=True, experimental=True),
    ))
    row = build_panel(inputs).features[0]
    assert "staged" in row.text and "ON" in row.text and row.desired is True
    assert row.experimental


# ------------------------------------------------------------------ switch mapping


def test_the_mapping_shows_every_gesture_and_marks_actions_that_do_nothing():
    inputs = replace(
        _inputs(facegesture=True, safety_cfg=False),
        switches=({"gesture": "smile", "intent": "pause_pointer"},),
    )
    mapping = build_panel(inputs).mapping
    assert [r.gesture for r in mapping.rows] == list(GESTURES)
    jaw = next(r for r in mapping.rows if r.gesture == "jaw_open")
    assert jaw.action == "hold_to_talk" and jaw.note == ""
    smile = next(r for r in mapping.rows if r.gesture == "smile")
    assert smile.action == "pause_pointer" and "does nothing" in smile.note.lower()
    brow = next(r for r in mapping.rows if r.gesture == "brow_raise")
    assert brow.action_label == "Not mapped"


def test_choices_mark_unwired_actions_with_the_reason():
    off = build_panel(_inputs(facegesture=True, safety_cfg=False)).mapping.choices
    choices = {k: (ok, why) for k, _label, ok, why in off}
    assert choices["hold_to_talk"] == (True, "") and choices["none"] == (True, "")
    # select / confirm / cancel are wired (facegesture/actions.py): they are offered, and
    # when they cannot act they say why in `yazses facegesture status`, not by being hidden.
    for action in ("select", "confirm", "cancel"):
        assert choices[action] == (True, "")
    assert choices["pause_pointer"][0] is False and "global stop" in choices["pause_pointer"][1]
    on = build_panel(_inputs(facegesture=True, safety_cfg=True)).mapping.choices
    assert {k: ok for k, _l, ok, _w in on}["pause_pointer"] is True


def test_invalid_mappings_are_rejected_with_a_reason_and_never_coerced():
    inputs = _inputs(facegesture=True, safety_cfg=False)
    for gesture, action, fragment in [
        ("wink", "hold_to_talk", "not a gesture"),
        ("smile", "launch_missiles", "not an action"),
        ("smile", "pause_pointer", "global stop"),
    ]:
        plan = plan_mapping(inputs, gesture, action)
        assert not plan.ok and fragment in plan.reason and plan.action is None


def test_a_valid_mapping_becomes_a_table_the_daemon_will_read_back_identically():
    inputs = _inputs(facegesture=True, safety_cfg=True)
    plan = plan_mapping(inputs, "smile", "pause_pointer")
    assert plan.ok and plan.action.needs_restart
    (write,) = plan.action.config
    assert write.name == "facegesture.switches"
    assert write.entries == ((("gesture", "smile"), ("intent", "pause_pointer")),)


@pytest.mark.parametrize("mode", ["full_text", "command"])
@pytest.mark.parametrize("primary", list(GESTURES))
def test_every_mapping_round_trips_through_the_daemons_own_parser(mode, primary):
    """Exhaustive over gesture x action from several starting tables: what the panel writes is
    exactly what ``parse_bindings`` reads back, so the panel cannot save a table the daemon
    would half-ignore."""
    starts = [
        (),
        ({"gesture": "smile", "intent": "hold_to_command"},),
        ({"gesture": primary, "intent": "none"}, {"gesture": "brow_raise", "intent": "hold_to_talk"}),
    ]
    for start in starts:
        inputs = replace(
            _inputs(facegesture=True, safety_cfg=True),
            switches=start, primary_gesture=primary, mode=mode,
        )
        current, _ = parse_bindings(list(start), primary, mode)
        for gesture, action in itertools.product(GESTURES, (*ACTIONS, "none")):
            plan = plan_mapping(inputs, gesture, action)
            assert plan.ok, (gesture, action, plan.reason)
            # An eyes-closed binding may also raise the hold (test_handsfree_panel_eyes_closed_hold).
            (write,) = [c for c in plan.action.config if isinstance(c, ConfigTableArray)]
            entries = [dict(e) for e in write.entries]
            got, problems = parse_bindings(entries, primary, mode)
            expected = dict(current)
            if action == "none":
                expected.pop(gesture, None)
            else:
                expected[gesture] = action
            assert problems == [] and got == expected, (start, gesture, action)


def test_saved_problems_in_the_switch_table_are_surfaced_not_hidden():
    inputs = replace(
        _inputs(facegesture=True),
        switches=({"gesture": "wink", "intent": "hold_to_talk"},),
    )
    problems = build_panel(inputs).mapping.problems
    assert problems and "wink" in problems[0]


def test_the_panel_offers_exactly_the_switch_actions_the_daemon_wires():
    """Drift guard against the real daemon: an action the panel offers must do something."""
    from yazses.config import Config, FacegestureConfig
    from yazses.core.daemon import Daemon
    from yazses.handsfree.safety import HandsFreeSafety
    from yazses.platform import get_platform

    for safety_on in (False, True):
        for action in ACTIONS:
            cfg = replace(
                Config(),
                facegesture=replace(
                    FacegestureConfig(), enabled=True,
                    switches=[{"gesture": "smile", "intent": action}],
                ),
            )
            daemon = Daemon(config=cfg, platform=get_platform())
            if safety_on:
                daemon._handsfree_safety = HandsFreeSafety(("facegesture",))
            source = daemon._build_face_gesture_source(cfg)[0]
            does_something = action not in source._mapper.unwired()
            assert does_something == (action in wired_switch_actions(safety_on)), (action, safety_on)


# ------------------------------------------------------------------ merging facts


def test_merge_keeps_what_only_the_os_knows_and_takes_what_only_the_daemon_knows():
    static = HandsFreeFacts(
        features_requested=("gaze",), camera_ready=True,
        calibration_validity="stale", calibration_reason="monitor changed",
    )
    live = HandsFreeFacts(
        features_requested=("gaze",), perception_state="running", perception_consumers=1,
        safety=_safety(SafetyState.PAUSED, "paused"), safety_configured=True,
    )
    merged = merge_facts(static, live)
    assert merged.camera_ready is True and merged.calibration_validity == "stale"
    assert merged.perception_state == "running" and merged.perception_consumers == 1
    assert merged.safety is not None and merged.safety.state is SafetyState.PAUSED
    assert merge_facts(static, None) is static


def test_merge_never_turns_an_undetermined_live_field_into_a_yes():
    static = HandsFreeFacts(features_requested=("headpointer",), camera_ready=None)
    live = HandsFreeFacts(features_requested=("headpointer",))
    assert merge_facts(static, live).camera_ready is None


def test_the_plain_text_rendering_carries_the_same_words_as_the_model():
    model = build_panel(
        _inputs(safety=_safety(SafetyState.PAUSED, "paused by the user"), headpointer=True, hp=_hp())
    )
    text = "\n".join(render_text(model))
    assert model.banner.headline in text
    assert "yazses handsfree resume" in text and "yazses headpointer recenter" in text
    assert "[OK] Pointer output" in text
