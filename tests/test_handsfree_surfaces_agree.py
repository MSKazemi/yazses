"""`doctor`, `yazses status` and the controls window must say the same thing — EYE-OBS-001 (#416).

Each surface was individually tested, and each passed, while describing one machine three ways.
Measured on the real payload path before this file existed:

* a running Head-Pointer waiting on the desktop's permission dialog read **unknown** on
  `yazses status` (the daemon never put the pointer's state in its reply, so the pointer row was
  "nothing here can name the backend") while `yazses headpointer status` said PENDING;
* a shared camera source that had FAILED (camera taken, model missing) read **running / OK**
  on `status`, because a consumer existing was taken to mean the camera was open;
* a face switch the daemon never built because a dependency was missing read "no runtime path
  in this build ... nothing to fix locally" -- the wrong cause and the wrong advice;
* a *denied* permission was a PROBLEM in the window and a WARN in `doctor`, and a head tracker
  that had not yet seen a face was OK in the window and unknown everywhere else;
* `doctor` printed "unknown" for every state that only the running daemon holds, because it
  never asked, while the window did.

Why the earlier tests could not see it: they fabricate the *facts* (`camera_ready=True`,
`face_wired=True`) and render them, so they prove the renderer and never the gathering -- and
the gathering is where the three surfaces differ. This file runs each surface's **real**
gathering path against one fabricated machine: the real `Daemon._handsfree_payload` for
`status`, the real `gather_panel_inputs` for the window, the real `_handsfree_checks` for
`doctor`. Only the hardware is fake (a head-pointer runtime built from the real
`status_dict`, a shared source reporting the real `PerceptionStatus`, a real safety gate).

Three further properties are held:

* **The table is total.** Every Head-Pointer controller state, every shared-source state and
  every global-gate state is a scenario -- read from the enums, so a new member fails here.
* **A guard that iterates is proven on an empty set.** `_assert_agree([])` must refuse.
* **No value can leak.** A machine whose runtime holds recognisable numbers is run through all
  three surfaces and none appears.
"""

from __future__ import annotations

import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from yazses.cameraperm import CameraBlocker, CameraGate
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.handsfree.observability import (
    HEAD_STATES,
    Health,
    facts_from_payload,
    health_rows,
    render_status_lines,
)
from yazses.handsfree.panel import build_panel, render_text
from yazses.handsfree.panel_io import gather_panel_inputs
from yazses.handsfree.probe import PointerEnvironment
from yazses.handsfree.safety import HandsFreeSafety, SafetyLimits
from yazses.headpointer.controller import HeadPointerStatus, State
from yazses.headpointer.runtime import status_dict
from yazses.perception.source import PerceptionStatus, SourceState
from yazses.system.doctor import _handsfree_checks

# ------------------------------------------------------------------ the fabricated machine

#: subsystem -> the label each surface gives its row. Calibration is deliberately absent: a
#: status poll may not read the disk, so only `doctor` and the window report it.
LABELS: dict[str, dict[str, str]] = {
    "safety": {"status": "hands-free safety", "doctor": "Hands-free safety",
               "panel": "Hands-free safety"},
    "perception": {"status": "hands-free perception", "doctor": "Hands-free perception",
                   "panel": "Hands-free perception"},
    "head": {"status": "head tracking", "doctor": "Head tracking", "panel": "Head tracking"},
    "face": {"status": "face switch", "doctor": "Face switch", "panel": "Face switch"},
    "gaze": {"status": "gaze routing", "doctor": "Gaze routing", "panel": "Gaze routing"},
    "pointer": {"status": "pointer output", "doctor": "Pointer output", "panel": "Pointer output"},
}

#: The window's own Head-Pointer row (it also has the shared "Head tracking" row above).
PANEL_EXTRA = {"head": "Head-Pointer"}

_SECRET_X, _SECRET_Y = 0.618033, 0.414213  # recognisable, must never be printed
HEADLESS = PointerEnvironment("headless", None, None, False)


class _FaceStandIn:
    """Identified by module, the way the daemon identifies a face switch source."""


