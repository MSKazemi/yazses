"""Gesture Chords against the orderings, timings and states a fake hides (#408).

``test_gesture_engine.py`` / ``test_gesture_sensors.py`` / ``test_gesture_runtime.py`` pin each
rule with the tokens arriving in one call. A real chord is not one call: the camera delivers a
frame, ``frame()`` runs, a face token is debounced for three frames, a head gesture is recognised
only when it *finishes*, and the global gate can close in the middle. These tests model that
shape. What they found, each fixed in the same change:

* **The stop path was outside the gate only for a one-token chord.** ``frame()`` discarded the
  engagement in flight whenever the gate (or the local ``yazses gesture pause``) was closed, so a
  chord that takes more than one tick -- the hands-free preset's own stop chord
  ``brow_raise+shake``, ``jaw_open+hold`` -- could never complete exactly when the pointer was
  running and the gesture source was un-armed. The engine now *taints* the engagement instead:
  it may still finish a stop chord, and nothing else it gathers can run, even if the gate
  reopens first (so nothing is replayed on resume).
* **A longer chord can be shadowed by a shorter one** -- ``jaw_open`` and ``jaw_open+nod`` bound
  together: the short one fires when ``chord_window_ms`` closes, a double nod finishes later, so
  the long (perhaps stop) chord never runs. Reported at load, and in ``gesture status``.
* **A chord and a face switch on one expression** both fire. Reported the same way.
* **``[gesture] freshness_ms`` had the unbounded shape ``stale_after_ms`` and
  ``[headpointer] freshness_ms`` had**: 0 accepted and applied literally (every sample stale, the
  chords silently dead, ``Config`` reporting a valid 0), a huge value meaning "never stale". And
  ``tilt_deg = 0`` made a perfectly level head a held ``tilt`` for ever. Bounded, repaired and
  reported by the loader, and applied by the same rule where used.

No number here is a recommendation: the timings are the config's defaults (provisional) and
synthetic traces.
"""
from __future__ import annotations

import ast
import dataclasses
import logging
import math
from pathlib import Path

import pytest

import yazses.gesture as gesture_pkg
from tests.test_gesture_engine import Calls, make
from tests.test_gesture_runtime import Rig
from yazses.config import Config, FacegestureConfig, GestureConfig, load_config_checked
from yazses.gesture.engine import (
    ChordEngine,
    parse_chords,
    shadowed_chords,
    switch_collisions,
)
from yazses.gesture.headmotion import HeadGestureDetector
from yazses.gesture.runtime import (
    MAX_FRESHNESS_S,
    build_gesture,
    effective_freshness_s,
    sensor_settings,
)
from yazses.handsfree.safety import HandsFreeSafety
from yazses.perception.signals import HeadPoseSignal

PACKAGE = Path(gesture_pkg.__file__).resolve().parent
WINDOW = 0.4


# --------------------------------------------------------------------------- #
# A stop chord that takes more than one tick, with the gate closed
# --------------------------------------------------------------------------- #


class Clock:
    def __init__(self) -> None:
        self.ms = 0.0

    def __call__(self) -> float:
        return self.ms


def _closed_gate(cause: str):
    """A gate that is closed to the ``gesture`` source for ``cause``; returns (gate, engine kwargs).

    "Stale" is not a cause here on purpose: an engine that is ticking with a signal samples the
    gate itself every tick, so a source cannot stay stale while chords are being made.
    """
    clock = Clock()
    gate = HandsFreeSafety(["gesture"], clock=clock)
    gate.sample("gesture")
    if cause == "never_armed":
        return gate, {}
    assert gate.resume(["gesture"]).ok
    if cause == "global_pause":
        gate.pause("test")
    else:  # pragma: no cover - a typo in this file
        raise AssertionError(cause)
    return gate, {}


CAUSES = [
    pytest.param("never_armed", id="never-armed"),
    pytest.param("global_pause", id="global-pause"),
]


def _realistic_stop(engine: ChordEngine, *, start: float = 1.0) -> float:
    """Raise the brows, hold them, and shake: the shake finishes ~0.7 s in, after the window.

    ``frame()`` runs every tick, as the sensors do. Returns the time the shake was recognised.
    """
    t = start
    engine.frame(True, t)
    engine.press("brow_raise", t)
    while t < start + 0.7:
        t += 1 / 15
        engine.frame(True, t)
        engine.tick(t)
    engine.pulse("shake", t)
    for _ in range(3):
        t += 1 / 15
        engine.frame(True, t)
        engine.tick(t)
    return t


