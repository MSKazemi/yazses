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

**With the global gate on, it hears the gate's stop -- and only reads it.** When
``[handsfree_safety]`` is enabled the daemon hands the runner ``stop_requested`` (the gate's
``user_paused`` flag). A pause that *begins* while the stream is open -- including a face
switch's ``pause_pointer``, which does not go through the ``handsfree`` IPC -- closes the stream
on the next chunk. The runner is **not** a gate source: it never samples, arms or re-arms the
gate (ADR-v2-148 R-24 keeps re-arming with the human entry points), so a joystick that stopped
can never leave a stale source that would report the whole hands-free system as faulted.

**A failure stops motion, never dictation.** A pointer error or an analysis crash is logged
once, handed to ``on_fault`` (the daemon turns it into a desktop notification, so the cursor
never just stops without a word) and faults the runner; the stream is closed by the worker and
nothing moves until the next ``resume``.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from yazses.audio.device_monitor import audio_is_live
from yazses.pointer.base import PointerButton, PointerError, PointerSink
from yazses.vocaljoystick.control import VocalJoystick
from yazses.vocaljoystick.drive import PointerIntent, SustainedVowelDriver
from yazses.vocaljoystick.formants import VocalFrameTracker

__all__ = [
    "VocalJoystickRunner",
    "VocalJoystickRuntime",
    "build_vocaljoystick",
    "notify_vocaljoystick_fault",
]

log = logging.getLogger(__name__)

#: Chunks the worker may fall behind by before it drops audio (and resets, so a gap is never
#: integrated as motion). Bounded so a stalled worker cannot queue seconds of stale intent.
_QUEUE_CHUNKS = 32


class _Recorder(Protocol):
    def start(self) -> None: ...

    def stop(self) -> Any: ...


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
        stop_requested: Callable[[], bool] | None = None,
        on_fault: Callable[[str], None] | None = None,
        thread: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sink = sink
        self._recorder_factory = recorder_factory
        self._busy = busy
        self._stop_requested = stop_requested
        self._on_fault = on_fault
        self._use_thread = thread
        self._clock = clock
        #: When the stream last delivered a chunk (``clock`` time), or None.
        self._last_audio_at: float | None = None
        #: Set when a device re-scan closed the stream; any other stop clears it.
        self._rescan_hold = False
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
        #: The stop flag as last seen; only a False -> True edge closes the stream.
        self._stop_seen = False
        self.fault = ""
        self.moves = 0
        self.clicks = 0

    @property
    def active(self) -> bool:
        return self._recorder is not None

    @property
    def engaged(self) -> bool:
        """A vowel is being held (or a click confirmed) on a stream that is still delivering.

        The device monitor defers a re-scan while this is true. A stream that stopped
        delivering (the microphone was unplugged mid-vowel) is not engaged, whatever state
        the driver froze in, so it cannot hold the re-scan off.
        """
        return (
            self._recorder is not None
            and self._driver.engaged
            and audio_is_live(self._last_audio_at, self._clock())
        )

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> tuple[bool, str]:
        """Open the microphone and start acting on it. Idempotent; never raises."""
        with self._lock:
            return self._start_locked()

    def _start_locked(self) -> tuple[bool, str]:
        if self._recorder is not None:
            return True, ""
        self.fault = ""
        self._complained = False
        self._rescan_hold = False
        self._reset_locked()
        self._queue = queue.Queue(maxsize=_QUEUE_CHUNKS)
        # A stop already in force when the user resumes is not a new stop: `handsfree
        # resume` clears it right after this. Only a pause that begins later closes us.
        self._stop_seen = self._stop_flag()
        try:
            recorder = self._recorder_factory(self._on_chunk)
            recorder.start()
        except Exception as exc:
            log.warning("Vocal Joystick could not open the microphone", exc_info=True)
            return False, f"could not open the microphone: {type(exc).__name__}"
        self._recorder = recorder
        if self._use_thread and self._worker is None:
            self._worker = threading.Thread(
                target=self._work, args=(self._queue,), name="vocaljoystick", daemon=True
            )
            self._worker.start()
        return True, ""

    def stop(self) -> None:
        """Close the microphone and stop the worker. Idempotent; never raises."""
        self._close(rescan=False)

    def release_for_rescan(self) -> bool:
        """Close the stream so the device monitor can re-init PortAudio. Never raises.

        True when a stream was open and is now closed. Only a stream closed here is
        reopened by :meth:`reacquire_after_rescan`.
        """
        return self._close(rescan=True)

    def reacquire_after_rescan(self) -> tuple[bool, str]:
        """Reopen a stream :meth:`release_for_rescan` closed. Never raises.

        Reopens nothing when anything else closed the stream since -- ``handsfree pause``,
        the spoken stop phrase, a fault, shutdown -- or when the hands-free gate's stop is
        in force: a re-scan never re-arms what a user or a fault disarmed.
        """
        with self._lock:
            if not self._rescan_hold:
                return True, ""
            self._rescan_hold = False
            if self._stop_flag():
                return True, ""
            return self._start_locked()

    def _close(self, *, rescan: bool) -> bool:
        with self._lock:
            recorder, self._recorder = self._recorder, None
            worker, self._worker = self._worker, None
            self._reset_locked()
            # Under the lock, so a pause racing a re-scan always wins: any stop that is
            # not a re-scan cancels a pending reopen.
            self._rescan_hold = rescan and recorder is not None
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
        return recorder is not None

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
        self._last_audio_at = self._clock()
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
            stop = self._stop_flag()
            began, self._stop_seen = stop and not self._stop_seen, stop
            if began:
                # A pause from any stop path the gate hears. Close the mic; resume is explicit.
                self._fail("paused by the hands-free gate", quiet=True)
                return
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

    def _stop_flag(self) -> bool:
        if self._stop_requested is None:
            return False
        try:
            return bool(self._stop_requested())
        except Exception:
            log.debug("Vocal Joystick stop check raised; treating it as a stop", exc_info=True)
            return True

    def _fail(self, reason: str, *, quiet: bool = False) -> None:
        self.fault = reason
        if not quiet and not self._complained:
            self._complained = True
            log.warning("Vocal Joystick stopped: %s", reason, exc_info=True)
            if self._on_fault is not None:
                try:
                    self._on_fault(reason)
                except Exception:
                    log.debug("Vocal Joystick fault notification raised", exc_info=True)
        if not self._use_thread:
            # No worker to hand the stop to; the inline path is the test path.
            self._recorder = None

    def _reset_locked(self) -> None:
        self._tracker.reset()
        self._driver.reset()
        self._dropped = False