_FaceStandIn.__module__ = "yazses.facegesture.backend"


class _HeadRuntime:
    """A Head-Pointer runtime reporting the real status dict, or the reason it has none."""

    def __init__(self, state: State | None, *, reason: str = "", consent: str = "granted",
                 backend: str = "portal", fault: str = "", age_s: float | None = 0.04,
                 inactive_reason: str = "") -> None:
        self._status = None if state is None else HeadPointerStatus(
            state=state, reason=reason, paused=state is State.PAUSED,
            clutched=state is State.CLUTCHED, calibrated=True, sample_age_s=age_s,
            dwell_enabled=False, dwell_armed=False, dwell_progress=0.0, fault=fault,
            backend=backend, consent=consent, consent_detail="",
        )
        self.reason = inactive_reason

    @property
    def active(self) -> bool:
        return self._status is not None

    def command(self, action: str, params: dict | None = None) -> dict[str, object]:
        assert action == "status", "a read-only surface issued a write"
        if self._status is None:
            return {"ok": True, "active": False, "reason": self.reason}
        return {"ok": True, "active": True, "notice": "", **status_dict(self._status)}


class _Source:
    def __init__(self, status: PerceptionStatus) -> None:
        self._status = status

    def status(self) -> PerceptionStatus:
        return self._status


def _perception(state: SourceState, *, channels=("head_pose", "face"), failure="") -> _Source:
    return _Source(PerceptionStatus(
        state=state, backend="mediapipe" if state is SourceState.RUNNING else "",
        consumers=("headpointer",), opens=1,
        channels=channels if state is SourceState.RUNNING else (),
        last_sample_age_s=0.03 if state is SourceState.RUNNING else None,
        failure_reason=failure,
    ))


def _gate(*, pause: bool = False, fault: str = "") -> HandsFreeSafety:
    now = [10_000.0]
    gate = HandsFreeSafety(("headpointer", "facegesture"), limits=SafetyLimits(500.0),
                           clock=lambda: now[0])
    gate.sample("headpointer")
    gate.sample("facegesture")
    gate.resume()
    if fault:
        gate.fault("facegesture", fault)
    elif pause:
        gate.pause("paused by the user")
    return gate


@dataclass
class Machine:
    """One fabricated machine. ``expect`` is what every surface must say, by subsystem."""

    name: str
    expect: dict[str, Health]
    features: tuple[str, ...] = ("headpointer",)
    head: _HeadRuntime | None = None
    perception: _Source | None = None
    gate: HandsFreeSafety | None = None
    face_built: bool = False
    gaze_built: bool = False
    running: bool = True
    camera: CameraGate = field(
        default_factory=lambda: CameraGate(True, CameraBlocker.NONE, "camera access is allowed")
    )

    @property
    def cfg(self) -> Config:
        cfg = Config()
        for feature in self.features:
            getattr(cfg, feature).enabled = True
        cfg.handsfree_safety.enabled = self.gate is not None
        return cfg


def _daemon_payload(m: Machine) -> dict[str, object] | None:
    """The REAL status payload method, over a stand-in that holds the fabricated parts."""
    daemon = types.SimpleNamespace(
        _config=m.cfg,
        _gaze_targeter=object() if m.gaze_built else None,
        _extra_activations=[_FaceStandIn()] if m.face_built else [],
        _headpointer=m.head,
        _perception=m.perception,
        _gaze_on_shared_source=m.gaze_built and m.perception is not None,
        _face_on_shared_source=m.face_built and m.perception is not None,
        _handsfree_safety=m.gate,
    )
    return Daemon._handsfree_payload(daemon)


# ------------------------------------------------------------------ the three surfaces


def _norm_doctor(tag: str, detail: str) -> Health:
    if tag == "SKIP":
        return Health.UNKNOWN if detail.lower().startswith("unknown") else Health.DORMANT
    return {"OK": Health.OK, "WARN": Health.DEGRADED, "FAIL": Health.FAULT}[tag]