@pytest.mark.parametrize("cause", CAUSES)
def test_a_multi_tick_stop_chord_completes_while_the_gate_is_closed(cause):
    gate, _ = _closed_gate(cause)
    calls = Calls()
    engine = ChordEngine(
        {"brow_raise+shake": "pause_pointer", "brow_raise+nod": "recenter"},
        {a: calls.handler(a) for a in ("pause_pointer", "recenter")},
        window_s=WINDOW, refractory_s=1.0, gate=gate,
    )
    _realistic_stop(engine)
    assert calls.log == ["pause_pointer"]


@pytest.mark.parametrize("cause", CAUSES)
def test_and_the_same_chord_bound_to_anything_else_reaches_nothing(cause):
    gate, _ = _closed_gate(cause)
    calls = Calls()
    engine = ChordEngine(
        {"brow_raise+shake": "recenter"}, {"recenter": calls.handler("recenter")},
        window_s=WINDOW, refractory_s=1.0, gate=gate,
    )
    _realistic_stop(engine)
    assert calls.log == []


def test_a_multi_tick_stop_chord_works_under_the_local_gesture_pause():
    """``yazses gesture pause`` says "the pause chord itself still works"."""
    engine, calls = make({"brow_raise+shake": "pause_pointer", "brow_raise+nod": "recenter"})
    engine.set_paused(True)
    _realistic_stop(engine)
    assert calls.log == ["pause_pointer"]


def test_the_local_pause_also_holds_back_a_multi_tick_recenter():
    engine, calls = make({"brow_raise+nod": "recenter"})
    engine.set_paused(True)
    engine.frame(True, 10.0)
    engine.press("brow_raise", 10.0)
    for i in range(1, 12):
        engine.frame(True, 10.0 + i / 15)
        engine.tick(10.0 + i / 15)
    engine.pulse("nod", 10.8)
    engine.tick(11.5)
    assert calls.log == []


def test_an_engagement_that_began_under_a_closed_gate_runs_nothing_after_it_reopens():
    """Taint, not forgetting: reopening the gate mid-chord must not replay what was gathered."""
    clock = Clock()
    gate = HandsFreeSafety(["gesture"], clock=clock)
    gate.sample("gesture")
    assert gate.resume(["gesture"]).ok
    engine, calls = make({"jaw_open+nod": "recenter", "jaw_open+shake": "pause_pointer"}, gate=gate)
    engine.frame(True, 1.0)
    engine.press("jaw_open", 1.0)
    gate.pause("test")
    engine.frame(True, 1.1)           # the engine sees the gate closed with a chord half made
    gate.sample("gesture")
    assert gate.resume(["gesture"]).ok  # reopened before the head gesture lands
    engine.frame(True, 1.2)
    engine.pulse("nod", 1.3)
    engine.tick(2.0)
    assert calls.log == []            # recenter is not replayed ...
    engine.release("jaw_open", 2.1)
    engine.tick(4.0)                  # ... a fresh engagement after the release works again
    engine.frame(True, 4.0)
    engine.press("jaw_open", 4.0)
    engine.pulse("nod", 4.1)
    engine.tick(5.0)
    assert calls.log == ["recenter"]


def test_a_stop_chord_through_the_real_source_pauses_the_pointer_while_only_the_pointer_is_armed():
    """End to end, the shape the preset hits: ``handsfree`` arms the pointer, the gesture waits.

    A real shared source, the real Head-Pointer controller, a real gate. The gesture source is
    left un-armed; the pointer is armed and moving. The multi-tick chord must still stop it.
    """
    holder: dict[str, Rig] = {}
    gate = HandsFreeSafety(
        ["headpointer", "gesture"], clock=lambda: holder["rig"].clock.now * 1000.0
    )
    rig = Rig({"jaw_open+hold": "pause_pointer"}, pointer=True, safety=gate)
    holder["rig"] = rig
    rig.start()
    for _ in range(3):
        rig.frame()
    assert gate.resume(["headpointer"]).ok
    assert gate.gate("gesture").allowed is False       # the gesture source was never armed
    rig.frame(yaw=0.3)
    rig.frame(yaw=0.3)
    assert gate.gate("headpointer").allowed is True     # and the pointer is live
    for _ in range(40):                                  # ~2.7 s of an open jaw: hold_ms is 800
        rig.frame(jaw=0.9, yaw=0.3)
    assert gate.gate("headpointer").allowed is False


