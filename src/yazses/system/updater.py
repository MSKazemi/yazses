"""Self-update for `yazses update` — check the matching source, upgrade if newer.

YazSes can be installed several ways (snap, `uv tool`, pipx, plain pip). This
module detects which one the running interpreter came from, looks up the latest
version from the source that matches (the tracked snap channel for snap, PyPI for
the pip-family installs), and only reports an update when it is *strictly* newer
than the running version — it never offers a downgrade.

Network (PyPI) and subprocess (snap/upgrade) are isolated behind small helpers so
the decision logic stays pure and testable offline.
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version


@dataclass
class UpdateStatus:
    method: str                       # snap | uv | pipx | pip | unknown
    current: str
    latest: str | None
    available: bool
    command: list[str] | None         # the upgrade command to run (None if N/A)
    note: str = ""


# ---- install-method detection ----------------------------------------------

def detect_install_method(package_file: str | None = None) -> str:
    """Infer how YazSes was installed from the package's on-disk location.

    ``package_file`` defaults to this package's ``__file__``; pass an explicit
    path in tests. Returns ``snap`` | ``uv`` | ``pipx`` | ``pip``.
    """
    path = package_file if package_file is not None else __file__
    p = path.replace("\\", "/")
    if "/snap/" in p:
        return "snap"
    if "/uv/tools/" in p:
        return "uv"
    if "/pipx/" in p:
        return "pipx"
    return "pip"


# ---- version comparison ----------------------------------------------------

def is_newer(latest: str, current: str) -> bool:
    """True iff ``latest`` is a strictly newer version than ``current``.

    Returns False (never offer an update) if either string is not a valid
    version, so a parse failure can't trigger a spurious or downgrade upgrade.
    """
    try:
        return Version(latest) > Version(current)
    except (InvalidVersion, TypeError):
        return False


# ---- source parsers (pure) -------------------------------------------------

def _pypi_version_from_json(payload: dict) -> str | None:
    try:
        return payload["info"]["version"]
    except (KeyError, TypeError):
        return None


def _snap_tracked_version(info_text: str) -> str | None:
    """Parse `snap info` output for the version on the *tracked* channel.

    Falls back to None when the tracked channel shows ``--`` (no release).
    """
    tracked = None
    for line in info_text.splitlines():
        s = line.strip()
        if s.startswith("tracking:"):
            tracked = s.split(":", 1)[1].strip()
            break
    if not tracked:
        return None
    # Channel rows look like "  latest/edge:  0.5.1 2026-05-31 (11) 136MB -".
    prefix = tracked + ":"
    for line in info_text.splitlines():
        s = line.strip()
        if s.startswith(prefix):
            rest = s[len(prefix):].strip()
            token = rest.split()[0] if rest else "--"
            return None if token in ("--", "") else token
    return None


# ---- source lookups (network / subprocess) ---------------------------------

def latest_pypi_version(package: str = "yazses", *, timeout: float = 5.0) -> str | None:
    """Latest released version from PyPI's JSON API, or None on any failure."""
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (https only)
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return _pypi_version_from_json(payload)