_PANEL_WORD = {
    "OK": Health.OK, "OFF": Health.DORMANT, "UNKNOWN": Health.UNKNOWN,
    # "NOT AVAILABLE" is the window's name for a requested-but-impossible-here DEGRADED state.
    "NEEDS ATTENTION": Health.DEGRADED, "NOT AVAILABLE": Health.DEGRADED,
    "PROBLEM": Health.FAULT,
}


def _platform(m: Machine, payload: dict[str, object] | None, tmp: Path) -> Any:
    def call(method: str, **_kw: object) -> dict[str, object]:
        if not m.running:
            raise ConnectionRefusedError("no daemon")
        if method == "status":
            return {"state": "idle", "handsfree": payload,
                    "headpointer": m.head.command("status") if m.head and m.head.active else None}
        if method == "headpointer":
            return m.head.command("status") if m.head else {
                "ok": False, "reason": "Head-Pointer is not available in this daemon"}
        raise AssertionError(f"unexpected daemon call {method!r}")

    class _Perms:
        def check_camera(self):
            raise AssertionError("a read-only surface asked the OS about the camera")

        def how_to_grant_camera(self):
            return ""

    return types.SimpleNamespace(
        name="linux",
        paths=types.SimpleNamespace(data_dir=tmp, ipc_socket=str(tmp / "s.sock")),
        lifecycle=types.SimpleNamespace(is_running=lambda: m.running),
        ipc_client_factory=lambda _s: types.SimpleNamespace(call=call),
        permissions=_Perms(),
    )


def _camera_row(m: Machine):
    if m.camera.allowed:
        return ("Camera", "OK", "ok")
    soft = m.camera.blocker in (CameraBlocker.PERMISSION_UNKNOWN, CameraBlocker.NOT_PROBED)
    return ("Camera", "WARN" if soft else "FAIL", m.camera.reason)


def observe(m: Machine, tmp: Path) -> dict[str, dict[str, list[tuple[Health, str]]]]:
    """surface -> subsystem -> [(health, text), ...], each from that surface's real path."""
    payload = _daemon_payload(m) if m.running else None
    platform = _platform(m, payload, tmp)
    out: dict[str, dict[str, list[tuple[Health, str]]]] = {"status": {}, "doctor": {}, "panel": {}}

    # status: exactly what `yazses status` renders from the daemon's reply.
    if payload is not None:
        facts = facts_from_payload(payload)
        assert facts is not None
        by_label = {row.label.lower(): row for row in health_rows(facts)}
        rendered = {ln.strip().split(":", 1)[0]: ln for ln in render_status_lines(payload)}
        for sub, names in LABELS.items():
            row = by_label.get(names["status"])
            if row is not None:
                assert names["status"] in rendered, "a row the CLI would not print"
                out["status"][sub] = [(row.health, rendered[names["status"]])]

    # doctor: the real check, over the real `_headpointer_daemon_view` and live status call.
    rows = _handsfree_checks(
        m.cfg, platform, _camera_row(m), unwired=frozenset(),
        read_context=lambda: None, pointer_env=HEADLESS,
    )
    by_name = {label: (tag, detail) for label, tag, detail in rows}
    for sub, names in LABELS.items():
        if names["doctor"] in by_name:
            tag, detail = by_name[names["doctor"]]
            out["doctor"][sub] = [(_norm_doctor(tag, detail), detail)]

    # panel: the real gatherer and the real view-model.
    def ipc(method: str, params: dict[str, object]) -> object:
        return platform.ipc_client_factory(None).call(method, **params)

    inputs = gather_panel_inputs(
        m.cfg, platform, ipc, deps_probe=lambda _m: [], blocked_probe=lambda _p: None,
        camera_gate=m.camera, read_context=lambda: None, unwired=frozenset(),
        pointer_env=HEADLESS,
    )
    panel = {row.label: row for row in build_panel(inputs).health}
    for sub, names in LABELS.items():
        wanted = [names["panel"], *([PANEL_EXTRA[sub]] if sub in PANEL_EXTRA else [])]
        found = [panel[label] for label in wanted if label in panel]
        if found:
            out["panel"][sub] = [(_PANEL_WORD[r.word], r.text) for r in found]
    return out


