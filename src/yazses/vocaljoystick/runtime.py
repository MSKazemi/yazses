"""Run the Vocal Joystick: own a microphone stream while armed, drive a pointer sink (#164).

The thin, impure shell around the pure chain ``formants.VocalFrameTracker`` →
``control.VocalJoystick`` → ``drive.SustainedVowelDriver``. It owns what those must not: a
**microphone stream**, a **worker thread**, a **pointer sink**, and the **construction rules**
that decide whether the feature runs at all. It imports no audio library and no platform API
itself -- the daemon hands it a ``recorder_factory`` and the platform's ``pointer_factory``.

**Dormant unless asked, and the microphone closed unless armed.** :func:`build_vocaljoystick`
returns a runtime with no runner when ``[vocaljoystick]`` is off (the shipped state) or when
the platform has no usable pointer backend, keeping the reason for the reply. Even an enabled
runner opens no microphone at build time: the stream is opened by an explicit
``yazses handsfree resume`` (the same re-arm the Head-Pointer uses, ADR-v2-148) and closed again
by ``yazses handsfree pause``, by the spoken stop phrase and by shutdown. There is no new
command, and no implicit start: a mode that moves the pointer from sound must never be on
because the daemon started.

**It never acts while dictation is busy.** ``busy()`` is asked for every chunk; while it is
true (a hold is recording, a transcript is being typed, a meeting runs) every frame is dropped
and every run is reset, so speech being dictated cannot steer the pointer.

**With the global gate on, it obeys it.** When ``[handsfree_safety]`` is enabled the runner
registers as source ``vocaljoystick``: an open stream is its evidence of life, and any pause the
gate hears -- including a face switch's ``pause_pointer``, which does not go through the
``handsfree`` IPC -- closes the stream on the next chunk. Re-arming stays explicit.

**A failure stops motion, never dictation.** A pointer error or an analysis crash is logged
once and faults the runner; the stream is closed by the worker and nothing moves until the
next ``resume``.
"""
from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from yazses.pointer.base import PointerButton, PointerError, PointerSink
from yazses.vocaljoystick.control import VocalJoystick
from yazses.vocaljoystick.drive import PointerIntent, SustainedVowelDriver
from yazses.vocaljoystick.formants import VocalFrameTracker

__all__ = [
    "SOURCE_NAME",
    "VocalJoystickRunner",
    "VocalJoystickRuntime",
    "build_vocaljoystick",
]

log = logging.getLogger(__name__)

#: The name this feature registers under in the hands-free safety gate.
SOURCE_NAME = "vocaljoystick"

#: Chunks the worker may fall behind by before it drops audio (and resets, so a gap is never
#: integrated as motion). Bounded so a stalled worker cannot queue seconds of stale intent.
_QUEUE_CHUNKS = 32


class _Recorder(Protocol):
    def start(self) -> None: ...

    def stop(self) -> Any: ...


class _Gate(Protocol):
    def sample(self, source: str) -> None: ...

    def gate(self, source: str) -> Any: ...

    def resume(self, sources: Any = None) -> Any: ...


