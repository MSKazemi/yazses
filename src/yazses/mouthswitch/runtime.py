"""Run Mouth-Sound Switch Access: own a microphone while armed, scan, act on a click (#164).

The thin, impure shell around the pure chain ``detect.MouthSoundDetector`` →
``scanner.SwitchScanner``. It owns what those must not: a **microphone stream**, a **worker
thread**, an optional **pointer sink**, the **command runner** the daemon hands it, and the
**construction rules** that decide whether the feature runs at all. Shaped like
``vocaljoystick/runtime.py`` and armed the same way, through the same existing IPC.

**Single-switch scanning (owner decision, 2026-10-22).** Two of the classifier's three sounds
are used, each for one thing:

* a **lip pop** starts the scan, and a second pop stops it;
* a **tongue click** selects the item highlighted when the click *began* -- and only while a
  scan runs. With no scan running, a click does nothing at all.

``sh`` is not used: a sustained hiss is the kind most easily confused with room noise
(``detect.py``). The click is the select because it is the sound the owner named; the pop,
the other short burst, is the toggle. Starting a scan only lights the highlight, so a false
pop costs a glance; a select needs a pop *and then* a click inside a running scan, and each
click selects at most once (ADR-021: a guard is judged on how rarely it fires).

**A selection keeps the scan going (owner decision, 2026-10-23).** After a click the
highlight stays on the selected item for one dwell and then steps on, so a second click
repeats it ("scroll down", twice) without a pop in between. The scan stops on a pop, on
pause, on dictation, and after three passes with no selection, counted from the last one.

**A select comes from a detected click, never from speech.** Nothing here reads a transcript.
The detector rejects any voiced sound and any release just after speech, and while dictation
is busy (``busy()``) every chunk is dropped, the detector reset and the scan stopped.

**What a selection does is existing code.** A command item is a phrase handed to
``run_command``, which the daemon routes through ``activation/pipeline.handle_intent`` and
the ordinary command grammar and dispatcher -- the path Gesture Chords use. An item whose
command is not reversible is refused at build time (it would need a confirmation a single
switch cannot give). A pointer item is one call on the platform's existing ``PointerSink``:
``click(LEFT)`` or ``scroll(0, ±3)``.

**Seen or heard, never neither.** The overlay draws the highlight. Where it will not run (a
native Wayland session, no ``desktop`` extra), the scan is *announced* instead
(``announce.py``): an earcon cue at every step when ``[earcon]`` is on, and the item's name
spoken by the offline read-back voice when ``[tts]`` can speak. The announcement comes from
the same timeline the select-at-onset rule reads, and an item stays lit until its name has
been said, so the item announced when a click began is the item that click selects. The cue
and the name are voiced and reach the microphone through the speakers, and the detector
cannot hear a click for ``detect.CONTEXT_MS`` after a voiced sound (:func:`post_voice_deaf_s`).
So a heard step is lit for the announcement, then that deaf window, then a whole
``dwell_s`` in which a click is heard: a long name slows the scan, it never shortens the
time to click. A scan the overlay draws makes no sound, and its steps are plain
``dwell_s``.

**Dormant unless asked, and the microphone closed unless armed.** :func:`build_mouthswitch`
returns a runtime with no runner while ``[mouthswitch]`` is off (the shipped state), when
neither the overlay nor an announcement can show the highlight (a switch must never select
an item nobody can see or hear), or when no item can run on this machine. Building opens no
microphone; ``yazses handsfree resume`` opens it, and ``handsfree pause``, the spoken stop
phrase, a pause of the global hands-free gate and shutdown close it.

The detector's thresholds were tuned on synthetic signals only (``detect.py``,
``tests/test_mouthswitch_detect.py``); nothing here has been run against a real microphone.
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

from yazses.audio.device_monitor import ENGAGED_AUDIO_FRESH_S, audio_is_live
from yazses.mouthswitch import detect as detect_module
from yazses.mouthswitch.announce import ScanAnnouncer
from yazses.mouthswitch.detect import MouthSoundDetector
from yazses.mouthswitch.scanner import ScanItem, SwitchScanner, parse_scan_items, scan_interval
from yazses.pointer.base import PointerButton, PointerError, PointerSink

__all__ = [
    "SOURCE_NAME",
    "SWITCH_ACTIONS",
    "MouthSwitchRunner",
    "MouthSwitchRuntime",
    "build_mouthswitch",
    "command_refusal",
    "notify_mouthswitch_fault",
    "post_voice_deaf_s",
]

log = logging.getLogger(__name__)

#: The name a command reaches the activation policy under (logs, a confirmation prompt).
SOURCE_NAME = "mouthswitch"
#: Sound kind → switch action for single-switch scanning. ``sh`` is deliberately absent.
SWITCH_ACTIONS: dict[str, str] = {"pop": "toggle", "click": "select"}

#: Chunks the worker may fall behind by before it drops audio (and resets the detector, so a
#: gap is never measured as part of a sound).
_QUEUE_CHUNKS = 32


class _Recorder(Protocol):
    def start(self) -> None: ...

    def stop(self) -> Any: ...


class _Detector(Protocol):
    def feed(self, chunk: Any) -> list[Any]: ...

    def reset(self) -> None: ...


def post_voice_deaf_s() -> float:
    """Seconds after a voiced sound ends during which the detector cannot hear a click.

    The detector rejects a click when the ``CONTEXT_MS`` of audio before its onset holds
    voiced frames (``detect.py``, "not after speech"). A heard scan's cue and spoken name are
    voiced, so that window follows every announcement. Read from the detector each time,
    never restated here, so the scan's timing and the detector's guard cannot drift apart.
    """
    return float(detect_module.CONTEXT_MS) / 1000.0


def command_refusal(label: str, classify: Callable[[str], object]) -> str:
    """Why the command phrase ``label`` cannot be a scan item, or ``""`` when it can.

    It must classify as a command (not dictation) in the existing grammar, and its action
    must be one the activation policy runs without confirmation. ``classify`` is injected.
    """
    from yazses.activation.confirm import Consequence, classify_consequence

    try:
        command = classify(label)
    except Exception as exc:
        return f"the command grammar raised {type(exc).__name__}"
    action = getattr(command, "action", "") or ""
    intent = getattr(getattr(command, "intent", None), "name", "")
    if command is None or not action or intent == "DICTATE":
        return "not a command the grammar knows"
    if classify_consequence(action) is not Consequence.REVERSIBLE:
        return f"{action!r} needs a confirmation, which a single switch cannot give"
    return ""


class MouthSwitchRunner:
    """Holds the microphone stream while armed; turns mouth sounds into a scan and actions.

    :meth:`process` is the whole per-chunk path and is public so a test drives it by hand;
    with ``thread=True`` the stream's callback only enqueues and a worker calls it.
    """

    def __init__(
        self,
        items: list[ScanItem],
        *,
        recorder_factory: Callable[[Callable[[np.ndarray], None]], _Recorder],
        run_command: Callable[[str], object],
        sink: PointerSink | None = None,
        sample_rate: int = 16000,
        interval_s: float = 1.2,
        busy: Callable[[], bool] = lambda: False,
        stop_requested: Callable[[], bool] | None = None,
        on_fault: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        detector: _Detector | None = None,
        thread: bool = True,
        announcer: ScanAnnouncer | None = None,
        engaged_fresh_s: float = ENGAGED_AUDIO_FRESH_S,
    ) -> None:
        self._sink = sink
        self._recorder_factory = recorder_factory
        self._run_command = run_command
        self._sample_rate = int(sample_rate)
        self._busy = busy
        self._stop_requested = stop_requested
        self._on_fault = on_fault
        self._clock = clock
        self._use_thread = thread
        #: `[audio] level_stream_fresh_s`: how recent audio must be for a running scan to
        #: count as in use and hold a device re-scan off.
        self._engaged_fresh_s = float(engaged_fresh_s)
        self._detector: _Detector = detector if detector is not None else MouthSoundDetector(
            self._sample_rate, actions=SWITCH_ACTIONS
        )
        #: Speaks / cues each step when the overlay cannot draw it; None when it can.
        self._announcer = announcer
        #: ``(scan generation, step)`` last announced, so each step is announced once.
        self._announced: tuple[int, int] | None = None
        self._scanner = SwitchScanner(
            items, interval_s,
            announce_s=announcer.announcement_s if announcer is not None else None,
            # Heard, not seen: every step also waits out the detector's post-voice
            # deafness, or part of each step could never hear the click meant for it.
            post_voice_s=post_voice_deaf_s() if announcer is not None else 0.0,
        )
        #: Guards the scanner: the worker moves it, the status IPC reads it.
        self._scan_lock = threading.Lock()
        self._lock = threading.Lock()
        self._recorder: _Recorder | None = None
        self._queue: queue.Queue[tuple[np.ndarray, float] | None] = queue.Queue(
            maxsize=_QUEUE_CHUNKS
        )
        self._worker: threading.Thread | None = None
        self._dropped = False
        self._complained = False
        self._stop_seen = False
        #: Samples fed to the detector since its last reset: its event times count from there.
        self._fed = 0
        #: When the stream last delivered a chunk (``clock`` time), or None.
        self._last_audio_at: float | None = None
        #: Set when a device re-scan closed the stream; any other stop clears it.
        self._rescan_hold = False
        self.fault = ""
        self.selections = 0
        self.last_selected = ""

    @property
    def active(self) -> bool:
        return self._recorder is not None

    @property
    def engaged(self) -> bool:
        """A scan is running on a stream that is still delivering audio.

        The device monitor defers a re-scan while this is true, so the stream is never
        closed under a highlight the user is waiting on. A stream that stopped delivering
        (the microphone was unplugged) is not engaged, so it cannot hold the re-scan off.
        """
        if self._recorder is None:
            return False
        now = self._clock()
        with self._scan_lock:
            scanning = self._scanner.view(now).scanning
        return scanning and audio_is_live(self._last_audio_at, now, self._engaged_fresh_s)

    @property
    def items(self) -> tuple[ScanItem, ...]:
        return self._scanner.items

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> tuple[bool, str]:
        """Open the microphone and start listening. Idempotent; never raises."""
        with self._lock:
            return self._start_locked()

    def _start_locked(self) -> tuple[bool, str]:
        if self._recorder is not None:
            return True, ""
        self.fault = ""
        self._complained = False
        self._rescan_hold = False
        self._reset_audio()
        self._queue = queue.Queue(maxsize=_QUEUE_CHUNKS)
        self._stop_seen = self._stop_flag()
        try:
            recorder = self._recorder_factory(self._on_chunk)
            recorder.start()
        except Exception as exc:
            log.warning("Mouth-Sound Switch could not open the microphone", exc_info=True)
            return False, f"could not open the microphone: {type(exc).__name__}"
        self._recorder = recorder
        if self._use_thread and self._worker is None:
            self._worker = threading.Thread(
                target=self._work, args=(self._queue,), name="mouthswitch", daemon=True
            )
            self._worker.start()
        return True, ""

    def stop(self) -> None:
        """Close the microphone, stop the scan and the worker. Idempotent; never raises."""
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
            self._reset_audio()
            # Under the lock, so a pause racing a re-scan always wins: any stop that is
            # not a re-scan cancels a pending reopen.
            self._rescan_hold = rescan and recorder is not None
        self._stop_scan()
        if recorder is not None:
            try:
                recorder.stop()
            except Exception:
                log.debug("Mouth-Sound Switch stream stop raised", exc_info=True)
        if worker is not None:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass  # a full queue still ends it: the recorder is cleared, so the worker returns at its next item
            if worker is not threading.current_thread():
                worker.join(timeout=2.0)
        return recorder is not None

    def close(self) -> None:
        """Stop and release the pointer sink, if there is one. Idempotent; never raises."""
        self.stop()
        if self._announcer is not None:
            self._announcer.close()
        if self._sink is not None:
            try:
                self._sink.close()
            except Exception:
                log.debug("Mouth-Sound Switch sink close raised", exc_info=True)

    # ------------------------------------------------------------------ the audio path

    def _on_chunk(self, chunk: np.ndarray) -> None:
        """The stream callback: enqueue only (or process inline when there is no thread)."""
        now = self._clock()
        self._last_audio_at = now
        if not self._use_thread:
            self.process(chunk, now)
            return
        try:
            self._queue.put_nowait((np.array(chunk, dtype=np.float32).ravel(), now))
        except queue.Full:
            self._dropped = True

    def _work(self, q: queue.Queue[tuple[np.ndarray, float] | None]) -> None:
        while True:
            item = q.get()
            if item is None or self._recorder is None:
                return
            self.process(*item)
            if self.fault:
                # Close the stream from the worker, never from the audio callback.
                threading.Thread(target=self.stop, name="mouthswitch-stop", daemon=True).start()
                return

    def process(self, chunk: np.ndarray, now: float | None = None) -> None:
        """One chunk, which ended at ``now``: gate, detect, scan, act. Never raises."""
        if self.fault:
            return
        if now is None:
            now = self._clock()
        try:
            if self._dropped:
                self._dropped = False
                self._reset_audio()
            stop = self._stop_flag()
            began, self._stop_seen = stop and not self._stop_seen, stop
            if began:
                # A pause from any stop path the gate hears. Close the mic; resume is explicit.
                self._stop_scan()
                self._fail("paused by the hands-free gate", quiet=True)
                return
            if self._busy():
                # Dictation owns the moment: nothing it records may become a switch press.
                self._reset_audio()
                self._stop_scan(now)
                return
            samples = np.asarray(chunk, dtype=np.float32).ravel()
            self._fed += samples.size
            events = self._detector.feed(samples)
            stream_end_s = self._fed / self._sample_rate
            for event in events:
                # The event's onset in clock time: the chunk ended at `now`, and the sound
                # began `stream_end_s - t_s` seconds of audio before that end.
                onset = now - max(0.0, stream_end_s - float(event.t_s))
                self._handle(event, onset, now)
            with self._scan_lock:
                self._scanner.tick(now)
            self._announce(now)
        except PointerError as exc:
            self._fail(f"pointer output failed: {type(exc).__name__}: {exc}"[:200])
        except Exception as exc:
            self._fail(f"runtime error: {type(exc).__name__}")

    def _handle(self, event: Any, onset: float, now: float) -> None:
        action = getattr(event, "action", None)
        if action == "toggle":
            with self._scan_lock:
                scanning = self._scanner.toggle(now)
            log.info("Mouth-Sound Switch: scan %s.", "started" if scanning else "stopped")
            return
        if action != "select":
            return
        with self._scan_lock:
            item = self._scanner.select(onset, now)
        if item is None:
            log.debug("Mouth-Sound Switch: a click with no scan to select from; ignored.")
            return
        self._run(item)

    def _run(self, item: ScanItem) -> None:
        """Do what ``item`` names, through code that already exists."""
        self.selections += 1
        self.last_selected = item.label
        log.info("Mouth-Sound Switch: selected %r.", item.label)
        if item.kind == "pointer":
            sink = self._sink
            if sink is None:  # build_mouthswitch never offers a pointer item without a sink
                log.warning("Mouth-Sound Switch: %r needs a pointer backend; none.", item.label)
                return
            if item.op == "click":
                sink.click(PointerButton.LEFT)
            elif item.op == "scroll":
                sink.scroll(0.0, float(item.dy))
            return
        try:
            outcome = self._run_command(item.label)
        except Exception:
            # One command failing is not a broken switch: say so, keep listening.
            log.warning("Mouth-Sound Switch: %r raised in the command path", item.label,
                        exc_info=True)
            return
        if getattr(outcome, "executed", True) is False:
            log.warning("Mouth-Sound Switch: %r was not run (%s).", item.label,
                        getattr(outcome, "rejection", None) or getattr(outcome, "decision", ""))

    def _announce(self, now: float) -> None:
        """Announce a step the moment the scan enters it; silence the voice when it stops.

        Read from the same scanner, at the same ``now``, that :meth:`_handle` selects
        from, so what is heard is what a click selects. Never blocks: the cue is fire and
        forget and the name is handed to the announcer's own thread.
        """
        announcer = self._announcer
        if announcer is None:
            return
        with self._scan_lock:
            view = self._scanner.view(now)
            generation = self._scanner.generation
        if not view.scanning or view.item is None:
            self._silence()
            return
        key = (generation, view.step)
        if key == self._announced:
            return
        self._announced = key
        announcer.announce(view.item, first=view.index == 0)

    def _silence(self) -> None:
        """Forget the last announced step and cut any name still being said."""
        if self._announcer is not None and self._announced is not None:
            self._announced = None
            self._announcer.stop()

    # ------------------------------------------------------------------ state

    def view(self) -> dict[str, object]:
        """Privacy-safe scan state for ``status``: labels from config, an index, flags."""
        with self._scan_lock:
            view = self._scanner.view(self._clock())
            labels = [item.label for item in self._scanner.items]
        return {
            "armed": self.active,
            "scanning": view.scanning,
            "index": view.index,
            "items": labels,
            "interval_s": self._scanner.interval_s,
            "fault": self.fault,
            "selections": self.selections,
            # How the scan reaches the user without the overlay: "speech", "earcon" or "".
            "announce": self._announcer.mode if self._announcer is not None else "",
        }

    def _stop_scan(self, now: float | None = None) -> None:
        with self._scan_lock:
            self._scanner.stop(self._clock() if now is None else now)
        self._silence()

    def _reset_audio(self) -> None:
        self._detector.reset()
        self._fed = 0
        self._dropped = False

    def _stop_flag(self) -> bool:
        if self._stop_requested is None:
            return False
        try:
            return bool(self._stop_requested())
        except Exception:
            log.debug("Mouth-Sound Switch stop check raised; treating it as a stop",
                      exc_info=True)
            return True

    def _fail(self, reason: str, *, quiet: bool = False) -> None:
        self.fault = reason
        self._stop_scan()
        if not quiet and not self._complained:
            self._complained = True
            log.warning("Mouth-Sound Switch stopped: %s", reason, exc_info=True)
            if self._on_fault is not None:
                try:
                    self._on_fault(reason)
                except Exception:
                    log.debug("Mouth-Sound Switch fault notification raised", exc_info=True)
        if not self._use_thread:
            # No worker to hand the stop to; the inline path is the test path.
            self._recorder = None


def notify_mouthswitch_fault(reason: str) -> None:
    """Tell the user the switch stopped, and how to restart it. Never raises."""
    try:
        from yazses.system.notify import notify

        notify("YazSes — Mouth-Sound Switch stopped",
               f"{reason}. Run `yazses handsfree resume` to start it again.")
    except Exception:  # a notification is never load-bearing
        log.debug("Mouth-Sound Switch fault notification failed", exc_info=True)


@dataclass
class MouthSwitchRuntime:
    """What the daemon holds: a runner (or the reason there is none) and the toggle surface."""

    runner: MouthSwitchRunner | None = None
    #: Why there is no runner, or ``""``.
    reason: str = ""
    #: Items dropped at build time and why, or ``""``.
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
        """A scan is running: the device monitor defers a re-scan."""
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
            return {"ok": False, "reason": self.reason or "the Mouth-Sound Switch is not running"}
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

        False only when a resume failed. A runtime that was never built (the feature on,
        but no overlay, say) answers a resume with its reason, so the user learns why.
        """
        was_open = self.mic_open
        reply = self.command(action)
        if reply.get("ok"):
            if action == "resume" and self.runner is not None:
                scope.append("Mouth-Sound Switch")
            elif action == "pause" and was_open:
                scope.append("Mouth-Sound Switch")
            return True
        if action == "pause":
            return True  # nothing was running; a pause of nothing is not a failure
        reasons.append(f"Mouth-Sound Switch: {reply.get('reason') or 'would not start'}")
        return False

    def status_payload(self) -> dict[str, object] | None:
        """The scan state for ``status`` (the overlay draws it), or None with no runner."""
        if self.runner is None:
            return None
        payload = self.runner.view()
        if self.notice:
            payload["notice"] = self.notice
        return payload

    def stop(self) -> None:
        if self.runner is not None:
            self.runner.close()


