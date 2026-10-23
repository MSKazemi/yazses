"""Which application has the keyboard focus on Windows -- its process image name only.

`Platform.focused_app_factory` on Windows. The editor command profiles
(`commands/profiles.py`) need to know whether the window in front is VS Code, a JetBrains
IDE or Sublime Text, and on Windows the reliable answer is the file name of the process
that owns the foreground window: ``Code.exe``, ``idea64.exe``, ``sublime_text.exe``.

Two documented calls give it, both readable from a normal (medium-integrity) process:
``GetForegroundWindow`` + ``GetWindowThreadProcessId`` for the process id (reused from
`integrity.foreground_pid`, which the no-text-target guard already calls), then
``OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`` + ``QueryFullProcessImageNameW`` for
the image path. ``PROCESS_QUERY_LIMITED_INFORMATION`` is the right a normal process is
granted even on an elevated target, which is how Task Manager lists them.

Privacy: the full image path contains the user's profile directory
(``C:\\Users\\<name>\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe``), so only its
last component ever leaves this module, and neither is logged. The window title is never
read -- unlike `winfo.read_focus`, which reads it for the user's own diagnostic report and
is deliberately not used here.

Untested on a real Windows machine: written without one, the Win32 layer is injected and
faked in `tests/test_focused_app_provider.py`.
"""

from __future__ import annotations

import logging
import ntpath
from collections.abc import Callable

from yazses.platform.windows.integrity import foreground_pid

log = logging.getLogger(__name__)

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
#: ``QueryFullProcessImageNameW`` takes the buffer size in characters. A Win32 path with
#: the ``\\?\\`` prefix can reach 32,767 characters; anything longer is not a path.
_MAX_IMAGE_PATH_CHARS = 32768


def image_name(path: str | None) -> str:
    """The file name of a process image path, without its directories. Pure.

    ``ntpath`` rather than ``os.path`` so the answer is the Windows one on every OS the
    suite runs on -- ``os.path.basename`` on Linux would keep the whole backslashed path.
    """
    if not path:
        return ""
    return ntpath.basename(path.strip())


def process_image_path(pid: int) -> str | None:
    """The full image path of process *pid*, or None when it cannot be read. Never raises."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # pragma: no cover - ctypes is always present
        return None
    if not hasattr(ctypes, "WinDLL"):
        return None  # not Windows
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
        ]

        process = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process:
            return None
        try:
            size = wintypes.DWORD(_MAX_IMAGE_PATH_CHARS)
            buf = ctypes.create_unicode_buffer(_MAX_IMAGE_PATH_CHARS)
            # dwFlags 0: the Win32 path format ("C:\\..."), not the native device path.
            if not kernel32.QueryFullProcessImageNameW(process, 0, buf, ctypes.byref(size)):
                return None
            return buf.value or None
        finally:
            kernel32.CloseHandle(process)
    except Exception:
        # The pid only: the path would carry the user's profile directory.
        log.debug("could not read the image name of pid %s", pid, exc_info=True)
        return None


class WindowsFocusedApp:
    """`FocusedAppProvider` for Windows: the foreground window's process image name.

    Both Win32 steps are injectable so the suite can exercise the logic on any OS.
    """

    def __init__(
        self,
        *,
        pid_fn: Callable[[], int | None] = foreground_pid,
        path_fn: Callable[[int], str | None] = process_image_path,
    ) -> None:
        self._pid_fn = pid_fn
        self._path_fn = path_fn

    def app_id(self) -> str:
        """``"Code.exe"``-style image name of the focused application, or ``""``."""
        try:
            pid = self._pid_fn()
            if not pid:
                return ""
            return image_name(self._path_fn(pid))
        except Exception:
            log.debug("focused-application lookup failed", exc_info=True)
            return ""


__all__ = ["WindowsFocusedApp", "image_name", "process_image_path"]
