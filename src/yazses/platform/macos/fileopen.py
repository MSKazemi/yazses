"""macOS openers: LaunchServices resolves a file or a URL scheme to its registered app.

:class:`MacosFileOpener` runs ``open <path>``. :class:`MacosUrlOpener` hands a
custom-scheme URL (``claude://``, ``codex://``) to its app through ``NSWorkspace``, the
in-process API ADR-031 §3 names, so the URL -- which for "send to" is the user's
dictation -- is never a process argument. LaunchServices delivers it to the app as an
Apple Event, not on its command line.

``NSWorkspace`` comes from ``pyobjc-framework-Cocoa``, a base dependency on macOS, and is
imported lazily so this module imports on every OS. When it cannot be imported (a broken
install), the opener falls back to ``open <url>``, and then the URL *is* in that short-lived
process's argument list, readable by other local processes while it runs.

**Unverified:** this project has no Mac. Neither path has been run on macOS, and whether
``NSWorkspace.openURL_`` may be called off the main thread, as the daemon does, is not
established here.
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable

from yazses.platform.base import require_local_scheme


class MacosFileOpener:
    def open(self, path: str) -> None:
        subprocess.run(["open", path], check=True)


def _workspace_opener() -> Callable[[str], bool] | None:
    """``NSWorkspace``'s URL opener, or ``None`` when PyObjC cannot be imported."""
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
        from Foundation import NSURL  # type: ignore[import-not-found]
    except ImportError:
        return None

    def open_with_workspace(url: str) -> bool:
        nsurl = NSURL.URLWithString_(url)
        if nsurl is None:
            raise OSError("NSURL could not parse the URL")
        return bool(NSWorkspace.sharedWorkspace().openURL_(nsurl))

    return open_with_workspace


class MacosUrlOpener:
    def open_url(self, url: str) -> None:
        require_local_scheme(url)
        workspace_open = _workspace_opener()
        if workspace_open is not None:
            if not workspace_open(url):
                raise OSError("NSWorkspace did not open the URL (is an app registered for it?)")
            return
        # Fallback: one argv element, no shell, output discarded (it can quote the URL).
        result = subprocess.run(
            ["open", url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            raise OSError(f"open exited with status {result.returncode}")
