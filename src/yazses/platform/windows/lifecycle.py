"""Windows daemon lifecycle — instance lock and PID file, detached spawn, HKCU\\Run autostart."""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path, PureWindowsPath

from yazses.platform.base import Paths
from yazses.platform.windows.update_handoff import APP_EXE
from yazses.system.proc import process_alive as _process_alive
from yazses.system.single_instance import holder_pid

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = "YazSes"

#: The console binary the spec builds beside ``YazSesApp.exe`` (packaging/windows/yazses.spec).
_CLI_EXE = "yazses-cli.exe"

#: The lock the daemon holds for its whole life (``core/daemon.py``), under ``data_dir``.
_LOCK_NAME = "daemon.lock"

#: The windowed launcher pip writes for the ``yazses-tray`` gui-script.
_TRAY_SCRIPT = "yazses-tray.exe"

#: ``Run`` value tail for an install that has no tray launcher to name.
_TRAY_MODULE_ARGS = " -m yazses.tray.app"

# The console interpreter, as opposed to its windowed twin pythonw*.exe.
_CONSOLE_PYTHON = re.compile(r"python(\d+(\.\d+)?)?\.exe", re.IGNORECASE)

# GetExitCodeProcess reports this while a process is still running.
_STILL_ACTIVE = 259
# OpenProcess access right that is enough to read an exit code.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# python.exe / pythonw.exe from python.org and uv; python3.exe and python3.11.exe from
# the Microsoft Store, whose interpreter runs under the versioned name even when it was
# started as python.exe.
_PYTHON_IMAGE = re.compile(r"pythonw?(\d+(\.\d+)?)?\.exe")


def process_alive(pid: int) -> bool:
    """True when *pid* names a live process. Never terminates anything.

    The implementation, and the explanation of why ``os.kill(pid, 0)`` may not be used
    here, now live in :mod:`yazses.system.proc` — this was the only copy for a while and
    two other call sites kept the destructive idiom because of it.
    """
    return _process_alive(pid)


def is_yazses_image(tasklist_csv: str) -> bool:
    """True when `tasklist /FO CSV /NH` output looks like a YazSes process.

    Kept pure so the recycled-PID guard is testable off Windows. Matching a
    bare ``"python"`` would call *any* Python process our daemon, which on a
    developer machine is a coin flip; the image name has to actually be one of
    ours.

    The interpreter's own name counts too, versioned or not. Accepting only
    ``python.exe`` missed the Microsoft Store build, which runs as
    ``python3.11.exe``. A pip or pipx install on it then had `status` saying "not
    running" about a live daemon, `stop` finding nothing to stop, and the tray
    restarting a daemon that had never gone.
    """
    image = tasklist_csv.strip().strip('"').split('","')[0].strip('"').lower()
    if not image:
        return False
    return image.startswith("yazses") or _PYTHON_IMAGE.fullmatch(image) is not None


# Subprocess creation flags — defined here because Linux dev machines don't
# have these constants on the subprocess module.
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_DETACHED_PROCESS = 0x00000008
_CREATE_NO_WINDOW = 0x08000000

# How long `stop_daemon` waits for a graceful shutdown to finish, and how often
# it asks. The RPC acknowledges *receipt*; the real teardown (unload model, close
# IPC server, release hotkey hook) runs afterwards, and the IPC server's close
# alone can take ~2 s. Without this wait a `restart` spawns the new daemon while
# the old one is still mid-teardown, and the named-pipe transport happily hosts
# both (_MAX_INSTANCES = 8), so `status` answers whichever pipe instance Windows
# routes to — stale hotkey included. Reported under #330.
_SHUTDOWN_GRACE_S = 10.0
_SHUTDOWN_POLL_S = 0.05
# And after a force-kill, the same question once more, briefly.
_FORCE_GRACE_S = 5.0


# ---- Pure command resolution ------------------------------------------------
#
# Kept free of winreg/subprocess (and therefore testable off Windows), mirroring
# platform/linux/autostart.py. The frozen bundle and a pip install need different
# argv, and getting either wrong fails silently under a windowed binary.


def resolve_daemon_command(executable: str, frozen: bool) -> list[str]:
    """argv that starts the daemon.

    The PyInstaller bundle dispatches on argv (see ``yazses/__main__.py``), so a
    frozen build takes ``--daemon``. Passing ``-m yazses.main`` to it — as this
    did — matches no mode, falls through to the Typer CLI, and exits 2 parsing
    ``-m``. Under a windowed build that failure is invisible, so the tray spawned
    nothing, forever, with no error anywhere. Same multi-call-binary trap as
    :func:`resolve_tray_command` below, on the other entry point.
    """
    if frozen:
        return [executable, "--daemon"]
    return [executable, "-m", "yazses.main"]


