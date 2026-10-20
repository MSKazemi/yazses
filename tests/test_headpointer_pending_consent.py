"""The Head-Pointer while the desktop's permission dialog is open (EYE: Wayland pointer).

On Wayland the pointer is the RemoteDesktop portal's, and the first time it is enabled the
compositor asks the user. The daemon builds the Head-Pointer *before* that answer, so for a
while the pointer exists, the camera is tracking, and the desktop will not let it move. That
used to look like a fault the first time the head moved -- a message about a dialog, a global
gate told something was broken, and a ``resume`` command the user had to know to run.

What is held here:

* **Pending is a state, not a fault.** No motion is attempted, nothing is reported to the
  safety gate, ``fault`` stays empty, and the state is ``pending_consent`` -- distinct from
  ``denied`` (the user said no) and ``unavailable`` (the desktop has no pointer to give).
* **It starts by itself, gently.** On approval the next sample is only a settling frame, so
  granting permission can never itself jump or click the pointer.
* **Unknown is not a refusal.** A sink whose report cannot be read is tried, and a real
  failure still faults honestly.
* **A sink with no consent step is untouched.**

Everything is a fake: the sink records calls, the portal is the injected fake session, and
nothing here moves a real pointer or raises a real dialog.
"""
from __future__ import annotations

from tests.pointer_fake import FakePointerSink
from tests.test_headpointer_controller import FRAME, LEGACY, GateRig, Rig
from tests.test_pointer_portal import _FakePortalSession
from yazses.headpointer.controller import HeadPointerController, HeadPointerSettings, State
from yazses.headpointer.runtime import HeadPointerRunner, HeadPointerRuntime, status_dict
from yazses.inject import portal
from yazses.perception.signals import HeadPoseSignal
from yazses.pointer.base import PointerBackendError, PointerButton
from yazses.pointer.consent import ConsentReport, PointerConsent


class ConsentSink(FakePointerSink):
    """A recording sink with a permission step the test can answer by hand."""

    def __init__(self, state: PointerConsent = PointerConsent.PENDING, detail: str = "") -> None:
        super().__init__()
        self.state = state
        self.detail = detail or f"fake permission is {state.value}"
        self.reads = 0

    def pointer_consent(self) -> ConsentReport:
        self.reads += 1
        return ConsentReport(self.state, self.detail)

    # Like the real portal sink: until the desktop has granted the pointer, an attempt to
    # use it *raises* and nothing is recorded. A controller that tried anyway would fault.
    def move_relative(self, dx: float, dy: float) -> None:
        self._require_permission()
        super().move_relative(dx, dy)

    def click(self, button=PointerButton.LEFT) -> None:
        self._require_permission()
        super().click(button)

    def _require_permission(self) -> None:
        if self.state not in (PointerConsent.GRANTED, PointerConsent.NOT_REQUIRED, PointerConsent.UNKNOWN):
            raise PointerBackendError(f"not allowed: {self.state.value}")


def _rig(state: PointerConsent = PointerConsent.PENDING, **kw) -> tuple[Rig, ConsentSink]:
    sink = ConsentSink(state)
    return Rig(sink=sink, **kw), sink


def _lean(rig: Rig, frames: int = 10, yaw: float = 0.3) -> None:
    """Sit straight for three frames (so a neutral pose exists), then lean."""
    for _ in range(3):
        rig.feed(0.0)
    for _ in range(frames):
        rig.feed(yaw)


# ----------------------------------------------------------------------------- pending


def test_pending_is_its_own_state_with_the_reason_and_no_fault() -> None:
    rig, sink = _rig()
    step = rig.feed(0.3)

    assert step.state is State.PENDING_CONSENT
    assert "fake permission is pending_consent" in step.reason
    status = rig.ctl.status()
    assert status.state is State.PENDING_CONSENT
    assert status.fault == "", "an unanswered dialog is not a fault"
    assert status.consent == "pending_consent"
    assert sink.actions == []


def test_pending_never_even_tries_to_move_however_far_the_head_leans() -> None:
    rig, sink = _rig()
    _lean(rig, 30, yaw=0.9)

    # A controller that tried anyway would have been refused by the sink and faulted.
    assert rig.ctl.status().state is State.PENDING_CONSENT
    assert rig.ctl.status().fault == ""
    assert [a for a in sink.actions if a.kind.value != "close"] == []


def test_pending_is_reported_before_the_camera_has_any_signal() -> None:
    """The dialog is the news, not "no sample"."""
    rig, _sink = _rig()
    rig.idle(FRAME)
    step = rig.ctl.update(None, rig.t)

    assert step.state is State.PENDING_CONSENT


