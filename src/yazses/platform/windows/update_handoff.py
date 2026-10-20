"""Windows `UpdateLauncher`: run a one-click update after YazSes has exited (ADR-027).

The installer replaces ``YazSesApp.exe``, ``yazses-cli.exe`` and the Python runtime in
``_internal\\`` — the very files the tray, the daemon and the CLI are executing. So the
update cannot be run *by* YazSes and waited on; it is handed to a detached Windows
PowerShell job that

1. waits — up to :data:`WAIT_SECONDS` in total — for the YazSes processes it was given to
   exit, and **aborts** (records :data:`EXIT_STILL_RUNNING`, installs nothing) if any is
   still running then: a daemon still saving a meeting must not be force-closed,
2. re-checks the installer's SHA-256 immediately before running it,
3. runs the installer silently — never elevated — or the package manager's upgrade, by
   absolute path; only Chocolatey is elevated, and only ``choco.exe`` from its
   administrator-owned install directory is ever run that way,
4. records the exit code, deletes the downloaded installer and the single-flight lock, and
5. starts YazSes again, **whether or not** the update worked: a failed update must leave
   the user with a running old version, never with no YazSes at all.

The script is passed with ``-EncodedCommand`` (UTF-16LE, base64), not as a ``.ps1`` file
or a ``cmd /c`` line: that sidesteps the execution policy for a file, cmd's ``%`` and
``&`` parsing, and the OEM code page — a Persian or accented user name in the temp path
must not be what breaks the update.

Before anything is offered, :meth:`WindowsUpdateLauncher.query_package_manager` asks
Chocolatey, winget or Scoop which version *its own feed* carries, so the button never
promises a version the manager will not deliver; and :meth:`install_scope` reads the Inno
uninstall key so an all-users install is never handed a temp-folder installer to elevate.

Everything except the spawns, the registry reads and the architecture probe is pure and
tested off Windows.
"""
from __future__ import annotations

import base64
import dataclasses
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path, PureWindowsPath
from typing import Any

from yazses.platform.base import UpdateHandoff

log = logging.getLogger(__name__)

#: The windowed binary the installer's shortcuts and HKCU\\Run start (installer.iss).
APP_EXE = "YazSesApp.exe"

#: installer.iss `AppId`; Inno writes its uninstall key as ``{AppId}_is1``.
_INNO_APP_ID = "{F3E8B8A4-1B6C-4F24-9BE8-9B7E58E9C4A2}"
UNINSTALL_SUBKEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + _INNO_APP_ID + "_is1"
)
_MACHINE_ENV_SUBKEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
#: Chocolatey's documented default install directory.
DEFAULT_CHOCOLATEY_ROOT = r"C:\ProgramData\chocolatey"

# Process-creation flags; not all exist on `subprocess` off Windows.
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000

#: Total time the job waits for every YazSes process to exit before it gives up and
#: installs nothing. Long, because a daemon finishing a meeting transcript is slow and is
#: exactly the case a force-close would destroy.
WAIT_SECONDS = 300

#: Exit codes the job itself records, alongside the installer's own. The same values as
#: `system/installer_update.py`, which describes them on the next start.
EXIT_NOT_STARTED = -1
EXIT_HASH_MISMATCH = -2
EXIT_STILL_RUNNING = -3

#: How each package manager is asked which version its own feed carries. Read-only.
FEED_QUERIES: dict[str, list[str]] = {
    "choco": ["choco", "search", "yazses", "--exact", "--limit-output"],
    "winget": ["winget", "show", "--id", "MSKazemi.YazSes", "-e",
               "--accept-source-agreements", "--disable-interactivity"],
    "scoop": ["scoop", "info", "yazses"],
}
_QUERY_TIMEOUT_S = 60.0

# PowerShell treats all of these as single quotes inside a single-quoted string.
_PS_QUOTES = ("'", "\u2018", "\u2019", "\u201a", "\u201b")

_IMAGE_FILE_MACHINE = {0x8664: "x64", 0xAA64: "arm64", 0x014C: "x86"}


# ---- pure helpers -----------------------------------------------------------

def ps_quote(value: str) -> str:
    """A PowerShell single-quoted literal. Every quote-like character is doubled."""
    text = str(value)
    for q in _PS_QUOTES:
        text = text.replace(q, q + q)
    return f"'{text}'"


def windows_command_line(args: list[str] | tuple[str, ...]) -> str:
    """Join arguments into one Windows command line for ``Start-Process``.

    ``/KEY=VALUE`` switches with a space keep Inno Setup's documented spelling,
    ``/LOG="C:\\path with space\\x.log"``; everything else uses the MS C runtime rules.
    """
    parts = []
    for arg in args:
        if arg.startswith("/") and "=" in arg and (" " in arg or "\t" in arg):
            key, value = arg.split("=", 1)
            parts.append(f'{key}="{value}"')
        else:
            parts.append(subprocess.list2cmdline([arg]))
    return " ".join(parts)