def _assert_agree(machines: list[Machine], tmp: Path) -> None:
    # A guard that iterates passes on an empty collection (it did, three times in one day).
    assert machines, "no scenarios were supplied: an empty table would pass vacuously"
    for m in machines:
        seen = observe(m, tmp)
        for sub, want in m.expect.items():
            for surface in (("doctor", "panel") if not m.running else ("status", "doctor", "panel")):
                rows = seen[surface].get(sub)
                assert rows, f"[{m.name}] {surface} printed no {sub!r} row at all"
                for health, text in rows:
                    assert health is want, (
                        f"[{m.name}] {surface} says {sub} is {health.name} "
                        f"(wanted {want.name}): {text!r}"
                    )
        # Whatever a surface chose to say, the others must say it too, and agree.
        surfaces = ("status", "doctor", "panel") if m.running else ("doctor", "panel")
        subjects = set().union(*(set(seen[s]) for s in surfaces))
        for sub in sorted(subjects):
            classes = {s: {h for h, _t in seen[s].get(sub, [])} for s in surfaces}
            missing = [s for s, h in classes.items() if not h]
            assert not missing, f"[{m.name}] {missing} print no {sub!r} row but others do: {classes}"
            union = set().union(*classes.values())
            assert len(union) == 1, f"[{m.name}] surfaces disagree about {sub}: {classes}"


# ------------------------------------------------------------------ the table

OK, DEG, FLT, DORM, UNK = (Health.OK, Health.DEGRADED, Health.FAULT, Health.DORMANT,
                           Health.UNKNOWN)

#: Hand-written expectations per Head-Pointer controller state, independent of
#: `HEAD_STATES`: the point is that three surfaces agree with a human's judgement, not that
#: three readers of one dict agree with the dict. (state, consent, expected head, expected pointer)
HEAD_CASES: tuple[tuple[State, str, Health, Health], ...] = (
    (State.WAITING, "granted", DEG, OK),
    (State.TRACKING, "granted", OK, OK),
    (State.LOST, "granted", DEG, OK),
    (State.PAUSED, "granted", DEG, OK),
    (State.CLUTCHED, "granted", OK, OK),
    (State.SUPPRESSED, "granted", DEG, OK),
    (State.FAULTED, "granted", FLT, OK),
    (State.PENDING_CONSENT, "pending_consent", DEG, DEG),
    (State.DENIED, "denied", DEG, DEG),
    (State.UNAVAILABLE, "unavailable", DEG, DEG),
    (State.CLOSED, "granted", DEG, OK),
)


def _head_machine(state: State, consent: str, head: Health, pointer: Health) -> Machine:
    return Machine(
        f"head-pointer {state.value}",
        {"head": head, "pointer": pointer, "perception": OK},
        head=_HeadRuntime(state, consent=consent,
                          reason="the camera was lost" if state in (State.LOST, State.FAULTED) else "",
                          fault="the pointer backend failed" if state is State.FAULTED else ""),
        perception=_perception(SourceState.RUNNING),
    )


def test_every_head_pointer_state_is_in_the_table() -> None:
    """Total over the enum: a state added to the controller fails here until it is decided."""
    assert {s for s, *_ in HEAD_CASES} == set(State)
    assert {s.value for s in State} <= set(HEAD_STATES), "HEAD_STATES misses a controller state"


@pytest.mark.parametrize("case", HEAD_CASES, ids=lambda c: c[0].value)
def test_the_three_surfaces_agree_on_every_head_pointer_state(case, tmp_path) -> None:
    _assert_agree([_head_machine(*case)], tmp_path)


def test_a_head_pointer_the_daemon_never_built_is_reported_not_unknown(tmp_path) -> None:
    _assert_agree([Machine(
        "head-pointer not built",
        {"head": DEG, "pointer": DEG},
        head=_HeadRuntime(None, inactive_reason="no pointer backend on this session"),
        perception=_perception(SourceState.DORMANT),
    )], tmp_path)


