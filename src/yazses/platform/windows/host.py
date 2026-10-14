"""Windows host description. Importable on any OS: every Win32 call is inside a function."""
from __future__ import annotations

import platform
import sys
from pathlib import Path

from yazses.platform.base import HostInfo
from yazses.platform.hostfacts import sysconf_ram_gb


def _windows_ram_gb() -> float | None:  # pragma: no cover - exercised only on Windows
    try:
        import ctypes

        class _MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        kernel32 = getattr(ctypes, "windll").kernel32
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return round(status.ullTotalPhys / 1e9, 1)
    except Exception:  # noqa: BLE001 - describing the host must never fail a run
        pass
    return None


def _msix_packaged() -> bool:
    """A frozen executable with an ``AppxManifest.xml`` beside it is the MSIX build."""
    if not getattr(sys, "frozen", False):
        return False
    try:
        return (Path(sys.executable).resolve().parent / "AppxManifest.xml").is_file()
    except OSError:  # pragma: no cover - defensive
        return False


class WindowsHost:
    def describe(self) -> HostInfo:
        return HostInfo(
            platform_name=sys.platform,
            os_name="Windows",
            os_version=platform.version() or platform.release(),
            ram_gb=sysconf_ram_gb() or _windows_ram_gb(),
            fixed_session_type="windows",
            msix_packaged=_msix_packaged(),
        )
