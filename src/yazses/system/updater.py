"""Self-update for `yazses update` — check the matching source, upgrade if newer.

YazSes can be installed several ways (snap, `uv tool`, pipx, plain pip, and on
Windows the .exe installer, Chocolatey, winget or Scoop). This module detects
which one the running interpreter came from, looks up the latest version from the
source that matches (the tracked snap channel for snap, the GitHub release for the
Windows channels — that is where the .exe actually lives — PyPI for the pip-family
installs), and only reports an update when it is *strictly* newer than the running
version — it never offers a downgrade.

Why the Windows methods have to exist here
------------------------------------------
Detection used to be three path substrings with ``pip`` as the fallback, so every
Windows install — the Inno installer, Chocolatey, winget, Scoop — came out as
``pip`` and was told to run ``pip install --upgrade yazses``. Inside a PyInstaller
bundle there is no pip at all; where a system pip does exist, that command installs
an unrelated second copy into some other Python and leaves the .exe the user
actually launches sitting at the old version, having printed success. A wrong
upgrade command that exits 0 is worse than no upgrade command, so the frozen
build now says what it really is and hands back real steps.

Network (PyPI/GitHub) and subprocess (snap/upgrade) are isolated behind small
helpers so the decision logic stays pure and testable offline. Every network
helper answers ``None`` rather than raising: a firewall that blocks the check must
degrade to "here is how to update by hand", never to a traceback.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field

from packaging.version import InvalidVersion, Version

# Package identifiers per channel, and where the Windows .exe is published.
WINGET_ID = "MSKazemi.YazSes"
RELEASES_URL = "https://github.com/MSKazemi/yazses/releases/latest"
_RELEASES_API = "https://api.github.com/repos/MSKazemi/yazses/releases/latest"

# Methods whose artifact is the Windows installer .exe rather than a Python wheel.
# They share a version source (the GitHub release) and a manual upgrade story.
WINDOWS_METHODS = ("windows-installer", "choco", "winget", "scoop")


@dataclass
class UpdateStatus:
    # snap | uv | pipx | pip | windows-installer | choco | winget | scoop | unknown
    method: str
    current: str
    latest: str | None
    available: bool
    command: list[str] | None         # the upgrade command to run (None if N/A)
    note: str = ""
    # Human steps for the cases a command cannot cover: the Windows installer
    # (nothing to shell out to) and a blocked/absent network (nothing to check
    # against). Always populated, so a caller never has to invent guidance.
    steps: list[str] = field(default_factory=list)


# ---- install-method detection ----------------------------------------------

def _choco_marker_present() -> bool:
    """True when Chocolatey's package DB has a yazses entry (cheap, no subprocess).

    Chocolatey installs the same Inno .exe as a direct download, so the install
    directory is identical and the only on-disk difference is this marker.
    """
    root = os.environ.get("ChocolateyInstall") or r"C:\ProgramData\chocolatey"
    return os.path.isdir(os.path.join(root, "lib", "yazses"))


def detect_install_method(
    package_file: str | None = None,
    *,
    frozen: bool | None = None,
    choco: bool | None = None,
) -> str:
    """Infer how YazSes was installed from the package's on-disk location.

    ``package_file`` defaults to this package's ``__file__``; pass an explicit
    path in tests. ``frozen``/``choco`` default to probing the running process
    (``sys.frozen`` — set by PyInstaller — and Chocolatey's package directory) and
    are injectable so the classification is testable on any OS.

    Returns ``snap`` | ``uv`` | ``pipx`` | ``pip`` | ``windows-installer`` |
    ``choco`` | ``winget`` | ``scoop``.
    """
    path = package_file if package_file is not None else __file__
    p = path.replace("\\", "/")
    if "/snap/" in p:
        return "snap"
    # Scoop keeps its own app tree, so the path alone is conclusive — check it
    # before the frozen branch, since a Scoop install of the .exe is also frozen.
    if "/scoop/apps/" in p:
        return "scoop"
    if frozen if frozen is not None else bool(getattr(sys, "frozen", False)):
        # One .exe, several channels that ship it. Chocolatey is distinguishable
        # from a marker on disk; winget is not without querying its database, so
        # it is offered as an alternative in the manual steps instead of being
        # guessed at here. Guessing wrong would print an upgrade command that
        # silently does nothing.
        if choco if choco is not None else _choco_marker_present():
            return "choco"
        return "windows-installer"
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


def _github_version_from_json(payload: dict) -> str | None:
    """Version from a GitHub "latest release" payload (``v2.19.0`` → ``2.19.0``).

    A draft or prerelease is refused: those tags exist before their assets do, and
    pointing a user at a release whose .exe is not uploaded yet is a dead end.
    """
    try:
        if payload.get("draft") or payload.get("prerelease"):
            return None
        tag = payload["tag_name"]
    except (KeyError, TypeError, AttributeError):
        return None
    if not isinstance(tag, str) or not tag:
        return None
    return tag[1:] if tag[:1].lower() == "v" else tag


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


def latest_github_release(*, timeout: float = 5.0) -> str | None:
    """Latest published (non-draft, non-prerelease) release tag, or None on failure.

    This is the source of truth for the Windows channels: the installer .exe is a
    GitHub release asset, and PyPI can lag a tag (or, as has happened, never
    receive it), so asking PyPI about a .exe install can report "up to date" when
    it is not.
    """
    req = urllib.request.Request(
        _RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "yazses-update-check"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https only)
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return _github_version_from_json(payload)


def _latest_for_method(method: str, package: str) -> str | None:
    """Resolve the latest version from the source matching the install method."""
    if method == "snap":
        return latest_snap_version(package)
    if method in WINDOWS_METHODS:
        return latest_github_release()
    return latest_pypi_version(package)


def source_name(method: str) -> str:
    """Human name of the source a `method` install is checked against."""
    if method == "snap":
        return "the snap store"
    if method in WINDOWS_METHODS:
        return "github.com"
    return "PyPI"


# ---- upgrade command -------------------------------------------------------

def upgrade_command(method: str, package: str = "yazses") -> list[str] | None:
    """The shell command that upgrades a `method`-style install (None if unknown).

    ``windows-installer`` deliberately has no command. The upgrade is a new .exe
    that has to be downloaded and run, and there is nothing safe to shell out to —
    so that method answers None and callers fall back to :func:`manual_update_steps`.
    """
    if method == "snap":
        return ["sudo", "snap", "refresh", package]
    if method == "uv":
        return ["uv", "tool", "upgrade", package]
    if method == "pipx":
        return ["pipx", "upgrade", package]
    if method == "pip":
        return ["pip", "install", "--upgrade", package]
    if method == "choco":
        return ["choco", "upgrade", package, "-y"]
    if method == "winget":
        return ["winget", "upgrade", "--id", WINGET_ID, "-e"]
    if method == "scoop":
        return ["scoop", "update", package]
    return None


# ---- manual instructions ---------------------------------------------------

_WINDOWS_ALTERNATIVES = [
    f"If you installed with winget:      winget upgrade --id {WINGET_ID} -e",
    "If you installed with Chocolatey:  choco upgrade yazses -y",
    "If you installed with Scoop:       scoop update yazses",
]


def manual_update_steps(method: str, package: str = "yazses") -> list[str]:
    """Step-by-step instructions for updating by hand, for the cases a command can't.

    Two of them, and both are ordinary rather than exceptional: the Windows
    installer (there is no command to run — the upgrade is a downloaded .exe), and
    a machine whose outbound network is blocked (a firewall, an offline site, a
    proxy). Neither is a reason to leave the user with an error and nothing else,
    which is what "could not determine the latest version" used to be.
    """
    if method in WINDOWS_METHODS:
        steps = [
            f"Open the releases page:  {RELEASES_URL}",
            "Download the newest YazSes-<version>-windows-<arch>.exe",
            "Run it — it upgrades in place and keeps your settings and models",
            "Restart YazSes (tray → Restart daemon, or `yazses restart`)",
        ]
        # A Chocolatey/winget/Scoop install can also upgrade through its own
        # package manager; list those rather than assuming the direct download.
        return steps + [""] + _WINDOWS_ALTERNATIVES
    command = upgrade_command(method, package)
    if command:
        return [
            f"Run:  {' '.join(command)}",
            "Restart the daemon afterwards:  yazses restart",
        ]
    return [
        f"Upgrade {package} the same way you installed it",
        f"Release notes and downloads:  {RELEASES_URL}",
    ]


def offline_steps(method: str, package: str = "yazses") -> list[str]:
    """What to tell someone whose update *check* could not reach the network.

    YazSes keeps working — dictation is entirely local and a blocked update check
    changes nothing about it. So this says that first, then gives the steps that
    still work once they are on a network (or on another machine).
    """
    return [
        f"YazSes keeps working — the update check needs {source_name(method)}, "
        "dictation does not.",
        "When you can reach the network again, update with:",
        *manual_update_steps(method, package),
    ]


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
            command=None,
            note=f"could not reach {source_name(method)} — offline, or a firewall is blocking it",
            steps=offline_steps(method, package),
        )
    available = is_newer(latest, current)
    return UpdateStatus(
        method=method,
        current=current,
        latest=latest,
        available=available,
        command=upgrade_command(method, package) if available else None,
        note="",
        steps=manual_update_steps(method, package) if available else [],
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
