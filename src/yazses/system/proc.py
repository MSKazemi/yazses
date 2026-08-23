"""Is this PID a live process? One implementation, because the POSIX idiom is destructive.

``os.kill(pid, 0)`` is *the* way to ask this on Unix and is **actively harmful on
Windows**. CPython's ``os.kill`` has no signal semantics there: anything that is not
``CTRL_C_EVENT``/``CTRL_BREAK_EVENT`` falls through to ``TerminateProcess(handle, sig)``,
so signal 0 *kills the process* and hands it exit code 0
(https://github.com/python/cpython/issues/58685). A liveness probe that terminates what
it asks about, silently and with a success code, is the worst shape a bug can take.

The project already knew: ``platform/windows/lifecycle.py`` carries this explanation and
the ``OpenProcess`` + ``GetExitCodeProcess`` replacement, written after the probe was
found killing the very daemon ``yazses status`` was asked about. What it did not do was
own the *only* copy. Two other call sites kept the POSIX idiom -- ``system/pid.py``,
reached by ``status``, ``doctor`` and the tray's poll loop, and ``tests/conftest.py``,
reached by every test run -- and both were still destructive on Windows. This module is
where the knowledge lives now; the other three call it.

It is deliberately import-light (``os``, ``sys``, ``ctypes`` only on Windows and only
inside the call), because ``system/pid.py`` is imported by the CLI on every invocation.
"""
from __future__ import annotations

import os
import sys

# GetExitCodeProcess reports this while a process is still running.
_STILL_ACTIVE = 259
# The OpenProcess access right that is enough to read an exit code, and no more. Asking
# for PROCESS_ALL_ACCESS -- which is what os.kill asks for -- is both unnecessary here
# and how the destructive version starts.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# OpenProcess sets this when the process exists but belongs to somebody else.
_ERROR_ACCESS_DENIED = 5


def process_alive(pid: int | None) -> bool:
    """True when *pid* names a live process. Never terminates anything, never raises.

    ``None``, ``0`` and negatives are dead: they are what a missing or malformed PID
    file yields, and on Unix they are also the "signal a whole process group" forms of
    ``os.kill`` -- which is not a question anything here wants to ask.
    """
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_alive(pid)
    return _posix_alive(pid)


def _posix_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return False
    return True


def _windows_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # ERROR_ACCESS_DENIED means the process exists but belongs to someone else;
        # anything else (typically ERROR_INVALID_PARAMETER) means there is no such
        # process.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)