# --------------------------------------------------------------------------- #
# Two chords sharing a prefix
# --------------------------------------------------------------------------- #


def test_the_shorter_chord_fires_when_the_window_closes_and_the_longer_is_then_unreachable():
    """What a double nod (~1 s) does to ``jaw_open`` + ``jaw_open+nod``: the short one wins."""
    engine, calls = make({"jaw_open": "recenter", "jaw_open+nod": "pause_pointer"})
    engine.press("jaw_open", 1.0)
    engine.tick(1.2)
    assert calls.log == []                    # the window is still open: nothing yet
    engine.tick(1.0 + WINDOW + 0.05)
    assert calls.log == ["recenter"]
    engine.pulse("nod", 2.0)                  # the nod lands a second in: too late
    engine.tick(3.0)
    assert calls.log == ["recenter"]


def test_the_longer_chord_wins_when_its_extra_token_arrives_inside_the_window():
    engine, calls = make({"jaw_open": "recenter", "jaw_open+nod": "pause_pointer"})
    engine.press("jaw_open", 1.0)
    engine.pulse("nod", 1.3)
    assert calls.log == ["pause_pointer"]


def test_with_only_the_longer_chord_bound_a_slow_head_gesture_still_completes():
    engine, calls = make({"jaw_open+nod": "pause_pointer"})
    engine.press("jaw_open", 1.0)
    engine.tick(1.6)
    engine.pulse("nod", 2.0)
    assert calls.log == ["pause_pointer"]


def test_shadowing_is_reported_with_both_chords_and_the_slow_token():
    notes = shadowed_chords({"jaw_open": "recenter", "jaw_open+nod": "pause_pointer"})
    assert len(notes) == 1
    note = notes[0]
    assert "'jaw_open+nod'" in note and "'jaw_open'" in note and "nod" in note
    assert "pause_pointer" in note and "recenter" in note and "chord_window_ms" in note


@pytest.mark.parametrize(
    "bound",
    [
        pytest.param({"jaw_open": "recenter", "jaw_open+smile": "pause_pointer"}, id="fast-face-extra"),
        pytest.param({"brow_raise+nod": "recenter", "brow_raise+shake": "pause_pointer"}, id="siblings"),
        pytest.param({"jaw_open+nod": "recenter", "smile+nod": "pause_pointer"}, id="disjoint"),
        pytest.param({"nod": "recenter"}, id="single"),
        pytest.param({}, id="empty"),
    ],
)
def test_chords_that_do_not_shadow_each_other_are_not_reported(bound):
    assert shadowed_chords(bound) == []


@pytest.mark.parametrize(
    ("short", "long", "slow"),
    [
        pytest.param("jaw_open", "jaw_open+shake", "shake", id="shake"),
        pytest.param("smile", "smile+tilt", "tilt", id="tilt"),
        pytest.param("jaw_open", "jaw_open+smile+hold", "hold", id="hold-non-exact"),
        pytest.param("nod", "jaw_open+nod", "", id="face-extra-is-fast"),
    ],
)
def test_the_slow_token_kinds_are_the_head_gestures_and_hold(short, long, slow):
    bound, _ = parse_chords({short: "recenter", long: "pause_pointer"})
    notes = shadowed_chords(bound)
    assert bool(notes) == bool(slow)
    if slow:
        assert slow in notes[0]


def test_the_plain_chord_and_its_hold_variant_are_still_refused_not_merely_reported():
    bound, problems = parse_chords({"smile": "recenter", "smile+hold": "pause_pointer"})
    assert bound == {} and len(problems) == 1
    assert shadowed_chords(bound) == []