def windowed_interpreter(executable: Path) -> Path | None:
    """The ``pythonw`` beside a console ``python`` (or the one given), else None. Pure."""
    name = executable.name
    if _CONSOLE_PYTHON.fullmatch(name):
        return executable.with_name("pythonw" + name[len("python"):])
    return executable if name.lower().startswith("pythonw") else None


def resolve_tray_command(
    executable: str,
    frozen: bool,
    tray_script: Path | None,
    windowed_exe: Path | None = None,
    windowed_python: Path | None = None,
) -> str:
    """The HKCU\\Run command line that starts YazSes in tray mode.

    Three things this has to get right, and previously got wrong:

    * **Quote the path.** A ``Run`` value is handed to ``CreateProcess`` as a raw
      command line, so an unquoted path containing a space is ambiguous —
      ``C:\\Users\\John Smith\\...\\YazSes.exe`` is first tried as
      ``C:\\Users\\John.exe``. Autostart then silently does nothing (and the
      ambiguity is the classic unquoted-service-path hijack shape). A username
      with a space is entirely ordinary, and the installer's
      ``DefaultDirName={userpf}`` puts us under ``C:\\Users\\<name>\\``.
    * **Pass ``--tray``.** The frozen bundle is one multi-call binary; without the
      flag it does not start in tray mode. ``installer.iss`` already writes
      ``"{app}\\YazSes.exe" --tray``, so omitting it here meant toggling autostart
      in-app *overwrote the installer's correct value with a broken one*.
    * **Name the windowed binary.** The bundle ships two: ``YazSesApp.exe``
      (windowed) and ``yazses-cli.exe`` (console). Run from the CLI, *executable*
      is the console one, and Windows gives a console program a terminal window
      when it starts at sign-in, so ``yazses start`` on a Scoop install left an
      empty window titled ``yazses-cli.exe`` open after every sign-in (#330), and
      ``yazses autostart enable`` swapped the installer's entry for that one. A
      *windowed_exe* that exists wins; without one, *executable* is all there is.
      The same holds outside the bundle: with no *tray_script*, an existing
      *windowed_python* runs the module instead of the console interpreter.
    """
    if frozen:
        if windowed_exe is not None and windowed_exe.exists():
            return f'"{windowed_exe}" --tray'
        return f'"{executable}" --tray'
    if tray_script is not None and tray_script.exists():
        return f'"{tray_script}"'
    if windowed_python is not None and windowed_python.exists():
        return f'"{windowed_python}"{_TRAY_MODULE_ARGS}'
    return f'"{executable}"{_TRAY_MODULE_ARGS}'


def is_console_twin(current: str, wanted: str) -> bool:
    """True when *current* is *wanted* with ``yazses-cli.exe`` in place of ``YazSesApp.exe``.

    That exact value is what an earlier ``yazses start`` or ``yazses autostart enable``
    wrote from the same install folder, so it is the only entry safe to rewrite: one
    pointing anywhere else (another install, a hand-edited command) is the user's,
    and is left alone. The paths compare as Windows paths, not as text: case and
    ``/`` against ``\\`` do not matter, which is also what lets this run off Windows.
    """
    app = _quoted_tray_exe(wanted)
    if app is None or app.name.lower() != APP_EXE.lower():
        return False
    return _quoted_tray_exe(current) == app.with_name(_CLI_EXE)


def is_console_python_entry(current: str, wanted: str) -> bool:
    """True when *current* starts the tray with console ``python`` and *wanted* does not.

    The pip counterpart of :func:`is_console_twin`: *current* is exactly
    ``"<dir>\\python.exe" -m yazses.tray.app``, and *wanted* is that same interpreter's
    ``pythonw``, or its ``yazses-tray.exe`` (beside it, or under its ``Scripts``).
    Any other entry belongs to another install or to the user, and is left alone.
    """
    python = _quoted_exe(current, _TRAY_MODULE_ARGS)
    if python is None or not _CONSOLE_PYTHON.fullmatch(python.name):
        return False
    pythonw = _quoted_exe(wanted, _TRAY_MODULE_ARGS)
    if pythonw is not None:
        return pythonw.name.lower().startswith("pythonw") and pythonw.parent == python.parent
    script = _quoted_exe(wanted, "")
    return (
        script is not None
        and script.name.lower() == _TRAY_SCRIPT
        and script.parent in (python.parent, python.parent / "Scripts")
    )


def _quoted_tray_exe(command: str) -> PureWindowsPath | None:
    """The program in a ``"<path>" --tray`` command line, or None for any other shape."""
    return _quoted_exe(command, " --tray")


