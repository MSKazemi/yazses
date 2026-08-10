"""StreamingInjector — tracks partial text cursor for correction-on-commit (ADR-004).

Usage:
    si = StreamingInjector(injector)
    si.inject_partial("hel")    # injects "hel", _chars_injected = 3
    si.inject_partial("lo ")    # injects "lo ", _chars_injected = 6
    si.commit("hello world")    # Shift+Left ×6, then inject "hello world"
    # or:
    si.cancel()                 # backspace ×6 to remove partial

Thread safety matters here and is not incidental. ``inject_partial`` is driven
from the daemon's ``partial-poll`` background thread while ``commit``/``cancel``
run on the hold-release path, so the two genuinely race: hold-end could read the
character count, and *then* an in-flight partial could land and type more text.
The correction would then select a span computed before that text existed and
delete whatever sat next to it. Every mutation therefore happens under one lock,
held across the injection itself, and a committed injector is **sealed** so a
late partial becomes a no-op rather than typing after the final text.
"""
from __future__ import annotations

import logging
import threading

from yazses.platform.base import InjectorBackend

log = logging.getLogger(__name__)


class StreamingInjector:
    """Wraps an InjectorBackend with cursor-tracking for streaming correction."""

    def __init__(self, injector: InjectorBackend) -> None:
        self._injector = injector
        self._chars_injected: int = 0
        # Held across the subprocess call, not merely around the counter: the
        # point is that a partial and a commit must never be typing at once.
        self._lock = threading.RLock()
        self._sealed = False

    @property
    def chars_injected(self) -> int:
        with self._lock:
            return self._chars_injected

    @property
    def sealed(self) -> bool:
        """True once commit/cancel ran — further partials are refused."""
        with self._lock:
            return self._sealed

    def inject_partial(self, text: str) -> None:
        """Inject partial text and track character count.

        A no-op once the injector is sealed. Silently dropping a partial is
        correct: by then the final text is already being typed, so this text is
        both stale and actively harmful.
        """
        if not text:
            return
        with self._lock:
            if self._sealed:
                log.debug("Dropping partial after commit: %r", text)
                return
            self._injector.inject(text)
            self._chars_injected += len(text)

    def commit(self, final_text: str) -> None:
        """Select all partial text (Shift+Left ×N) and replace with final_text.

        If _chars_injected is 0, just injects final_text directly. Seals the
        injector, so a partial still in flight on the poll thread cannot append
        text behind the correction.
        """
        with self._lock:
            self._sealed = True
            pending = self._chars_injected
            self._chars_injected = 0
            if pending > 0:
                # Select all injected partial characters
                self._injector.inject_key_sequence(["shift+Left"] * pending)
            self._injector.inject(final_text)

    def cancel(self) -> None:
        """Remove all partial text by injecting backspaces."""
        with self._lock:
            self._sealed = True
            pending = self._chars_injected
            self._chars_injected = 0
            if pending > 0:
                self._injector.inject_backspaces(pending)

    def reset(self) -> None:
        """Reset counter without injecting anything (e.g. after error).

        Also unseals: this is the "pretend nothing happened" hook, so an injector
        put back into service must accept partials again.
        """
        with self._lock:
            self._chars_injected = 0
            self._sealed = False
