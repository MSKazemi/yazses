"""Windows `UpdateLauncher`: run a one-click update after YazSes has exited (ADR-027).

The installer replaces ``YazSesApp.exe``, ``yazses-cli.exe`` and the Python runtime in
``_internal\\`` — the very files the tray, the daemon and the CLI are executing. So the
update cannot be run *by* YazSes and waited on; it is handed to a detached Windows
PowerShell job that

1. waits for the YazSes processes it was given to exit,
2. re-checks the installer's SHA-256 immediately before running it (so the shutdown
   window cannot be used to swap the file),
3. runs the installer silently (or the package manager's upgrade), recording the exit
   code — elevated only where that is needed (Chocolatey); an Inno installer from an
   all-users install raises its own UAC prompt,
4. deletes the downloaded installer, and
5. starts YazSes again, **whether or not** the update worked: a failed update must leave
   the user with a running old version, never with no YazSes at all.

The script is passed with ``-EncodedCommand`` (UTF-16LE, base64), not as a ``.ps1`` file
or a ``cmd /c`` line: that sidesteps the execution policy for a file, cmd's ``%`` and
``&`` parsing, and the OEM code page — a Persian or accented user name in the temp path
must not be what breaks the update.

Everything except :meth:`WindowsUpdateLauncher.hand_off`'s spawn and the architecture
probe is pure and tested off Windows.
"""
from __future__ import annotations

import base64
import logging
import os
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

# Process-creation flags; not all exist on `subprocess` off Windows.
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000

#: How long the job waits for each YazSes process before going ahead anyway (the
#: installer's Restart Manager then closes whatever is left).
WAIT_SECONDS = 90

#: Exit codes the job itself records, alongside the installer's own.
EXIT_NOT_STARTED = -1
EXIT_HASH_MISMATCH = -2

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


def build_script(handoff: UpdateHandoff) -> str:
    """The PowerShell job for ``handoff`` (pure; see the module docstring)."""
    q = ps_quote
    lines = [
        "$ErrorActionPreference = 'Continue'",
        f"$log = {q(str(handoff.log_file))}",
        f"$result = {q(str(handoff.result_file))}",
        "function Write-Note([string]$m) { try { Add-Content -LiteralPath $log "
        "-Value ('[' + (Get-Date -Format o) + '] ' + $m) -Encoding UTF8 } catch {} }",
        f"Write-Note {q('YazSes update started: ' + handoff.kind)}",
        "foreach ($id in @(" + ", ".join(str(int(p)) for p in handoff.wait_pids) + ")) {",
        f"  try {{ Wait-Process -Id $id -Timeout {WAIT_SECONDS} -ErrorAction Stop }} catch {{}}",
        "}",
        "Write-Note 'YazSes has exited; starting the update'",
        f"$code = {EXIT_NOT_STARTED}",
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
        "Write-Note ('exit code ' + $code)",
        "try { Set-Content -LiteralPath $result -Value $code -Encoding ASCII } catch {}",
    ]
    for path in handoff.cleanup:
        lines.append(
            f"Remove-Item -LiteralPath {q(str(path))} -Force -ErrorAction SilentlyContinue"
        )
    if handoff.relaunch:
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


# ---- the launcher ------------------------------------------------------------

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


class WindowsUpdateLauncher:
    """``UpdateLauncher`` for Windows. Construction is cheap and touches nothing."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        executable: str | None = None,
        frozen: bool | None = None,
        spawn: Callable[..., Any] | None = None,
        exists: Callable[[str], bool] = os.path.exists,
    ) -> None:
        self._env = env if env is not None else os.environ
        self._executable = executable if executable is not None else sys.executable
        self._frozen = frozen if frozen is not None else bool(getattr(sys, "frozen", False))
        self._spawn = spawn or subprocess.Popen
        self._exists = exists

    def staging_dir(self) -> Path:
        # %TEMP% is per-user (under %LOCALAPPDATA%), so another account cannot write here.
        return Path(tempfile.gettempdir()) / "yazses-update"

    def native_arch(self) -> str:
        return _native_arch_from_api() or arch_from_env(self._env)

    def relaunch_command(self) -> list[str] | None:
        return relaunch_argv(self._executable, self._frozen)

    def hand_off(self, handoff: UpdateHandoff) -> None:
        powershell = default_powershell(self._env)
        if not self._exists(powershell):
            raise OSError(f"Windows PowerShell was not found at {powershell}")
        argv = powershell_argv(powershell, build_script(handoff))
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
    "EXIT_HASH_MISMATCH",
    "EXIT_NOT_STARTED",
    "WindowsUpdateLauncher",
    "arch_from_env",
    "build_script",
    "default_powershell",
    "encode_command",
    "powershell_argv",
    "ps_quote",
    "relaunch_argv",
    "windows_command_line",
]