def _quoted_exe(command: str, args: str) -> PureWindowsPath | None:
    """The program in a ``"<path>"<args>`` command line, or None for any other shape."""
    suffix = '"' + args
    command = command.strip()
    if not (command.startswith('"') and command.lower().endswith(suffix)):
        return None
    program = command[1 : -len(suffix)]
    return None if '"' in program else PureWindowsPath(program)


class WindowsLifecycle:
    """LifecycleBackend for Windows."""

    def __init__(self, paths: Paths, *, alive_probe: Callable[[int], bool] | None = None) -> None:
        self._paths = paths
        # Injected so the liveness probe can be exercised off Windows.
        self._alive = alive_probe or process_alive

    # ---- PID file ----------------------------------------------------------

    def write_pid(self) -> None:
        self._paths.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self._paths.pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def clear_pid(self) -> None:
        self._paths.pid_file.unlink(missing_ok=True)

    def read_pid(self) -> int | None:
        """The daemon's PID: from the instance lock if it is held, else the PID file.

        The PID file outlives a daemon that Windows ends at sign-out or shutdown, and
        the number in it is soon some other process's. ``yazses restart`` stops whatever
        this returns, and the one-click update waits for it. So a lock that exists and
        is free answers None: the OS releases it the moment the daemon dies. The PID
        file alone decides only where there is no lock file, or the holder wrote no PID.
        Same rule as ``system/pid.py`` on Linux.
        """
        lock = self._paths.data_dir / _LOCK_NAME
        holder = holder_pid(lock)
        if holder is not None and holder > 0:
            return holder
        if holder is None and lock.exists():
            return None
        return self._read_pid_file()

    def _read_pid_file(self) -> int | None:
        try:
            return int(self._paths.pid_file.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            return None

    def is_running(self) -> bool:
        lock = self._paths.data_dir / _LOCK_NAME
        if holder_pid(lock) is not None:
            return True  # held: a daemon runs, whatever the PID file says
        if lock.exists():
            return False
        pid = self._read_pid_file()
        if pid is None:
            return False
        if not self._alive(pid):
            return False
        # Best-effort recycled-PID guard via tasklist.
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
                timeout=2.0,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            return True
        return is_yazses_image(result.stdout)

    # ---- Process spawn / stop ---------------------------------------------

    def start_daemon_detached(self) -> None:
        # CREATE_NEW_PROCESS_GROUP so we can later send CTRL_BREAK_EVENT for a
        # graceful shutdown; CREATE_NO_WINDOW so the console-subsystem daemon has
        # a hidden console rather than a visible one.
        #
        # DETACHED_PROCESS is deliberately NOT part of this flag set any more.
        # It did not buy the daemon its survival — Windows has no parent/child
        # process lifecycle, so the daemon outlives the CLI either way — and on
        # the pipx route it cost a blank console window that sat open for the
        # daemon's whole life: a detached (console-less) parent launching the venv
        # redirector makes *that* give the real interpreter a brand-new visible
        # console, because a console program with no console gets one when it
        # spawns one. CREATE_NO_WINDOW instead hands the daemon an invisible
        # console that the redirector's child inherits — no window anywhere, and
        # stdout/stderr are DEVNULL regardless. #330.
        flags = _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW
        argv = resolve_daemon_command(sys.executable, bool(getattr(sys, "frozen", False)))
        log.info("Starting daemon detached: %s", argv)
        subprocess.Popen(
            argv,
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

    def stop_daemon(self, pid: int) -> None:
        # Try a graceful shutdown first via the IPC `shutdown` RPC. The
        # caller (cli.stop) doesn't know about IPC, so we attempt it here
        # before falling back to TerminateProcess.
        #
        # And then *wait for the process to actually exit*. The RPC returns when
        # the daemon acknowledges, not when it is gone; returning at the ack let
        # `restart` spawn the successor while the predecessor still held a live
        # IPC server on the same pipe (up to 8 coexist by design), which is how
        # `status` kept answering with the *old* hotkey after a clean-looking
        # restart. #330.
        rpc_acknowledged = False
        try:
            from yazses.ipc.client import IpcUnreachableError
            from yazses.platform.windows.ipc import NamedPipeIpcClient

            client = NamedPipeIpcClient(self._paths.ipc_socket, timeout_s=1.0)
            try:
                client.call("shutdown")
                rpc_acknowledged = True
            except IpcUnreachableError:
                pass
            except Exception as exc:
                log.warning("Graceful shutdown RPC failed: %s; falling back to kill.", exc)
        except Exception:
            log.exception("Could not attempt graceful shutdown")

        if rpc_acknowledged and self._wait_for_exit(pid, _SHUTDOWN_GRACE_S):
            return

        # Forceful fallback. signal.SIGTERM on Windows maps to TerminateProcess.
        if rpc_acknowledged:
            log.info("Daemon %s did not exit within %.0fs; terminating.", pid, _SHUTDOWN_GRACE_S)
        else:
            log.info("No graceful shutdown for daemon %s; terminating.", pid)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return  # exited between the last probe and the signal — that is success
        if not self._wait_for_exit(pid, _FORCE_GRACE_S):
            # Nothing further we can do that does not risk a recycled-PID kill.
            # Say so loudly instead of pretending; the supervisor in cli sees the
            # stale PID through `is_running` and the user gets an honest state.
            log.warning("Daemon %s survived termination; still alive after %.0fs.", pid, _FORCE_GRACE_S)

    def _wait_for_exit(self, pid: int, grace_s: float) -> bool:
        """Poll the liveness probe until *pid* is gone or *grace_s* elapses.

        Returns True on exit. Never touches the PID file and never sends a
        signal: this asks a question, it does not take action (see
        :mod:`yazses.system.proc` for why that distinction is load-bearing here).
        """
        deadline = time.monotonic() + grace_s
        while time.monotonic() < deadline:
            if not self._alive(pid):
                return True
            time.sleep(_SHUTDOWN_POLL_S)
        return not self._alive(pid)

    # ---- Autostart (HKCU\Run) ---------------------------------------------

    def install_autostart(self) -> None:
        try:
            import winreg  # type: ignore[import-not-found]
        except ImportError:
            log.error("winreg unavailable; not on Windows?")
            return
        target = self._tray_executable()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, target)

    def uninstall_autostart(self) -> None:
        try:
            import winreg  # type: ignore[import-not-found]
        except ImportError:
            return
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, _RUN_VALUE_NAME)
        except FileNotFoundError:
            pass

    def is_autostart_installed(self) -> bool:
        try:
            import winreg  # type: ignore[import-not-found]
        except ImportError:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, _RUN_VALUE_NAME)
                return bool(value)
        except (FileNotFoundError, OSError):
            return False

    def repair_autostart(self) -> bool:
        """Point an entry this install wrote for a console program at the windowed one.

        Returns True when it rewrote the entry. Fixes installs that already carry a
        value :func:`resolve_tray_command` used to produce; see :func:`is_console_twin`
        and :func:`is_console_python_entry` for why nothing else is touched.
        """
        try:
            import winreg  # type: ignore[import-not-found]
        except ImportError:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
                current, _ = winreg.QueryValueEx(key, _RUN_VALUE_NAME)
        except OSError:
            return False
        wanted = self._tray_executable()
        if not (
            is_console_twin(str(current), wanted)
            or is_console_python_entry(str(current), wanted)
        ):
            return False
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, wanted)
        log.info("Autostart pointed at the console binary; now %s", wanted)
        return True

    def _tray_executable(self) -> str:
        """The HKCU\\Run command line that starts YazSes in tray mode.

        Two things this has to get right, and previously got wrong:

        * **Quote the path.** A ``Run`` value is handed to ``CreateProcess`` as
          a raw command line, so an unquoted path containing a space is
          ambiguous — ``C:\\Users\\John Smith\\...\\YazSes.exe`` is first tried
          as ``C:\\Users\\John.exe``. Autostart then silently does nothing (and
          the ambiguity is the classic unquoted-service-path hijack shape).
          A username with a space is entirely ordinary, and the installer's
          ``DefaultDirName={userpf}`` puts us under ``C:\\Users\\<name>\\``.
        * **Pass ``--tray``.** The frozen bundle is one multi-call binary;
          without the flag it does not start in tray mode. ``installer.iss``
          already writes ``"{app}\\YazSes.exe" --tray``, so omitting it here
          meant toggling autostart in-app *overwrote the installer's correct
          value with a broken one*.
        * **Name the windowed binary**, not the console one the CLI runs as;
          see :func:`resolve_tray_command`.

        pip puts the tray launcher beside ``python.exe`` in a virtual environment, but
        under ``Scripts`` for an interpreter installed on its own.
        """
        exe = Path(sys.executable)
        scripts = (exe.parent / _TRAY_SCRIPT, exe.parent / "Scripts" / _TRAY_SCRIPT)
        return resolve_tray_command(
            sys.executable,
            bool(getattr(sys, "frozen", False)),
            next((s for s in scripts if s.exists()), None),
            exe.parent / APP_EXE,
            windowed_interpreter(exe),
        )
