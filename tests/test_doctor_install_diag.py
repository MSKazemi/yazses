"""Tests for the doctor install/lifecycle + hotkey-device diagnostics.

These catch the three deployment traps behind a "dead hotkey" report:
a hotkey bound to a virtual injector device, duplicate installs on PATH, and a
systemd ExecStart pointing at a missing/different binary.
"""

import sys
import types

import pytest

from yazses.platform import PermissionState
from yazses.platform.linux.permissions import LinuxPermissions
from yazses.system import doctor

# ---- keyboard capture permissions -----------------------------------------


def test_keyboard_capture_denied_includes_input_group_fix(monkeypatch):
    perms = LinuxPermissions()
    monkeypatch.setattr(perms, "check_keyboard_capture", lambda: PermissionState.DENIED)
    monkeypatch.setattr(perms, "how_to_grant", lambda: "Ask an administrator.")
    monkeypatch.setattr(doctor, "_input_group_pending_relogin", lambda: False)

    name, status, detail = doctor._keyboard_capture_check(perms, "linux")
    rendered = doctor._format_check(name, status, detail)

    assert name == "Keyboard capture"
    assert status == "FAIL"
    assert "sudo usermod -aG input $USER" in rendered
    assert "log out and back in" in rendered.lower()


# ---- _hotkey_device_check --------------------------------------------------


class _Cfg:
    class hotkey:
        key = "right_alt"


def _fake_dev(name, path="/dev/input/event3"):
    return types.SimpleNamespace(name=name, path=path)


@pytest.mark.skipif(sys.platform != "linux", reason="evdev/hotkey path is Linux-only")
def test_hotkey_device_ok_for_real_keyboard(mocker):
    mocker.patch(
        "yazses.hotkeys.evdev_hold.EvdevHoldListener._find_keyboards",
        return_value=[_fake_dev("AT Translated Set 2 keyboard")],
    )
    name, status, detail = doctor._hotkey_device_check(_Cfg())
    assert status == "OK"
    assert "AT Translated Set 2 keyboard" in detail


@pytest.mark.skipif(sys.platform != "linux", reason="evdev/hotkey path is Linux-only")
def test_hotkey_device_lists_all_real_keyboards(mocker):
    """A laptop + external keyboard: doctor reports both, since both are watched."""
    mocker.patch(
        "yazses.hotkeys.evdev_hold.EvdevHoldListener._find_keyboards",
        return_value=[
            _fake_dev("Logitech USB Keyboard", "/dev/input/event17"),
            _fake_dev("AT Translated Set 2 keyboard", "/dev/input/event3"),
        ],
    )
    name, status, detail = doctor._hotkey_device_check(_Cfg())
    assert status == "OK"
    assert "Logitech USB Keyboard" in detail
    assert "AT Translated Set 2 keyboard" in detail


@pytest.mark.skipif(sys.platform != "linux", reason="evdev/hotkey path is Linux-only")
def test_hotkey_device_fail_for_virtual(mocker):
    mocker.patch(
        "yazses.hotkeys.evdev_hold.EvdevHoldListener._find_keyboards",
        return_value=[_fake_dev("ydotoold virtual device", "/dev/input/event16")],
    )
    name, status, detail = doctor._hotkey_device_check(_Cfg())
    assert status == "FAIL"
    assert "virtual device" in detail


@pytest.mark.skipif(sys.platform != "linux", reason="evdev/hotkey path is Linux-only")
def test_hotkey_device_skip_on_enumeration_error(mocker):
    mocker.patch(
        "yazses.hotkeys.evdev_hold.EvdevHoldListener._find_keyboards",
        side_effect=PermissionError("no access to /dev/input"),
    )
    name, status, detail = doctor._hotkey_device_check(_Cfg())
    assert status == "SKIP"


# ---- _systemd_execstart parsing -------------------------------------------


@pytest.mark.skipif(sys.platform != "linux", reason="systemctl path is Linux-only")
def test_systemd_execstart_parses_path(mocker):
    fake = types.SimpleNamespace(
        stdout="{ path=/home/u/.local/bin/yazses-daemon ; argv[]=/home/u/.local/bin/yazses-daemon ; ... }\n"
    )
    mocker.patch("subprocess.run", return_value=fake)
    assert doctor._systemd_execstart() == "/home/u/.local/bin/yazses-daemon"


@pytest.mark.skipif(sys.platform != "linux", reason="systemctl path is Linux-only")
def test_systemd_execstart_none_when_no_unit(mocker):
    mocker.patch("subprocess.run", return_value=types.SimpleNamespace(stdout="\n"))
    assert doctor._systemd_execstart() is None


# ---- _install_consistency_checks ------------------------------------------


@pytest.mark.skipif(sys.platform != "linux", reason="install diag is Linux-only")
def test_install_flags_missing_execstart(mocker):
    mocker.patch.object(doctor, "_yazses_paths_on_path", return_value=["/a/yazses"])
    mocker.patch.object(doctor, "_systemd_execstart", return_value="/usr/bin/yazses-daemon")
    mocker.patch("pathlib.Path.exists", return_value=False)
    checks = doctor._install_consistency_checks()
    unit = [c for c in checks if c[0] == "systemd unit"]
    assert unit and unit[0][1] == "FAIL"
    assert "203/EXEC" in unit[0][2]


@pytest.mark.skipif(sys.platform != "linux", reason="install diag is Linux-only")
def test_install_warns_on_multiple_paths(mocker):
    mocker.patch.object(
        doctor, "_yazses_paths_on_path",
        return_value=["/a/yazses", "/b/yazses"],
    )
    mocker.patch.object(doctor, "_systemd_execstart", return_value=None)
    checks = doctor._install_consistency_checks()
    inst = [c for c in checks if c[0] == "Install"]
    assert inst and inst[0][1] == "WARN"
    assert "multiple yazses" in inst[0][2]


@pytest.mark.skipif(sys.platform != "linux", reason="install diag is Linux-only")
def test_install_ok_when_execstart_matches(mocker):
    mocker.patch.object(doctor, "_yazses_paths_on_path", return_value=["/home/u/.local/bin/yazses"])
    mocker.patch.object(doctor, "_systemd_execstart", return_value="/home/u/.local/bin/yazses-daemon")
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("shutil.which", return_value="/home/u/.local/bin/yazses-daemon")
    checks = doctor._install_consistency_checks()
    unit = [c for c in checks if c[0] == "systemd unit"]
    assert unit and unit[0][1] == "OK"
    assert not [c for c in checks if c[0] == "Install"]  # single path → no warn
