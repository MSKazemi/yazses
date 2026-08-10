"""Detect whether the focused UI element accepts text — the "text target" guard.

Dictation silently fails when you speak with no editable field focused: the transcript is
typed into a window that ignores it (or nowhere). This module answers "is there a text
target?" so the daemon can warn (yellow tray) and copy the transcript to the clipboard
instead of typing it into the wrong place.

Answer is tri-state: ``True`` (editable text focused), ``False`` (no text target), ``None``
(unknown → treat as OK, never false-alarm). Precedence: AT-SPI (reliable, opt-in) → xdotool
best-effort → ``None``. All pieces are import-guarded and injectable, so the pure logic
unit-tests without pyatspi, X11, or a running desktop.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

# AT-SPI role names (``getRoleName()``) that accept typed text even without the EDITABLE
# state (terminals, document bodies). STATE_EDITABLE is the primary signal; this backstops it.
_EDITABLE_ROLES = frozenset(
    {
        "text",
        "entry",
        "password text",
        "terminal",
        "document text",
        "document frame",
        "document web",
        "paragraph",
        "spin button",
    }
)


def is_editable_role(role_name: str, editable: bool) -> bool:
    """Whether an accessible with ``role_name`` and STATE_EDITABLE=``editable`` takes text."""
    if editable:
        return True
    return (role_name or "").strip().lower() in _EDITABLE_ROLES


class AtspiFocusTracker:
    """Background AT-SPI listener caching whether the focused element is editable text.

    Runs the pyatspi event loop on a daemon thread and updates a cached tri-state on every
    focus change, so ``has_text_target()`` is an instant read at hold-start. Entirely
    import-guarded: with no pyatspi / accessibility bus it simply never becomes available
    and the caller falls back to the xdotool heuristic.
    """

    def __init__(self) -> None:
        self._editable: bool | None = None
        self._app_class: str = ""
        self._thread: threading.Thread | None = None
        self._started = False

    @staticmethod
    def available() -> bool:
        try:
            import pyatspi  # noqa: F401
        except Exception:
            return False
        return True

    def start(self) -> bool:
        if self._started:
            return True
        try:
            import pyatspi
        except Exception as exc:
            log.debug("AT-SPI unavailable (%s); using best-effort target detection.", exc)
            return False

        def _on_focus(event) -> None:
            # state-changed:focused fires on both gain (detail1==1) and loss; only read on gain.
            if getattr(event, "detail1", 1) != 1:
                return
            try:
                src = event.source
                role = src.getRoleName()
                editable = src.getState().contains(pyatspi.STATE_EDITABLE)
                self._editable = is_editable_role(role, editable)
                try:
                    app = src.getApplication()
                    if app:
                        self._app_class = app.getName() or ""
                except Exception:
                    pass
            except Exception:
                pass  # transient AT-SPI errors must never break the listener

        def _run() -> None:
            try:
                pyatspi.Registry.registerEventListener(
                    _on_focus, "object:state-changed:focused"
                )
                pyatspi.Registry.registerEventListener(_on_focus, "focus")
                pyatspi.Registry.start()  # blocks on the GLib main loop
            except Exception as exc:
                log.debug("AT-SPI registry loop ended: %s", exc)

        self._thread = threading.Thread(target=_run, name="atspi-focus", daemon=True)
        self._thread.start()
        self._started = True
        log.info("AT-SPI focus tracker started (precise text-target detection).")
        return True

    def has_text_target(self) -> bool | None:
        return self._editable

    def get_app_class(self) -> str:
        return self._app_class

    def stop(self) -> None:
        try:
            import pyatspi

            pyatspi.Registry.stop()
        except Exception:
            pass


def xdotool_target_ok(
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    env: dict[str, str] | None = None,
) -> bool | None:
    """Best-effort (X11): ``False`` when no real window is focused, else ``None`` (unknown).

    Cannot tell whether a *field* inside a focused app has the caret — only AT-SPI can — so
    it stays conservative: it reports a definite "no target" only when there is no focused
    window at all (desktop/root), and ``None`` otherwise so we never false-alarm.
    """
    env = env if env is not None else dict(os.environ)
    if not env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
        return None  # not plain X11 → can't use xdotool reliably
    if not shutil.which("xdotool"):
        return None
    try:
        proc = runner(
            ["xdotool", "getwindowfocus", "getwindowname"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if getattr(proc, "returncode", 0) != 0:
        return False  # no focused window → nowhere to type
    name = (getattr(proc, "stdout", "") or "").strip()
    if not name:
        return False
    return None  # a window is focused; can't tell if a text field is


def xdotool_app_class(
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    env: dict[str, str] | None = None,
) -> str:
    """Best-effort (X11) get window class."""
    env = env if env is not None else dict(os.environ)
    if not env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
        return ""
    if not shutil.which("xdotool"):
        return ""
    try:
        proc = runner(
            ["xdotool", "getwindowfocus", "getwindowclassname"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    if getattr(proc, "returncode", 0) != 0:
        return ""
    return (getattr(proc, "stdout", "") or "").strip()


class TargetDetector:
    """Resolve whether there's a text target: AT-SPI first, then xdotool, then unknown."""

    def __init__(
        self,
        atspi: AtspiFocusTracker | None = None,
        xdotool_fn: Callable[[], bool | None] = xdotool_target_ok,
        xdotool_class_fn: Callable[[], str] = xdotool_app_class,
    ) -> None:
        self._atspi = atspi
        self._xdotool = xdotool_fn
        self._xdotool_class = xdotool_class_fn

    def resolve(self) -> bool | None:
        if self._atspi is not None:
            result = self._atspi.has_text_target()
            if result is not None:
                return result
        try:
            return self._xdotool()
        except Exception:
            return None

    def get_app_class(self) -> str:
        if self._atspi is not None:
            c = self._atspi.get_app_class()
            if c:
                return c
        try:
            return self._xdotool_class()
        except Exception:
            return ""