def latest_snap_version(name: str = "yazses", *, timeout: float = 10.0) -> str | None:
    """Latest version on the tracked snap channel via `snap info`, or None."""
    try:
        out = subprocess.run(
            ["snap", "info", name],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return _snap_tracked_version(out.stdout)


def _latest_for_method(method: str, package: str) -> str | None:
    """Resolve the latest version from the source matching the install method."""
    if method == "snap":
        return latest_snap_version(package)
    return latest_pypi_version(package)


# ---- upgrade command -------------------------------------------------------

def upgrade_command(method: str, package: str = "yazses") -> list[str] | None:
    """The shell command that upgrades a `method`-style install (None if unknown)."""
    if method == "snap":
        return ["sudo", "snap", "refresh", package]
    if method == "uv":
        return ["uv", "tool", "upgrade", package]
    if method == "pipx":
        return ["pipx", "upgrade", package]
    if method == "pip":
        return ["pip", "install", "--upgrade", package]
    return None


# ---- orchestration ---------------------------------------------------------

def check_update(
    current: str,
    *,
    method: str | None = None,
    package: str = "yazses",
) -> UpdateStatus:
    """Resolve the install method, find the latest version, decide if newer."""
    method = method or detect_install_method()
    latest = _latest_for_method(method, package)
    if latest is None:
        return UpdateStatus(
            method=method, current=current, latest=None, available=False,
            command=None, note="could not determine the latest version",
        )
    available = is_newer(latest, current)
    return UpdateStatus(
        method=method,
        current=current,
        latest=latest,
        available=available,
        command=upgrade_command(method, package) if available else None,
        note="",
    )


def run_upgrade(status: UpdateStatus) -> int:
    """Run the upgrade command for *status*; return its exit code (1 if none).

    Output is left on the terminal rather than captured, so `yazses update` shows
    the package manager's own progress and hints live. Callers that need to know
    whether the upgrade *took* must use :func:`run_upgrade_checked` — an exit code
    of 0 does not mean the version moved.
    """
    if not status.command:
        return 1
    try:
        return subprocess.run(status.command, check=False).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


@dataclass
class UpgradeOutcome:
    """What actually happened when the upgrade command ran."""

    code: int                 # the command's exit status
    before: str               # the version that was installed when we started
    after: str | None         # the version on disk now; None = could not be read
    expected: str | None      # the version we were trying to reach
    method: str = ""          # snap | uv | pipx | pip — decides the "why not" hint
    command: list[str] | None = None  # what was run, to quote back to the user

    @property
    def changed(self) -> bool:
        """Did the installed version actually move?"""
        return self.after is not None and self.after != self.before

    @property
    def ok(self) -> bool:
        """A clean exit *and* a version that really changed."""
        return self.code == 0 and self.changed


def installed_version(
    *, package: str = "yazses", runner=subprocess.run, timeout: float = 20.0
) -> str | None:
    """The version on disk *right now*, read from a fresh process.

    Deliberately out-of-process: after an upgrade the caller is still running the
    code it started with, and its own import machinery has already resolved the
    old distribution. Asking the console script is what a user would do, and it is
    the only answer that reflects what the next launch will actually run.

    Falls back to reading our own metadata (with the import caches invalidated) when
    the console script cannot be reached — a frozen bundle, or `yazses` not on PATH.
    """
    try:
        proc = runner(
            [package, "--version"], capture_output=True, text=True, timeout=timeout
        )
        out = f"{proc.stdout or ''} {proc.stderr or ''}".strip()
        if proc.returncode == 0 and out:
            # `yazses --version` prints "yazses X.Y.Z"; take the last token.
            return out.split()[-1]
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    try:
        import importlib
        import importlib.metadata

        importlib.invalidate_caches()
        return importlib.metadata.version(package)
    except Exception:
        return None


def pinned_install_hint(method: str, command: list[str] | None) -> str:
    """How to get out of an install that refuses to upgrade itself.

    ``uv tool upgrade`` reports "Nothing to upgrade" and exits **0** when the tool was
    installed with an exact version pin (``uv tool install yazses==2.19.0``). The fix is
    to reinstall unpinned — and it has to carry the extras across, because a bare
    ``yazses@latest`` installs base dependencies only and takes PySide6 with it, which
    silently removes the Qt tray and the overlay.
    """
    if method == "uv":
        return (
            "An install pinned to an exact version will not upgrade itself. Reinstall it "
            "unpinned, keeping your extras:\n"
            "    uv tool install 'yazses[desktop]@latest'"
        )
    joined = " ".join(command or [])
    if joined:
        return f"Run it in a terminal to see what it reported:\n    {joined}"
    return "Run `yazses update` in a terminal to see what it reported."


def run_upgrade_checked(
    status: UpdateStatus, *, upgrade=None, read_version=None
) -> UpgradeOutcome:
    """Run the upgrade, then *verify* it by re-reading the installed version.

    The exit code alone is not evidence. `uv tool upgrade` exits 0 and prints
    "Nothing to upgrade" when the tool was installed with an exact version pin
    (`uv tool install yazses==2.19.0`), and the pip family behaves the same way for
    a constraint it cannot satisfy. Reporting that as "Updated to 2.20.0" sends the
    user off to restart a daemon that comes back on exactly the version they had —
    which is the failure this function exists to make impossible.
    """
    # Resolved here rather than as default arguments: a default binds the function
    # object at definition time, so patching the module attribute in a test (or
    # swapping it at runtime) would never be seen.
    upgrade = upgrade or run_upgrade
    read_version = read_version or installed_version

    code = upgrade(status)
    return UpgradeOutcome(
        code=code,
        before=status.current,
        after=read_version(),
        expected=status.latest,
        method=status.method,
        command=status.command,
    )