def test_a_shadowed_chord_is_named_at_load_and_stays_bound(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[gesture]\nenabled = true\n[gesture.chords]\n"jaw_open" = "recenter"\n'
        '"jaw_open+nod" = "pause_pointer"\n',
        encoding="utf-8",
    )
    loaded = load_config_checked(path)
    messages = [str(p) for p in loaded.problems]
    assert len(messages) == 1 and "shadowed" in messages[0] and "[gesture.chords]" in messages[0]
    assert all(p.repaired for p in loaded.problems)       # kept: doctor shows a WARN, not a FAIL
    assert loaded.config.gesture.chords == {"jaw_open": "recenter", "jaw_open+nod": "pause_pointer"}


# --------------------------------------------------------------------------- #
# A chord and a face switch on the same expression
# --------------------------------------------------------------------------- #


def test_a_chord_token_that_is_the_switchs_gesture_is_reported():
    notes = switch_collisions({"jaw_open+nod": "recenter"}, {"jaw_open": "hold_to_talk"})
    assert len(notes) == 1
    assert "jaw_open" in notes[0] and "hold_to_talk" in notes[0] and "jaw_open+nod" in notes[0]


def test_head_tokens_cannot_collide_with_a_face_switch_and_unrelated_faces_do_not():
    assert switch_collisions({"brow_raise+nod": "recenter"}, {"jaw_open": "hold_to_talk"}) == []
    assert switch_collisions({}, {"jaw_open": "hold_to_talk"}) == []
    assert switch_collisions({"nod": "recenter"}, {}) == []


def _load(tmp_path, body: str):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return load_config_checked(path)


def test_the_default_switch_gesture_collides_with_a_jaw_chord_only_when_both_features_are_on(tmp_path):
    chords = '[gesture.chords]\n"jaw_open+hold" = "recenter"\n'
    both = _load(tmp_path, f"[gesture]\nenabled = true\n[facegesture]\nenabled = true\n{chords}")
    assert any("[facegesture]" in str(p) and "hold_to_talk" in str(p) for p in both.problems)
    only_chords = _load(tmp_path, f"[gesture]\nenabled = true\n{chords}")
    assert only_chords.problems == []
    only_switch = _load(tmp_path, f"[facegesture]\nenabled = true\n{chords}")
    assert only_switch.problems == []


def test_a_switch_table_that_moves_the_binding_changes_what_collides(tmp_path):
    chords = '[gesture.chords]\n"brow_raise+shake" = "pause_pointer"\n'
    base = "[gesture]\nenabled = true\n[facegesture]\nenabled = true\n"
    assert _load(tmp_path, base + chords).problems == []   # the default switch is the jaw
    moved = _load(
        tmp_path,
        base + '[[facegesture.switches]]\ngesture = "brow_raise"\nintent = "select"\n' + chords,
    )
    assert any("brow_raise" in str(p) and "select" in str(p) for p in moved.problems)
    removed = _load(
        tmp_path,
        base + '[[facegesture.switches]]\ngesture = "brow_raise"\nintent = "none"\n' + chords,
    )
    assert removed.problems == []                            # "none" unbinds it


def test_the_hands_free_preset_does_not_collide_with_itself(tmp_path):
    from yazses.handsfree.preset import CHORDS_RECENTER, CHORDS_STOP

    body = (
        "[gesture]\nenabled = true\n[facegesture]\nenabled = true\n[gesture.chords]\n"
        f'"{CHORDS_STOP}" = "pause_pointer"\n"{CHORDS_RECENTER}" = "recenter"\n'
    )
    assert _load(tmp_path, body).problems == []


def test_the_runtime_status_carries_the_notes_but_a_plain_install_does_not(caplog):
    cfg = Config()
    cfg.gesture.enabled = True
    cfg.gesture.chords = {"jaw_open": "recenter", "jaw_open+nod": "pause_pointer"}
    rig = Rig(cfg.gesture.chords)
    with caplog.at_level(logging.WARNING, logger="yazses.gesture.runtime"):
        runtime = build_gesture(
            cfg.gesture, facegesture=cfg.facegesture, perception=rig.source, thread=False,
        )
    status = runtime.command("status")
    assert len(status["notes"]) == 1 and "shadowed" in status["notes"][0]
    assert status["problems"] == []
    assert any("shadowed" in r.message for r in caplog.records)

    plain = Rig({"nod": "recenter"}).runtime.command("status")
    assert "notes" not in plain                              # the reply shape is unchanged