def test_pending_does_not_fault_the_global_safety_gate() -> None:
    sink = ConsentSink()
    rig = GateRig(sink=sink)
    rig.arm()  # armed, so a failed move would reach the gate rather than be suppressed
    _lean(rig, 10, yaw=0.3)

    status = rig.gate.status()
    assert status.state.value == "active", status
    assert rig.ctl.status().state is State.PENDING_CONSENT


def test_a_pending_pointer_does_not_need_resume_once_it_is_approved() -> None:
    rig, sink = _rig()
    _lean(rig, 5)
    assert rig.ctl.status().state is State.PENDING_CONSENT

    sink.state = PointerConsent.GRANTED
    step = rig.feed(0.0)

    assert step.state is State.TRACKING
    assert rig.ctl.status().consent == "granted"


def test_approval_never_jumps_or_clicks_the_pointer() -> None:
    """The first sample after a grant captures the neutral pose -- zero motion, zero click."""
    rig, sink = _rig(dwell=True, hold=3)
    _lean(rig, 20, yaw=0.5)  # leaning hard the whole time the dialog was open
    sink.state = PointerConsent.GRANTED

    first = rig.feed(0.5)

    assert first.state is State.TRACKING and first.reason == "centred"
    assert (first.dx, first.dy, first.clicked) == (0, 0, False)
    assert [a for a in sink.actions if a.kind.value not in ("close",)] == []
    # ...and motion follows only from where the head is *now*, not from the lean it held.
    rig.feed(0.5)
    assert sink.actions == []


def test_after_approval_the_pointer_follows_the_head_normally() -> None:
    rig, sink = _rig()
    sink.state = PointerConsent.GRANTED
    rig.feed(0.0)
    rig.feed(0.0)
    moved = False
    for _ in range(10):
        step = rig.feed(0.3)
        moved = moved or step.dx != 0
    assert moved
    assert sink.actions, "the approved pointer must reach the sink"


def test_a_pointer_that_loses_its_grant_rests_and_resettles_when_it_returns() -> None:
    rig, sink = _rig(PointerConsent.GRANTED)
    for _ in range(5):
        rig.feed(0.0)
    _lean(rig, 5, yaw=0.3)
    moves = len(sink.actions)
    assert moves > 0

    sink.state = PointerConsent.PENDING  # the session was released while idle
    _lean(rig, 5, yaw=0.3)
    assert rig.ctl.status().state is State.PENDING_CONSENT
    assert len(sink.actions) == moves

    sink.state = PointerConsent.GRANTED
    first = rig.feed(0.3)
    assert (first.dx, first.dy) == (0, 0), "the first frame after a return is a settling frame"


# ------------------------------------------------------------------- denied / unavailable


def test_denied_is_distinct_from_pending_and_from_a_fault() -> None:
    rig, sink = _rig(PointerConsent.DENIED)
    step = rig.feed(0.3)

    assert step.state is State.DENIED
    assert rig.ctl.status().fault == ""
    assert rig.ctl.status().consent == "denied"
    assert sink.actions == []


def test_unavailable_is_distinct_from_denied() -> None:
    rig, sink = _rig(PointerConsent.UNAVAILABLE)
    step = rig.feed(0.3)

    assert step.state is State.UNAVAILABLE
    assert State.UNAVAILABLE is not State.DENIED
    assert sink.actions == []


def test_the_three_consent_states_have_three_distinct_words() -> None:
    words = {State.PENDING_CONSENT.value, State.DENIED.value, State.UNAVAILABLE.value}
    assert words == {"pending_consent", "denied", "unavailable"}
    assert not words & {State.FAULTED.value, State.WAITING.value, State.TRACKING.value}


# ------------------------------------------------------------------- unknown / no concept


def test_an_unreadable_consent_is_tried_not_treated_as_a_refusal() -> None:
    rig, sink = _rig(PointerConsent.UNKNOWN)
    for _ in range(3):
        rig.feed(0.0)
    _lean(rig, 8)

    assert rig.ctl.status().state is State.TRACKING
    assert sink.actions, "an unknown permission state must not silence a working pointer"


def test_a_failing_unknown_sink_still_faults_honestly() -> None:
    rig, sink = _rig(PointerConsent.UNKNOWN)
    for _ in range(3):
        rig.feed(0.0)
    sink.fail_with()
    _lean(rig, 8)

    assert rig.ctl.status().state is State.FAULTED


