"""Linux daemon lifecycle — PID file + detached-spawn + systemd autostart."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path

from yazses.platform.base import Paths
from yazses.system import pid as pid_module
from yazses.system.relaunch import Mode, command_for


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
            command_for(Mode.DAEMON),
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
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                check=False, capture_output=True, text=True,
            )
        # Captured, not inherited: systemctl narrates ("Created symlink …") on success,
        # and that chatter in the middle of `yazses start`'s output reads like something
        # went wrong. On failure the message is the only useful thing there is, so it is
        # raised rather than swallowed — CalledProcessError alone would say only "exit 1".
        result = subprocess.run(
            ["systemctl", "--user", "enable", "--now", "yazses.service"],
            check=False, capture_output=True, text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            raise RuntimeError(
                f"systemctl --user enable failed: {detail[-1] if detail else 'unknown error'}"
            )

    def uninstall_autostart(self) -> None:
        """Disable autostart **and remove the unit file this class wrote.**

        `systemctl --user disable` only drops the symlink in `.wants/`; the unit text
        itself stays at `~/.config/systemd/user/yazses.service` for ever. That file is
        written by `install_autostart` above, so leaving it behind means the documented
        uninstall -- which removes `~/.config/yazses` and `~/.local/share/yazses` -- ends
        with a file YazSes created still on disk, and `systemctl --user list-unit-files`
        still listing a program that is gone. The macOS backend has always deleted its
        launchd plist here; the same Protocol method meant two different things.

        Removing it is safe because nothing is lost: `install_autostart` regenerates the
        unit from the running interpreter's own console script, and `needs_rewrite`
        already rewrites a stale one, so re-enabling does not depend on this file
        surviving.
        """
        if not shutil.which("systemctl"):
            return
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "yazses.service"],
            check=False,
        )
        removed = self._service_file.exists()
        self._service_file.unlink(missing_ok=True)
        if removed:
            # Without this systemd keeps the vanished unit in its cache and reports it
            # as "not-found" rather than forgetting it.
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)

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