def build_mouthswitch(
    config: Any,
    *,
    pointer_factory: Callable[[], PointerSink] | None,
    recorder_factory: Callable[[Callable[[np.ndarray], None]], _Recorder],
    run_command: Callable[[str], object],
    classify: Callable[[str], object],
    highlight_available: bool,
    announcer: ScanAnnouncer | None = None,
    sample_rate: int = 16000,
    busy: Callable[[], bool] = lambda: False,
    stop_requested: Callable[[], bool] | None = None,
    on_fault: Callable[[str], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    thread: bool = True,
    engaged_fresh_s: float = ENGAGED_AUDIO_FRESH_S,
) -> MouthSwitchRuntime:
    """The switch for ``[mouthswitch]``, or a runtime that says why there is none.

    ``highlight_available`` is whether the overlay that draws the scan will be on screen.
    Without it, ``announcer`` (an earcon cue and/or the offline voice) makes the scan
    audible instead; with neither, there is no switch. An announcer is used only when the
    overlay is unavailable. Building opens no microphone. It opens the pointer sink only
    when a pointer item is configured, as the Vocal Joystick does, so a missing backend is
    known at start-up.
    """
    if not getattr(config, "enabled", False):
        return MouthSwitchRuntime()
    audible = announcer is not None and announcer.can_announce
    if not highlight_available and not audible:
        return MouthSwitchRuntime(
            reason="the scan highlight is drawn by the overlay, which will not run here "
            "(enable [overlay] and install the desktop extra; on a native Wayland session "
            "the overlay is not started), and neither [earcon] nor a working [tts] voice "
            "is on to announce the items instead -- a switch must never select an item you "
            "cannot see or hear"
        )
    if highlight_available:
        announcer = None
    items, notes = parse_scan_items(getattr(config, "scan_items", None))
    usable: list[ScanItem] = []
    for item in items:
        if item.kind == "command":
            why = command_refusal(item.label, classify)
            if why:
                notes.append(f"{item.label!r} dropped: {why}")
                continue
        usable.append(item)

    sink: PointerSink | None = None
    if any(item.kind == "pointer" for item in usable):
        sink, refused = _pointer_sink(pointer_factory, usable)
        for label, why in refused.items():
            notes.append(f"{label!r} dropped: {why}")
        usable = [item for item in usable if item.label not in refused]

    if not usable:
        if sink is not None:
            _close_quietly(sink)
        return MouthSwitchRuntime(
            reason="no scan item can run here" + (": " + "; ".join(notes) if notes else "")
        )
    for note in notes:
        log.warning("[mouthswitch] %s", note)
    if announcer is not None:
        log.info("[mouthswitch] no overlay here; each scan step is announced (%s).",
                 announcer.mode)
    runner = MouthSwitchRunner(
        usable,
        recorder_factory=recorder_factory,
        run_command=run_command,
        sink=sink,
        sample_rate=sample_rate,
        interval_s=scan_interval(getattr(config, "dwell_s", None)),
        busy=busy,
        stop_requested=stop_requested,
        on_fault=on_fault,
        clock=clock,
        thread=thread,
        announcer=announcer,
        engaged_fresh_s=engaged_fresh_s,
    )
    return MouthSwitchRuntime(runner=runner, notice="; ".join(notes))


def _pointer_sink(
    pointer_factory: Callable[[], PointerSink] | None, items: list[ScanItem]
) -> tuple[PointerSink | None, dict[str, str]]:
    """A sink for the pointer items, and ``{label: why}`` for each one it cannot serve."""
    pointer = [item for item in items if item.kind == "pointer"]
    if pointer_factory is None:
        return None, {item.label: "this platform has no pointer backend yet" for item in pointer}
    try:
        sink = pointer_factory()
    except Exception as exc:
        why = f"no pointer output: {type(exc).__name__}: {exc}"[:200]
        return None, {item.label: why for item in pointer}
    caps = sink.capabilities()
    refused: dict[str, str] = {}
    for item in pointer:
        if item.op == "click" and not caps.supports_button(PointerButton.LEFT):
            refused[item.label] = f"pointer backend {caps.backend!r} has no left button"
        elif item.op == "scroll" and not caps.supports_scroll(0.0, float(item.dy)):
            refused[item.label] = f"pointer backend {caps.backend!r} cannot scroll vertically"
    if len(refused) == len(pointer):
        _close_quietly(sink)
        return None, refused
    return sink, refused


def _close_quietly(sink: PointerSink) -> None:
    try:
        sink.close()
    except Exception:
        log.debug("closing an unusable pointer sink raised", exc_info=True)
