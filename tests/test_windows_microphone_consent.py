"""The Windows microphone check reads the privacy switches, not only the device list.

Settings → Privacy & Security → Microphone does not hide a single device when it is
turned off: PortAudio keeps enumerating every input, and the stream just delivers
nothing. So a probe that looks only at the device list reports OK for the one state
that needs the user's hand, and the daemon's start-up diagnosis -- which raises a
notification on DENIED and stays silent on OK -- never tells them why dictation
records silence.

These fake `winreg` and `sounddevice`, so they run on every OS. The registry layout
they model was read off a real Windows 11 machine.
"""

from __future__ import annotations

import sys
import types

import pytest

from yazses.platform.base import PermissionState
from yazses.platform.windows import permissions as winperms
from yazses.platform.windows.permissions import (
    WindowsPermissions,
    microphone_permission_state,
)


@pytest.mark.parametrize(
    ("consent", "has_device", "expected"),
    [
        (("Allow", "Allow", "Allow"), True, PermissionState.OK),
        # The arm the device list could not see: devices present, access revoked.
        (("Allow", "Allow", "Deny"), True, PermissionState.DENIED),
        (("Deny", None, None), True, PermissionState.DENIED),
        # Nothing recorded is not a refusal -- the device list decides.
        ((None, None, None), True, PermissionState.OK),
        ((), True, PermissionState.OK),
        # The long-standing answer for an empty list is unchanged.
        (("Allow", "Allow", "Allow"), False, PermissionState.DENIED),
        ((), False, PermissionState.DENIED),
    ],
)
def test_the_mapping_lets_one_refusal_outrank_the_device_list(
    consent, has_device, expected
) -> None:
    assert microphone_permission_state(consent, has_device) is expected


def _fake_winreg(values: dict[str, str]) -> types.ModuleType:
    """A `winreg` whose keys hold `values`, keyed by the subkey's tail."""
    mod = types.ModuleType("winreg")
    mod.HKEY_LOCAL_MACHINE = "HKLM"  # type: ignore[attr-defined]
    mod.HKEY_CURRENT_USER = "HKCU"  # type: ignore[attr-defined]

    class _Key:
        def __init__(self, hive: str, path: str) -> None:
            tail = path.rsplit("\\ConsentStore\\", 1)[1]
            self.name = f"{hive}:{tail}"

        def __enter__(self) -> _Key:
            if self.name not in values:
                raise FileNotFoundError(self.name)
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    mod.OpenKey = _Key  # type: ignore[attr-defined]
    mod.QueryValueEx = lambda key, _name: (values[key.name], 1)  # type: ignore[attr-defined]
    return mod


def _fake_sounddevice(devices: list[dict] | Exception) -> types.ModuleType:
    mod = types.ModuleType("sounddevice")

    def query_devices():
        if isinstance(devices, Exception):
            raise devices
        return devices

    mod.query_devices = query_devices  # type: ignore[attr-defined]
    return mod


_MIC = [{"name": "Microphone Array", "max_input_channels": 2}]
_ALLOWED = {
    "HKLM:microphone": "Allow",
    "HKCU:microphone": "Allow",
    "HKCU:microphone\\NonPackaged": "Allow",
}


def test_a_revoked_desktop_app_switch_is_denied_with_a_microphone_plugged_in(
    monkeypatch,
) -> None:
    """The case this file exists for: the top toggle on, the desktop-app one off."""
    monkeypatch.setitem(
        sys.modules,
        "winreg",
        _fake_winreg({**_ALLOWED, "HKCU:microphone\\NonPackaged": "Deny"}),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sounddevice(_MIC))
    assert WindowsPermissions().check_microphone() is PermissionState.DENIED


def test_a_refusal_wins_even_when_the_device_query_fails(monkeypatch) -> None:
    """The switch is read first, so a broken PortAudio cannot hide a known refusal."""
    monkeypatch.setitem(
        sys.modules, "winreg", _fake_winreg({**_ALLOWED, "HKLM:microphone": "Deny"})
    )
    monkeypatch.setitem(
        sys.modules, "sounddevice", _fake_sounddevice(OSError("PortAudio not initialized"))
    )
    assert WindowsPermissions().check_microphone() is PermissionState.DENIED


def test_allowed_with_a_device_is_ok(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(_ALLOWED))
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sounddevice(_MIC))
    assert WindowsPermissions().check_microphone() is PermissionState.OK


def test_a_failed_device_query_without_a_refusal_stays_unknown(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(_ALLOWED))
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sounddevice(OSError("boom")))
    assert WindowsPermissions().check_microphone() is PermissionState.UNKNOWN


def test_without_winreg_the_device_list_still_decides(monkeypatch) -> None:
    """`None` in `sys.modules` makes `import winreg` raise ImportError, so this holds
    on a real Windows host too."""
    monkeypatch.setitem(sys.modules, "winreg", None)
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sounddevice(_MIC))
    assert WindowsPermissions().check_microphone() is PermissionState.OK
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sounddevice([]))
    assert WindowsPermissions().check_microphone() is PermissionState.DENIED


def test_the_camera_and_microphone_read_the_same_three_switches() -> None:
    """One layout, two capabilities -- so a fix to one read cannot miss the other."""
    for capability in ("webcam", "microphone"):
        reads = winperms._consent_reads(capability)
        assert [hive for hive, _ in reads] == [
            "HKEY_LOCAL_MACHINE",
            "HKEY_CURRENT_USER",
            "HKEY_CURRENT_USER",
        ]
        assert reads[0][1].endswith(rf"\ConsentStore\{capability}")
        assert reads[2][1].endswith(rf"\ConsentStore\{capability}\NonPackaged")
