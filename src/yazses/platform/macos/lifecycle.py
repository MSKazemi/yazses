"""macOS daemon lifecycle — PID file + detached spawn + launchd plist."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

from yazses.platform.base import Paths
from yazses.system.relaunch import Mode, command_for

_LABEL = "com.yazses.daemon"


def command_is_yazses(command: str) -> bool:
    """Whether a ``ps`` command line belongs to a YazSes process.

    Case-insensitive, and that is the whole point. The bundled app's executable is
    ``/Applications/YazSes.app/Contents/MacOS/YazSes`` -- capital Y and S -- so the
    earlier ``"yazses" in command`` test was False for every daemon the ``.app``
    ever started. ``doctor`` then answered "Daemon: not running" about a daemon that
    was running, which is what #562's log and report showed side by side. The check
    exists to reject a *recycled* PID (some unrelated process), not the real daemon.
    """
    return "yazses" in command.lower()


class MacosLifecycle:
    """LifecycleBackend for macOS."""

    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    # ---- PID file ----------------------------------------------------------

    def write_pid(self) -> None:
        self._paths.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self._paths.pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def clear_pid(self) -> None:
        self._paths.pid_file.unlink(missing_ok=True)

    def read_pid(self) -> int | None:
        try:
            return int(self._paths.pid_file.read_text(encoding="utf-8").strip())
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
        return command_is_yazses(result.stdout)

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
        log_dir = self._paths.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        plist = render_launch_agent(
            command_for(Mode.DAEMON),
            stdout=log_dir / "stdout.log",
            stderr=log_dir / "stderr.log",
        )
        self._plist_path.write_text(plist, encoding="utf-8")
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


def render_launch_agent(argv: list[str], *, stdout: Path, stderr: Path) -> str:
    """The launchd plist that runs *argv* at login. Pure, so it tests without a Mac.

    ``argv`` comes from :func:`~yazses.system.relaunch.command_for`, not from
    ``[sys.executable, "-m", "yazses.main"]``. In the .app / .dmg bundle
    ``sys.executable`` is the bundle itself, which is not an interpreter: it read
    ``-m`` as a CLI option and exited 2 with "No such option: -m", so the login
    agent ``doctor`` reported as loaded never started a daemon. Every other
    platform's autostart already goes through ``command_for``.
    """
    arguments = "\n".join(f"        <string>{escape(a)}</string>" for a in argv)
    return _PLIST_TEMPLATE.format(
        label=_LABEL,
        arguments=arguments,
        stdout=escape(str(stdout)),
        stderr=escape(str(stderr)),
    )


_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{arguments}
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
