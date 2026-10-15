"""Run the Head-Pointer: lease the shared camera, poll it, drive the controller (#404/#405).

The thin, impure shell around :class:`~yazses.headpointer.controller.HeadPointerController`.
It owns exactly three things the controller must not: a **lease** on the one shared camera
(``perception/source.py``), a **poll loop**, and the **construction rules** that decide whether
the feature runs at all. It never opens a camera, never imports OpenCV or MediaPipe and never
touches a platform API -- the source gives it derived ``HeadPoseSignal`` values and the
platform's ``pointer_factory`` gives it a ``PointerSink``.

**Dormant unless asked, and quiet about why not.** :func:`build_headpointer` returns a runtime
with no runner when ``[headpointer]`` is off (the shipped state), when there is no shared camera
source, or when the platform has no usable pointer backend. In each case nothing is leased, no
sink is opened and no thread starts; the reason is kept so ``yazses headpointer status`` can say
*why* the pointer is not moving rather than leave a user staring at it (ADR-v2-146: unsupported
is a word, not a silence).

**The loop polls faster than the camera delivers and acts once per observation.** The controller
dedupes by sample timestamp, so a 30 Hz poll over a 15 fps camera moves the pointer 15 times a
second, not 30. The motion model is in real time: ``x_gain``/``y_gain`` are pointer units per
*second* per radian and each accepted sample moves the pointer by velocity x the real time since
the previous one (capped; see ``HeadPointerController``), so neither the camera's frame rate nor
this poll rate changes how fast the pointer goes.

**A crash in this loop must not take dictation with it.** Anything the loop raises faults the
controller (motion stops, the gate is told) and is logged once; the thread then keeps polling so
an explicit ``resume`` can bring it back.
"""
from __future__ import annotations

import dataclasses
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yazses.handsfree.safety import HandsFreeSafety
from yazses.headpointer.controller import (
    SOURCE_NAME,
    DwellFeedback,
    HeadPointerController,
    HeadPointerSettings,
    HeadPointerStatus,
)
from yazses.headpointer.pointer import PointerCalib
from yazses.perception.signals import FacePerceptionSource
from yazses.pointer.base import PointerButton, PointerSink

__all__ = [
    "HeadPointerRunner",
    "HeadPointerRuntime",
    "build_headpointer",
    "settings_from_config",
]

log = logging.getLogger(__name__)

#: Poll interval bounds (seconds). Faster than the camera so no observation is skipped.
_MIN_INTERVAL_S = 1.0 / 120.0
_MAX_INTERVAL_S = 1.0 / 10.0
_DEFAULT_INTERVAL_S = 1.0 / 30.0


def _num(value: object, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):  # OverflowError: an int too large for a float
        return default
    return number if number == number and abs(number) != float("inf") else default


def settings_from_config(section: Any) -> HeadPointerSettings:
    """``[headpointer]`` as :class:`HeadPointerSettings`. Duck-typed; unreadable values fall back.

    The config loader already coerces types and ``doctor`` reports what it rejected, so a
    value that still cannot be read here has been complained about once; refusing it a second
    time by raising would turn a typo into a daemon that does not start.
    """
    defaults = HeadPointerSettings()
    calib = PointerCalib(
        x_gain=_num(getattr(section, "x_gain", None), defaults.calib.x_gain),
        y_gain=_num(getattr(section, "y_gain", None), defaults.calib.y_gain),
        deadzone=_num(getattr(section, "deadzone", None), defaults.calib.deadzone),
        max_speed_x=_num(getattr(section, "max_speed_x", None), defaults.calib.max_speed_x),
        max_speed_y=_num(getattr(section, "max_speed_y", None), defaults.calib.max_speed_y),
        max_speed_overall=_num(getattr(section, "max_speed_overall", None), defaults.calib.max_speed_overall),
    )
    return HeadPointerSettings(
        calib=calib,
        freshness_s=_num(getattr(section, "freshness_ms", None), defaults.freshness_s * 1000.0)
        / 1000.0,
        min_confidence=_num(getattr(section, "min_confidence", None), defaults.min_confidence),
        dwell_enabled=bool(getattr(section, "dwell_enabled", False)),
        dwell_radius_px=_num(getattr(section, "dwell_radius_px", None), defaults.dwell_radius_px),
        dwell_hold_s=_num(getattr(section, "dwell_ms", None), defaults.dwell_hold_s * 1000.0) / 1000.0,
        dwell_hold_frames=int(
            _num(getattr(section, "dwell_hold_frames", None), defaults.dwell_hold_frames)
        ),
    )


