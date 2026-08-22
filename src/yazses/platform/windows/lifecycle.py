"""Windows daemon lifecycle — PID file + detached spawn + HKCU\\Run autostart."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from yazses.platform.base import Paths

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = "YazSes"

# GetExitCodeProcess reports this while a process is still running.
_STILL_ACTIVE = 259
# OpenProcess access right that is enough to read an exit code.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def process_alive(pid: int) -> bool:
    """True when *pid* names a live process. Never terminates anything.

    ``os.kill(pid, 0)`` is the POSIX idiom for this and is **actively harmful on
    Windows**: CPython's ``os.kill`` has no signal semantics there, so anything
    that is not ``CTRL_C_EVENT``/``CTRL_BREAK_EVENT`` falls through to
    ``TerminateProcess(handle, sig)``. Signal 0 therefore *kills the process*
    and gives it exit code 0 (see https://bugs.python.org/issue14480). Because
    ``yazses status``, ``doctor`` and the tray's poll loop all reach
    ``is_running()``, the liveness probe was killing the very daemon it was
    asked about.

    ``OpenProcess`` + ``GetExitCodeProcess`` is the read-only equivalent.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # ERROR_ACCESS_DENIED (5) means the process exists but belongs to
        # someone else; anything else (typically ERROR_INVALID_PARAMETER) means
        # there is no such process.
        return ctypes.get_last_error() == 5
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def is_yazses_image(tasklist_csv: str) -> bool:
    """True when `tasklist /FO CSV /NH` output looks like a YazSes process.

    Kept pure so the recycled-PID guard is testable off Windows. Matching a
    bare ``"python"`` would call *any* Python process our daemon, which on a
    developer machine is a coin flip; the image name has to actually be one of
    ours.
    """
    image = tasklist_csv.strip().strip('"').split('","')[0].strip('"').lower()
    if not image:
        return False
    return image.startswith("yazses") or image in {"python.exe", "pythonw.exe"}


# Subprocess creation flags — defined here because Linux dev machines don't
# have these constants on the subprocess module.
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_DETACHED_PROCESS = 0x00000008
_CREATE_NO_WINDOW = 0x08000000


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


def resolve_tray_command(executable: str, frozen: bool, tray_script: Path | None) -> str:
    """The HKCU\\Run command line that starts YazSes in tray mode.

    Two things this has to get right, and previously got wrong:

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
    """
    if frozen:
        return f'"{executable}" --tray'
    if tray_script is not None and tray_script.exists():
        return f'"{tray_script}"'
    return f'"{executable}" -m yazses.tray.app'


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
        try:
            return int(self._paths.pid_file.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            return None

    def is_running(self) -> bool:
        pid = self.read_pid()
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
        # graceful shutdown; DETACHED_PROCESS so the daemon survives the parent.
        flags = _CREATE_NEW_PROCESS_GROUP | _DETACHED_PROCESS | _CREATE_NO_WINDOW
        argv = resolve_daemon_command(sys.executable, bool(getattr(sys, "frozen", False)))
        log.info("Starting daemon detached: %s", argv)
        subprocess.Popen(
            argv,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

    def stop_daemon(self, pid: int) -> None:
        # Try a graceful shutdown first via the IPC `shutdown` RPC. The
        # caller (cli.stop) doesn't know about IPC, so we attempt it here
        # before falling back to TerminateProcess.
        try:
            from yazses.ipc.client import IpcUnreachableError
            from yazses.platform.windows.ipc import NamedPipeIpcClient

            client = NamedPipeIpcClient(self._paths.ipc_socket, timeout_s=1.0)
            try:
                client.call("shutdown")
                return
            except IpcUnreachableError:
                pass
            except Exception as exc:
                log.warning("Graceful shutdown RPC failed: %s; falling back to kill.", exc)
        except Exception:
            log.exception("Could not attempt graceful shutdown")

        # Forceful fallback. signal.SIGTERM on Windows maps to TerminateProcess.
        os.kill(pid, signal.SIGTERM)

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
        """
        return resolve_tray_command(
            sys.executable,
            bool(getattr(sys, "frozen", False)),
            Path(sys.executable).parent / "yazses-tray.exe",
        )
