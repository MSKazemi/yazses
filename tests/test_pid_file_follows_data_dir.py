"""The Linux lifecycle looks for the daemon's lock and PID file where the daemon puts them.

The daemon takes its instance lock at ``paths.data_dir / "daemon.lock"``, and on Linux
``paths.data_dir`` is platformdirs' ``user_data_dir``, which follows ``$XDG_DATA_HOME``.
``system/pid.py`` hard-coded ``~/.local/share/yazses`` instead, so with ``XDG_DATA_HOME`` set
(a sandbox, a relocated home, an immutable distro) ``is_running()`` / ``read_pid()`` looked
for the lock in a different directory from the one it is held in and said "not running" for a
live daemon -- while ``yazses restart`` (which does use ``paths.data_dir``) saw the holder.
It also meant a run under a sandboxed ``XDG_DATA_HOME`` wrote and deleted the *real*
``~/.local/share/yazses/daemon.pid``.

These tests move the module's fallback paths to an empty temp directory first, so nothing here
can touch the real ones, and then check the lifecycle agrees with the daemon about where to look.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from yazses.platform.base import Paths
from yazses.platform.linux.lifecycle import LinuxLifecycle
from yazses.system import pid as pid_module
from yazses.system.single_instance import SingleInstanceLock

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX instance lock")


@pytest.fixture
def home_fallback(tmp_path, monkeypatch):
    """Point the module's no-argument fallback at an empty dir that is *not* the data dir."""
    fallback = tmp_path / "home-fallback"
    fallback.mkdir()
    monkeypatch.setattr(pid_module, "_PID_FILE", fallback / "daemon.pid")
    monkeypatch.setattr(pid_module, "_LOCK_FILE", fallback / "daemon.lock")
    return fallback


def _lifecycle(data_dir: Path) -> LinuxLifecycle:
    state = data_dir.parent / "state"
    return LinuxLifecycle(
        Paths(config_dir=data_dir.parent / "cfg", state_dir=state,
              cache_dir=data_dir.parent / "cache", log_dir=data_dir.parent / "log",
              data_dir=data_dir)
    )


def test_a_lock_held_in_the_data_dir_is_seen(tmp_path, home_fallback):
    data_dir = tmp_path / "xdg-data" / "yazses"
    data_dir.mkdir(parents=True)
    lock = SingleInstanceLock(data_dir / "daemon.lock")  # exactly what the daemon does
    assert lock.acquire()
    try:
        lifecycle = _lifecycle(data_dir)
        assert lifecycle.is_running() is True
        assert lifecycle.read_pid() == os.getpid()
    finally:
        lock.release()


def test_write_and_clear_pid_use_the_data_dir_only(tmp_path, home_fallback):
    data_dir = tmp_path / "xdg-data" / "yazses"
    lifecycle = _lifecycle(data_dir)
    lifecycle.write_pid()
    assert (data_dir / "daemon.pid").read_text(encoding="utf-8") == str(os.getpid())
    assert not (home_fallback / "daemon.pid").exists()
    lifecycle.clear_pid()
    assert not (data_dir / "daemon.pid").exists()


def test_clear_pid_never_deletes_the_other_locations_file(tmp_path, home_fallback):
    other = home_fallback / "daemon.pid"
    other.write_text("4242", encoding="utf-8")  # stands in for the real daemon's file
    _lifecycle(tmp_path / "xdg-data" / "yazses").clear_pid()
    assert other.read_text(encoding="utf-8") == "4242"


def test_the_real_linux_paths_follow_xdg_data_home(tmp_path, monkeypatch, home_fallback):
    """End to end through `build_paths`, the resolver the daemon itself uses."""
    if sys.platform != "linux":
        pytest.skip("platformdirs honours XDG_DATA_HOME on Linux only")
    from yazses.platform.linux.paths import build_paths

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    paths = build_paths()
    assert paths.data_dir == tmp_path / "xdg" / "yazses"
    paths.data_dir.mkdir(parents=True)
    lock = SingleInstanceLock(paths.data_dir / "daemon.lock")
    assert lock.acquire()
    try:
        assert LinuxLifecycle(paths).is_running() is True
    finally:
        lock.release()
