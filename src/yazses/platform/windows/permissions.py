"""Windows permissions.

Windows doesn't gate WH_KEYBOARD_LL behind a UAC or privacy prompt — it Just
Works. Microphone, on the other hand, has been gated by Settings → Privacy →
Microphone since Windows 10 1903. We probe the ConsentStore switches that page
writes, then ask sounddevice for the device list. The device list alone cannot
answer the question: a revoked switch leaves every device enumerated, and the
capture stream just delivers nothing.
"""

from __future__ import annotations

import logging

from yazses.cameraperm.contract import CameraPermission
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



#: Where Windows records the camera privacy decision.
#:
#: Microsoft documents the *setting* -- "camera access can be disabled for the
#: entire device, for all unpackaged apps, or for individual packaged apps"
#: (learn.microsoft.com/windows/apps/develop/camera/camera-privacy-setting) --
#: and that is exactly these three values. What Microsoft does **not** document
#: is a way for an unpackaged desktop app to *ask*: `AppCapability.CheckAccess`
#: is for packaged apps, and the documented route for a Win32 app is to open the
#: capture device and handle `E_ACCESSDENIED`.
#:
#: Opening the device is not available to us here: that is the very prompt this
#: contract exists to avoid raising on a machine that never asked for a camera
#: feature. So this reads the ConsentStore values the Settings page writes, which
#: is an **undocumented location** -- and that is why a value it cannot read is
#: reported as undetermined rather than assumed. The authoritative answer still
#: arrives later, as `E_ACCESSDENIED` from whatever opens the camera.
#:
#: The microphone page writes the same three values under ``microphone``. Both
#: layouts were read on a real Windows 11 machine (22H2), where every value
#: was the string ``Allow`` exactly as assumed here.
_CONSENT_ROOT = (
    r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager"
    r"\ConsentStore"
)


def _consent_reads(capability: str) -> tuple[tuple[str, str], ...]:
    """``(hive attribute name, subkey)`` for one capability, in decreasing scope.

    The device-wide switch, this user's switch, and "Let desktop apps access
    your camera/microphone" -- the last of which is the one that governs YazSes
    installed from the .exe, and the one that is most often off while the other
    two look fine.
    """
    subkey = rf"{_CONSENT_ROOT}\{capability}"
    return (
        ("HKEY_LOCAL_MACHINE", subkey),
        ("HKEY_CURRENT_USER", subkey),
        ("HKEY_CURRENT_USER", subkey + r"\NonPackaged"),
    )


def _read_consent(capability: str) -> tuple[str | None, ...]:
    """The three ConsentStore values for `capability`; ``None`` for each unreadable one.

    An empty tuple means `winreg` is not importable at all (not Windows), which
    every mapping below already treats as "nothing recorded".
    """
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return ()

    # The `attr-defined` ignores are the checking platform, not a defect:
    # typeshed declares every `winreg` attribute behind `sys.platform ==
    # "win32"`, and CI runs mypy on Linux. Ignored per line rather than by
    # adding this module to the `disable_error_code` block in pyproject.toml,
    # so a real attribute mistake anywhere else in the file still fails.
    values: list[str | None] = []
    for hive_name, path in _consent_reads(capability):
        try:
            hive = getattr(winreg, hive_name)
            with winreg.OpenKey(hive, path) as key:  # type: ignore[attr-defined]
                value, _ = winreg.QueryValueEx(key, "Value")  # type: ignore[attr-defined]
            values.append(str(value))
        except (OSError, AttributeError):
            values.append(None)
    return tuple(values)


def camera_consent_state(values: tuple[str | None, ...]) -> CameraPermission:
    """Map the ConsentStore values onto a camera state. Pure, so it is testable.

    Split out from the registry read for the reason this whole contract exists:
    there is no Windows machine on this project, so the read cannot be exercised
    anywhere, but the *mapping* can be -- and the mapping is where an optimistic
    default would hide.

    * any value ``Deny`` -> ``DENIED``. Windows ANDs these switches, so one
      refusal is a refusal however permissive the others are.
    * at least one explicit ``Allow`` and no ``Deny`` -> ``GRANTED``. An explicit
      value is the user's recorded decision, so reading it is determining the
      state rather than guessing it.
    * nothing explicit at all -- keys absent, hive unreadable, not on Windows --
      > ``NOT_DETERMINED``. **Never ``GRANTED``.** A key that is merely missing
      is not consent, even though Windows would in fact allow access.

    The asymmetry in the last two arms is deliberate: this probe is allowed to
    under-claim and is not allowed to over-claim.
    """
    if any(v == "Deny" for v in values):
        return CameraPermission.DENIED
    if any(v == "Allow" for v in values):
        return CameraPermission.GRANTED
    return CameraPermission.NOT_DETERMINED


