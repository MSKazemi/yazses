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

from yazses.cameraperm.contract import CameraPermission
from yazses.platform.base import PermissionState
from yazses.platform.windows import host as winhost
from yazses.platform.windows import permissions as winperms
from yazses.platform.windows.permissions import (
    WindowsPermissions,
    camera_consent_state,
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


# ---- #653: the Store (MSIX) build is a packaged app ---------------------------
#
# "Let desktop apps access your microphone/camera" (the ``NonPackaged`` key) governs
# the .exe, pip, Scoop, winget and Chocolatey installs. A packaged app is governed by
# its own per-app entry instead, so on the Store build a ``Deny`` on the desktop-apps
# switch is evidence about other apps, and reading it gave a false `doctor` FAIL and a
# start-up notification. The per-app entry's location is not documented by Microsoft,
# so it is not read: the packaged build learns only from the two broader switches.
# None of this has run on a real MSIX install.


def _packaged(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(winhost, "_msix_packaged", lambda: value)


def _recording_winreg(values: dict[str, str], opened: list[str]) -> types.ModuleType:
    """`_fake_winreg`, plus a log of every subkey tail the probe tried to open."""
    mod = _fake_winreg(values)
    key_cls = mod.OpenKey  # type: ignore[attr-defined]

    def open_key(hive: str, path: str):
        opened.append(path.rsplit("\\ConsentStore\\", 1)[1])
        return key_cls(hive, path)

    mod.OpenKey = open_key  # type: ignore[attr-defined]
    return mod


@pytest.mark.parametrize("capability", ["microphone", "webcam"])
def test_a_packaged_build_skips_the_desktop_apps_switch(capability) -> None:
    packaged = winperms._consent_reads(capability, packaged=True)
    assert [hive for hive, _ in packaged] == ["HKEY_LOCAL_MACHINE", "HKEY_CURRENT_USER"]
    assert all(not path.endswith("NonPackaged") for _, path in packaged)
    assert all(path.endswith(rf"\ConsentStore\{capability}") for _, path in packaged)
    # ...and the unpackaged install still reads all three, in the same order.
    unpackaged = winperms._consent_reads(capability, packaged=False)
    assert unpackaged[:2] == packaged
    assert unpackaged[2] == ("HKEY_CURRENT_USER", packaged[1][1] + r"\NonPackaged")


def test_the_default_asks_the_host_whether_this_is_the_msix_build(monkeypatch) -> None:
    _packaged(monkeypatch, True)
    assert len(winperms._consent_reads("microphone")) == 2
    _packaged(monkeypatch, False)
    assert len(winperms._consent_reads("microphone")) == 3


def test_the_real_msix_detector_drives_the_reads(monkeypatch, tmp_path) -> None:
    """Not a stubbed boolean: a frozen executable with an AppxManifest.xml beside it,
    which is what `host._msix_packaged` recognises as the Store build."""
    (tmp_path / "AppxManifest.xml").write_text("<Package/>", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "yazses.exe"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert all(
        not path.endswith("NonPackaged") for _, path in winperms._consent_reads("webcam")
    )
    monkeypatch.delattr(sys, "frozen")
    assert winperms._consent_reads("webcam")[-1][1].endswith("NonPackaged")


def test_a_detector_that_raises_keeps_the_unpackaged_reads(monkeypatch) -> None:
    def boom() -> bool:
        raise RuntimeError("no host")

    monkeypatch.setattr(winhost, "_msix_packaged", boom)
    assert len(winperms._consent_reads("microphone")) == 3


def test_packaged_a_revoked_desktop_app_switch_is_not_a_refusal(monkeypatch) -> None:
    """The bug: desktop-apps switch off, YazSes allowed, microphone plugged in."""
    registry = {**_ALLOWED, "HKCU:microphone\\NonPackaged": "Deny"}
    opened: list[str] = []
    monkeypatch.setitem(sys.modules, "winreg", _recording_winreg(registry, opened))
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sounddevice(_MIC))

    _packaged(monkeypatch, True)
    assert WindowsPermissions().check_microphone() is PermissionState.OK
    assert opened == ["microphone", "microphone"], "the NonPackaged key must not be read"

    # The same registry on an unpackaged install is still the refusal it always was.
    _packaged(monkeypatch, False)
    assert WindowsPermissions().check_microphone() is PermissionState.DENIED


@pytest.mark.parametrize("revoked", ["HKLM:microphone", "HKCU:microphone"])
def test_packaged_the_broader_switches_still_refuse(monkeypatch, revoked) -> None:
    """Device-wide and per-user access apply to packaged apps too."""
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg({**_ALLOWED, revoked: "Deny"}))
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sounddevice(_MIC))
    _packaged(monkeypatch, True)
    assert WindowsPermissions().check_microphone() is PermissionState.DENIED


def test_packaged_the_device_list_still_decides(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(_ALLOWED))
    _packaged(monkeypatch, True)
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sounddevice([]))
    assert WindowsPermissions().check_microphone() is PermissionState.DENIED
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sounddevice(OSError("boom")))
    assert WindowsPermissions().check_microphone() is PermissionState.UNKNOWN


_CAMERA_ALLOWED = {
    "HKLM:webcam": "Allow",
    "HKCU:webcam": "Allow",
    "HKCU:webcam\\NonPackaged": "Allow",
}


def test_packaged_the_camera_ignores_the_desktop_apps_switch(monkeypatch) -> None:
    registry = {**_CAMERA_ALLOWED, "HKCU:webcam\\NonPackaged": "Deny"}
    opened: list[str] = []
    monkeypatch.setitem(sys.modules, "winreg", _recording_winreg(registry, opened))

    _packaged(monkeypatch, True)
    # Not DENIED (that switch does not govern a packaged app) and not GRANTED either:
    # the per-app decision that does govern it was never read.
    assert WindowsPermissions().check_camera() is CameraPermission.NOT_DETERMINED
    assert "webcam\\NonPackaged" not in opened

    _packaged(monkeypatch, False)
    assert WindowsPermissions().check_camera() is CameraPermission.DENIED


def test_packaged_the_camera_still_honours_a_broader_refusal(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules, "winreg", _fake_winreg({**_CAMERA_ALLOWED, "HKLM:webcam": "Deny"})
    )
    _packaged(monkeypatch, True)
    assert WindowsPermissions().check_camera() is CameraPermission.DENIED


def test_unpackaged_the_camera_mapping_is_unchanged(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(_CAMERA_ALLOWED))
    _packaged(monkeypatch, False)
    assert WindowsPermissions().check_camera() is CameraPermission.GRANTED


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (("Allow", "Allow"), CameraPermission.NOT_DETERMINED),
        (("Deny", "Allow"), CameraPermission.DENIED),
        (("Allow", "Deny"), CameraPermission.DENIED),
        ((None, None), CameraPermission.NOT_DETERMINED),
        ((), CameraPermission.NOT_DETERMINED),
    ],
)
def test_the_packaged_camera_mapping_never_grants(values, expected) -> None:
    assert camera_consent_state(values, packaged=True) is expected


def test_the_microphone_remedy_names_the_switch_that_governs_this_build(monkeypatch) -> None:
    _packaged(monkeypatch, True)
    packaged = WindowsPermissions().how_to_grant_microphone()
    assert "Let desktop apps" not in packaged
    assert "YazSes" in packaged
    assert "ms-settings:privacy-microphone" in packaged

    _packaged(monkeypatch, False)
    unpackaged = WindowsPermissions().how_to_grant_microphone()
    assert "Let desktop apps access your microphone" in unpackaged
