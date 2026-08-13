"""Windows permissions.

Windows doesn't gate WH_KEYBOARD_LL behind a UAC or privacy prompt — it Just
Works. Microphone, on the other hand, has been gated by Settings → Privacy →
Microphone since Windows 10 1903. We probe by asking sounddevice for the
device list; an empty list strongly suggests the user has revoked access (or
no mic is plugged in).
"""

from __future__ import annotations

import logging

from yazses.platform.base import PermissionState

log = logging.getLogger(__name__)


# TokenElevation == 20 in the TOKEN_INFORMATION_CLASS enum.
_TOKEN_ELEVATION = 20
_TOKEN_QUERY = 0x0008


def is_elevated() -> bool | None:
    """True when this process runs elevated, None when it can't be determined.

    Elevation is what decides whether YazSes can type into *other* elevated
    windows. Windows' User Interface Privilege Isolation blocks `SendInput`
    from a lower-integrity process to a higher-integrity one, and the low-level
    keyboard hook likewise never sees keys typed into an elevated window. Both
    fail silently: `SendInput` returns 0 with ERROR_ACCESS_DENIED and nothing
    reaches the target, which reads as "dictation just doesn't work in this one
    app".
    """
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # pragma: no cover - ctypes is always present
        return None
    if not hasattr(ctypes, "WinDLL"):
        return None  # not Windows
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
        ]
        advapi32.OpenProcessToken.restype = wintypes.BOOL

        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
        ):
            return None
        try:
            elevation = wintypes.DWORD()
            size = wintypes.DWORD()
            ok = advapi32.GetTokenInformation(
                token,
                _TOKEN_ELEVATION,
                ctypes.byref(elevation),
                ctypes.sizeof(elevation),
                ctypes.byref(size),
            )
            if not ok:
                return None
            return bool(elevation.value)
        finally:
            kernel32.CloseHandle(token)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("elevation probe failed: %s", exc)
        return None


def elevation_detail(elevated: bool | None) -> str:
    """Human-readable consequence of the current elevation state."""
    if elevated is None:
        return (
            "could not determine elevation — if one app ignores dictation, it is "
            "probably running as administrator (UIPI blocks input from this process)"
        )
    if elevated:
        return (
            "running as administrator — dictation reaches elevated windows too. "
            "This is more privilege than YazSes needs; prefer an unelevated run "
            "unless you specifically dictate into admin tools."
        )
    return (
        "not elevated (the safer default) — Windows will silently block dictation "
        "into windows that run as administrator, e.g. Task Manager or an elevated "
        "PowerShell. Run YazSes as administrator only if you need those."
    )


class WindowsPermissions:
    """PermissionsBackend for Windows."""

    def check_keyboard_capture(self) -> PermissionState:
        # WH_KEYBOARD_LL doesn't require a privacy grant. We can't easily
        # verify the hook will install without actually installing it.
        #
        # Note this OK is about *installing* the hook. It says nothing about
        # elevated windows, which UIPI excludes regardless — see is_elevated()
        # and the "Elevated windows" line in `yazses doctor`.
        return PermissionState.OK

    def check_microphone(self) -> PermissionState:
        try:
            import sounddevice as sd

            inputs = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
            return PermissionState.OK if inputs else PermissionState.DENIED
        except Exception as exc:
            log.warning("sounddevice query failed: %s", exc)
            return PermissionState.UNKNOWN

    def request_keyboard_capture(self) -> None:
        # No interactive prompt on Windows.
        return

    def how_to_grant(self) -> str:
        return (
            "If the daemon can't see the microphone, allow it in:\n"
            "  Settings → Privacy & Security → Microphone\n"
            "Or open the pane directly:\n"
            "  start ms-settings:privacy-microphone\n"
            "If instead dictation works everywhere except one app, that app is\n"
            "probably elevated — Windows blocks input from a non-elevated process\n"
            "to an administrator window."
        )
