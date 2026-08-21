"""macOS daemon lifecycle — PID file + detached spawn + launchd plist."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from yazses.platform.base import Paths
from yazses.system.relaunch import Mode, command_for

_LABEL = "com.yazses.daemon"


class MacosLifecycle:
    """LifecycleBackend for macOS."""

    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    # ---- PID file ----------------------------------------------------------

    def write_pid(self) -> None:
        self._paths.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self._paths.pid_file.write_text(str(os.getpid()))

    def clear_pid(self) -> None:
        self._paths.pid_file.unlink(missing_ok=True)

    def read_pid(self) -> int | None:
        try:
            return int(self._paths.pid_file.read_text().strip())
        except (FileNotFoundError, ValueError):
            return None

    def is_running(self) -> bool:
        pid = self.read_pid()
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        # Best-effort recycle-PID guard via BSD ps (no /proc on macOS).
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                check=False,
                timeout=1.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            return True
        return "yazses" in result.stdout

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

    # ---- Autostart (launchd) ----------------------------------------------

    @property
    def _plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"

    def install_autostart(self) -> None:
        self._plist_path.parent.mkdir(parents=True, exist_ok=True)
        executable = sys.executable
        log_dir = self._paths.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        plist = _PLIST_TEMPLATE.format(
            label=_LABEL,
            executable=executable,
            stdout=log_dir / "stdout.log",
            stderr=log_dir / "stderr.log",
        )
        self._plist_path.write_text(plist)
        uid = os.getuid()
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(self._plist_path)],
            check=False,
        )

    def uninstall_autostart(self) -> None:
        uid = os.getuid()
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}/{_LABEL}"],
            check=False,
        )
        self._plist_path.unlink(missing_ok=True)

    def is_autostart_installed(self) -> bool:
        if not self._plist_path.exists():
            return False
        uid = os.getuid()
        result = subprocess.run(
            ["launchctl", "print", f"gui/{uid}/{_LABEL}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0


_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{executable}</string>
        <string>-m</string>
        <string>yazses.main</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key>
    <dict>
        <key>Crashed</key><true/>
    </dict>
    <key>ProcessType</key><string>Background</string>
    <key>StandardOutPath</key><string>{stdout}</string>
    <key>StandardErrorPath</key><string>{stderr}</string>
</dict>
</plist>
"""