def relaunch_argv(executable: str, frozen: bool) -> list[str] | None:
    """argv that starts the tray again after the update, or ``None`` if unknown.

    Only the frozen bundle has a fixed ``YazSesApp.exe`` beside it. A Scoop install runs
    from ``apps\\yazses\\<version>\\``; after ``scoop update`` the new files live under a
    new version directory reached through the ``current`` junction, so relaunching the
    old versioned path would start the old version — it is rewritten to ``current``.
    """
    if not frozen or not executable:
        return None
    exe = PureWindowsPath(executable)
    parts = list(exe.parent.parts)
    lowered = [p.lower() for p in parts]
    for i in range(len(lowered) - 2):
        if lowered[i] == "scoop" and lowered[i + 1] == "apps" and i + 3 < len(parts):
            # ...\scoop\apps\yazses\<version>\...  →  ...\scoop\apps\yazses\current\...
            parts[i + 3] = "current"
            break
    return [str(PureWindowsPath(*parts) / APP_EXE), "--tray"]


def arch_from_env(env: Mapping[str, str]) -> str:
    """The machine's architecture from the environment, the way build-windows.ps1 reads
    it: ``PROCESSOR_ARCHITEW6432`` (set under WOW64) before ``PROCESSOR_ARCHITECTURE``."""
    from yazses.system.installer_update import normalize_arch

    raw = env.get("PROCESSOR_ARCHITEW6432") or env.get("PROCESSOR_ARCHITECTURE") or ""
    return normalize_arch(raw)