SOURCE_CASES = (
    # (state, failure, expected perception)
    (SourceState.RUNNING, "", OK),
    # A lazy source nobody has opened yet stays "running" with the reason saying so: that is
    # the contract tests/test_gaze_shared_source.py holds, and "OFF" would read as disabled.
    (SourceState.DORMANT, "", OK),
    (SourceState.FAILED, "the camera could not be opened (device busy)", FLT),
)


def test_every_shared_source_state_is_in_the_table() -> None:
    assert {c[0] for c in SOURCE_CASES} == set(SourceState)


@pytest.mark.parametrize("case", SOURCE_CASES, ids=lambda c: c[0].value)
def test_the_three_surfaces_agree_on_every_shared_camera_state(case, tmp_path) -> None:
    state, failure, want = case
    _assert_agree([Machine(
        f"shared camera {state.value}", {"perception": want},
        features=("headpointer",),
        head=_HeadRuntime(State.WAITING if state is not SourceState.RUNNING else State.TRACKING),
        perception=_perception(state, failure=failure),
    )], tmp_path)


def test_a_failed_camera_names_its_reason_on_every_surface(tmp_path) -> None:
    m = Machine(
        "failed camera reason", {"perception": FLT},
        head=_HeadRuntime(State.LOST),
        perception=_perception(SourceState.FAILED, failure="the camera could not be opened (busy)"),
    )
    seen = observe(m, tmp_path)
    for surface in ("status", "doctor", "panel"):
        assert "busy" in seen[surface]["perception"][0][1], surface


GATE_CASES = (
    ("active", _gate, OK),
    ("paused", lambda: _gate(pause=True), DEG),
    ("faulted", lambda: _gate(fault="the camera was taken by another application"), FLT),
)


def test_every_global_gate_state_is_in_the_table() -> None:
    from yazses.handsfree.safety import SafetyState

    assert {name for name, *_ in GATE_CASES} == {s.value for s in SafetyState}


@pytest.mark.parametrize("name,build,want", GATE_CASES, ids=[c[0] for c in GATE_CASES])
def test_the_three_surfaces_agree_on_every_global_gate_state(name, build, want, tmp_path) -> None:
    _assert_agree([Machine(
        f"gate {name}", {"safety": want},
        features=("headpointer", "facegesture"),
        head=_HeadRuntime(State.TRACKING), perception=_perception(SourceState.RUNNING),
        gate=build(), face_built=True,
    )], tmp_path)


def test_the_three_surfaces_agree_on_the_face_switch(tmp_path) -> None:
    _assert_agree([
        Machine("face switch built, channel present", {"face": OK},
                features=("facegesture",), perception=_perception(SourceState.RUNNING),
                face_built=True),
        Machine("face switch built, no face in view", {"face": DEG},
                features=("facegesture",),
                perception=_perception(SourceState.RUNNING, channels=()), face_built=True),
        Machine("face switch not built (missing dependency)", {"face": DEG},
                features=("facegesture",), face_built=False),
    ], tmp_path)


def test_a_face_switch_that_was_never_built_does_not_blame_the_build(tmp_path) -> None:
    """The old text said 'no runtime path in this build ... nothing to fix locally' about a
    face switch that merely lacked a dependency -- the wrong cause and the wrong advice."""
    m = Machine("face switch not built", {"face": DEG}, features=("facegesture",))
    seen = observe(m, tmp_path)
    for surface in ("status", "doctor", "panel"):
        text = seen[surface]["face"][0][1]
        assert "no runtime path in this build" not in text, surface
        assert "did not construct it" in text, surface


def test_the_three_surfaces_agree_on_gaze_routing(tmp_path) -> None:
    _assert_agree([
        Machine("gaze built", {"gaze": OK}, features=("gaze",),
                perception=_perception(SourceState.DORMANT), gaze_built=True),
        Machine("gaze enabled, not built", {"gaze": DEG}, features=("gaze",), gaze_built=False),
    ], tmp_path)