def notify_vocaljoystick_fault(reason: str) -> None:
    """Tell the user the Vocal Joystick stopped, and how to restart it. Never raises."""
    try:
        from yazses.system.notify import notify

        notify("YazSes — Vocal Joystick stopped",
               f"{reason}. Run `yazses handsfree resume` to start it again.")
    except Exception:  # a notification is never load-bearing
        log.debug("Vocal Joystick fault notification failed", exc_info=True)


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

    @property
    def mic_open(self) -> bool:
        """True while the runner holds a live microphone stream (the device monitor's cue)."""
        return self.runner is not None and self.runner.active

    # The device monitor's `LevelStreamOwner` surface (audio/device_monitor.py).

    @property
    def mic_engaged(self) -> bool:
        """A vowel is being steered with right now: the device monitor defers a re-scan."""
        return self.runner is not None and self.runner.engaged

    def release_mic_for_rescan(self) -> bool:
        """Close the stream for a device re-scan; True when one was closed."""
        return self.runner is not None and self.runner.release_for_rescan()

    def reacquire_mic_after_rescan(self) -> object:
        """Reopen the stream a re-scan closed, unless a pause or fault closed it since."""
        if self.runner is None:
            return True, ""
        return self.runner.reacquire_after_rescan()

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
        was_open = self.mic_open
        reply = self.command(action)
        if reply.get("ok"):
            # Name it only for what it really did: a pause of a mode that was off is no pause.
            if action == "resume" and self.runner is not None:
                scope.append("Vocal Joystick" + (f" ({self.notice})" if self.notice else ""))
            elif action == "pause" and was_open:
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
    stop_requested: Callable[[], bool] | None = None,
    on_fault: Callable[[str], None] | None = None,
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
        stop_requested=stop_requested,
        on_fault=on_fault,
        thread=thread,
    )
    return VocalJoystickRuntime(runner=runner, notice=notice)
