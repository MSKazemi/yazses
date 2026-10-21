"""The hands-free panel lists the ways to stop that exist, and the dependency state that is true (#420).

Two gaps in EYE-SETTINGS-001 held here, both of the same shape -- the panel said something
that was true on some machines and false on others:

* The ACTIVE banner promised "the keyboard shortcut, `yazses handsfree pause`, or a face-switch
  mapped to pause" everywhere, including where no face switch was mapped to pause. The panel
  now lists the routes the saved config sets up (:func:`stop_routes`) and the banner points at
  that list instead of making a promise of its own.
* A switched-on camera feature with missing packages said "Press Apply to install them" in an
  environment that can never install them, and a switched-off one did not say that turning it
  on means an install.

Pure: no Qt, no camera, no daemon, no socket (the gatherer tests use a fake platform).
"""
from __future__ import annotations

import types

from yazses.cameraperm import CameraBlocker, CameraGate
from yazses.config import Config
from yazses.handsfree.observability import HandsFreeFacts
from yazses.handsfree.panel import (
    FeatureFact,
    PanelInputs,
    build_panel,
    render_text,
    stop_routes,
    wired_switch_actions,
)
from yazses.handsfree.panel_io import gather_panel_inputs
from yazses.handsfree.safety import SafetyState, SafetyStatus


def _inputs(*, safety_cfg=True, hp=True, face=False, switches=(), phrase="", chords=(),
            features=None, state=SafetyState.ACTIVE) -> PanelInputs:
    feats = features if features is not None else (
        FeatureFact("headpointer", "Head-Pointer", hp),
        FeatureFact("facegesture", "Face switch", face),
        FeatureFact("gaze", "Gaze", False),
    )
    status = SafetyStatus(state, "", False, state is SafetyState.PAUSED, 1, ()) if safety_cfg else None
    return PanelInputs(
        daemon_reachable=True,
        features=feats,
        safety_configured=safety_cfg,
        facts=HandsFreeFacts(
            features_requested=tuple(f.slug for f in feats if f.enabled),
            camera_ready=True, safety_configured=safety_cfg, safety=status,
            head_wired=True, face_wired=True,
        ),
        headpointer={"ok": True, "active": True, "state": "tracking", "backend": "x11"}
        if hp else None,
        switches=tuple(switches),
        stop_phrase=phrase,
        stop_chords=tuple(chords),
    )


def _joined(inputs: PanelInputs) -> str:
    return "\n".join(stop_routes(inputs))


# ------------------------------------------------------------------ which routes are listed


def test_nothing_switched_on_lists_no_routes():
    inputs = _inputs(hp=False, face=False, safety_cfg=False)
    assert stop_routes(inputs) == ()
    assert build_panel(inputs).stop_routes == ()


def test_the_window_and_the_terminal_are_always_listed_because_they_always_work():
    routes = stop_routes(_inputs())
    assert any("Alt+P" in r and "Alt+R" in r for r in routes), routes
    assert any("`yazses handsfree pause`" in r for r in routes), routes


def test_no_stop_phrase_is_reported_as_not_set_up_never_as_a_route():
    text = _joined(_inputs(phrase=""))
    assert "Voice: no stop phrase is set up" in text
    assert "dictate exactly" not in text


def test_a_stop_phrase_is_listed_verbatim_with_its_limits():
    text = _joined(_inputs(phrase="  pause   hands free "))
    assert "dictate exactly “pause hands free” on its own" in text
    assert "never typed" in text and "no spoken resume" in text
    assert "no stop phrase" not in text


def test_a_face_switch_mapped_to_pause_is_listed_only_when_it_is_wired():
    smile = ({"gesture": "smile", "intent": "pause_pointer"},)
    on = _inputs(face=True, switches=smile, safety_cfg=True)
    assert "pause_pointer" in wired_switch_actions(True)
    assert "Face switch: Smile pauses (needs the camera)." in stop_routes(on)

    # Gate off: the daemon leaves pause_pointer unwired on this build, so it is not a route --
    # and the panel must not claim "no gesture is mapped" either, because one is.
    off = _inputs(face=True, switches=smile, safety_cfg=False)
    text = _joined(off)
    assert "Smile pauses" not in text
    assert "no gesture is mapped" not in text


def test_a_face_switch_with_no_pause_mapping_says_so_and_where_to_fix_it():
    text = _joined(_inputs(face=True))
    assert "Face switch: no gesture is mapped" in text
    assert "Face switch mapping" in text


def test_a_mapping_saved_for_a_face_switch_that_is_off_is_not_a_route():
    smile = ({"gesture": "smile", "intent": "pause_pointer"},)
    text = _joined(_inputs(face=False, switches=smile))
    assert "Face switch" not in text


def test_each_pause_chord_is_its_own_route():
    routes = stop_routes(_inputs(chords=("jaw_open+shake", "brow_raise+nod")))
    assert "Gesture chord: jaw_open+shake pauses (needs the camera)." in routes
    assert "Gesture chord: brow_raise+nod pauses (needs the camera)." in routes


def test_with_the_global_stop_off_the_scope_is_said_once():
    text = _joined(_inputs(safety_cfg=False))
    assert text.count("pauses the Head-Pointer only") == 1
    assert "Head-Pointer only" not in _joined(_inputs(safety_cfg=True))


# ------------------------------------------------------------------ the banner and the terminal


def test_the_active_banner_no_longer_promises_routes_it_did_not_check():
    banner = build_panel(_inputs()).banner
    assert banner.headline.startswith("Active")
    assert "face-switch mapped" not in banner.detail
    assert "keyboard shortcut" not in banner.detail
    assert "Ways to stop without pointing" in banner.detail


