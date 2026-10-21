"""Session bookmarks as the daemon uses them: a store, a caret backend, one message (ADR-v2-090).

`store.py` parses the phrase and holds the names; `caret.py` decides whether a jump is
safe; `atspi.py` talks to the desktop. This module is the thin seam that joins them for
a caller, so the daemon needs one lazy import and one call rather than the join.

Everything the desktop-facing part needs is injected (``backend_factory``), so the whole
service runs in a test against a fake caret. Nothing here types: a bookmark is a position
the toolkit reports, and a jump is one positioning call, never a run of arrow keys.
"""
from __future__ import annotations

from collections.abc import Callable

from yazses.bidi import wrap_user_text
from yazses.bookmarks.caret import Caret, CaretBackend, Refusal, capture, jump
from yazses.bookmarks.store import BookmarkStore


def _default_backend() -> CaretBackend | None:
    from yazses.bookmarks.atspi import build_caret_backend

    return build_caret_backend()


class BookmarkService:
    """Named caret positions for one daemon session. Never raises, never types."""

    def __init__(self, backend_factory: Callable[[], CaretBackend | None] | None = None) -> None:
        self._factory = backend_factory or _default_backend
        self._backend: CaretBackend | None = None
        self._probed = False
        self._store = BookmarkStore()

    def _caret_backend(self) -> CaretBackend | None:
        # Probed on first use, not at construction: a daemon whose user never says
        # "bookmark" must not touch the accessibility bus.
        if not self._probed:
            self._probed = True
            try:
                self._backend = self._factory()
            except Exception:
                self._backend = None
        return self._backend

    def add(self, name: str | None) -> str:
        """Bookmark the caret as ``name`` (or the next free "bookmark N"). Returns the message."""
        found = capture(self._caret_backend())
        if isinstance(found, Refusal):
            return f"Bookmark not set: {found.value}."
        label = (name or "").strip() or self._next_name()
        self._store.add(label, found)
        # The label is stored raw; only the message's copy is isolated (#516).
        return f"Bookmarked '{wrap_user_text(label)}'."

    def goto(self, name: str | None) -> str:
        """Move the caret to ``name`` (None = the most recent). Returns the message."""
        saved: Caret | None = self._store.last() if not name else self._store.goto(name)
        done = jump(saved, self._caret_backend())
        if isinstance(done, Refusal):
            return f"Did not jump: {done.value}."
        return "Jumped to " + (f"'{wrap_user_text(name)}'." if name else "the last bookmark.")

    def _next_name(self) -> str:
        n = len(self._store.names()) + 1
        while f"bookmark {n}" in self._store.names():
            n += 1
        return f"bookmark {n}"
