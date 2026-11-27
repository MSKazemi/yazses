"""Windows lifecycle: who the daemon is, and an autostart entry with no console window.

Found by reading the code, not observed on Windows. Everything here runs on any OS: the
instance lock is the real one (``flock`` or ``msvcrt``), ``winreg`` is a stand-in and
``tasklist`` is never run.

* The PID file survives a daemon that Windows ends at sign-out, and `read_pid` returned
  the number in it. `yazses restart` stops whatever `read_pid` returns.
* On an interpreter installed on its own, pip puts ``yazses-tray.exe`` under
  ``Scripts``, so autostart wrote a console ``python.exe`` command instead.
"""

from __future__ import annotations

import contextlib
import os
import sys

import pytest

from yazses.platform.base import Paths
from yazses.platform.windows import lifecycle as win_lifecycle
from yazses.platform.windows.lifecycle import (
    WindowsLifecycle,
    is_console_python_entry,
    windowed_interpreter,
)
from yazses.system import single_instance

# ---- Who is the daemon: the lock before the PID file -----------------------

# Some other process's number, as a recycled PID would be.
_STALE_PID = 4321


def _paths(tmp_path) -> Paths:
    return Paths(
        config_dir=tmp_path,
        state_dir=tmp_path,
        cache_dir=tmp_path,
        log_dir=tmp_path,
        data_dir=tmp_path,
    )


@pytest.fixture
def no_tasklist(monkeypatch):
    def _run(*args, **kwargs):
        raise AssertionError("the instance lock already answered; tasklist must not run")

    monkeypatch.setattr(win_lifecycle.subprocess, "run", _run)


def _daemon_that_died(tmp_path) -> Paths:
    """What a sign-out leaves behind: a lock file nobody holds, and the old PID file."""
    lock = single_instance.SingleInstanceLock(tmp_path / "daemon.lock")
    assert lock.acquire()
    lock.release()
    paths = _paths(tmp_path)
    paths.pid_file.write_text(str(_STALE_PID), encoding="utf-8")
    return paths


def test_a_stale_pid_file_names_no_process_once_the_lock_is_free(tmp_path, no_tasklist):
    """`_restart_daemon` calls `stop_daemon(read_pid())` without asking `is_running`,
    and `stop_daemon` ends in TerminateProcess."""
    lifecycle = WindowsLifecycle(_daemon_that_died(tmp_path), alive_probe=lambda pid: True)

    assert lifecycle.read_pid() is None
    assert lifecycle.is_running() is False


def test_a_held_lock_is_a_running_daemon_whatever_the_pid_file_says(tmp_path, no_tasklist):
    paths = _paths(tmp_path)
    paths.pid_file.write_text(str(_STALE_PID), encoding="utf-8")
    lock = single_instance.SingleInstanceLock(tmp_path / "daemon.lock")
    assert lock.acquire()
    try:
        lifecycle = WindowsLifecycle(paths, alive_probe=lambda pid: False)
        assert lifecycle.is_running() is True
        assert lifecycle.read_pid() == os.getpid()
        paths.pid_file.unlink()
        assert lifecycle.is_running() is True
        assert lifecycle.read_pid() == os.getpid()
    finally:
        lock.release()


def test_a_holder_without_a_readable_pid_falls_back_to_the_pid_file(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    paths.pid_file.write_text("77", encoding="utf-8")
    monkeypatch.setattr(win_lifecycle, "holder_pid", lambda path: -1)
    lifecycle = WindowsLifecycle(paths)

    assert lifecycle.read_pid() == 77
    assert lifecycle.is_running() is True


def test_without_a_lock_file_the_pid_file_still_answers(tmp_path):
    paths = _paths(tmp_path)
    paths.pid_file.write_text("77", encoding="utf-8")

    assert WindowsLifecycle(paths).read_pid() == 77


# ---- Autostart without a console window ------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("python.exe", "pythonw.exe"),
        ("python3.11.exe", "pythonw3.11.exe"),
        ("Python.EXE", "pythonw.EXE"),
        ("pythonw.exe", "pythonw.exe"),
        ("yazses-cli.exe", None),
    ],
)
def test_windowed_interpreter(tmp_path, name, expected):
    result = windowed_interpreter(tmp_path / name)
    assert result == (None if expected is None else tmp_path / expected)


