"""Will Windows let what YazSes types reach the focused window?

User Interface Privilege Isolation (UIPI) drops synthetic input aimed at a process
running at a higher integrity level than the sender: an elevated Task Manager, an
administrator PowerShell, an installer. Microsoft documents that for ``SendInput``
"neither GetLastError nor the return value will indicate the failure was caused by
UIPI blocking", and on Windows 11 22H2 that held exactly: with an elevated Task
Manager in front, ``SendInput`` returned 2/2 with GetLastError 0, and the keys went
nowhere. So a dictation into such a window was lost without a trace, not even a log
line, because the injector's warning waits for a short count that never comes.

The reliable signal is the one UIPI itself uses: compare the integrity level of the
focused window's process with our own. A normal (medium) process can read an
elevated process's level with ``PROCESS_QUERY_LIMITED_INFORMATION`` and
``TOKEN_QUERY``, as Task Manager's own "Elevated" column does. Anything that cannot be
read answers None, "cannot tell", so the guard never fires on a guess (ADR-021).
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

#: Reason slug for `Platform.input_block_probe`, read by the daemon's no-target guard.
ELEVATED = "elevated"

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TOKEN_QUERY = 0x0008
_TOKEN_INTEGRITY_LEVEL = 25  # TOKEN_INFORMATION_CLASS.TokenIntegrityLevel


def blocks_input(ours: int | None, theirs: int | None) -> bool:
    """True when UIPI drops input from integrity level *ours* into *theirs*. Pure.

    Unknown on either side is not a block: a guard that fires on "could not read"
    would fire on every protected process and teach people to ignore it.
    """
    return ours is not None and theirs is not None and theirs > ours


def process_integrity(pid: int) -> int | None:
    """The mandatory integrity RID of process *pid* (0x2000 medium, 0x3000 high), or None."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # pragma: no cover - ctypes is always present
        return None
    if not hasattr(ctypes, "WinDLL"):
        return None  # not Windows
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
        advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]

        process = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process:
            return None
        try:
            token = wintypes.HANDLE()
            if not advapi32.OpenProcessToken(process, _TOKEN_QUERY, ctypes.byref(token)):
                return None
            try:
                size = wintypes.DWORD()
                advapi32.GetTokenInformation(
                    token, _TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(size)
                )
                if not size.value:
                    return None
                buf = ctypes.create_string_buffer(size.value)
                if not advapi32.GetTokenInformation(
                    token, _TOKEN_INTEGRITY_LEVEL, buf, size, ctypes.byref(size)
                ):
                    return None
                # TOKEN_MANDATORY_LABEL starts with SID_AND_ATTRIBUTES, whose first
                # member is the SID pointer; the level is the SID's last sub-authority.
                sid = ctypes.c_void_p.from_buffer(buf).value
                count = advapi32.GetSidSubAuthorityCount(sid)[0]
                return int(advapi32.GetSidSubAuthority(sid, count - 1)[0])
            finally:
                kernel32.CloseHandle(token)
        finally:
            kernel32.CloseHandle(process)
    except Exception:
        log.debug("could not read the integrity level of pid %s", pid, exc_info=True)
        return None


def foreground_pid() -> int | None:
    """The process that owns the foreground window, or None when there is none."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # pragma: no cover
        return None
    if not hasattr(ctypes, "WinDLL"):
        return None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        ]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value or None
    except Exception:
        return None


def foreground_input_block() -> str | None:
    """``"elevated"`` when UIPI will drop our input into the focused window, else None.

    This is `Platform.input_block_probe` on Windows. It never raises.
    """
    pid = foreground_pid()
    if pid is None:
        return None
    if blocks_input(process_integrity(os.getpid()), process_integrity(pid)):
        return ELEVATED
    return None