def test_a_sink_with_no_consent_step_reports_none_and_behaves_as_before() -> None:
    rig = Rig()
    for _ in range(3):
        rig.feed(0.0)
    _lean(rig, 8)

    status = rig.ctl.status()
    assert status.consent == ""
    assert status.state is State.TRACKING
    assert rig.sink.actions


def test_a_consent_report_that_raises_does_not_stop_the_pointer() -> None:
    class Angry(FakePointerSink):
        def pointer_consent(self):
            raise RuntimeError("bus gone")

    rig = Rig(sink=Angry())
    for _ in range(3):
        rig.feed(0.0)
    _lean(rig, 8)

    assert rig.ctl.status().state is State.TRACKING


# --------------------------------------------------------------------------- status wire


def test_status_dict_carries_the_consent_state_and_reason() -> None:
    rig, _sink = _rig()
    rig.feed(0.0)

    wire = status_dict(rig.ctl.status())

    assert wire["state"] == "pending_consent"
    assert wire["consent"] == "pending_consent"
    assert "fake permission" in str(wire["consent_reason"])
    assert wire["fault"] == ""


def test_status_dict_of_a_sink_without_consent_has_empty_consent() -> None:
    wire = status_dict(Rig().ctl.status())
    assert wire["consent"] == "" and wire["consent_reason"] == ""


def test_status_reads_consent_live_not_from_the_last_tick() -> None:
    """`yazses headpointer status` must reflect an approval that landed between ticks."""
    rig, sink = _rig()
    rig.feed(0.0)
    sink.state = PointerConsent.GRANTED

    assert rig.ctl.status().consent == "granted"


# ------------------------------------------------------------- the real deferred portal sink


def test_end_to_end_on_the_deferred_portal_sink_over_the_fake_session() -> None:
    """Pending -> approved -> moving, with the shipped sink and the injected D-Bus fake."""
    session = _FakePortalSession()
    injector = portal.PortalInjector(session=session)
    sink = injector.deferred_pointer_sink()
    ctl = HeadPointerController(sink, HeadPointerSettings(calib=LEGACY))
    t = 100.0

    def tick(yaw: float):
        nonlocal t
        t += FRAME
        return ctl.update(HeadPoseSignal(t, yaw, 0.0, 0.0, 1.0), t)

    for _ in range(6):
        step = tick(0.3)
    assert step.state is State.PENDING_CONSENT
    assert ctl.status().fault == ""
    assert session.calls == [], "the Head-Pointer must never raise the dialog itself"
    assert session.notified == []

    assert injector.warm() is True  # the user approves
    for _ in range(3):
        tick(0.0)
    moved = [tick(0.3) for _ in range(8)]

    assert ctl.status().state is State.TRACKING
    assert ctl.status().consent == "granted"
    assert any(s.dx for s in moved)
    assert any(member == "NotifyPointerMotion" for member, _, _ in session.notified)


def test_end_to_end_a_cancelled_dialog_reads_denied_not_faulted() -> None:
    session = _FakePortalSession(refuse="Start")
    injector = portal.PortalInjector(session=session)
    sink = injector.deferred_pointer_sink()
    ctl = HeadPointerController(sink, HeadPointerSettings(calib=LEGACY))
    assert injector.warm() is False

    t = 100.0
    for _ in range(6):
        t += FRAME
        step = ctl.update(HeadPoseSignal(t, 0.3, 0.0, 0.0, 1.0), t)

    assert step.state is State.DENIED
    assert ctl.status().fault == ""
    assert session.notified == []


# ------------------------------------------------- the IPC command the CLI and panel read


class _Lease:
    def __init__(self) -> None:
        self.sample: HeadPoseSignal | None = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def latest(self):
        from yazses.perception import PerceptionSample

        if self.sample is None:
            return None
        return PerceptionSample(self.sample.timestamp_s, head_pose=self.sample)


def test_the_status_command_reports_pending_consent_over_ipc() -> None:
    sink = ConsentSink()
    ctl = HeadPointerController(sink, HeadPointerSettings(calib=LEGACY))
    lease = _Lease()
    clock = [100.0]
    runner = HeadPointerRunner(ctl, lease, clock=lambda: clock[0], thread=False)
    runtime = HeadPointerRuntime(runner=runner)
    lease.sample = HeadPoseSignal(100.0, 0.2, 0.0, 0.0, 1.0)
    runner.pump()

    reply = runtime.command("status")

    assert reply["ok"] is True and reply["active"] is True
    assert reply["state"] == "pending_consent"
    assert reply["consent"] == "pending_consent"
    assert reply["fault"] == ""
    assert sink.actions == []