class _RunKey:
    """Just enough of `winreg` for one REG_SZ under HKCU\\Run."""

    HKEY_CURRENT_USER = object()
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.value: str | None = None
        self.writes: list[str] = []

    def OpenKey(self, root, sub, reserved, access):  # noqa: N802 -- winreg's name
        return contextlib.nullcontext(self)

    def QueryValueEx(self, key, name):  # noqa: N802
        if self.value is None:
            raise FileNotFoundError(name)
        return self.value, self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):  # noqa: N802
        self.value = value
        self.writes.append(value)


def _standalone_python(monkeypatch, tmp_path, *files):
    """A python.org-style folder: python.exe at the top, launchers under Scripts."""
    root = tmp_path / "Ada Lovelace" / "Python312"
    (root / "Scripts").mkdir(parents=True)
    for name in ("python.exe", *files):
        (root / name).write_bytes(b"")
    reg = _RunKey()
    monkeypatch.setitem(sys.modules, "winreg", reg)
    monkeypatch.setattr(sys, "executable", str(root / "python.exe"))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    return WindowsLifecycle(_paths(tmp_path)), reg, root


def test_autostart_finds_the_tray_launcher_under_scripts(monkeypatch, tmp_path):
    lifecycle, reg, root = _standalone_python(
        monkeypatch, tmp_path, "pythonw.exe", "Scripts/yazses-tray.exe"
    )
    lifecycle.install_autostart()

    assert reg.writes == [f'"{root / "Scripts" / "yazses-tray.exe"}"']


def test_autostart_without_a_launcher_uses_pythonw(monkeypatch, tmp_path):
    lifecycle, reg, root = _standalone_python(monkeypatch, tmp_path, "pythonw.exe")
    lifecycle.install_autostart()

    assert reg.writes == [f'"{root / "pythonw.exe"}" -m yazses.tray.app']


def test_autostart_keeps_python_when_there_is_nothing_windowed(monkeypatch, tmp_path):
    lifecycle, reg, root = _standalone_python(monkeypatch, tmp_path)
    lifecycle.install_autostart()

    assert reg.writes == [f'"{root / "python.exe"}" -m yazses.tray.app']
    assert lifecycle.repair_autostart() is False


@pytest.mark.parametrize("windowed", ["pythonw.exe", "Scripts/yazses-tray.exe"])
def test_repair_replaces_the_console_python_entry(monkeypatch, tmp_path, windowed):
    lifecycle, reg, root = _standalone_python(monkeypatch, tmp_path, windowed)
    reg.value = f'"{root / "python.exe"}" -m yazses.tray.app'

    assert lifecycle.repair_autostart() is True
    assert "python.exe" not in reg.value
    assert lifecycle.repair_autostart() is False


_PY = r'"C:\Python312\python.exe" -m yazses.tray.app'
_PYW = r'"C:\Python312\pythonw.exe" -m yazses.tray.app'


@pytest.mark.parametrize(
    ("current", "wanted", "expected"),
    [
        (_PY, _PYW, True),
        (_PY.upper(), _PYW, True),
        (_PY, r'"C:\Python312\Scripts\yazses-tray.exe"', True),
        (_PY, _PY, False),  # nothing windowed to move to
        (_PY, r'"C:\other\pythonw.exe" -m yazses.tray.app', False),
        (_PY, r'"C:\other\Scripts\yazses-tray.exe"', False),
        (_PY + " --debug", _PYW, False),  # hand-edited
        (_PYW, _PYW, False),
        (r'"C:\tools\launcher.exe"', _PYW, False),
        ("", _PYW, False),
    ],
)
def test_only_this_interpreters_console_entry_is_replaced(current, wanted, expected):
    assert is_console_python_entry(current, wanted) is expected
