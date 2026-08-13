"""Real caret positions for session bookmarks (#162).

The first attempt (#160) counted characters YazSes had injected and jumped by
sending that many arrow keys. It cannot work, for three reasons that are worth
keeping written down because the counting approach is the obvious one:

* **The count desynchronises and never recovers.** It only tracks what *we*
  typed. A mouse click, an arrow key, a manual edit, a window switch or a soft
  wrap moves the real caret without changing the number. After the first one,
  every jump lands somewhere arbitrary — and the next dictation is inserted
  there.
* **The jump is an unbounded key injection.** The delta grows with the session,
  so a bookmark set early and jumped to later injects thousands of keypresses —
  the same shape as the ydotool flood in #153.
* **It bypasses the no-text-target guard.** `inject/target.py` exists precisely
  because the focused element may not accept text.

So a bookmark stores a position the *toolkit* reports, and jumping is one
positioning call. This module is the seam and the policy; the backends live
beside it. Everything here is pure and testable without a desktop.

A bookmark is scoped to a **document**, not a session: "offset since I started
the daemon" is not a place a user thinks in, and a jump that silently lands in a
different file is worse than no jump at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Caret:
    """Where the caret is, as the accessibility layer or editor reports it.

    ``document`` identifies the thing being edited (a file path, a buffer name,
    an accessible object id). It is compared for equality only — this layer
    never parses it.
    """

    document: str
    offset: int


class Refusal(Enum):
    """Why a bookmark operation did not happen. Never a silent wrong jump."""

    NO_BACKEND = "no caret backend available"
    NO_CARET = "the focused element does not report a caret"
    UNKNOWN_BOOKMARK = "no bookmark by that name"
    DIFFERENT_DOCUMENT = "that bookmark belongs to a different document"
    MOVE_FAILED = "the backend refused to move the caret"


@runtime_checkable
class CaretBackend(Protocol):
    """Something that can report and set the caret in the focused element.

    Implemented by AT-SPI on Linux and by the editor bridge for Neovim. Both are
    optional; when neither is present the feature refuses rather than guessing.
    """

    def caret(self) -> Caret | None:
        """The current caret, or None when nothing focused reports one."""

    def move_to(self, caret: Caret) -> bool:
        """Move the caret. True on success. One call — never N keypresses."""


def capture(backend: CaretBackend | None) -> Caret | Refusal:
    """Read the caret to store as a bookmark."""
    if backend is None:
        return Refusal.NO_BACKEND
    caret = backend.caret()
    if caret is None:
        return Refusal.NO_CARET
    return caret


def resolve_jump(
    saved: Caret | None,
    backend: CaretBackend | None,
) -> Caret | Refusal:
    """Decide whether jumping to ``saved`` is safe, without performing it. Pure.

    The document check is the load-bearing one. A stored offset stays valid when
    the user moves the caret around — that is the whole point of an absolute
    position — but it means nothing in a *different* document, where offset 400
    is simply somewhere else. Refusing there is what keeps a bookmark from
    dropping the next dictation into an unrelated file.
    """
    if backend is None:
        return Refusal.NO_BACKEND
    if saved is None:
        return Refusal.UNKNOWN_BOOKMARK
    current = backend.caret()
    if current is None:
        return Refusal.NO_CARET
    if current.document != saved.document:
        return Refusal.DIFFERENT_DOCUMENT
    return saved


def jump(saved: Caret | None, backend: CaretBackend | None) -> Caret | Refusal:
    """Resolve and perform the jump. One positioning call, or a refusal."""
    resolved = resolve_jump(saved, backend)
    if isinstance(resolved, Refusal):
        return resolved
    if not backend.move_to(resolved):      # type: ignore[union-attr]
        return Refusal.MOVE_FAILED
    return resolved
