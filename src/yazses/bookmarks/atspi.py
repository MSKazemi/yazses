"""AT-SPI caret backend for session bookmarks (#162). Linux, opt-in.

`Text.caretOffset` is the true offset inside the focused element, and
`setCaretOffset` moves the caret in **one call** — which is the whole reason
bookmarks are built on it rather than on counted arrow keys.

`pyatspi` ships via system packages, not pip (`apt install python3-pyatspi
gir1.2-atspi-2.0`), so it is imported lazily and every failure returns None.
Absent accessibility support means bookmarks refuse honestly; it never means a
guess.
"""

from __future__ import annotations

import logging

from yazses.bookmarks.caret import Caret

log = logging.getLogger(__name__)


class AtspiCaret:
    """CaretBackend over AT-SPI's Text interface."""

    def _focused_text(self):
        """The focused accessible's Text interface, or None.

        Every step is guarded: the bus may be absent, the toolkit may not
        implement Text (a canvas, a terminal drawing its own cursor), and
        querying a window that just closed raises.
        """
        try:
            import pyatspi
        except Exception:
            return None
        try:
            desktop = pyatspi.Registry.getDesktop(0)
            focused = _find_focused(desktop, pyatspi)
            if focused is None:
                return None
            return focused.queryText(), _document_id(focused)
        except Exception:
            log.debug("AT-SPI caret lookup failed", exc_info=True)
            return None

    def caret(self) -> Caret | None:
        found = self._focused_text()
        if found is None:
            return None
        text, document = found
        try:
            return Caret(document=document, offset=int(text.caretOffset))
        except Exception:
            log.debug("caretOffset unavailable", exc_info=True)
            return None

    def move_to(self, caret: Caret) -> bool:
        found = self._focused_text()
        if found is None:
            return False
        text, document = found
        if document != caret.document:
            # resolve_jump already checks this; belt and braces, because moving
            # the caret in the wrong document is the failure we are avoiding.
            return False
        try:
            return bool(text.setCaretOffset(int(caret.offset)))
        except Exception:
            log.debug("setCaretOffset failed", exc_info=True)
            return False


def _document_id(accessible) -> str:
    """A stable-enough identity for "the thing being edited".

    Application name plus the toolkit's own name for the element. Not a file
    path — AT-SPI does not reliably expose one — but it distinguishes two
    windows, which is what the document check needs.
    """
    try:
        app = accessible.getApplication()
        app_name = app.name if app is not None else ""
    except Exception:
        app_name = ""
    try:
        name = accessible.name or ""
    except Exception:
        name = ""
    return f"{app_name}:{name}"


def _find_focused(desktop, pyatspi):
    """Depth-first search for the focused accessible. None when there is none."""
    try:
        for app in desktop:
            if app is None:
                continue
            for window in app:
                if window is None:
                    continue
                found = _focused_in(window, pyatspi)
                if found is not None:
                    return found
    except Exception:
        return None
    return None


def _focused_in(node, pyatspi):
    try:
        if node.getState().contains(pyatspi.STATE_FOCUSED):
            return node
        for child in node:
            if child is None:
                continue
            found = _focused_in(child, pyatspi)
            if found is not None:
                return found
    except Exception:
        return None
    return None


def build_caret_backend():
    """Return an AT-SPI caret backend, or None when it cannot work here.

    Probing with a real lookup rather than a bare import: pyatspi installs
    happily on a machine with no accessibility bus, where every call then fails.
    """
    try:
        import pyatspi  # noqa: F401
    except Exception:
        log.info("Bookmarks: pyatspi unavailable — caret positioning disabled "
                 "(apt install python3-pyatspi gir1.2-atspi-2.0).")
        return None
    backend = AtspiCaret()
    if backend.caret() is None:
        log.info("Bookmarks: AT-SPI present but no focused element reports a "
                 "caret; bookmarks will refuse until one does.")
    return backend