# --------------------------------------------------------------------------- #
# Token flicker through the real sensors
# --------------------------------------------------------------------------- #


def test_a_jaw_that_flickers_before_it_settles_fires_the_chord_exactly_once():
    called: list[str] = []
    rig = Rig({"jaw_open": "command:undo"}, run_command=called.append)
    rig.start()
    for jaw in (0.9, 0.9, 0.1, 0.9, 0.9, 0.1, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9):
        rig.frame(jaw=jaw)
    assert called == ["undo"]


def test_a_flicker_that_never_reaches_the_debounce_fires_nothing():
    called: list[str] = []
    rig = Rig({"jaw_open": "command:undo"}, run_command=called.append)
    rig.start()
    for _ in range(10):
        rig.frame(jaw=0.9)
        rig.frame(jaw=0.0)
    assert called == []


def test_a_held_jaw_with_a_flicker_inside_it_is_still_one_engagement():
    called: list[str] = []
    rig = Rig({"jaw_open": "command:undo"}, run_command=called.append)
    rig.start()
    for jaw in [0.9] * 6 + [0.2, 0.9] + [0.9] * 20:
        rig.frame(jaw=jaw)
    assert called == ["undo"]


# --------------------------------------------------------------------------- #
# [gesture] freshness_ms and the other settings that were applied literally
# --------------------------------------------------------------------------- #


def _gesture_load(tmp_path, key: str, literal: str):
    path = tmp_path / "config.toml"
    path.write_text(f"[gesture]\n{key} = {literal}\n", encoding="utf-8")
    return load_config_checked(path)


HOSTILE_FRESHNESS = [
    pytest.param(literal, id=ident)
    for literal, ident in (
        ("0", "zero"), ("0.0", "zero-float"), ("-1", "negative"), ("nan", "nan"), ("inf", "inf"),
        ("60001", "just-over"), ("99999999999999999999", "big-int"), (str(10**400), "overflow"),
        ('"abc"', "string"), ("true", "bool"),
    )
]


@pytest.mark.parametrize("literal", HOSTILE_FRESHNESS)
def test_a_hostile_freshness_is_repaired_to_the_default_and_reported(tmp_path, literal):
    loaded = _gesture_load(tmp_path, "freshness_ms", literal)
    assert loaded.config.gesture.freshness_ms == GestureConfig().freshness_ms == 500, literal
    assert any(p.key == "freshness_ms" for p in loaded.problems), "a repair must be reported"
    assert sensor_settings(loaded.config.gesture, FacegestureConfig()).freshness_s == 0.5


def test_zero_is_named_as_zero_not_as_a_type_error(tmp_path):
    message = " ".join(str(p) for p in _gesture_load(tmp_path, "freshness_ms", "0").problems)
    assert "freshness_ms" in message and "greater than 0" in message, message


@pytest.mark.parametrize("literal", ["1", "250", "500", "2000", "60000"])
def test_a_sensible_freshness_passes_through_unchanged_and_unreported(tmp_path, literal):
    loaded = _gesture_load(tmp_path, "freshness_ms", literal)
    assert loaded.config.gesture.freshness_ms == int(literal)
    assert sensor_settings(loaded.config.gesture, FacegestureConfig()).freshness_s == int(literal) / 1000.0
    assert not [p for p in loaded.problems if p.key == "freshness_ms"]


def test_the_shipped_values_are_inside_their_own_bounds():
    meta = {f.name: f.metadata for f in dataclasses.fields(GestureConfig)}
    shipped = GestureConfig()
    assert meta["freshness_ms"]["min_exclusive"] < shipped.freshness_ms <= meta["freshness_ms"]["max"]
    assert meta["freshness_ms"]["max"] / 1000.0 == MAX_FRESHNESS_S
    for key in ("tilt_deg", "head_amplitude_deg"):
        assert meta[key]["min_exclusive"] < getattr(shipped, key) <= meta[key]["max"], key


def test_the_loader_and_the_runtime_agree_on_what_nonsense_is():
    for bad in (0, 0.0, -1, math.nan, math.inf, MAX_FRESHNESS_S * 1000.0 + 1, 10**400, "x", None, True):
        assert effective_freshness_s(bad) == 0.5, bad
    assert effective_freshness_s(250) == 0.25
    assert effective_freshness_s(MAX_FRESHNESS_S * 1000.0) == MAX_FRESHNESS_S


