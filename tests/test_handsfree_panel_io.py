"""Gathering the hands-free panel's inputs and carrying out its buttons (#420).

The two properties that matter most are negative ones: gathering never opens a camera (the
panel is displayed without anyone having asked for the camera), and no failure — a dead
socket, a refused write, a malformed reply — escapes as an exception into a window the user
may have no other way to operate YazSes from.
"""
from __future__ import annotations

import sys
import types

from yazses.cameraperm import CameraBlocker, CameraGate
from yazses.config import Config
from yazses.handsfree.observability import HandsFreeFacts, as_payload
from yazses.handsfree.panel import (
    ActionSpec,
    ConfigSet,
    ConfigTableArray,
    IpcCall,
    Overall,
    build_panel,
)
from yazses.handsfree.panel_io import gather_panel_inputs, perform_action
from yazses.handsfree.safety import HandsFreeSafety


class _Platform:
    """Enough platform for the gatherer. Asking about the camera is recorded, not answered."""

    def __init__(self, tmp_path):
        self.paths = types.SimpleNamespace(data_dir=tmp_path)
        self.asked: list[str] = []
        outer = self

        class Perms:
            def check_camera(self):
                outer.asked.append("check_camera")
                from yazses.cameraperm import CameraPermission

                return CameraPermission.GRANTED

            def how_to_grant_camera(self):
                return ""

        self.permissions = Perms()


def _cfg(**sections):
    cfg = Config()
    for name, values in sections.items():
        for key, value in values.items():
            setattr(getattr(cfg, name), key, value)
    return cfg


def _no_deps(_modules):
    return []


def _not_blocked(_pkgs):
    return None


def _gather(cfg, tmp_path, ipc, **kw):
    return gather_panel_inputs(
        cfg, _Platform(tmp_path), ipc,
        deps_probe=_no_deps, blocked_probe=_not_blocked,
        camera_gate=kw.pop("camera_gate", CameraGate(True, CameraBlocker.NONE, "camera ok")),
        read_context=kw.pop("read_context", lambda: None),
        **kw,
    )


# ------------------------------------------------------------------ no camera, ever


def test_gathering_never_imports_the_camera_stack(monkeypatch, tmp_path):
    """Mutation check: make cv2/mediapipe unimportable. If gathering reached for either, the
    import would raise inside a path that swallows it and the facts would silently degrade —
    so also assert the facts did NOT degrade."""
    for name in ("cv2", "mediapipe"):
        monkeypatch.setitem(sys.modules, name, None)
    cfg = _cfg(headpointer={"enabled": True}, facegesture={"enabled": True})
    inputs = _gather(cfg, tmp_path, lambda m, p: {"state": "idle"})
    assert inputs.daemon_reachable is True
    assert {f.slug for f in inputs.features if f.enabled} == {"headpointer", "facegesture"}
    assert inputs.facts.camera_ready is True  # the injected gate was consulted, nothing else


def test_a_default_install_asks_the_os_nothing_about_the_camera(tmp_path):
    platform = _Platform(tmp_path)
    calls: list[str] = []

    def ipc(method, params):
        calls.append(method)
        return {"state": "idle", "handsfree": None}

    inputs = gather_panel_inputs(
        Config(), platform, ipc, deps_probe=_no_deps, blocked_probe=_not_blocked
    )
    assert platform.asked == [], "no camera feature is on, so the permission probe must not run"
    assert calls == ["status"], "and the Head-Pointer is not asked about when it is off"
    assert build_panel(inputs).banner.state is Overall.OFF


# ------------------------------------------------------------------ the daemon


def test_an_unreachable_daemon_is_a_fact_not_an_exception(tmp_path):
    def ipc(method, params):
        raise ConnectionRefusedError("no socket")

    inputs = _gather(_cfg(headpointer={"enabled": True}), tmp_path, ipc)
    assert inputs.daemon_reachable is False and inputs.headpointer is None
    assert build_panel(inputs).banner.state is Overall.NOT_RUNNING


def test_no_ipc_at_all_is_the_same_as_unreachable(tmp_path):
    inputs = _gather(_cfg(headpointer={"enabled": True}), tmp_path, None)
    assert inputs.daemon_reachable is False


