"""Detectors for audio-input trouble: silent-clip streaks and default-device changes.

Two independent signals feed the daemon's notify + auto-heal policy:

* ``SilentStreakTracker`` — counts consecutive silent-discards. A run of them is the
  direct "dictation stopped writing" symptom (the mic switched to a wrong/quiet source).
* ``DeviceMonitor`` — a background thread that watches PortAudio's default input device
  and fires a callback when it changes, so a silent switch is never invisible.

The pure pieces (``SilentStreakTracker``, ``device_changed``, ``DeviceMonitor.poll_once``)
take injected callables and hold no hardware or timing dependency, so they unit-test
without an audio backend or real threads.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

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


class DeviceMonitor:
    """Poll the default input device on a cadence and fire ``on_change`` on a change.

    Mirrors the daemon's existing poll-thread pattern (a ``threading.Event`` stop flag +
    a daemon thread). ``poll_fn`` returns the current default input name; ``is_idle``
    gates polling so PortAudio is never re-initialised mid-recording; ``on_change`` is
    called with ``(prev_name, new_name)``. Injecting all three keeps the loop testable.
    """

    def __init__(
        self,
        *,
        poll_fn: Callable[[], str | None],
        is_idle: Callable[[], bool],
        on_change: Callable[[str | None, str | None], None],
        interval_s: float = 3.0,
    ) -> None:
        self._poll_fn = poll_fn
        self._is_idle = is_idle
        self._on_change = on_change
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: str | None = None

    def poll_once(self) -> bool:
        """Run one poll iteration. Returns True when a change fired ``on_change``.

        Skips entirely while not idle (never touches the audio backend during a
        recording). The first successful poll establishes the baseline silently.
        """
        try:
            if not self._is_idle():
                return False
            cur = self._poll_fn()
        except Exception as exc:
            log.debug("device poll failed: %s", exc)
            return False
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