def test_the_terminal_rendering_carries_every_route():
    inputs = _inputs(face=True, phrase="pause hands free", chords=("jaw_open+shake",))
    model = build_panel(inputs)
    lines = render_text(model)
    assert "Ways to stop without pointing:" in lines
    for route in model.stop_routes:
        assert f"  {route}" in lines


# ------------------------------------------------------------------ dependency state, truthfully


def _feature(**kw) -> tuple[FeatureFact, ...]:
    return (
        FeatureFact("headpointer", "Head-Pointer", **kw),
        FeatureFact("facegesture", "Face switch", False),
        FeatureFact("gaze", "Gaze", False),
    )


def test_an_enabled_feature_whose_packages_cannot_be_installed_here_never_offers_apply():
    blocked = "this snap is strictly confined; install the classic build instead."
    inputs = _inputs(features=_feature(enabled=True, missing_packages=("mediapipe",),
                                       blocked=blocked))
    row = next(r for r in build_panel(inputs).features if r.slug == "headpointer")
    assert row.status == "problem"
    assert "Press Apply" not in row.text
    assert "Apply cannot install them here" in row.text and blocked.rstrip(".") in row.text
    assert row.desired is False  # it can still be switched off


def test_an_enabled_feature_whose_packages_can_be_installed_still_offers_apply():
    inputs = _inputs(features=_feature(enabled=True, missing_packages=("mediapipe",)))
    row = next(r for r in build_panel(inputs).features if r.slug == "headpointer")
    assert row.status == "attention" and "Press Apply to install them" in row.text


def test_an_off_feature_says_what_turning_it_on_installs_before_it_is_pressed():
    inputs = _inputs(hp=False, features=_feature(enabled=False,
                                                 missing_packages=("mediapipe", "opencv-python")))
    row = next(r for r in build_panel(inputs).features if r.slug == "headpointer")
    assert row.status == "off" and row.desired is True
    assert "Turning it on needs mediapipe, opencv-python, which Apply installs." in row.text


def test_an_off_feature_with_nothing_missing_mentions_no_install():
    inputs = _inputs(hp=False, features=_feature(enabled=False))
    row = next(r for r in build_panel(inputs).features if r.slug == "headpointer")
    assert "install" not in row.text.lower()


def test_an_off_feature_that_cannot_be_installed_here_stays_not_available():
    inputs = _inputs(hp=False, features=_feature(enabled=False, missing_packages=("mediapipe",),
                                                 blocked="read-only install."))
    row = next(r for r in build_panel(inputs).features if r.slug == "headpointer")
    assert row.status == "unavailable" and row.desired is None


# ------------------------------------------------------------------ the gatherer


class _Platform:
    def __init__(self, tmp_path):
        self.paths = types.SimpleNamespace(data_dir=tmp_path)
        self.permissions = types.SimpleNamespace(
            check_camera=lambda: None, how_to_grant_camera=lambda: ""
        )


def _gather(cfg, tmp_path):
    return gather_panel_inputs(
        cfg, _Platform(tmp_path), None,
        deps_probe=lambda _m: [], blocked_probe=lambda _p: None,
        camera_gate=CameraGate(True, CameraBlocker.NONE, "camera ok"),
        read_context=lambda: None,
    )


def test_the_gatherer_reads_the_saved_stop_phrase_and_the_pause_chords(tmp_path):
    cfg = Config()
    cfg.headpointer.enabled = True
    cfg.handsfree_safety.stop_phrase = "pause hands free"
    cfg.gesture.enabled = True
    cfg.gesture.chords = {
        "shake+jaw_open": "pause_pointer",   # normalised to the daemon's own chord id
        "brow_raise+nod": "recenter",        # not a stop
        "jaw_open+wink": "pause_pointer",    # unknown token: the daemon refuses it, so do we
    }
    inputs = _gather(cfg, tmp_path)
    assert inputs.stop_phrase == "pause hands free"
    assert inputs.stop_chords == ("jaw_open+shake",)


def test_chords_count_only_while_gesture_chords_are_switched_on(tmp_path):
    cfg = Config()
    cfg.gesture.enabled = False
    cfg.gesture.chords = {"jaw_open+shake": "pause_pointer"}
    assert _gather(cfg, tmp_path).stop_chords == ()


def test_the_defaults_have_no_stop_phrase_and_no_chords(tmp_path):
    inputs = _gather(Config(), tmp_path)
    assert inputs.stop_phrase == "" and inputs.stop_chords == ()


# ------------------------------------------------------------------ the window's pure helpers


def test_the_window_lists_one_route_per_line_and_says_when_there_is_nothing_to_stop():
    from yazses.settingsui.handsfree_panel import stop_routes_text

    model = build_panel(_inputs(phrase="pause hands free"))
    lines = stop_routes_text(model).splitlines()
    assert len(lines) == len(model.stop_routes) and all(ln.startswith("• ") for ln in lines)
    nothing = build_panel(_inputs(hp=False, face=False, safety_cfg=False))
    assert stop_routes_text(nothing).startswith("Nothing hands-free is switched on")


def test_apply_follows_the_settings_window_while_it_installs():
    from yazses.settingsui.handsfree_panel import apply_control

    assert apply_control(True, "") == (True, "")
    enabled, why = apply_control(True, "Installing mediapipe (about 40 MB)…")
    assert not enabled
    assert why.startswith("Busy: Installing mediapipe") and "Pause, Resume and Recenter" in why
    assert apply_control(False, "")[0] is False