def test_a_hand_built_zero_freshness_does_not_leave_the_chords_dead():
    """The behaviour the bug produced: with 0 applied literally every sample was stale."""
    called: list[str] = []
    rig = Rig({"jaw_open": "command:undo"}, run_command=called.append, freshness_ms=0)
    rig.start()
    for _ in range(5):
        rig.frame(jaw=0.9)
    assert called == ["undo"]


def test_a_hand_built_huge_freshness_does_not_mean_never_stale():
    cfg = Config().gesture
    cfg.freshness_ms = 10**9
    assert sensor_settings(cfg, FacegestureConfig()).head.freshness_s == 0.5


@pytest.mark.parametrize("literal", ["0", "-5", "90.5", "500", "nan"])
def test_a_tilt_that_no_head_could_make_or_that_every_head_makes_is_repaired(tmp_path, literal):
    loaded = _gesture_load(tmp_path, "tilt_deg", literal)
    assert loaded.config.gesture.tilt_deg == 20.0
    assert any(p.key == "tilt_deg" for p in loaded.problems)


@pytest.mark.parametrize("literal", ["0", "-5", "91", "nan"])
def test_a_nod_amplitude_of_nothing_or_of_more_than_a_head_can_do_is_repaired(tmp_path, literal):
    loaded = _gesture_load(tmp_path, "head_amplitude_deg", literal)
    assert loaded.config.gesture.head_amplitude_deg == 10.0
    assert any(p.key == "head_amplitude_deg" for p in loaded.problems)


def test_a_level_head_is_not_a_tilt_even_for_a_hand_built_zero_tilt_angle():
    """The behaviour the bug produced: ``tilt_deg = 0`` pressed ``tilt`` on a level head."""
    cfg = Config().gesture
    cfg.tilt_deg = 0.0
    detector = HeadGestureDetector(sensor_settings(cfg, FacegestureConfig()).head)
    events: list[tuple[str, str]] = []
    t = 100.0
    for _ in range(60):
        t += 1 / 30
        events += detector.update(HeadPoseSignal(t, 0.0, 0.0, 0.0, 1.0), t)
    assert events == []


def test_sensible_tilt_and_amplitude_still_reach_the_detector_in_radians():
    cfg = Config().gesture
    cfg.tilt_deg, cfg.head_amplitude_deg = 30.0, 15.0
    head = sensor_settings(cfg, FacegestureConfig()).head
    assert math.isclose(head.tilt_rad, math.radians(30.0))
    assert math.isclose(head.amplitude_rad, math.radians(15.0))


# --------------------------------------------------------------------------- #
# No second resolver
# --------------------------------------------------------------------------- #


def test_the_sensor_side_never_normalises_or_resolves_a_chord_itself():
    """``chords.py`` is the one resolver: nothing else joins tokens with ``+`` or looks a chord up."""
    modules = sorted(p for p in PACKAGE.glob("*.py") if p.name != "chords.py")
    assert len(modules) >= 5
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "join" and isinstance(node.func.value, ast.Constant):
                    assert node.func.value.value != "+", f"{path.name}:{node.lineno} joins chord tokens"
                owner = node.func.value
                if (
                    node.func.attr in {"get", "pop", "setdefault"}
                    and isinstance(owner, ast.Attribute)
                    and owner.attr == "_bindings"
                ):
                    raise AssertionError(f"{path.name}:{node.lineno} looks a chord up itself")
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
                assert node.value.attr != "_bindings", f"{path.name}:{node.lineno} indexes bindings"
    engine_text = (PACKAGE / "engine.py").read_text(encoding="utf-8")
    assert "normalize_chord" in engine_text and "resolve_chord" in engine_text


def test_an_empty_mapping_watches_nothing_and_does_nothing_through_the_real_source():
    cfg = Config()
    cfg.gesture.enabled = True
    rig = Rig({"nod": "recenter"})
    runtime = build_gesture(cfg.gesture, facegesture=cfg.facegesture, perception=rig.source, thread=False)
    assert runtime.runner is None and "no chords" in runtime.reason
    assert runtime.command("pause") == {"ok": False, "reason": runtime.reason}
