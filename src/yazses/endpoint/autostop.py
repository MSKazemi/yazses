"""Hands-free auto-stop decision (pure) — ADR-v2-029.

Decide when to end a tap-and-speak turn: trailing silence exceeds the timeout, or the turn
hits a hard max-duration cap. Pure and deterministic; the semantic (Smart Turn v2) refinement
lives behind the ``turn`` extra and only tightens the silence decision when present.
"""
from __future__ import annotations

import threading
from dataclasses import is_dataclass, replace
from typing import Callable

#: An end-of-turn judge for the trailing silence: ``endpoint(silence_ms)`` returns
#: ``"commit"`` (end the turn now) or ``"hold"`` (keep listening). The shape of
#: ``yazses.hesitation.stream.HesitationMonitor.decision`` (ADR-v2-101), which extends the
#: commit threshold right after a filled pause ("um...") so a thinking user is not cut off.
Endpoint = Callable[[float], str]


def should_stop(silence_ms, elapsed_ms, config) -> bool:
    """Return True when a hands-free turn should end.

    Ends when ``elapsed_ms`` reaches ``max_duration_ms`` (hard safety cap, checked first) or
    trailing ``silence_ms`` reaches ``silence_timeout_ms``. Disabled config never stops
    (caller keeps its own boundary). Pure.
    """
    if not getattr(config, "enabled", False):
        return False
    max_ms = float(getattr(config, "max_duration_ms", 30000))
    if max_ms > 0 and elapsed_ms >= max_ms:
        return True
    silence_timeout = float(getattr(config, "silence_timeout_ms", 800))
    return silence_ms >= silence_timeout


#: A press shorter than this is a *tap* (latch the recording open); longer is an ordinary
#: hold-to-talk. It mirrors ``[hotkey] hold_threshold_ms`` (the daemon passes that value),
#: so there is no second number for a user to learn.
DEFAULT_TAP_MS = 500

#: Floor on ``silence_timeout_ms``. Below ~300 ms a normal between-word pause ends the turn,
#: so a mistyped ``silence_timeout_ms = 0`` would cut every sentence after its first word.
MIN_SILENCE_TIMEOUT_MS = 300

#: How long a latched turn waits for the *first* word before giving up. The silence timeout
#: only counts after speech has been heard, otherwise "tap, think for a second, speak" would
#: end before the user began; but a stray tap must not record until the 30 s cap either.
NO_SPEECH_GRACE_MS = 5000


class AutoStopTurn:
    """Tap-to-latch state machine for hands-free dictation (ADR-v2-029). Pure.

    The hotkey backends only ever say "pressed" and "released". This sits between those two
    events and the daemon's start/end handlers and decides whether a release really ends the
    recording:

    * a press shorter than ``tap_ms`` is a tap: the release is **swallowed** and the turn is
      *latched* open, to be ended by :meth:`tick` (silence / duration cap) or a second tap;
    * a longer press is ordinary hold-to-talk and its release passes straight through, so a
      user who keeps holding the key sees exactly the behaviour they had before.

    ``endpoint``, when given, replaces the plain ``silence_timeout_ms`` comparison once speech
    has been heard (see :data:`Endpoint`). The ``max_duration_ms`` cap is still checked first
    and the no-speech grace is unchanged, so a judge that always says ``"hold"`` cannot keep a
    turn open past the cap; it can never commit inside ``MIN_SILENCE_TIMEOUT_MS`` of silence;
    and if it raises, that tick falls back to the plain threshold. With ``endpoint=None``
    (the default) :meth:`tick` is exactly the plain-threshold machine.

    Every method takes ``now`` (seconds, monotonic) so tests drive time directly. Thread-safe:
    the hotkey thread (press/release) and the watcher thread (tick) share one lock, and the
    transitions that end a turn happen under it, so a turn is ended exactly once.
    """

    def __init__(
        self, config, tap_ms: float = DEFAULT_TAP_MS, *, endpoint: Endpoint | None = None
    ) -> None:
        timeout = int(getattr(config, "silence_timeout_ms", 800))
        if is_dataclass(config) and timeout < MIN_SILENCE_TIMEOUT_MS:
            config = replace(config, silence_timeout_ms=MIN_SILENCE_TIMEOUT_MS)  # type: ignore[type-var]
        self._cfg = config
        self._endpoint = endpoint
        self._tap_s = max(float(tap_ms), 0.0) / 1000.0
        self._lock = threading.Lock()
        self._down = False
        self._pressed_at = 0.0
        self._latched = False
        self._latched_at = 0.0
        self._heard = False
        self._silent_since: float | None = None
        self._swallow_release = False

    @property
    def latched(self) -> bool:
        return self._latched

    def press(self, now: float) -> bool:
        """The hotkey went down. True = swallow it (a turn is already latched open)."""
        with self._lock:
            self._down = True
            if self._latched:
                return True
            self._pressed_at = now
            return False

    def release(self, now: float) -> bool:
        """The hotkey came up. True = swallow it (a tap just latched the turn open)."""
        with self._lock:
            if self._swallow_release:
                # The press that belonged to a turn the watcher already ended.
                self._swallow_release = False
                self._down = False
                return True
            if not self._down:
                return False  # not a key release at all (the watcher's own end call)
            self._down = False
            if self._latched:
                self._latched = False  # second tap: end the turn the ordinary way
                return False
            if (now - self._pressed_at) < self._tap_s:
                self._latched = True
                self._latched_at = now
                self._heard = False
                self._silent_since = None
                return True
            return False

    def tick(self, now: float, speech: bool) -> bool:
        """One poll of the mic. True = the turn is over; the caller ends it, once."""
        with self._lock:
            if not self._latched:
                return False
            if speech:
                self._heard = True
                self._silent_since = None
            elif self._silent_since is None:
                self._silent_since = now
            elapsed_ms = (now - self._latched_at) * 1000.0
            if self._heard:
                silence_ms = (now - self._silent_since) * 1000.0 if self._silent_since else 0.0
            else:
                silence_ms = 0.0
            if self._endpoint is None:
                stop = should_stop(silence_ms, elapsed_ms, self._cfg)
            else:
                stop = self._endpoint_stop_locked(silence_ms, elapsed_ms)
            if not stop and not self._heard and elapsed_ms >= NO_SPEECH_GRACE_MS:
                stop = True
            if stop:
                self._finish_locked()
            return stop

    def _endpoint_stop_locked(self, silence_ms: float, elapsed_ms: float) -> bool:
        """``should_stop`` with the silence comparison delegated to ``self._endpoint``."""
        cfg = self._cfg
        if not getattr(cfg, "enabled", False):
            return False
        max_ms = float(getattr(cfg, "max_duration_ms", 30000))
        if max_ms > 0 and elapsed_ms >= max_ms:
            return True
        # Before the first word ``silence_ms`` is 0 by construction and the no-speech grace
        # governs; under the floor a between-word pause would end the sentence.
        if not self._heard or silence_ms < MIN_SILENCE_TIMEOUT_MS:
            return False
        endpoint = self._endpoint
        assert endpoint is not None
        try:
            return endpoint(silence_ms) == "commit"
        except Exception:
            # The judge is an optional refinement: a fault in it must not stop hands-free
            # dictation from ending, so this tick uses the plain threshold instead.
            return should_stop(silence_ms, elapsed_ms, cfg)

    def cancel(self) -> None:
        """Drop a latched turn without ending it (the recording ended some other way)."""
        with self._lock:
            self._latched = False
            self._swallow_release = False

    def _finish_locked(self) -> None:
        self._latched = False
        # A second press may be physically down right now; its release must not end anything.
        self._swallow_release = self._down