def test_the_live_gate_state_reaches_the_banner_through_the_real_wire_format(tmp_path):
    """The daemon's payload -> facts_from_payload -> merge -> banner, with no fabricated
    intermediate: this is the path that used to say 'unknown' forever."""
    cfg = _cfg(headpointer={"enabled": True}, handsfree_safety={"enabled": True})
    now = [1000.0]
    gate = HandsFreeSafety(("headpointer",), clock=lambda: now[0])
    gate.sample("headpointer")
    gate.resume()
    live = as_payload(
        HandsFreeFacts(features_requested=("headpointer",), safety_configured=True,
                       safety=gate.status())
    )
    replies = {
        "status": {"state": "idle", "handsfree": live},
        "headpointer": {"ok": True, "active": True, "state": "tracking", "reason": "",
                        "paused": False, "clutched": False, "calibrated": True,
                        "dwell_enabled": False, "fault": "", "backend": "x11"},
    }
    inputs = _gather(cfg, tmp_path, lambda m, p: replies[m])
    assert build_panel(inputs).banner.state is Overall.ACTIVE
    gate.pause("test")
    live = as_payload(
        HandsFreeFacts(features_requested=("headpointer",), safety_configured=True,
                       safety=gate.status())
    )
    replies["status"] = {"state": "idle", "handsfree": live}
    assert build_panel(_gather(cfg, tmp_path, lambda m, p: replies[m])).banner.state is Overall.PAUSED


def test_an_older_daemon_without_the_hands_free_field_does_not_read_as_active(tmp_path):
    cfg = _cfg(headpointer={"enabled": True}, handsfree_safety={"enabled": True})
    replies = {
        "status": {"state": "idle"},  # no "handsfree" key
        "headpointer": {"ok": False, "reason": "unknown method"},
    }
    banner = build_panel(_gather(cfg, tmp_path, lambda m, p: replies[m])).banner
    assert banner.state is not Overall.ACTIVE


def test_the_gate_verdict_is_a_tri_state_like_doctors(tmp_path):
    cfg = _cfg(headpointer={"enabled": True})
    soft = CameraGate(False, CameraBlocker.PERMISSION_UNKNOWN, "not asked yet", "run doctor")
    hard = CameraGate(False, CameraBlocker.NO_DEVICE, "no camera", "plug one in")
    assert _gather(cfg, tmp_path, None, camera_gate=soft).facts.camera_ready is None
    blocked = _gather(cfg, tmp_path, None, camera_gate=hard)
    assert blocked.facts.camera_ready is False and blocked.camera_remedy == "plug one in"


def test_dependency_state_is_read_from_the_same_registry_as_the_settings_window(tmp_path):
    cfg = _cfg(headpointer={"enabled": True})
    inputs = gather_panel_inputs(
        cfg, _Platform(tmp_path), None,
        deps_probe=lambda modules: ["mediapipe"], blocked_probe=_not_blocked,
        camera_gate=CameraGate(True, CameraBlocker.NONE, "ok"),
    )
    hp = next(f for f in inputs.features if f.slug == "headpointer")
    assert hp.enabled and "mediapipe>=0.10.35" in hp.missing_packages


def test_staged_changes_are_carried_through(tmp_path):
    inputs = _gather(Config(), tmp_path, None, staged={"gaze": True})
    gaze = next(f for f in inputs.features if f.slug == "gaze")
    assert gaze.staged is True and gaze.enabled is False


def test_a_stored_face_baseline_is_reported_from_disk_without_a_camera(tmp_path):
    cfg = _cfg(facegesture={"enabled": True, "use_baseline": True})
    inputs = _gather(cfg, tmp_path, None)
    assert inputs.baseline == "missing"


# ------------------------------------------------------------------ doing


def _spec(**kw) -> ActionSpec:
    base = {"id": "x", "label": "X", "kind": "stop", "enabled": True}
    base.update(kw)
    return ActionSpec(**base)