class HeadPointerRunner:
    """Holds the camera lease and polls it into the controller.

    ``pump()`` is one poll and is public so a test drives the whole thing by hand; the thread
    started by :meth:`start` does nothing but call it on a timer.
    """

    def __init__(
        self,
        controller: HeadPointerController,
        lease: FacePerceptionSource,
        *,
        interval_s: float = _DEFAULT_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
        thread: bool = True,
    ) -> None:
        self.controller = controller
        self._lease = lease
        self._interval_s = min(_MAX_INTERVAL_S, max(_MIN_INTERVAL_S, interval_s))
        self._clock = clock
        self._use_thread = thread
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._leased = False
        self._complained = False

    @property
    def running(self) -> bool:
        return self._leased

    def start(self) -> None:
        """Take the camera lease and start polling. Idempotent; never raises."""
        if self._leased:
            return
        try:
            self._lease.start()
        except Exception:
            log.warning("Head-Pointer could not lease the camera", exc_info=True)
            self.controller.fail("could not lease the camera")
            return
        self._leased = True
        self._stop.clear()
        if self._use_thread:
            self._thread = threading.Thread(target=self._loop, name="headpointer", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop polling, release the lease and close the sink. Idempotent; never raises."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        if self._leased:
            self._leased = False
            try:
                self._lease.stop()
            except Exception:
                log.debug("Head-Pointer lease release raised", exc_info=True)
        self.controller.close()

    def pump(self) -> None:
        """One poll: read the newest observation and advance the controller."""
        try:
            sample = self._lease.latest()
            head = sample.head_pose if sample is not None else None
            self.controller.update(head, self._clock())
        except Exception as exc:
            # Reported once: a loop that logs every tick would bury the one useful line.
            if not self._complained:
                self._complained = True
                log.warning("Head-Pointer loop failed", exc_info=True)
            self.controller.fail(f"runtime error: {type(exc).__name__}")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.pump()
            self._stop.wait(self._interval_s)


@dataclass
class HeadPointerRuntime:
    """What the daemon holds: a runner (or the reason there is none) and the command surface."""

    runner: HeadPointerRunner | None = None
    #: Why there is no runner, or ``""``. Printed by ``yazses headpointer status``.
    reason: str = ""
    #: A caveat on a runner that *is* running (e.g. dwell-click held off), or ``""``.
    notice: str = ""
    #: Why dwell-click cannot run on this build, or ``""``. Then a runtime ``dwell on`` is
    #: refused too: the guard must not be one CLI call away from being switched off.
    dwell_refusal: str = ""

    @property
    def active(self) -> bool:
        return self.runner is not None

    def start(self) -> None:
        if self.runner is not None:
            self.runner.start()

    def stop(self) -> None:
        if self.runner is not None:
            self.runner.stop()

    def command(self, action: str, params: dict[str, Any] | None = None) -> dict[str, object]:
        """The IPC/CLI surface: ``status | recenter | pause | resume | clutch | dwell``.

        Every action takes no pointer position and no precision, so each can be reached from a
        voice command, a switch or a tray item for a user who cannot aim (ADR-v2-148).
        """
        params = params or {}
        if self.runner is None:
            if action == "status":
                return {"ok": True, "active": False, "reason": self.reason}
            return {"ok": False, "reason": self.reason or "Head-Pointer is not running"}
        ctl = self.runner.controller
        if action == "status":
            return {
                "ok": True, "active": True, "notice": self.notice, **status_dict(ctl.status())
            }
        if action == "recenter":
            ctl.recenter()
            return {"ok": True}
        if action == "pause":
            ctl.pause()
            return {"ok": True}
        if action == "resume":
            result = ctl.resume()
            return {"ok": result.ok, "reason": result.reason}
        if action == "clutch":
            ctl.set_clutch(
                str(params.get("source", "user")) or "user",
                bool(params.get("active")),
                since_s=_optional_float(params.get("since_s")),
                max_rewind_s=_optional_float(params.get("max_rewind_s")),
            )
            return {"ok": True}
        if action == "dwell":
            enabled = bool(params.get("enabled"))
            if enabled and self.dwell_refusal:
                return {"ok": False, "reason": self.dwell_refusal}
            ctl.set_dwell_enabled(enabled)
            return {"ok": True}
        return {"ok": False, "reason": f"unknown action {action!r}"}


def _optional_float(value: object) -> float | None:
    """``value`` as a float, or ``None`` when it is absent or not a number (never raises)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def status_dict(status: HeadPointerStatus) -> dict[str, object]:
    """A JSON-safe status. Names, flags and ages only -- never an angle or a position."""
    return {
        "state": status.state.value,
        "reason": status.reason,
        "paused": status.paused,
        "clutched": status.clutched,
        "calibrated": status.calibrated,
        "sample_age_s": None if status.sample_age_s is None else round(status.sample_age_s, 3),
        "dwell_enabled": status.dwell_enabled,
        "dwell_armed": status.dwell_armed,
        "dwell_progress": round(status.dwell_progress, 3),
        "fault": status.fault,
        "backend": status.backend,
        "consent": status.consent,
        "consent_reason": status.consent_detail,
    }


def build_headpointer(
    config: Any,
    *,
    perception: Any,
    pointer_factory: Callable[[], PointerSink] | None,
    safety: HandsFreeSafety | None = None,
    feedback: DwellFeedback | None = None,
    dwell_feedback_available: bool = False,
    fps: int = 15,
    clock: Callable[[], float] = time.monotonic,
    thread: bool = True,
) -> HeadPointerRuntime:
    """The Head-Pointer for ``[headpointer]``, or a runtime that says why there is none.

    ``config`` is the ``[headpointer]`` section, ``perception`` the daemon's shared camera
    source (or ``None``) and ``pointer_factory`` the platform's lazy sink builder (or ``None``).
    Building opens no camera -- the lease is taken by :meth:`HeadPointerRuntime.start` -- but
    it does open the pointer sink, because a backend that cannot be had should be known now
    and not on the first head movement a user makes.
    """
    if not getattr(config, "enabled", False):
        return HeadPointerRuntime()
    if perception is None:
        return HeadPointerRuntime(
            reason="no shared camera source -- `[perception]` could not be built "
            "(is the `gaze` extra installed? see `yazses doctor`)"
        )
    if pointer_factory is None:
        return HeadPointerRuntime(reason="this platform has no pointer backend yet")
    try:
        sink = pointer_factory()
    except Exception as exc:
        return HeadPointerRuntime(
            reason=f"no pointer output: {type(exc).__name__}: {exc}"[:200]
        )
    caps = sink.capabilities()
    if not caps.relative_motion:
        _close_quietly(sink)
        return HeadPointerRuntime(
            reason=f"pointer backend {caps.backend!r} cannot move the pointer relatively"
        )
    settings = settings_from_config(config)
    # Why dwell-click may not run here, or "". Fail closed on both counts: a click the user
    # was never shown coming is the Midas-touch failure this feature is judged on (#405,
    # "user-visible dwell progress ... before firing"), and a backend with no left button
    # cannot click at all.
    refusal = ""
    if not (dwell_feedback_available or feedback is not None):
        refusal = (
            "dwell-click is held off: it needs the overlay to show its progress "
            "(`yazses features enable overlay`)"
        )
    elif not caps.supports_button(PointerButton.LEFT):
        refusal = f"dwell-click is held off: backend {caps.backend!r} has no left button"
    notice = ""
    if refusal and settings.dwell_enabled:
        notice = refusal
        log.warning("Head-Pointer: %s", notice)
        settings = dataclasses.replace(settings, dwell_enabled=False)
    controller = HeadPointerController(
        sink, settings, safety=safety, feedback=feedback, backend=caps.backend
    )
    lease = perception.consumer(SOURCE_NAME)
    interval = 1.0 / (2.0 * max(1, int(fps)))
    return HeadPointerRuntime(
        notice=notice,
        dwell_refusal=refusal,
        runner=HeadPointerRunner(
            controller, lease, interval_s=interval, clock=clock, thread=thread
        )
    )


def _close_quietly(sink: PointerSink) -> None:
    try:
        sink.close()
    except Exception:
        log.debug("closing an unusable pointer sink raised", exc_info=True)
