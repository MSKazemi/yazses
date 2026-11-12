"""Windows host description. Importable on any OS: every Win32 call is inside a function."""
from __future__ import annotations

import platform
import sys
from collections.abc import Callable
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


#: winerror.h. ``GetCurrentPackageFullName`` returns one of these (Microsoft Learn,
#: "Detect package identity and runtime context"): asked for the name with no buffer, a
#: process that HAS package identity answers ERROR_INSUFFICIENT_BUFFER; one that has none
#: answers APPMODEL_ERROR_NO_PACKAGE. Anything else is an error, not an answer.
_ERROR_SUCCESS = 0
_ERROR_INSUFFICIENT_BUFFER = 122


def package_identity_from_code(code: int) -> bool:
    """True when a ``GetCurrentPackageFullName`` return code means "has identity". Pure.

    Only the two documented positive answers count. ``APPMODEL_ERROR_NO_PACKAGE`` (15700)
    and every other error read as "not packaged": a failed probe must not make an
    unpackaged install look packaged and take its updater away.
    """
    return code in (_ERROR_INSUFFICIENT_BUFFER, _ERROR_SUCCESS)


def _query_package_full_name() -> int:
    """The raw ``GetCurrentPackageFullName`` return code, asked with no buffer.

    ``ctypes.windll`` only exists on Windows; elsewhere this raises and the caller reads
    that as "not packaged". Imported here, never at module top level.
    """
    import ctypes

    length = ctypes.c_uint32(0)
    kernel32 = getattr(ctypes, "windll").kernel32
    return int(kernel32.GetCurrentPackageFullName(ctypes.byref(length), None))


def has_package_identity(query: Callable[[], int] | None = None) -> bool:
    """Does this process have an MSIX package identity? Never raises.

    The OS's own answer, independent of what sits beside the executable. ``query`` returns
    the raw return code and exists so tests can supply one on any OS. UNTESTED on a real
    packaged install.
    """
    try:
        return package_identity_from_code((query or _query_package_full_name)())
    except Exception:  # noqa: BLE001 - describing the host must never fail a run
        return False


def _msix_packaged(*, identity: Callable[[], bool] | None = None) -> bool:
    """A frozen executable that is the MSIX build.

    Two independent signals, either of which is enough: an ``AppxManifest.xml`` beside the
    executable (what the package carries), or package identity from the OS itself
    (:func:`has_package_identity`). Both are required to be *frozen* first: a pip install
    run by the Store's own Python has Python's package identity, not YazSes's, and must not
    lose its updater.
    """
    if not getattr(sys, "frozen", False):
        return False
    try:
        if (Path(sys.executable).resolve().parent / "AppxManifest.xml").is_file():
            return True
    except OSError:  # pragma: no cover - defensive
        pass
    return bool((identity or has_package_identity)())


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