def test_a_stop_goes_to_the_daemon_and_reports_what_it_did():
    sent = []

    def ipc(method, params):
        sent.append((method, params))
        return {"ok": True, "scope": ["all hands-free input"]}

    result = perform_action(
        _spec(ipc=IpcCall("handsfree", (("action", "pause"),))),
        ipc=ipc, write_key=None, write_table=None,
    )
    assert result.ok and sent == [("handsfree", {"action": "pause"})]


def test_a_disabled_action_does_nothing_and_says_why():
    sent = []
    result = perform_action(
        _spec(enabled=False, why_disabled="Already paused.", ipc=IpcCall("handsfree")),
        ipc=lambda m, p: sent.append(m), write_key=None, write_table=None,
    )
    assert not result.ok and result.message == "Already paused." and sent == []


def test_an_unreachable_daemon_fails_with_a_sentence_not_a_traceback():
    def ipc(method, params):
        raise ConnectionRefusedError

    result = perform_action(
        _spec(ipc=IpcCall("handsfree")), ipc=ipc, write_key=None, write_table=None
    )
    assert not result.ok and "running" in result.message


def test_a_refused_resume_carries_the_daemons_reason():
    result = perform_action(
        _spec(ipc=IpcCall("handsfree", (("action", "resume"),))),
        ipc=lambda m, p: {"ok": False, "reason": "not ready to re-arm: headpointer"},
        write_key=None, write_table=None,
    )
    assert not result.ok and "headpointer" in result.message


def test_dwell_off_is_saved_even_when_the_daemon_declines():
    writes = []
    spec = _spec(
        ipc=IpcCall("headpointer", (("action", "dwell"), ("enabled", False))),
        config=(ConfigSet("headpointer", "dwell_enabled", False),),
        config_always=True,
    )
    result = perform_action(
        spec, ipc=lambda m, p: {"ok": False, "reason": "Head-Pointer is not running"},
        write_key=lambda *a: writes.append(a), write_table=None,
    )
    assert writes == [("headpointer", "dwell_enabled", False, None)]
    assert result.ok and result.saved_only


def test_dwell_on_refused_by_the_daemon_is_not_written_behind_its_back():
    writes = []
    spec = _spec(
        ipc=IpcCall("headpointer", (("action", "dwell"), ("enabled", True))),
        config=(ConfigSet("headpointer", "dwell_enabled", True),),
    )
    result = perform_action(
        spec, ipc=lambda m, p: {"ok": False, "reason": "dwell-click is held off"},
        write_key=lambda *a: writes.append(a), write_table=None,
    )
    assert writes == [] and not result.ok and "held off" in result.message


def test_dwell_on_with_no_daemon_is_saved_for_the_next_start():
    writes = []
    spec = _spec(
        ipc=IpcCall("headpointer", (("action", "dwell"), ("enabled", True))),
        config=(ConfigSet("headpointer", "dwell_enabled", True),),
    )

    def ipc(method, params):
        raise ConnectionRefusedError

    result = perform_action(spec, ipc=ipc, write_key=lambda *a: writes.append(a), write_table=None)
    assert writes and result.ok and result.saved_only and "start" in result.message


def test_a_failed_write_is_reported_not_raised():
    def boom(*_a):
        raise OSError("Read-only file system")

    result = perform_action(
        _spec(config=(ConfigSet("handsfree_safety", "enabled", True),), needs_restart=True),
        ipc=None, write_key=boom, write_table=None,
    )
    assert not result.ok and "Read-only" in result.message


def test_a_config_only_action_says_it_needs_a_restart():
    result = perform_action(
        _spec(config=(ConfigSet("handsfree_safety", "enabled", True),), needs_restart=True),
        ipc=None, write_key=lambda *a: None, write_table=None,
    )
    assert result.ok and "restart" in result.message


def test_a_mapping_goes_through_the_table_writer():
    seen = []
    entries = ((("gesture", "smile"), ("intent", "hold_to_talk")),)
    result = perform_action(
        _spec(config=(ConfigTableArray("facegesture.switches", entries),), needs_restart=True),
        ipc=None, write_key=None, write_table=lambda n, e: seen.append((n, e)),
    )
    assert result.ok and seen == [("facegesture.switches", entries)]
