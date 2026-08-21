"""The one voice timer, and the thread that fires it — ADR-v2-131.

`voicetimer/parse.py` turns "set a timer for 25 minutes" into seconds and has done
since it was written; what it never had was anything to *hold* the timer. This is
that, and it is deliberately the smallest thing that can be one:

* **One timer, not a table.** "Cancel the timer" is the only cancel phrase the
  grammar parses, so a second concurrent timer would be unreachable by voice —
  a feature the user can start and cannot stop. Setting a new one replaces the
  old and says so.
* **The scheduler is injected.** `threading.Timer` is the default, but a test
  passes a fake and asserts the whole lifecycle without a real 25-minute wait —
  and without `time.sleep`, which is how a suite acquires flakes.
* **Firing never raises.** It runs on a timer thread with no exception handler
  above it, so an exception there is silent and kills nothing but the timer. The
  notify callback is best-effort exactly like the rest of `system/notify.py`.

Daemon threads: the process must never linger at exit waiting for a timer the
user has forgotten, and a timer that is still pending at shutdown has nothing to
report to a desktop that is going away.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class TimerService:
    """Holds at most one pending voice timer."""

    def __init__(
        self,
        notify: Callable[[str], None],
        timer_factory: Callable[[float, Callable[[], None]], object] | None = None,
    ) -> None:
        self._notify = notify
        self._factory = timer_factory or self._default_factory
        self._lock = threading.Lock()
        self._pending: object | None = None

    @staticmethod
    def _default_factory(delay: float, fire: Callable[[], None]) -> object:
        timer = threading.Timer(delay, fire)
        timer.daemon = True
        return timer

    def set(self, seconds: int, message: str = "") -> bool:
        """Start a timer, replacing any pending one. True if it was started.

        A non-positive duration is refused rather than fired immediately: the
        grammar only produces one from a phrase that parsed, so zero here means
        the utterance was misheard, and an alarm going off at once is the least
        useful possible response to that.
        """
        if seconds <= 0:
            return False
        self.cancel()
        text = message or f"Timer finished ({seconds}s)."

        def fire() -> None:
            with self._lock:
                self._pending = None
            try:
                self._notify(text)
            except Exception:  # noqa: BLE001 — a timer thread has nobody to raise to
                log.debug("Voice timer notification failed", exc_info=True)

        timer = self._factory(float(seconds), fire)
        with self._lock:
            self._pending = timer
        start = getattr(timer, "start", None)
        if callable(start):
            start()
        log.info("Voice timer set for %d seconds.", seconds)
        return True

    def cancel(self) -> bool:
        """Cancel the pending timer. True if one was actually cancelled."""
        with self._lock:
            timer, self._pending = self._pending, None
        if timer is None:
            return False
        stop = getattr(timer, "cancel", None)
        if callable(stop):
            stop()
        return True

    @property
    def pending(self) -> bool:
        """Whether a timer is currently waiting to fire."""
        with self._lock:
            return self._pending is not None

    def shutdown(self) -> None:
        """Drop any pending timer. Safe to call more than once."""
        self.cancel()