def microphone_permission_state(
    consent: tuple[str | None, ...], has_input_device: bool
) -> PermissionState:
    """Combine the microphone ConsentStore values with the device list. Pure.

    * any switch ``Deny`` -> ``DENIED``, *whatever the device list says*. This
      is the arm the device list used to miss: Windows keeps enumerating every
      microphone after the user revokes access, so "devices present" was
      reported as OK while the daemon recorded silence.
    * otherwise a device -> ``OK``; no device -> ``DENIED``, the long-standing
      answer for an empty list (`how_to_grant_microphone` names both causes).
    """
    if any(v == "Deny" for v in consent):
        return PermissionState.DENIED
    return PermissionState.OK if has_input_device else PermissionState.DENIED


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
        # The switches first: a revoked one is the answer even when the device
        # query below would fail, and it is the only signal of a revocation.
        consent = _read_consent("microphone")
        if any(v == "Deny" for v in consent):
            return PermissionState.DENIED
        try:
            import sounddevice as sd

            inputs = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
            return microphone_permission_state(consent, bool(inputs))
        except Exception as exc:
            log.warning("sounddevice query failed: %s", exc)
            return PermissionState.UNKNOWN

    def request_keyboard_capture(self) -> None:
        # No interactive prompt on Windows.
        return

    def how_to_grant(self) -> str:
        """The keyboard-row remedy -- which on Windows is only ever about elevation.

        ⚠ This text used to lead with the *microphone* pane, and `doctor` prints it
        on the keyboard row alone. `check_keyboard_capture` here always answers OK
        (WH_KEYBOARD_LL needs no grant), so that microphone advice could never be
        printed at all, while the row that does fail -- Microphone -- rendered the
        bare word "denied". The microphone half now lives in
        :meth:`how_to_grant_microphone`, where the failing row can reach it.
        """
        return (
            "Windows does not gate keyboard capture behind a privacy prompt, so\n"
            "there is nothing to grant. If dictation works everywhere except one\n"
            "app, that app is probably elevated — Windows blocks input from a\n"
            "non-elevated process to an administrator window (UIPI). Run YazSes as\n"
            "administrator only if you need to dictate into those windows.\n"
            "Looking for the microphone instead? See the Microphone row."
        )

    def how_to_grant_microphone(self) -> str:
        """Settings → Privacy → Microphone has gated this since Windows 10 1903.

        `check_microphone` answers DENIED for a revoked privacy switch and also for
        an empty device list, which is the same symptom as an unplugged microphone,
        so the message names both rather than asserting one of them.
        """
        return (
            "Allow microphone access in:\n"
            "  Settings → Privacy & Security → Microphone\n"
            "and make sure 'Let desktop apps access your microphone' is on too.\n"
            "Or open the pane directly:\n"
            "  start ms-settings:privacy-microphone\n"
            "Already allowed? Then Windows sees no input device — check it is\n"
            "plugged in and enabled in Sound settings, then run: yazses audio devices\n"
            "After an update you may have to allow it again: unsigned apps get a new\n"
            "identity when their hash changes."
        )

    def check_camera(self) -> CameraPermission:
        """Read the camera privacy setting Windows actually gates desktop apps on.

        Windows exposes no API a plain desktop process can call to ask "may I use
        the camera" -- the WinRT ``AppCapability`` surface is for packaged apps --
        so the honest probe is the ConsentStore value the Settings page writes.
        Opening the device to find out is not an option here: that is the prompt
        this contract exists to avoid raising on a machine that never asked for a
        camera feature.

        Every failure path returns ``NOT_DETERMINED``. The mapping itself lives in
        :func:`camera_consent_state`, and is the part the test suite can reach.

        The registry read has run on one real Windows 11 machine with every switch
        on, and answered ``GRANTED``. A ``Deny`` has still only been exercised by
        the mapping tests.
        """
        return camera_consent_state(_read_consent("webcam"))

    def how_to_grant_camera(self) -> str:
        """Settings -> Privacy & Security -> Camera, and the switch under it.

        Two switches, and the second is the one that catches people: the master
        camera toggle can be on while "Let desktop apps access your camera" is
        off, and YazSes installed from the .exe is a desktop app. That is the
        same shape as the microphone advice above, which exists because the same
        pair caught someone there.
        """
        return (
            "Allow camera access in:\n"
            "  Settings -> Privacy & Security -> Camera\n"
            "and make sure 'Let desktop apps access your camera' is on too --\n"
            "the top toggle can be on while that one is off.\n"
            "Or open the pane directly:\n"
            "  start ms-settings:privacy-webcam\n"
            "Installed from the .exe installer or the MSIX? Those bundles ship no\n"
            "camera runtime and cannot add one, so no permission will make the\n"
            "camera features work there -- use `pipx install 'yazses[gaze]'`.\n"
            "Already allowed and still nothing? Windows may simply not have\n"
            "written a decision yet; YazSes reports that as undetermined rather\n"
            "than claiming access it cannot confirm."
        )
