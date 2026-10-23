"""Run Vocal Morse: own a level-only microphone stream and type what it decodes (#164).

The thin, impure shell around the pure chain ``mode.MorseMode`` -> ``segment.MorseStream``
-> ``decode.MorseDecoder``. It owns what those must not: a **microphone stream**, a
**worker thread**, a **clock**, and the callbacks into the daemon (type text, say the
mode changed). It imports no audio library and no platform API itself — the daemon hands
it a ``recorder_factory`` and an ``inject`` callable, exactly as the Vocal Joystick does.

**Off by default, and only a level ever leaves the audio callback.** Nothing is built
while ``[morsevox]`` is off. When it is on, the stream callback reduces each chunk to one
number, ``mean(|samples|)`` — the metric the daemon's VAD gate and overlay already use —
and drops the audio. No sample is kept, written or decoded by speech-to-text: Morse mode
never invokes STT, and the hum that enters it is not a recording.

**When the microphone is open.** With the long-hum trigger on (``entry_hum_s > 0``, the
shipped value) the stream opens when the daemon starts and stays open, because a user who
cannot press a key has to be heard to start; ``yazses handsfree pause`` (and the spoken
stop phrase) closes it and ``handsfree resume`` reopens it. With ``entry_hum_s = 0`` the
stream opens only when the spoken "morse mode" command enters the mode, and closes again
when the mode ends. The audio device monitor briefly closes and reopens the listening
stream for a device re-scan (``release_mic_for_rescan`` / ``reacquire_mic_after_rescan``),
never while Morse mode is on and audio is arriving, so an unplugged or switched microphone
is noticed while the hum entry listens.

**It never competes with dictation.** ``busy()`` is asked for every chunk; while it is
true (a hold-to-talk recording, a meeting) the hum is not listened for and an active Morse
mode ends — the user reached for the other input.

**A failure stops Morse, never dictation.** An injection error is logged once and the
mode carries on; any other error in the per-chunk path faults the runner and closes the
stream (``status()`` says why, and ``handsfree resume`` restarts it).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np

from yazses.audio.device_monitor import ENGAGED_AUDIO_FRESH_S, audio_is_live
from yazses.morsevox.mode import ModeConfig, ModeStep, MorseMode, resolve

__all__ = ["MorseRunner", "build_morse_runner"]

log = logging.getLogger(__name__)

#: Level samples the worker may fall behind by before new ones are dropped. Each is two
#: floats carrying its own timestamp, so a late sample is still decoded at the right time;
#: a dropped one can split a dash. Generous for that reason (~40 s of 20 ms chunks).
_QUEUE_SAMPLES = 2048


class _Recorder(Protocol):
    def start(self) -> None: ...

    def stop(self) -> Any: ...


class MorseRunner:
    """Holds the level stream and the mode, and types what the mode decodes.

    :meth:`process` is the whole per-sample path and is public so a test drives it by
    hand with its own timestamps; with ``thread=True`` the stream callback only computes
    the level and enqueues it, and a worker calls :meth:`process`.
    """

    def __init__(
        self,
        config: ModeConfig,
        *,
        recorder_factory: Callable[[Callable[[np.ndarray], None]], _Recorder],
        inject: Callable[[str], None],
        busy: Callable[[], bool] = lambda: False,
        stop_requested: Callable[[], bool] | None = None,
        on_change: Callable[[bool, str], None] | None = None,
        on_level: Callable[[float], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        thread: bool = True,
        engaged_fresh_s: float = ENGAGED_AUDIO_FRESH_S,
    ) -> None:
        self._mode = MorseMode(config)
        self._recorder_factory = recorder_factory
        self._inject = inject
        self._busy = busy
        self._stop_requested = stop_requested
        self._on_change = on_change
        self._on_level = on_level
        self._clock = clock
        self._use_thread = thread
        #: `[audio] level_stream_fresh_s`: how recent audio must be for Morse mode to count
        #: as in use and hold a device re-scan off.
        self._engaged_fresh_s = float(engaged_fresh_s)
        self._lock = threading.RLock()
        self._recorder: _Recorder | None = None
        self._queue: queue.Queue[tuple[float, float] | None] = queue.Queue(maxsize=_QUEUE_SAMPLES)
        self._worker: threading.Thread | None = None
        #: Set by an explicit pause (`handsfree pause`); cleared by `resume`.
        self._paused = False
        #: When the stream last delivered a chunk (``clock`` time, seconds), or None.
        self._last_audio_at: float | None = None
        #: Set when a device re-scan closed the stream; any other stop clears it.
        self._rescan_hold = False
        self._inject_complained = False
        self.fault = ""
        self.typed_chars = 0

    # ------------------------------------------------------------------ facts

    @property
    def config(self) -> ModeConfig:
        return self._mode.config

    @property
    def listens_for_hum(self) -> bool:
        return self._mode.config.hum_entry

    @property
    def mic_open(self) -> bool:
        return self._recorder is not None

    @property
    def active(self) -> bool:
        return self._mode.active

    # The device monitor's `LevelStreamOwner` surface (audio/device_monitor.py).

    @property
    def mic_engaged(self) -> bool:
        """Morse mode is on and the stream is still delivering: defer a device re-scan.

        Listening for the entry hum is *not* engaged -- that is the state the stream sits in
        all session, and a re-scan cutting a hum short costs one retry. A stream that stopped
        delivering (the microphone was unplugged mid-letter) is not engaged either, so a
        mode frozen by the silence cannot hold the re-scan off.
        """
        return (
            self._recorder is not None
            and self._mode.active
            and audio_is_live(self._last_audio_at, float(self._clock()), self._engaged_fresh_s)
        )

    def release_mic_for_rescan(self) -> bool:
        """Close the stream so the device monitor can re-init PortAudio. Never raises.

        True when a stream was open and is now closed. Like any stop it ends an active Morse
        mode; the monitor asks only while :attr:`mic_engaged` is false, bar its backstop.
        """
        return self._close(rescan=True)

    def reacquire_mic_after_rescan(self) -> tuple[bool, str]:
        """Reopen a stream :meth:`release_mic_for_rescan` closed. Never raises.

        Reopens nothing when anything else closed the stream since (``handsfree pause``,
        the spoken stop phrase, a fault, shutdown), while paused or under the hands-free
        gate's stop, or without the hum trigger (that stream existed only for a mode the
        close has ended).
        """
        with self._lock:
            if not self._rescan_hold:
                return True, ""
            self._rescan_hold = False
            if self._paused or self._stop_flag() or not self.listens_for_hum:
                return True, ""
            return self._open()

    def status(self) -> dict[str, object]:
        """Privacy-safe state for `yazses status`: names, flags and a count, never text."""
        with self._lock:
            return {
                "active": self._mode.active,
                "state": self._mode.state,
                "entered_by": self._mode.entered_by,
                "listening": self.mic_open,
                "hum_entry": self.listens_for_hum,
                "paused": self._paused,
                "fault": self.fault,
                "typed_chars": self.typed_chars,
            }

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> tuple[bool, str]:
        """Start listening for the entry hum (no-op without the hum trigger). Never raises."""
        if not self.listens_for_hum:
            return True, ""
        return self._open()

    def enter_by_command(self) -> tuple[bool, str]:
        """The spoken "morse mode": open the stream if needed and enter. Never raises."""
        with self._lock:
            if self._paused or self._stop_flag():
                return False, "hands-free input is paused — run `yazses handsfree resume`"
            if self._mode.active:
                return True, "already in Morse mode"
            ok, reason = self._open()
            if not ok:
                return False, reason
            step = self._mode.enter(self._now_ms(), "command")
        self._report(step)
        return True, ""

    def stop(self) -> None:
        """Close the stream, end the mode, stop the worker. Idempotent; never raises."""
        self._close(rescan=False)

    def _close(self, *, rescan: bool) -> bool:
        with self._lock:
            step = self._mode.exit(self._now_ms(), "stopped")
            recorder, self._recorder = self._recorder, None
            worker, self._worker = self._worker, None
            # Under the lock, so a pause racing a re-scan always wins: any stop that is
            # not a re-scan cancels a pending reopen.
            self._rescan_hold = rescan and recorder is not None
        self._report(step)
        if recorder is not None:
            try:
                recorder.stop()
            except Exception:
                log.debug("Vocal Morse stream stop raised", exc_info=True)
        if worker is not None:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass  # a full queue still ends it: the recorder is cleared, so the worker returns at its next item
            if worker is not threading.current_thread():
                worker.join(timeout=2.0)
        return recorder is not None

    def toggle(self, action: str, scope: list[str], reasons: list[str]) -> bool:
        """``handsfree pause|resume`` for Vocal Morse: add to ``scope`` or ``reasons``.

        The daemon's ``handsfree`` IPC calls this, so the CLI, the settings panel and the
        spoken stop phrase reach it through one path. False only when a resume failed.
        """
        if action == "pause":
            was_open = self.mic_open
            self._paused = True
            self.stop()
            if was_open:
                scope.append("Vocal Morse")
            return True
        if action == "resume":
            self._paused = False
            self.fault = ""
            if not self.listens_for_hum:
                return True  # nothing to reopen: the spoken command opens the stream itself
            ok, reason = self.start()
            if ok:
                scope.append("Vocal Morse (listening for the entry hum)")
                return True
            reasons.append(f"Vocal Morse: {reason or 'would not start'}")
            return False
        return True

    # ------------------------------------------------------------------ the audio path

    def _open(self) -> tuple[bool, str]:
        with self._lock:
            if self._recorder is not None:
                return True, ""
            if self._paused:
                return False, "paused"
            self.fault = ""
            self._rescan_hold = False  # opened by anyone: a pending re-scan reopen is moot
            self._queue = queue.Queue(maxsize=_QUEUE_SAMPLES)
            try:
                recorder = self._recorder_factory(self._on_chunk)
                recorder.start()
            except Exception as exc:
                log.warning("Vocal Morse could not open the microphone", exc_info=True)
                return False, f"could not open the microphone: {type(exc).__name__}"
            self._recorder = recorder
            if self._use_thread and self._worker is None:
                self._worker = threading.Thread(
                    target=self._work, args=(self._queue,), name="morsevox", daemon=True
                )
                self._worker.start()
            return True, ""

    def _on_chunk(self, chunk: np.ndarray) -> None:
        """The stream callback: reduce to one level, timestamp it, hand it on. Audio is dropped."""
        t_ms = self._now_ms()
        self._last_audio_at = t_ms / 1000.0
        level = float(np.abs(chunk).mean()) if chunk.size else 0.0
        if not self._use_thread:
            self.process(t_ms, level)
            return
        try:
            self._queue.put_nowait((t_ms, level))
        except queue.Full:
            pass  # a stalled worker loses samples; the mode copes with a gap in time

    def _work(self, q: queue.Queue[tuple[float, float] | None]) -> None:
        while True:
            item = q.get()
            if item is None or self._recorder is None:
                return
            self.process(*item)
            if self.fault:
                threading.Thread(target=self.stop, name="morsevox-stop", daemon=True).start()
                return

    def process(self, t_ms: float, level: float) -> None:
        """One level sample: gate, step the mode, type, report. Never raises."""
        if self.fault:
            return
        try:
            with self._lock:
                busy = self._safe_busy()
                if self._stop_flag():
                    step = self._mode.exit(t_ms, "paused")
                    if not step.exited:
                        step = self._mode.push(t_ms, level, busy=True)
                else:
                    step = self._mode.push(t_ms, level, busy=busy)
                active = self._mode.active
            if step.text:
                self._type(step.text)
            self._report(step)
            if active and self._on_level is not None:
                self._on_level(level)
            if step.exited and not self.listens_for_hum and self._recorder is not None:
                # Entered by command only: the stream was opened for this mode; close it.
                self._close_after_exit()
        except Exception as exc:
            self.fault = f"runtime error: {type(exc).__name__}"
            log.warning("Vocal Morse stopped: %s", self.fault, exc_info=True)
            if not self._use_thread:
                self._recorder = None

    def _close_after_exit(self) -> None:
        with self._lock:
            recorder, self._recorder = self._recorder, None
            worker, self._worker = self._worker, None
            self._rescan_hold = False
        if worker is not None:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass  # a full queue still ends it: the recorder is cleared, so the worker returns at its next item
        if recorder is not None:
            # Never stop a stream from inside its own callback: hand it to a thread.
            def _stop() -> None:
                try:
                    recorder.stop()
                except Exception:
                    log.debug("Vocal Morse stream stop raised", exc_info=True)

            if self._use_thread:
                threading.Thread(target=_stop, name="morsevox-close", daemon=True).start()
            else:
                _stop()

    def _type(self, text: str) -> None:
        try:
            self._inject(text)
            self.typed_chars += len(text)
        except Exception:
            if not self._inject_complained:
                self._inject_complained = True
                log.warning("Vocal Morse could not type a decoded character", exc_info=True)

    def _report(self, step: ModeStep) -> None:
        if self._on_change is None:
            return
        try:
            if step.entered:
                self._on_change(True, step.entered)
            if step.exited:
                self._on_change(False, step.exited)
        except Exception:
            log.debug("Vocal Morse mode-change callback raised", exc_info=True)

    def _safe_busy(self) -> bool:
        try:
            return bool(self._busy())
        except Exception:
            return True  # when in doubt, do not act on sound

    def _stop_flag(self) -> bool:
        if self._stop_requested is None:
            return False
        try:
            return bool(self._stop_requested())
        except Exception:
            log.debug("Vocal Morse stop check raised; treating it as a stop", exc_info=True)
            return True

    def _now_ms(self) -> float:
        return float(self._clock()) * 1000.0


def build_morse_runner(
    config: Any,
    *,
    threshold: float,
    recorder_factory: Callable[[Callable[[np.ndarray], None]], _Recorder],
    inject: Callable[[str], None],
    busy: Callable[[], bool] = lambda: False,
    stop_requested: Callable[[], bool] | None = None,
    on_change: Callable[[bool, str], None] | None = None,
    on_level: Callable[[float], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    thread: bool = True,
    engaged_fresh_s: float = ENGAGED_AUDIO_FRESH_S,
) -> tuple[MorseRunner | None, list[str]]:
    """The runner for ``[morsevox]``, or None, plus every note worth logging. Never raises.

    ``threshold`` is the voice threshold the hum and the pulses are judged against (the
    daemon passes ``[accessibility] vad_threshold``). Building opens no microphone.
    """
    if not getattr(config, "enabled", False):
        return None, []
    mode_cfg, notes = resolve(
        getattr(config, "entry_hum_s", None),
        getattr(config, "exit_silence_s", None),
        threshold,
        dot_max_ms=getattr(config, "dot_max_ms", 200.0),
        letter_gap_ms=getattr(config, "letter_gap_ms", 600.0),
        word_gap_ms=getattr(config, "word_gap_ms", 1400.0),
    )
    if mode_cfg is None:
        return None, notes
    runner = MorseRunner(
        mode_cfg,
        recorder_factory=recorder_factory,
        inject=inject,
        busy=busy,
        stop_requested=stop_requested,
        on_change=on_change,
        on_level=on_level,
        clock=clock,
        thread=thread,
        engaged_fresh_s=engaged_fresh_s,
    )
    return runner, notes