def _num(value: object, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return number if number == number and abs(number) != float("inf") else default


class VocalJoystickRunner:
    """Holds the microphone stream while armed and turns its audio into pointer actions.

    :meth:`process` is the whole per-chunk path and is public so a test drives it by hand;
    with ``thread=True`` the stream's callback only enqueues and a worker calls it.
    """

    def __init__(
        self,
        sink: PointerSink,
        *,
        recorder_factory: Callable[[Callable[[np.ndarray], None]], _Recorder],
        sample_rate: int = 16000,
        max_speed: float = 20.0,
        click_pitch: float = 250.0,
        clicks: bool = True,
        busy: Callable[[], bool] = lambda: False,
        safety: _Gate | None = None,
        thread: bool = True,
    ) -> None:
        self._sink = sink
        self._recorder_factory = recorder_factory
        self._busy = busy
        self._safety = safety
        self._use_thread = thread
        self._tracker = VocalFrameTracker(sample_rate)
        self._driver = SustainedVowelDriver(
            VocalJoystick(max_speed=max_speed, click_pitch=click_pitch),
            click_pitch=click_pitch, clicks=clicks,
        )
        self._lock = threading.Lock()
        self._recorder: _Recorder | None = None
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=_QUEUE_CHUNKS)
        self._worker: threading.Thread | None = None
        self._dropped = False
        self._complained = False
        self._gate_armed = False
        self.fault = ""
        self.moves = 0
        self.clicks = 0

    @property
    def active(self) -> bool:
        return self._recorder is not None

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> tuple[bool, str]:
        """Open the microphone and start acting on it. Idempotent; never raises."""
        with self._lock:
            if self._recorder is not None:
                return True, ""
            self.fault = ""
            self._reset_locked()
            self._queue = queue.Queue(maxsize=_QUEUE_CHUNKS)
            try:
                recorder = self._recorder_factory(self._on_chunk)
                recorder.start()
            except Exception as exc:
                log.warning("Vocal Joystick could not open the microphone", exc_info=True)
                return False, f"could not open the microphone: {type(exc).__name__}"
            self._recorder = recorder
            self._gate_armed = False
        if self._safety is not None:
            # An open stream is this source's evidence of life; without a sample the gate
            # refuses to arm a source. Arming only this source is what `handsfree resume`
            # (the one caller) is about to do for every source anyway.
            try:
                self._safety.sample(SOURCE_NAME)
                rearm = self._safety.resume([SOURCE_NAME])
            except Exception as exc:
                self.stop()
                return False, f"the hands-free gate failed: {type(exc).__name__}"
            if SOURCE_NAME not in getattr(rearm, "armed", ()):
                self.stop()
                return False, "the hands-free gate would not arm it: " + (
                    str(getattr(rearm, "reason", "")) or "refused")
        with self._lock:
            if self._recorder is None:
                return False, self.fault or "stopped while starting"
            if self._use_thread and self._worker is None:
                self._worker = threading.Thread(
                    target=self._work, args=(self._queue,), name="vocaljoystick", daemon=True
                )
                self._worker.start()
            return True, ""

    def stop(self) -> None:
        """Close the microphone and stop the worker. Idempotent; never raises."""
        with self._lock:
            recorder, self._recorder = self._recorder, None
            worker, self._worker = self._worker, None
            self._reset_locked()
        if recorder is not None:
            try:
                recorder.stop()
            except Exception:
                log.debug("Vocal Joystick stream stop raised", exc_info=True)
        if worker is not None:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
            if worker is not threading.current_thread():
                worker.join(timeout=2.0)

    def close(self) -> None:
        """Stop and release the pointer sink. Idempotent; never raises."""
        self.stop()
        try:
            self._sink.close()
        except Exception:
            log.debug("Vocal Joystick sink close raised", exc_info=True)

    # ------------------------------------------------------------------ the audio path

    def _on_chunk(self, chunk: np.ndarray) -> None:
        """The stream callback: enqueue only (or process inline when there is no thread)."""
        if not self._use_thread:
            self.process(chunk)
            return
        try:
            self._queue.put_nowait(np.array(chunk, dtype=np.float32).ravel())
        except queue.Full:
            self._dropped = True

    def _work(self, q: queue.Queue[np.ndarray | None]) -> None:
        while True:
            chunk = q.get()
            if chunk is None or self._recorder is None:
                return
            self.process(chunk)
            if self.fault:
                # Close the stream from the worker, never from the audio callback.
                threading.Thread(target=self.stop, name="vocaljoystick-stop", daemon=True).start()
                return

    def process(self, chunk: np.ndarray) -> None:
        """One chunk: gate, analyse, drive. Never raises."""
        if self.fault:
            return
        try:
            if self._dropped:
                self._dropped = False
                self._tracker.reset()
                self._driver.reset()
            if self._safety is not None:
                self._safety.sample(SOURCE_NAME)
                decision = self._safety.gate(SOURCE_NAME)
                if getattr(decision, "clear_pending", False):
                    self._tracker.reset()
                    self._driver.reset()
                if not getattr(decision, "allowed", False):
                    if self._gate_armed:
                        # Armed, then suppressed: a pause from any stop path. Close the mic.
                        self._fail("paused by the hands-free gate", quiet=True)
                    return  # not armed yet: `start` is still between opening and arming
                self._gate_armed = True
            if self._busy():
                self._tracker.reset()
                self._driver.reset()
                return
            for frame in self._tracker.feed(chunk):
                intent = self._driver.feed(frame)
                if intent is not None:
                    self._apply(intent)
        except PointerError as exc:
            self._fail(f"pointer output failed: {type(exc).__name__}: {exc}"[:200])
        except Exception as exc:
            self._fail(f"runtime error: {type(exc).__name__}")

    def _apply(self, intent: PointerIntent) -> None:
        if intent.kind == "click":
            self._sink.click(PointerButton.LEFT)
            self.clicks += 1
        elif intent.kind == "move":
            self._sink.move_relative(intent.dx, intent.dy)
            self.moves += 1

    def _fail(self, reason: str, *, quiet: bool = False) -> None:
        self.fault = reason
        if not quiet and not self._complained:
            self._complained = True
            log.warning("Vocal Joystick stopped: %s", reason, exc_info=True)
        if not self._use_thread:
            # No worker to hand the stop to; the inline path is the test path.
            self._recorder = None

    def _reset_locked(self) -> None:
        self._tracker.reset()
        self._driver.reset()
        self._dropped = False