def test_a_daemon_that_is_not_running_is_never_reported_as_ok(tmp_path) -> None:
    """Nothing is knowable, so the honest word is unknown (or the session prediction) -- and
    on no surface does a state held by a process that is not there read as healthy."""
    m = Machine("daemon down", {"head": UNK, "perception": UNK},
                features=("headpointer",), running=False)
    seen = observe(m, tmp_path)
    assert seen["status"] == {}, "`status` has no daemon to describe"
    _assert_agree([m], tmp_path)
    for surface in ("doctor", "panel"):
        for sub, rows in seen[surface].items():
            assert all(h is not Health.OK for h, _t in rows), (surface, sub)


def test_a_blocked_camera_is_one_cause_on_every_surface_that_can_see_the_gate(tmp_path) -> None:
    """`status` cannot see the permission gate (a poll may not touch the OS); `doctor` and the
    window can, and both point at the Camera row rather than restating its failure."""
    m = Machine(
        "camera blocked", {"perception": DORM}, features=("facegesture",),
        camera=CameraGate(False, CameraBlocker.NO_DEVICE, "no camera was found"),
        running=False,
    )
    _assert_agree([m], tmp_path)


# ------------------------------------------------------------------ the harness guards


def test_the_harness_refuses_an_empty_table(tmp_path) -> None:
    with pytest.raises(AssertionError, match="no scenarios"):
        _assert_agree([], tmp_path)


def test_the_harness_notices_a_surface_that_disagrees(tmp_path, monkeypatch) -> None:
    """Mutation check: make the window call a denied permission a PROBLEM again (what it said
    before this file) and the comparison must fail. Without this a harness that cannot fail
    would be indistinguishable from one that holds."""
    from yazses.handsfree import panel as panel_mod

    monkeypatch.setitem(panel_mod._HEALTH_TO_WORD, Health.DEGRADED, "problem")
    with pytest.raises(AssertionError, match="disagree|says"):
        _assert_agree([_head_machine(State.DENIED, "denied", DEG, DEG)], tmp_path)


# ------------------------------------------------------------------ privacy & cost


def test_no_pose_gaze_or_position_value_reaches_any_surface(tmp_path) -> None:
    class _Leaky(_HeadRuntime):
        def command(self, action, params=None):
            reply = super().command(action, params)
            # A future field a careless change could add to the runtime's reply.
            reply.update({"yaw": _SECRET_X, "pitch": _SECRET_Y, "x": _SECRET_X, "y": _SECRET_Y,
                          "gaze": [_SECRET_X, _SECRET_Y]})
            return reply

    m = Machine("leaky", {"head": OK}, head=_Leaky(State.TRACKING),
                perception=_perception(SourceState.RUNNING))
    payload = _daemon_payload(m)
    seen = observe(m, tmp_path)
    blob = repr(payload) + repr(seen) + "\n".join(render_status_lines(payload))
    inputs = gather_panel_inputs(
        m.cfg, _platform(m, payload, tmp_path),
        lambda method, params: _platform(m, payload, tmp_path).ipc_client_factory(None).call(
            method, **params),
        deps_probe=lambda _m: [], blocked_probe=lambda _p: None, camera_gate=m.camera,
        read_context=lambda: None, unwired=frozenset(), pointer_env=HEADLESS,
    )
    blob += "\n".join(render_text(build_panel(inputs)))
    for secret in (str(_SECRET_X), str(_SECRET_Y), "0.618", "0.414"):
        assert secret not in blob, f"{secret} leaked into a status surface"


def test_reading_every_surface_never_issues_a_write_or_asks_the_os(tmp_path) -> None:
    """`_HeadRuntime.command` refuses anything but `status`, `_Perms` refuses the camera probe
    and the call fake refuses any method but status/headpointer: observing all of the above
    already ran under those refusals, so this just pins that they exist."""
    runtime = _HeadRuntime(State.TRACKING)
    with pytest.raises(AssertionError):
        runtime.command("resume")


# ------------------------------------------------------------------ the wire and the report