def _same_dir(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    norm = [str(PureWindowsPath(x.strip().strip('"'))).rstrip("\\/").casefold() for x in (a, b)]
    return norm[0] == norm[1]


def scope_for(app_dir: str | None, user_location: str | None,
              machine_location: str | None) -> str:
    """Which Inno uninstall key owns the running install (pure).

    Matched on the install directory, not on which key exists: a machine can carry both
    (an old all-users install left behind), and only the one this process runs from
    decides how the upgrade will run.
    """
    if _same_dir(app_dir, user_location):
        return "user"
    if _same_dir(app_dir, machine_location):
        return "machine"
    return "unknown"


def chocolatey_exe(machine_root: str | None, exists: Callable[[str], bool]) -> str | None:
    """Absolute path of ``choco.exe`` to run elevated, or ``None`` (pure given ``exists``).

    ``machine_root`` is the **machine** environment's ``ChocolateyInstall`` (HKLM), not
    this process's environment: a user-level variable is writable by any process running
    as the user, and an elevated run of whatever it names is exactly the privilege
    boundary ADR-027 refuses to open. A value that still needs expanding is not trusted.
    """
    root = machine_root if machine_root and "%" not in machine_root else DEFAULT_CHOCOLATEY_ROOT
    for candidate in (PureWindowsPath(root) / "choco.exe",
                      PureWindowsPath(root) / "bin" / "choco.exe"):
        if exists(str(candidate)):
            return str(candidate)
    return None


def _wait_block(pids: tuple[int, ...]) -> list[str]:
    ids = ", ".join(str(int(p)) for p in pids)
    return [
        f"$pids = @({ids})",
        f"$deadline = (Get-Date).AddSeconds({WAIT_SECONDS})",
        "foreach ($id in $pids) {",
        "  $left = [int][Math]::Max(1, ($deadline - (Get-Date)).TotalSeconds)",
        "  try { Wait-Process -Id $id -Timeout $left -ErrorAction Stop } catch {}",
        "}",
        "$still = @($pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })",
    ]


def build_script(handoff: UpdateHandoff) -> str:
    """The PowerShell job for ``handoff`` (pure; see the module docstring).

    Raises ``ValueError`` for an elevated installer: a file in the user's temp folder is
    never run with administrator rights (ADR-027).
    """
    if handoff.elevate and handoff.kind == "installer":
        raise ValueError("a downloaded installer is never run elevated")
    q = ps_quote
    lines = [
        "$ErrorActionPreference = 'Continue'",
        f"$log = {q(str(handoff.log_file))}",
        f"$result = {q(str(handoff.result_file))}",
        "function Write-Note([string]$m) { try { Add-Content -LiteralPath $log "
        "-Value ('[' + (Get-Date -Format o) + '] ' + $m) -Encoding UTF8 } catch {} }",
        f"Write-Note {q('YazSes update started: ' + handoff.kind)}",
        *_wait_block(handoff.wait_pids),
        f"$code = {EXIT_NOT_STARTED}",
        "if ($still.Count -gt 0) {",
        f"  $code = {EXIT_STILL_RUNNING}",
        "  Write-Note ('YazSes did not exit in time (pid ' + ($still -join ', ') + "
        "'); nothing was installed')",
        "} else {",
        "Write-Note 'YazSes has exited; starting the update'",
        "try {",
    ]
    program, args = handoff.argv[0], list(handoff.argv[1:])
    if handoff.sha256:
        lines += [
            f"  $hash = (Get-FileHash -LiteralPath {q(program)} -Algorithm SHA256)"
            ".Hash.ToLowerInvariant()",
            f"  if ($hash -ne {q(handoff.sha256.lower())}) {{",
            f"    $code = {EXIT_HASH_MISMATCH}",
            "    throw ('SHA-256 mismatch immediately before running: ' + $hash)",
            "  }",
        ]
    if handoff.capture_output and not handoff.elevate:
        call = " ".join(["&", q(program), *(q(a) for a in args)])
        lines += [
            "  $global:LASTEXITCODE = $null",
            f"  $out = {call} 2>&1",
            "  $ok = $?",
            "  $out | Out-File -LiteralPath $log -Append -Encoding UTF8",
            "  if ($null -ne $LASTEXITCODE) { $code = $LASTEXITCODE } "
            "elseif ($ok) { $code = 0 } else { $code = 1 }",
        ]
    else:
        start = f"  $p = Start-Process -FilePath {q(program)}"
        if args:
            start += f" -ArgumentList {q(windows_command_line(args))}"
        if handoff.elevate:
            start += " -Verb RunAs"
        start += " -PassThru"
        lines += [
            start,
            # Touching .Handle before the process exits is what makes ExitCode readable
            # afterwards in Windows PowerShell 5.1.
            "  $null = $p.Handle",
            "  $p.WaitForExit()",
            "  $code = $p.ExitCode",
        ]
    lines += [
        "} catch {",
        "  Write-Note ('the update did not run: ' + $_.Exception.Message)",
        "}",
        "}",
        "Write-Note ('exit code ' + $code)",
        "try { Set-Content -LiteralPath $result -Value $code -Encoding ASCII } catch {}",
    ]
    for path in handoff.cleanup:
        lines.append(
            f"Remove-Item -LiteralPath {q(str(path))} -Force -ErrorAction SilentlyContinue"
        )
    if handoff.relaunch:
        # Outside every branch above: whatever happened, YazSes is started again. If a
        # process was still running, the second tray finds the single-instance lock held
        # and exits quietly.
        relaunch = f"Start-Process -FilePath {q(handoff.relaunch[0])}"
        if len(handoff.relaunch) > 1:
            relaunch += f" -ArgumentList {q(windows_command_line(handoff.relaunch[1:]))}"
        lines.append(
            f"try {{ {relaunch} }} catch {{ Write-Note ('relaunch failed: ' + "
            "$_.Exception.Message) }"
        )
    return "\r\n".join(lines) + "\r\n"


def encode_command(script: str) -> str:
    """``-EncodedCommand`` payload: base64 of the UTF-16LE script."""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def powershell_argv(powershell: str, script: str) -> list[str]:
    return [
        powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden", "-EncodedCommand", encode_command(script),
    ]


def default_powershell(env: Mapping[str, str]) -> str:
    """Windows PowerShell by absolute path, so a ``powershell.exe`` earlier on PATH (or
    in the working directory) is never the one run."""
    root = env.get("SystemRoot") or env.get("SYSTEMROOT") or r"C:\Windows"
    return str(PureWindowsPath(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


# ---- Windows-only probes ------------------------------------------------------

def _native_arch_from_api() -> str | None:
    """The *machine's* architecture even under emulation (an x64 build on ARM64 sees
    ``AMD64`` in its environment). ``IsWow64Process2`` is Windows 10 1511+."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = getattr(ctypes, "windll").kernel32
        process_machine = wintypes.USHORT()
        native_machine = wintypes.USHORT()
        ok = kernel32.IsWow64Process2(
            kernel32.GetCurrentProcess(),
            ctypes.byref(process_machine),
            ctypes.byref(native_machine),
        )
        if not ok:
            return None
        return _IMAGE_FILE_MACHINE.get(int(native_machine.value))
    except Exception:
        return None


def _read_registry(hive: str, subkey: str, names: tuple[str, ...]) -> str | None:
    """First of ``names`` present under ``hive\\subkey``, or None. Never raises."""
    try:
        import importlib

        # Through importlib so the module types as Any: typeshed's winreg is gated on
        # sys.platform == "win32", and mypy runs on Linux.
        winreg: Any = importlib.import_module("winreg")
        root = getattr(winreg, hive)
        with winreg.OpenKey(root, subkey) as key:
            for name in names:
                try:
                    value, _kind = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                if isinstance(value, str) and value:
                    return value
    except Exception:
        return None
    return None


# ---- the launcher ------------------------------------------------------------

RegistryReader = Callable[[str, str, tuple[str, ...]], "str | None"]


class WindowsUpdateLauncher:
    """``UpdateLauncher`` for Windows. Construction is cheap and touches nothing."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        executable: str | None = None,
        frozen: bool | None = None,
        spawn: Callable[..., Any] | None = None,
        run: Callable[..., Any] | None = None,
        exists: Callable[[str], bool] = os.path.exists,
        which: Callable[[str], str | None] = shutil.which,
        registry: RegistryReader | None = None,
    ) -> None:
        self._env = env if env is not None else os.environ
        self._executable = executable if executable is not None else sys.executable
        self._frozen = frozen if frozen is not None else bool(getattr(sys, "frozen", False))
        self._spawn = spawn or subprocess.Popen
        self._run = run or subprocess.run
        self._exists = exists
        self._which = which
        self._registry = registry or _read_registry

    def staging_dir(self) -> Path:
        # %TEMP% is per-user (under %LOCALAPPDATA%), so another account cannot write here.
        return Path(tempfile.gettempdir()) / "yazses-update"

    def native_arch(self) -> str:
        return _native_arch_from_api() or arch_from_env(self._env)

    def relaunch_command(self) -> list[str] | None:
        return relaunch_argv(self._executable, self._frozen)

    def install_scope(self) -> str:
        if not self._frozen:
            return "unknown"
        names = ("Inno Setup: App Path", "InstallLocation")
        return scope_for(
            str(PureWindowsPath(self._executable).parent),
            self._registry("HKEY_CURRENT_USER", UNINSTALL_SUBKEY, names),
            self._registry("HKEY_LOCAL_MACHINE", UNINSTALL_SUBKEY, names),
        )

    def resolve_program(self, name: str) -> str | None:
        """Absolute path for a package manager. Chocolatey is resolved from the machine
        environment (it runs elevated); winget and Scoop from PATH (they do not)."""
        if name == "choco":
            root = self._registry("HKEY_LOCAL_MACHINE", _MACHINE_ENV_SUBKEY, ("ChocolateyInstall",))
            return chocolatey_exe(root, self._exists)
        return self._which(name)

    def query_package_manager(self, method: str) -> str | None:
        argv = FEED_QUERIES.get(method)
        if argv is None:
            return None
        program = self.resolve_program(argv[0])
        if program is None:
            return None
        try:
            proc = self._run(
                [program, *argv[1:]],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=_QUERY_TIMEOUT_S, stdin=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        if proc.returncode != 0:
            return None
        return f"{proc.stdout or ''}\n{proc.stderr or ''}"

    def hand_off(self, handoff: UpdateHandoff) -> None:
        if handoff.kind == "package-manager":
            program = self.resolve_program(handoff.argv[0])
            if program is None:
                raise OSError(f"{handoff.argv[0]} was not found")
            handoff = dataclasses.replace(handoff, argv=(program, *handoff.argv[1:]))
        powershell = default_powershell(self._env)
        if not self._exists(powershell):
            raise OSError(f"Windows PowerShell was not found at {powershell}")
        try:
            script = build_script(handoff)
        except ValueError as exc:
            raise OSError(str(exc)) from exc
        argv = powershell_argv(powershell, script)
        base = _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW
        kwargs: dict[str, Any] = dict(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            cwd=str(handoff.log_file.parent),
        )
        try:
            # Out of any job object YazSes runs in, so the job is not killed with it.
            self._spawn(argv, creationflags=base | _CREATE_BREAKAWAY_FROM_JOB, **kwargs)
        except OSError:
            # A job that forbids breakaway refuses the flag outright; try without it.
            log.info("breakaway refused; starting the update job inside the job object")
            self._spawn(argv, creationflags=base, **kwargs)


__all__ = [
    "APP_EXE",
    "DEFAULT_CHOCOLATEY_ROOT",
    "EXIT_HASH_MISMATCH",
    "EXIT_NOT_STARTED",
    "EXIT_STILL_RUNNING",
    "FEED_QUERIES",
    "UNINSTALL_SUBKEY",
    "WAIT_SECONDS",
    "WindowsUpdateLauncher",
    "arch_from_env",
    "build_script",
    "chocolatey_exe",
    "default_powershell",
    "encode_command",
    "powershell_argv",
    "ps_quote",
    "relaunch_argv",
    "scope_for",
    "windows_command_line",
]
