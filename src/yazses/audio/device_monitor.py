"""Detectors for audio-input trouble: silent-clip streaks and default-device changes.

Two independent signals feed the daemon's notify + auto-heal policy:

* ``SilentStreakTracker`` — counts consecutive silent-discards. A run of them is the
  direct "dictation stopped writing" symptom (the mic switched to a wrong/quiet source).
* ``DeviceMonitor`` — a background thread that watches PortAudio's default input device
  and fires a callback when it changes, so a silent switch is never invisible.

The pure pieces (``SilentStreakTracker``, ``device_changed``, ``plan_device_poll``,
``audio_is_live``, ``DeviceMonitor.poll_once``) take injected callables and an injected
clock and hold no hardware dependency, so they unit-test without an audio backend or real
threads.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from typing import Protocol

log = logging.getLogger(__name__)


class SilentStreakTracker:
    """Counts consecutive silent-discards; any usable capture resets the streak."""

    def __init__(self) -> None:
        self._streak = 0

    @property
    def streak(self) -> int:
        return self._streak

    def record_silent(self) -> int:
        """Register one silent-discard; returns the new streak length."""
        self._streak += 1
        return self._streak

    def record_success(self) -> None:
        """A clip produced usable audio — the mic is working; clear the streak."""
        self._streak = 0

    def reset(self) -> None:
        """Clear the streak without implying a success (e.g. after auto-healing)."""
        self._streak = 0

    def should_notify(self, threshold: int) -> bool:
        return threshold > 0 and self._streak >= threshold


#: Discard reasons that *prove capture worked* rather than casting doubt on it.
#:
#: Every one of these is set **after** a transcript exists: the key was held, the
#: microphone delivered audio, the recogniser turned it into words, and a policy one
#: layer further on decided those words should not be typed here. That is a question
#: about where text goes, not about whether the microphone works — so a run of them
#: must not read as a run of silent clips.
#:
#: Found running the product (2026-08-20). Three bursts were transcribed at levels
#: 0.0057–0.0118 while the command key was held, matched no command, and were correctly
#: not typed. Because the streak's reset required a burst with *no* discard reason, none
#: of the three counted as proof, and `yazses status` went on reporting "2 silent clips
#: in a row — run `yazses audio status`" across an hour that contained three successful
#: captures. At `silent_streak_threshold` the next discard would have popped a toast and,
#: with `auto_heal_device` on, moved the capture device on that evidence.
#:
#: Deliberately **not** here: ``silent`` and ``empty`` (the two that mean no usable audio
#: arrived), ``cocktail_gated`` (dropped before any decode), and ``hallucination`` /
#: ``post_filter``. The last two produce a transcript but are themselves evidence *about*
#: the audio — the hallucination guard exists because non-speech decodes to fabricated
#: words — so treating them as proof would blind the streak to the symptom it watches for.
CAPTURE_PROVING_DISCARDS = frozenset({
    "command_unmatched",
    "command_no_text_target",
    "timeline_no_text_target",
    "revise_no_text_target",
    # "accept" was heard and decoded; the predicted suggestion was not typed because
    # no text field had focus -- the same downstream refusal as the three above.
    "predict_no_text_target",
    "no_target",
    "window_focus_no_match",
    # A layout command parsed and the window manager would not carry it out (no
    # active window, xdotool refused a step). The microphone was heard and the
    # phrase decoded well enough to match a grammar — everything that failed is
    # downstream of capture.
    "window_action_failed",
    "deixis_no_target",
    # A destructive deixis command was refused because gaze could not pick the window and
    # `[gaze] refuse_destructive_fallback` is on: heard and decoded, refused downstream.
    "deixis_gaze_unavailable",
    # A deixis command on a session where gaze can never name a window (Wayland, #418):
    # heard, decoded and parsed, then refused because no gaze target can exist there.
    "deixis_no_gaze_target",
    # A spoken capability (ADR-v2-131) produced text and a policy declined to type it:
    # the safety gate held it for a confirm, or the injector refused it. Both mean the
    # microphone was heard and decoded — the failure is downstream of capture.
    "cmdsafety_held",
    "spoken_inject_failed",
    # Field-Aware Dictation refused the *destination* (a password box). The audio was
    # captured, decoded and shaped; only the target was wrong.
    "fieldaware_refused",
    # The Voice Mouse Grid (ADR-v2-030) claimed the utterance: a grid phrase was heard,
    # decoded and parsed, whatever the pointer then did.
    "mousegrid",
})


#: The other half: discard reasons that are *not* proof the microphone is working.
#:
#: Declared rather than implied so the classification is reviewable, and so
#: ``test_every_discard_reason_is_classified`` can read the reasons out of
#: ``core/daemon.py`` itself and fail the build on one that belongs to neither set. The
#: set that must not be hand-written is the *source* set; these two are the judgement.
CAPTURE_DOUBTING_DISCARDS = frozenset({
    "silent",           # mean(|audio|) below the gate — nothing usable arrived
    "empty",            # audio decoded to no words at all
    "cocktail_gated",   # dropped before any decode; there is no transcript to trust
    "no_speech",        # loud enough, but a speech detector found none; dropped before decode
    "hallucination",    # words fabricated from non-speech — evidence *against* the audio
    "post_filter",      # the transcript was disfluency only; same doubt as above
    "acoustic_floor",   # flat room noise under the profile gate; no transcript, no proof
    "voiceguard_rejected",  # not the enrolled speaker; dropped before any decode
})


def capture_proved(discard_reason: str | None) -> bool:
    """Did this burst prove the microphone is working? Pure.

    ``None`` means the text was typed — the strongest proof there is. Anything else
    must be named in :data:`CAPTURE_PROVING_DISCARDS` to count, so a discard reason
    added later defaults to *not* proof and leaves the guard sensitive rather than
    silently widening what resets it.
    """
    if discard_reason is None or not str(discard_reason):
        return True
    return str(discard_reason) in CAPTURE_PROVING_DISCARDS


def silent_streak_advice(
    streak: int,
    *,
    active: str | None = None,
    last_good: str | None = None,
    healed: bool = False,
) -> tuple[str, list[str]]:
    """One ``(headline, remedies)`` for a run of silent clips, for every surface.

    There were three phrasings of this fault and they disagreed. `yazses status` said
    *"run `yazses audio status`"*; `yazses audio status` then said *"mic may have
    changed"* and stopped, offering **no remedy at all** -- so following the product's
    own advice chain reached a dead end. Only the desktop toast named a command, and it
    fires once, at a streak the CLI does not wait for.

    It also asserted a cause it cannot know. A silent discard is by definition
    ``mean(|audio|) < vad_threshold``, which has exactly three causes:

      1. nothing was said (the key was held early, or released late),
      2. the gate sits above this voice -- `mic-level --set` measures and moves it,
      3. capture is not receiving this microphone -- it is muted, or the wrong device.

    "Your mic may have changed" is only the third, and on a typical Linux desktop it is
    the one YazSes can least confirm: the OS default is a routing alias whose name does
    not change when the device behind it does (`devices.is_routing_alias`). `yazses audio
    status` printed that warning two lines above the guess. All three are named now, in
    the order a user can act on them, and the caller decides how many lines it can show.

    Pure: no config, no IPC, no hardware -- so both the toast and the CLI can call it.
    """
    if healed and last_good:
        headline = f"Heard nothing on {active or 'the current mic'} {streak}x in a row."
        return headline, [
            f"Switched capture back to '{last_good}' (the last one that worked).",
            "Not right?  yazses audio use <name>",
        ]
    headline = f"Heard nothing {streak}x in a row."
    return headline, [
        "Nothing was said, or the silence gate is above your voice, or capture is not "
        "getting this mic.",
        "Check the gate:   yazses mic-level --set",
        "Check the mic:    yazses audio devices   then   yazses audio use <name>",
    ]


def device_changed(prev: str | None, cur: str | None) -> bool:
    """True when the default input device meaningfully changed.

    Only reports a change between two *known* device names; a None (no baseline yet, or
    no input device) is not treated as a change, so establishing the baseline is quiet.
    """
    return bool(prev) and bool(cur) and prev != cur


# ---- Level streams: the hands-free features that hold the microphone while idle ----------
#
# Vocal Morse (listening for its entry hum -- the default whenever `[morsevox]` is on), the
# Mouth-Sound Switch and the Vocal Joystick (while armed) keep a level stream open while the
# daemon itself is IDLE. Re-initialising PortAudio closes every open stream, so the monitor
# used to treat any of them as "not idle" and skip the poll -- which, with Vocal Morse on,
# meant it never polled at all: an unplugged mic, a new default device or a Bluetooth headset
# switch went unnoticed for the whole session, and the next hold-to-talk recorded from a dead
# device. The monitor now coordinates instead (`plan_device_poll`): it reads the default
# without a re-init while the streams are open, and every `LEVEL_STREAM_RESCAN_S` (or as soon
# as that read sees a change) it asks each owner to close its stream, re-inits, and lets each
# reopen -- never while dictation records, and not while a user is in the middle of using one
# of those streams.

#: Poll actions :func:`plan_device_poll` chooses between.
SKIP = "skip"  #: touch nothing (a hold-to-talk recording is in flight)
RESCAN = "rescan"  #: re-init PortAudio and read the default (no stream is open: the old path)
PEEK = "peek"  #: read the default *without* a re-init; safe with streams open
CYCLE = "cycle"  #: close the level streams, re-init and read, reopen them

#: How often the open level streams are cycled for a full re-scan when nothing else asks for
#: one. A cycle is a short gap in a hands-free stream, so it is far rarer than the 3 s poll;
#: the PEEK in between still notices a switch on PipeWire, where the name is read through the
#: ``default`` alias by ``wpctl`` rather than from PortAudio's start-up device list.
LEVEL_STREAM_RESCAN_S = 30.0

#: The longest an owner that says it is in use can hold off a re-scan. A backstop for a
#: sound that never ends (a fan read as one endless Morse pulse), not the normal path:
#: :func:`audio_is_live` already stops a dead stream from counting as in use.
ENGAGED_DEFER_MAX_S = 600.0

#: An owner counts as "in use" only while its stream has delivered audio this recently. A
#: microphone unplugged mid-gesture stops the callbacks and freezes the gesture's state;
#: without this the frozen state would hold the re-scan off -- the very blindness fixed here.
ENGAGED_AUDIO_FRESH_S = 2.0


def audio_is_live(
    last_audio_at: float | None, now: float, fresh_s: float = ENGAGED_AUDIO_FRESH_S
) -> bool:
    """Has a stream delivered audio within ``fresh_s`` of ``now``? Pure."""
    return last_audio_at is not None and 0.0 <= now - last_audio_at <= fresh_s


def plan_device_poll(
    *,
    recording: bool,
    streams_open: bool,
    engaged: bool,
    now: float,
    last_rescan_at: float,
    engaged_since: float | None,
    rebind_pending: bool,
    can_peek: bool,
    rescan_every_s: float = LEVEL_STREAM_RESCAN_S,
    max_defer_s: float = ENGAGED_DEFER_MAX_S,
) -> str:
    """Decide what one device-monitor poll may do. Pure: every input is a value.

    * ``recording`` -- a hold-to-talk recording (anything but IDLE) is in flight. Nothing
      is touched, ever: :data:`SKIP`.
    * no level stream open -- the old path, :data:`RESCAN` (re-init, then read).
    * level streams open -- :data:`CYCLE` when one is due (``rebind_pending``: a peek saw
      the device change and the streams are still bound to the old one; or
      ``rescan_every_s`` has passed since ``last_rescan_at``) and no owner is ``engaged``.
      An engaged owner defers the cycle, for at most ``max_defer_s`` since
      ``engaged_since``. Otherwise :data:`PEEK`, or :data:`SKIP` with no peek reader.
    """
    if recording:
        return SKIP
    if not streams_open:
        return RESCAN
    due = rebind_pending or now - last_rescan_at >= rescan_every_s
    if due:
        if not engaged:
            return CYCLE
        if engaged_since is not None and now - engaged_since >= max_defer_s:
            return CYCLE
    return PEEK if can_peek else SKIP


class LevelStreamOwner(Protocol):
    """A feature that holds a microphone stream while the daemon is IDLE.

    ``mic_open``: the stream is open. ``mic_engaged``: a user is using it right now (a
    Morse mode, a scan, a held vowel) *and* audio is still arriving.
    ``release_mic_for_rescan`` closes the stream (True when it closed one) and remembers to
    reopen it; ``reacquire_mic_after_rescan`` reopens it only if nothing else -- a pause, a
    fault, a shutdown -- closed it in between. Neither raises.
    """

    @property
    def mic_open(self) -> bool: ...

    @property
    def mic_engaged(self) -> bool: ...

    def release_mic_for_rescan(self) -> bool: ...

    def reacquire_mic_after_rescan(self) -> object: ...


class DeviceMonitor:
    """Poll the default input device on a cadence and fire ``on_change`` on a change.

    Mirrors the daemon's existing poll-thread pattern (a ``threading.Event`` stop flag +
    a daemon thread). ``poll_fn`` re-initialises the audio backend and returns the current
    default input name; ``is_idle`` says whether that is safe *right now* (nothing records,
    no stream is open) and is asked immediately before every ``poll_fn``; ``on_change`` is
    called with ``(prev_name, new_name)``. Injecting all of them keeps the loop testable.

    The level-stream coordination is opt-in through ``level_streams`` (the
    :class:`LevelStreamOwner` objects), ``recording`` (a dictation is in flight: touch
    nothing), ``peek_fn`` (read the default without a re-init) and ``clock`` (monotonic).
    Without them the monitor behaves as it always has: skip unless ``is_idle``.
    """

    def __init__(
        self,
        *,
        poll_fn: Callable[[], str | None],
        is_idle: Callable[[], bool],
        on_change: Callable[[str | None, str | None], None],
        interval_s: float = 3.0,
        level_streams: Callable[[], Sequence[LevelStreamOwner | None]] | None = None,
        recording: Callable[[], bool] | None = None,
        peek_fn: Callable[[], str | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        rescan_every_s: float = LEVEL_STREAM_RESCAN_S,
        max_defer_s: float = ENGAGED_DEFER_MAX_S,
    ) -> None:
        self._poll_fn = poll_fn
        self._is_idle = is_idle
        self._on_change = on_change
        self._interval_s = interval_s
        self._level_streams = level_streams
        self._recording = recording
        self._peek_fn = peek_fn
        self._clock = clock
        self._rescan_every_s = rescan_every_s
        self._max_defer_s = max_defer_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: str | None = None
        # PortAudio was initialised about now: the daemon builds this at start-up.
        self._last_rescan_at = float(clock())
        self._engaged_since: float | None = None
        self._rebind_pending = False
        #: The action the last poll chose (one of SKIP/RESCAN/PEEK/CYCLE), for tests and logs.
        self.last_action = SKIP

    def poll_once(self) -> bool:
        """Run one poll iteration. Returns True when a change fired ``on_change``.

        Never touches the audio backend during a recording, and never re-initialises it
        under an open stream. The first successful poll establishes the baseline silently.
        See :func:`plan_device_poll` for what a poll may do while level streams are open.
        """
        try:
            owners = self._owners()
            open_owners = [o for o in owners if o.mic_open]
            engaged = any(o.mic_engaged for o in open_owners)
            if self._recording is not None:
                recording = bool(self._recording())
            else:
                recording = not self._is_idle()
            now = float(self._clock())
        except Exception as exc:
            log.debug("device poll failed: %s", exc)
            return False
        if open_owners and engaged:
            if self._engaged_since is None:
                self._engaged_since = now
        else:
            self._engaged_since = None
        action = plan_device_poll(
            recording=recording,
            streams_open=bool(open_owners),
            engaged=engaged,
            now=now,
            last_rescan_at=self._last_rescan_at,
            engaged_since=self._engaged_since,
            rebind_pending=self._rebind_pending,
            can_peek=self._peek_fn is not None,
            rescan_every_s=self._rescan_every_s,
            max_defer_s=self._max_defer_s,
        )
        self.last_action = action
        if action == SKIP:
            return False
        try:
            if action == RESCAN:
                if not self._is_idle():
                    return False
                cur = self._poll_fn()
                self._last_rescan_at = now
                self._rebind_pending = False
            elif action == PEEK:
                peek = self._peek_fn
                if peek is None:  # plan_device_poll never picks PEEK without one
                    return False
                cur = peek()
            else:
                ran, cur = self._cycle(open_owners, now)
                if not ran:
                    return False
        except Exception as exc:
            log.debug("device poll failed: %s", exc)
            return False
        changed = self._observe(cur)
        if changed and action == PEEK:
            # Seen without a re-init: the open streams are still bound to the old device.
            # Cycle them at the next poll that may.
            self._rebind_pending = True
        return changed

    def _owners(self) -> list[LevelStreamOwner]:
        if self._level_streams is None:
            return []
        return [o for o in self._level_streams() if o is not None]

    def _cycle(self, owners: list[LevelStreamOwner], now: float) -> tuple[bool, str | None]:
        """Close every open level stream, re-init and read, then reopen what was closed.

        Returns ``(ran, name)``; ``ran`` is False when the re-init could not run (a
        recording began, or a stream would not close). What was closed is reopened either
        way, and a failed attempt still counts as an attempt, so a stream that will not
        close is retried at the rescan cadence rather than on every poll.
        """
        released: list[LevelStreamOwner] = []
        self._last_rescan_at = now
        try:
            for owner in owners:
                try:
                    if owner.release_mic_for_rescan():
                        released.append(owner)
                except Exception:
                    log.debug("A level stream would not close for a device re-scan",
                              exc_info=True)
            # Asked again after the close: a hold-to-talk may have begun meanwhile, and a
            # stream that would not close must not have PortAudio re-initialised under it.
            if not self._is_idle():
                return False, None
            cur = self._poll_fn()
            self._rebind_pending = False
            log.debug("Device re-scan with %d level stream(s) briefly closed.", len(released))
            return True, cur
        finally:
            for owner in released:
                try:
                    owner.reacquire_mic_after_rescan()
                except Exception:
                    log.warning("A hands-free level stream did not reopen after a device "
                                "re-scan", exc_info=True)

    def _observe(self, cur: str | None) -> bool:
        """Compare ``cur`` with the baseline; fire ``on_change`` on a real change."""
        if device_changed(self._last, cur):
            prev = self._last
            self._last = cur
            try:
                self._on_change(prev, cur)
            except Exception:
                log.exception("Device-change handler raised")
            return True
        if cur is not None:
            self._last = cur  # keep the baseline fresh
        return False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="yazses-device-monitor"
        )
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self._interval_s)
            if self._stop.is_set():
                break
            self.poll_once()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