def test_an_unrecognised_head_state_is_unknown_and_names_the_word() -> None:
    """A newer daemon may report a state this build has never heard of. Never OK."""
    from yazses.handsfree.observability import head_state_row

    row = head_state_row("Head tracking", "levitating", "", None)
    assert row.health is Health.UNKNOWN
    assert "levitating" in row.reason


def test_the_new_fields_round_trip_through_json() -> None:
    import json

    from yazses.handsfree.observability import as_payload

    m = Machine("round trip", {}, head=_HeadRuntime(State.PENDING_CONSENT, consent="pending_consent"),
                perception=_perception(SourceState.RUNNING), gaze_built=False)
    payload = _daemon_payload(m)
    assert payload is not None
    facts = facts_from_payload(json.loads(json.dumps(payload)))
    assert facts is not None
    assert (facts.head_state, facts.head_built, facts.pointer_consent, facts.pointer_available) == (
        "pending_consent", True, "pending_consent", True)
    assert as_payload(facts) == json.loads(json.dumps(payload))


@pytest.mark.parametrize("junk", [17, ["x"], {"a": 1}, None, True])
def test_malformed_new_fields_degrade_to_not_determined(junk) -> None:
    facts = facts_from_payload({
        "features_requested": ["headpointer"], "head_state": junk, "head_built": junk,
        "head_age_ms": junk, "pointer_consent": junk, "pointer_available": junk,
    })
    assert facts is not None
    for row in health_rows(facts):
        assert isinstance(row.reason, str)


def test_an_older_daemon_without_the_new_fields_still_reads_unknown_not_ok() -> None:
    old = {"features_requested": ["headpointer", "facegesture"], "camera_ready": True,
           "perception_state": "running", "head_wired": True, "face_wired": True}
    facts = facts_from_payload(old)
    assert facts is not None
    by_label = {r.label: r for r in health_rows(facts)}
    assert by_label["Head tracking"].health is Health.UNKNOWN
    assert by_label["Face switch"].health is Health.UNKNOWN


def test_the_report_bundle_redacts_the_new_free_text_keys(tmp_path, monkeypatch) -> None:
    """The reason strings are sentences from the desktop and the camera stack, and exception
    text is mostly paths. The whole `handsfree` block goes through `redact_text`."""
    import getpass

    # `redact_text` removes THIS machine's home directory and account name, so the fixture
    # has to carry the real ones -- an invented name would pass without proving anything.
    import re

    from yazses.system import report as report_mod
    from yazses.system.report import redact_status

    # A fixed, non-generic identity. The redactor compiles both patterns at import and
    # deliberately leaves generic CI account names such as `runner` alone, so reading the real
    # ones would make this test mean something else on CI. Rebuild them for a fake identity.
    home = "/home/ada"
    user = "ada"
    monkeypatch.setattr(getpass, "getuser", lambda: user)
    monkeypatch.setattr(report_mod, "_ACCOUNT", report_mod._account_pattern())
    monkeypatch.setattr(report_mod, "_HOME", re.compile(re.escape(home)))

    class _Rt(_HeadRuntime):
        def command(self, action, params=None):
            reply = super().command(action, params)
            reply["reason"] = f"could not open {home}/.config/yazses/portal.token"
            reply["consent_reason"] = f"refused for {user}@example.com"
            return reply

    m = Machine("redaction", {}, head=_Rt(State.LOST, consent="pending_consent"),
                perception=_perception(SourceState.FAILED,
                                       failure=f"could not open {home}/video0"))
    payload = _daemon_payload(m)
    assert payload is not None
    blob = repr(payload)
    assert home in blob and f"{user}@" in blob, "the fixture must actually carry the secrets"
    cleaned = repr(redact_status({"handsfree": payload}))
    assert home not in cleaned and f"{user}@" not in cleaned


