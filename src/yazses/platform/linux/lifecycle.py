"""Linux daemon lifecycle — PID file + detached-spawn + systemd autostart."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from yazses.platform.base import Paths
from yazses.system import pid as pid_module


class LinuxLifecycle:
    """LifecycleBackend implementation for Linux."""

    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    # ---- PID file ----------------------------------------------------------

    def write_pid(self) -> None:
        pid_module.write_pid()

    def clear_pid(self) -> None:
        pid_module.clear_pid()

    def read_pid(self) -> int | None:
        return pid_module.read_pid()

    def is_running(self) -> bool:
        return pid_module.is_running()

    # ---- Process spawn / stop ---------------------------------------------

    def start_daemon_detached(self) -> None:
        subprocess.Popen(
            [sys.executable, "-m", "yazses.main"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop_daemon(self, pid: int) -> None:
        os.kill(pid, signal.SIGTERM)

    # ---- Autostart (systemd --user) ---------------------------------------

    @property
    def _service_file(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user" / "yazses.service"

    def install_autostart(self) -> None:
        """Write the unit if needed, then enable it. Works for any install method.

        This used to refuse unless install.sh had already written the unit, which meant
        every ordinary Python install — pipx, uv tool, pip --user — had no autostart at
        all and needed `yazses start` after each reboot. The unit text is generated from
        the running interpreter's own console script, so it points at *this* install and
        is rewritten when an upgrade moves it.
        """
        from yazses.platform.linux import autostart

        if not shutil.which("systemctl"):
            raise RuntimeError("systemctl not found; cannot manage autostart.")

        wanted = autostart.unit_text(autostart.resolve_daemon_command())
        existing = self._service_file.read_text() if self._service_file.exists() else None
        if autostart.needs_rewrite(existing, wanted):
            self._service_file.parent.mkdir(parents=True, exist_ok=True)
            self._service_file.write_text(wanted)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "--user", "enable", "--now", "yazses.service"], check=True)

    def uninstall_autostart(self) -> None:
        if not shutil.which("systemctl"):
            return
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "yazses.service"],
            check=False,
        )

    def is_autostart_installed(self) -> bool:
        if not shutil.which("systemctl"):
            return False
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", "yazses.service"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0 and "enabled" in result.stdout
