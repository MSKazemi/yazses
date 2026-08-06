"""Opt-in post-dictation edit capture (signal b).

After YazSes injects dictated text, the user often fixes a misrecognition in
place ("thetext" → "the text"). YazSes cannot see that edit — it does **not**
log keystrokes (that would be invasive and violate ADR-011). The only
non-keylogging way to observe it is to ask the *editor* what the text looks like
now. :class:`EditWatcher` does exactly that: a short delay after injection it
reads the editor region back and, if it changed into a near-by correction,
records it.

The editor I/O is injected as a ``read_current_text`` callable so the diff logic
is fully unit-testable without a live editor. Currently wired to Neovim via a
``--listen`` socket; other editors can supply their own reader.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from yazses.learning.analysis import _char_distance

log = logging.getLogger(__name__)

# If the region changed more than this (char-level), the user moved on or typed
# something unrelated — not an in-place correction of what we dictated.
_MAX_CORRECTION_DISTANCE = 0.5


class EditWatcher:
    """Schedule a delayed editor read-back per dictation and detect in-place edits."""

    def __init__(
        self,
        read_current_text: Callable[[], str | None],
        # Return value is ignored, so `object` keeps this compatible with the real
        # collaborator (`CorpusWriter.update_correction_for`, which returns bool and
        # takes an optional third `signal` argument) without narrowing the contract.
        on_correction: Callable[[str, str], object],
        delay_s: float = 8.0,
        timer_factory: Callable = threading.Timer,
    ) -> None:
        self._read = read_current_text
        self._on_correction = on_correction
        self._delay = delay_s
        self._timer_factory = timer_factory
        self._timers: set = set()
        self._lock = threading.Lock()

    def watch(self, injected_text: str) -> None:
        """Schedule a read-back of the editor region we just dictated into."""
        injected = (injected_text or "").strip()
        if not injected:
            return
        timer = self._timer_factory(self._delay, self._check, [injected])
        try:
            timer.daemon = True
        except AttributeError:
            pass
        with self._lock:
            self._timers.add(timer)
        timer.start()

    def _check(self, injected: str) -> None:
        try:
            current = self._read()
        except Exception:
            log.debug("EditWatcher: editor read failed", exc_info=True)
            return
        finally:
            self._reap()
        if not current:
            return
        current = current.strip()
        if current == injected:
            return  # unchanged — nothing to learn
        dist = _char_distance(injected, current)
        if 0.0 < dist <= _MAX_CORRECTION_DISTANCE:
            log.debug("EditWatcher: in-place correction captured")
            try:
                self._on_correction(injected, current)
            except Exception:
                log.debug("EditWatcher: on_correction failed", exc_info=True)

    def _reap(self) -> None:
        with self._lock:
            self._timers = {t for t in self._timers if t.is_alive()}

    def cancel(self) -> None:
        with self._lock:
            for t in self._timers:
                t.cancel()
            self._timers.clear()


def build_neovim_reader(socket_path: str) -> Callable[[], str | None] | None:
    """Return a callable that reads the current Neovim cursor line, or ``None``
    if Neovim isn't reachable. Never raises."""
    if not socket_path:
        return None
    try:
        from yazses.commands.lsp_context import NeovimBridge
    except Exception:
        log.debug("EditWatcher: NeovimBridge unavailable", exc_info=True)
        return None
    bridge = NeovimBridge(socket_path)
    if not bridge.connect():
        log.info("EditWatcher: could not connect to Neovim at %s; edit capture disabled", socket_path)
        return None
    return bridge.read_cursor_line