@dataclass
class VocalJoystickRuntime:
    """What the daemon holds: a runner (or the reason there is none) and the toggle surface."""

    runner: VocalJoystickRunner | None = None
    #: Why there is no runner, or ``""``.
    reason: str = ""
    #: A caveat on a runner that *is* built (clicks held off), or ``""``.
    notice: str = ""

    @property
    def available(self) -> bool:
        return self.runner is not None

    def command(self, action: str) -> dict[str, object]:
        """``status | pause | resume`` -- reached through the ``handsfree`` IPC, not its own."""
        runner = self.runner
        if runner is None:
            if action == "status":
                return {"ok": True, "active": False, "reason": self.reason}
            return {"ok": False, "reason": self.reason or "the Vocal Joystick is not running"}
        if action == "status":
            return {"ok": True, "active": runner.active, "fault": runner.fault,
                    "notice": self.notice}
        if action == "pause":
            runner.stop()
            return {"ok": True}
        if action == "resume":
            ok, reason = runner.start()
            return {"ok": ok, "reason": reason}
        return {"ok": False, "reason": f"unknown action {action!r}"}

    def toggle(self, action: str, scope: list[str], reasons: list[str]) -> bool:
        """``handsfree pause|resume`` for this feature: add to ``scope`` or ``reasons``.

        The daemon's ``handsfree`` IPC calls this, so the CLI, the settings panel and the spoken
        stop phrase all reach it through one path. False only when a resume failed.
        """
        reply = self.command(action)
        if reply.get("ok"):
            if self.runner is not None:
                scope.append("Vocal Joystick")
            return True
        reasons.append(f"Vocal Joystick: {reply.get('reason') or 'would not start'}")
        return False

    def stop(self) -> None:
        if self.runner is not None:
            self.runner.close()


def build_vocaljoystick(
    config: Any,
    *,
    pointer_factory: Callable[[], PointerSink] | None,
    recorder_factory: Callable[[Callable[[np.ndarray], None]], _Recorder],
    sample_rate: int = 16000,
    busy: Callable[[], bool] = lambda: False,
    safety: _Gate | None = None,
    thread: bool = True,
) -> VocalJoystickRuntime:
    """The Vocal Joystick for ``[vocaljoystick]``, or a runtime that says why there is none.

    Building opens no microphone. It does open the pointer sink, as the Head-Pointer does,
    so a backend that cannot be had is known at start-up rather than on the first hum.
    """
    if not getattr(config, "enabled", False):
        return VocalJoystickRuntime()
    if pointer_factory is None:
        return VocalJoystickRuntime(reason="this platform has no pointer backend yet")
    try:
        sink = pointer_factory()
    except Exception as exc:
        return VocalJoystickRuntime(reason=f"no pointer output: {type(exc).__name__}: {exc}"[:200])
    caps = sink.capabilities()
    if not caps.relative_motion:
        try:
            sink.close()
        except Exception:
            log.debug("closing an unusable pointer sink raised", exc_info=True)
        return VocalJoystickRuntime(
            reason=f"pointer backend {caps.backend!r} cannot move the pointer relatively"
        )
    clicks = caps.supports_button(PointerButton.LEFT)
    notice = "" if clicks else f"clicks are off: backend {caps.backend!r} has no left button"
    runner = VocalJoystickRunner(
        sink,
        recorder_factory=recorder_factory,
        sample_rate=sample_rate,
        max_speed=_num(getattr(config, "max_speed", None), 20.0),
        click_pitch=_num(getattr(config, "click_pitch", None), 250.0),
        clicks=clicks,
        busy=busy,
        safety=safety,
        thread=thread,
    )
    return VocalJoystickRuntime(runner=runner, notice=notice)
