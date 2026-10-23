"""Which application is frontmost on macOS -- its bundle identifier only.

`Platform.focused_app_factory` on macOS. The editor command profiles
(`commands/profiles.py`) need to know whether the app in front is VS Code, a JetBrains
IDE or Sublime Text. AppKit answers that directly:
``NSWorkspace.sharedWorkspace().frontmostApplication()`` is "the frontmost app, which is
the app that receives key events", and its ``bundleIdentifier()`` is
``com.microsoft.VSCode``, ``com.jetbrains.pycharm``, ``com.sublimetext.4``. An app with no
bundle (a bare executable) has none, so ``localizedName()`` is the fallback.

The AppKit bridge (pyobjc-framework-Cocoa) is already a hard dependency on darwin, and it
is imported here lazily, inside :func:`build_macos_focused_app`, so building the platform
bundle -- or importing this module off a Mac -- touches no framework. No permission is
needed: NSWorkspace's running-application list is public to every process.

``frontmostApplication`` is kept current by workspace notifications that AppKit delivers
on the main run loop. The daemon's main thread runs one (the hotkey's ``CFRunLoopRun``),
but if the value proved stale on a real Mac that is the first thing to check.

Privacy: an identifier, never a window title or anything on screen -- the click
observer's rule of "a time and a place" and nothing more.

Untested on a real Mac: written without one, NSWorkspace is faked in
`tests/test_focused_app_provider.py`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

#: Why there is no provider when the AppKit bridge cannot be imported (a stripped or
#: broken install). Raised by :func:`build_macos_focused_app` for the daemon to log.
NO_APPKIT_REASON = (
    "the frontmost application cannot be read: the PyObjC AppKit bridge "
    "(pyobjc-framework-Cocoa) is not importable"
)


def app_identifier(app: Any) -> str:
    """The bundle id of an ``NSRunningApplication``, else its name, else ``""``. Pure.

    Never raises: a selector that is missing or fails counts as "no answer".
    """
    if app is None:
        return ""
    for selector in ("bundleIdentifier", "localizedName"):
        try:
            value = getattr(app, selector)()
        except Exception:
            continue
        if value:
            return str(value)
    return ""


class MacosFocusedApp:
    """`FocusedAppProvider` for macOS: the frontmost application's bundle identifier.

    ``workspace`` returns the shared ``NSWorkspace``; injected so the suite needs no Mac.
    """

    def __init__(self, workspace: Callable[[], Any]) -> None:
        self._workspace = workspace

    def app_id(self) -> str:
        """``"com.microsoft.VSCode"``-style identifier of the frontmost app, or ``""``."""
        try:
            app = self._workspace().frontmostApplication()
        except Exception:
            log.debug("frontmost-application lookup failed", exc_info=True)
            return ""
        return app_identifier(app)


def build_macos_focused_app() -> MacosFocusedApp:
    """The macOS provider. Raises ``RuntimeError(NO_APPKIT_REASON)`` without AppKit."""
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(NO_APPKIT_REASON) from exc
    return MacosFocusedApp(NSWorkspace.sharedWorkspace)


__all__ = ["MacosFocusedApp", "NO_APPKIT_REASON", "app_identifier", "build_macos_focused_app"]