def test_doctor_asks_the_daemon_without_taking_the_trays_notifications(tmp_path) -> None:
    calls: list[tuple[str, dict]] = []
    m = Machine("kwargs", {}, head=_HeadRuntime(State.TRACKING),
                perception=_perception(SourceState.RUNNING))
    payload = _daemon_payload(m)
    platform = _platform(m, payload, tmp_path)
    inner = platform.ipc_client_factory(None)

    def spy(method, **kw):
        calls.append((method, kw))
        return inner.call(method, **kw)

    platform.ipc_client_factory = lambda _s: types.SimpleNamespace(call=spy)
    _handsfree_checks(m.cfg, platform, ("Camera", "OK", "ok"), unwired=frozenset(),
                      read_context=lambda: None, pointer_env=HEADLESS)
    status_calls = [kw for method, kw in calls if method == "status"]
    assert status_calls == [{"consume_notifications": False}]
    assert {method for method, _ in calls} <= {"status", "headpointer"}


def test_facegesture_status_does_not_tell_an_enabled_switch_to_enable_itself() -> None:
    """`yazses facegesture status` for a switch that is on and was never built used to say
    "not running (`yazses features enable facegesture`)" -- advice to do what was done."""
    from yazses.ipc.protocol import Request

    def reply(enabled: bool) -> dict:
        cfg = Config()
        cfg.facegesture.enabled = enabled
        daemon = types.SimpleNamespace(_config=cfg, _facegesture_payload=lambda: None)
        return Daemon._handle_facegesture(daemon, Request("facegesture", {"action": "status"}))

    on, off = reply(True), reply(False)
    assert on["active"] is False and off["active"] is False
    assert "features enable" not in str(on["reason"]) and "doctor" in str(on["reason"])
    assert "features enable facegesture" in str(off["reason"])


@pytest.mark.parametrize(("command", "enable_hint"), [
    (["headpointer", "status"], "features enable headpointer"),
    (["gesture", "status"], "features enable gesture"),
])
def test_a_status_command_only_says_to_turn_it_on_when_it_is_off(monkeypatch, command, enable_hint) -> None:
    """`headpointer status` printed "Turn it on with: yazses features enable headpointer" even
    when the pointer was on and had failed to build ("no pointer backend"). A reason means it is
    on; no reason means it is off."""
    from typer.testing import CliRunner

    from yazses import cli

    def run(reply: dict) -> str:
        client = types.SimpleNamespace(call=lambda _m, **_k: reply)
        platform = types.SimpleNamespace(
            paths=types.SimpleNamespace(ipc_socket="x"), ipc_client_factory=lambda _s: client)
        monkeypatch.setattr(cli, "get_platform", lambda: platform)
        result = CliRunner().invoke(cli.app, command)
        assert result.exit_code == 0, result.output
        return result.output

    assert enable_hint in run({"ok": True, "active": False, "reason": ""})
    assert enable_hint not in run({"ok": True, "active": False, "reason": "no pointer backend"})


def test_gaze_status_never_builds_the_backend_or_downloads_the_model(monkeypatch, tmp_path) -> None:
    """`yazses gaze status` answered "are the deps present?" by constructing the MediaPipe backend,
    which loads the landmarker and downloads its model on a cold cache. A status command is
    read-only: building (and the network it can reach) must not happen."""
    from typer.testing import CliRunner

    from yazses import cli

    def boom(*_a, **_k):
        raise AssertionError("`gaze status` built the backend / fetched the model")

    cfg = Config()
    cfg.gaze.enabled = True
    platform = types.SimpleNamespace(
        paths=types.SimpleNamespace(config_file=tmp_path / "c.toml", data_dir=tmp_path))
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    monkeypatch.setattr("yazses.config.load_config", lambda _p: cfg)
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", boom)
    monkeypatch.setattr("yazses.gaze.download.ensure_face_landmarker", boom)
    monkeypatch.setattr("yazses.gaze.mediapipe_backend.MediapipeGazeBackend.__init__", boom)
    monkeypatch.setattr("yazses.gaze.desktop.build_desktop", lambda: object())
    result = CliRunner().invoke(cli.app, ["gaze", "status"])
    assert result.exit_code == 0, result.output
    assert "gaze backend/deps" in result.output
