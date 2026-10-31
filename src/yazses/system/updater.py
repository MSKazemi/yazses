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
import re
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from packaging.version import InvalidVersion, Version

from yazses.system.opencv_health import (  # noqa: F401 - re-exported
    CV2_CONTRIB,
    CV2_DISTRIBUTIONS,
    installed_cv2_versions,
    uses_cv2,
)

# Package identifiers per channel, and where the Windows .exe is published.
WINGET_ID = "MSKazemi.YazSes"
RELEASES_URL = "https://github.com/MSKazemi/yazses/releases/latest"
_RELEASES_API = "https://api.github.com/repos/MSKazemi/yazses/releases/latest"

# Where someone lands when the upgrade reported success and changed nothing.
#
# A repair to the update path cannot be delivered *through* the update path: the
# person who needs it is, by definition, running the build without it. So the way
# out has to be reachable by hand, and it has to be a page rather than only a
# command — a page can be corrected after the fact without shipping a client,
# which is the one property a message compiled into the old build does not have.
RECOVERY_URL = "https://mskazemi.com/yazses/how-to/update-did-nothing.html"

# Methods whose artifact is the Windows installer .exe rather than a Python wheel.
# They share a version source (the GitHub release) and a manual upgrade story.
WINDOWS_METHODS = ("windows-installer", "choco", "winget", "scoop")

# The macOS .app, installed from the .dmg. It needs its own name for one reason:
# `detect_install_method` classified *anything frozen* as `windows-installer`, so a
# Mac user opening "Check for updates" was told to download a
# `YazSes-<version>-windows-<arch>.exe`. Not a silent failure — a confident wrong
# instruction, which is worse, because it sends someone to a file that will not run
# on their machine and offers no hint that the advice itself is the problem.
MACOS_METHODS = ("macos-app",)

# The MSIX package (ADR-027). The same PyInstaller payload as the .exe, so it is frozen
# too, and it used to be classified `windows-installer` — which offered it the .exe:
# running that beside an MSIX installs a second, unrelated copy rather than updating
# the package. An MSIX updates through whatever installed it (the Store, or App
# Installer for a sideloaded package), so it gets steps that say so and no one-click.
MSIX_METHODS = ("msix",)

# Methods whose version comes from the GitHub release rather than PyPI, because the
# artifact *is* a release asset. Keep this separate from WINDOWS_METHODS: that tuple
# also selects Windows-specific prose, and folding the two together is how the .app
# came to be described as an .exe in the first place.
GITHUB_METHODS = (*WINDOWS_METHODS, *MACOS_METHODS, *MSIX_METHODS)


@dataclass
class UpdateStatus:
    # snap | uv | pipx | pip | windows-installer | choco | winget | scoop
    # | macos-app | msix | unknown
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
    platform: str | None = None,
    msix: bool | None = None,
    prefix: str | None = None,
) -> str:
    """Infer how YazSes was installed from the package's on-disk location.

    A ``uv tool install`` is recognised by the ``uv-receipt.toml`` uv writes at the
    root of the tool's environment, read at *prefix* — by default ``sys.prefix``,
    the environment actually running, but only when *package_file* is not given, so
    a test that names a path is never answered by the test runner's own venv. The
    path substrings remain as a fallback. They alone used to decide it, so an
    install under a custom ``UV_TOOL_DIR`` read as ``pip`` and `yazses update` told
    the user to ``pip install --upgrade yazses`` — which upgrades some other
    environment and leaves the running one where it was.

    ``package_file`` defaults to this package's ``__file__``; pass an explicit
    path in tests. ``frozen``/``choco`` default to probing the running process
    (``sys.frozen`` — set by PyInstaller — and Chocolatey's package directory) and
    are injectable so the classification is testable on any OS.

    Returns ``snap`` | ``uv`` | ``pipx`` | ``pip`` | ``windows-installer`` |
    ``choco`` | ``winget`` | ``scoop`` | ``macos-app`` | ``msix``.

    ``msix`` defaults to the platform seam's ``HostInfo.msix_packaged`` — the same fact
    ``cameraperm/matrix.py`` uses — rather than a second reading of the bundle here.

    Note: a winget install runs the same Inno installer into the same directory as a
    direct download, and nothing on disk distinguishes the two, so it is classified
    ``windows-installer``; the ``winget`` method is not produced by this function.

    ``platform`` defaults to ``sys.platform`` and exists for the same reason the
    others do: the frozen branch used to answer ``windows-installer`` on **any**
    platform, so every macOS ``.app`` was told to download a Windows ``.exe``. A
    bundle is not a Windows bundle; it is a bundle on whichever OS is running it.
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
        if (platform if platform is not None else sys.platform) == "darwin":
            # The .dmg .app. Homebrew installs the same bundle, and the two are not
            # distinguishable from inside the process without probing the Caskroom —
            # so rather than guess, `brew upgrade --cask` is offered as an
            # alternative in the steps. A wrong command that exits 0 having done
            # nothing is the failure this whole module keeps being written against.
            return "macos-app"
        if msix if msix is not None else _msix_packaged():
            return "msix"
        # One .exe, several channels that ship it. Chocolatey is distinguishable
        # from a marker on disk; winget is not without querying its database, so
        # it is offered as an alternative in the manual steps instead of being
        # guessed at here. Guessing wrong would print an upgrade command that
        # silently does nothing.
        if choco if choco is not None else _choco_marker_present():
            return "choco"
        return "windows-installer"
    # The receipt is uv's own record that this environment is a tool install, so it
    # holds wherever UV_TOOL_DIR points. A pipx venv carries pipx_metadata.json and
    # a plain venv neither, so neither can be mistaken for one.
    root = prefix if prefix is not None else (sys.prefix if package_file is None else None)
    if root:
        try:
            if os.path.isfile(os.path.join(root, "uv-receipt.toml")):
                return "uv"
        except (OSError, ValueError):  # pragma: no cover - an unreadable root: fall back
            pass
    # `uv/tools` on Unix, `uv\data\tools` on Windows (`uv help tool dir`): the
    # fallback for a tool environment whose receipt is missing or unreadable.
    if "/uv/tools/" in p or "/uv/data/tools/" in p:
        return "uv"
    if "/pipx/" in p:
        return "pipx"
    return "pip"


def _msix_packaged() -> bool:
    """``HostInfo.msix_packaged`` through the platform seam. Never raises."""
    try:
        from yazses.platform.factory import describe_host

        return bool(describe_host().msix_packaged)
    except Exception:
        return False


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
    if method in GITHUB_METHODS:
        return latest_github_release()
    return latest_pypi_version(package)


def source_name(method: str) -> str:
    """Human name of the source a `method` install is checked against."""
    if method == "snap":
        return "the snap store"
    if method in GITHUB_METHODS:
        return "github.com"
    return "PyPI"


# ---- upgrade command -------------------------------------------------------

def upgrade_command(method: str, package: str = "yazses") -> list[str] | None:
    """The shell command that upgrades a `method`-style install (None if unknown).

    ``windows-installer`` and ``macos-app`` deliberately have no command. The
    upgrade is a new .exe or .dmg that has to be downloaded and run, and there is
    nothing safe to shell out to — so those methods answer None and callers fall
    back to :func:`manual_update_steps`.
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


# Homebrew ships the same .app as the .dmg, and nothing inside the running bundle
# distinguishes the two without probing the Caskroom. It is offered as an
# alternative rather than detected, for the same reason winget is above.
_MACOS_ALTERNATIVES = [
    "If you installed with Homebrew:  brew upgrade --cask yazses",
]


def manual_update_steps(method: str, package: str = "yazses") -> list[str]:
    """Step-by-step instructions for updating by hand, for the cases a command can't.

    Three of them, and all are ordinary rather than exceptional: the Windows
    installer (there is no command to run — the upgrade is a downloaded .exe), the
    macOS .app (the same, with a .dmg), and a machine whose outbound network is
    blocked (a firewall, an offline site, a proxy). None is a reason to leave the
    user with an error and nothing else, which is what "could not determine the
    latest version" used to be.
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
    if method in MSIX_METHODS:
        # No .msix is published on the releases page, and the .exe there would install
        # a second copy beside the package rather than update it.
        return [
            "This is the MSIX package — it updates through whatever installed it:",
            "From the Microsoft Store:  Store → Library → Get updates",
            "Sideloaded:  open the newer .msix with App Installer",
            "Do not run the .exe installer over it — that installs a second copy",
        ]
    if method in MACOS_METHODS:
        return [
            f"Open the releases page:  {RELEASES_URL}",
            "Download the newest YazSes-<version>-macos-<arch>.dmg",
            "Open it and drag YazSes.app to Applications, replacing the old one",
            "Restart YazSes (tray → Restart daemon, or `yazses restart`)",
            "",
            *_MACOS_ALTERNATIVES,
        ]
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
    # Set when OpenCV (`cv2`) worked before the upgrade, or a camera feature is on,
    # and it does not load afterwards: the exact command that repairs it. See
    # :func:`run_upgrade_checked`. None = nothing to repair (or nothing checked).
    cv2_repair: list[str] | None = None

    @property
    def changed(self) -> bool:
        """Did the installed version actually move?"""
        return self.after is not None and self.after != self.before

    @property
    def ok(self) -> bool:
        """A clean exit, a version that really changed, and nothing left broken."""
        return self.code == 0 and self.changed and not self.cv2_repair


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

    Every method ends at :data:`RECOVERY_URL`. The reinstall command is not known for
    all of them, and the old fallback — "run it in a terminal to see what it reported" —
    told someone who had just run it exactly nothing. Only commands checked against the
    real tool are quoted here; a guessed flag that also does nothing repeats the failure
    this whole path exists to correct.
    """
    escape = {
        "uv": (
            "An install pinned to an exact version will not upgrade itself. Reinstall it "
            "unpinned, keeping your extras:\n"
            "    uv tool install 'yazses[desktop]@latest'"
        ),
        "pipx": (
            "pipx upgrades from the source it recorded when you installed. If that was a "
            "folder that has since been deleted, the upgrade cannot find it and nothing "
            "changes. Reinstall from PyPI, keeping your extras:\n"
            "    pipx install --force 'yazses[desktop]'"
        ),
        "pip": (
            "A pin or a constraint file makes --upgrade a no-op. Force the reinstall, "
            "keeping your extras:\n"
            "    pip install --upgrade --force-reinstall 'yazses[desktop]'"
        ),
        "snap": (
            "A held snap refuses to refresh and still exits 0. Release the hold first:\n"
            "    sudo snap refresh --unhold yazses\n"
            "    sudo snap refresh yazses"
        ),
    }.get(method)

    if method == "windows-installer":
        # No shell command upgrades the .exe channel — the upgrade *is* a download.
        # Quoting one would be the same class of untruth as trusting the exit code.
        escape = f"Download and run the current installer:\n    {RELEASES_URL}"
    elif method in MSIX_METHODS:
        escape = (
            "The MSIX package updates through the Microsoft Store (Library → Get "
            "updates) or by opening the newer .msix — not through the .exe installer."
        )
    elif method in MACOS_METHODS:
        # Same shape as the installer: the upgrade is a download, not a command.
        # Homebrew is named because a cask install is the one case where a command
        # exists — and the tap publishes after a release, so it can lag.
        escape = (
            "Download and open the current .dmg, replacing YazSes.app in "
            f"Applications:\n    {RELEASES_URL}\n"
            "If you installed with Homebrew:  brew upgrade --cask yazses"
        )
    elif method in WINDOWS_METHODS:
        # choco/winget/scoop each carry their own manifest, and those are published
        # after the release rather than with it — they were still on 2.19.0 for a
        # while after v2.20.0 shipped. So "already up to date" here is usually the
        # channel lagging, which the user cannot fix and should not keep retrying.
        escape = (
            f"{method} may still be publishing the previous version — its manifest is "
            "updated after a release, not with it. To get the current release now, "
            f"download and run the installer:\n    {RELEASES_URL}"
        )
    elif escape is None:
        joined = " ".join(command or [])
        ran = f"\n{joined} finished without upgrading anything." if joined else ""
        escape = f"Reinstall YazSes the way you first installed it.{ran}"

    return f"{escape}\nIf that does not move it either:  {RECOVERY_URL}"


# ---- keeping enabled features across a uv-tool upgrade ---------------------
#
# Kept apart from everything above on purpose: it concerns only the `uv` method,
# and touches nothing on the Windows/installer paths.


def _enabled_requirements() -> tuple[str, ...]:
    """Requirements of every enabled feature whose libraries are installed now.

    Best effort, like the rest of this module: an unreadable config answers
    "nothing to keep", which leaves the upgrade exactly as it always was. Callers
    first confirm this interpreter *is* a uv tool install (see
    :func:`preserve_enabled_features`); this only reads the config.
    """
    try:
        from yazses.config import load_config
        from yazses.platform import get_platform
        from yazses.system.dormant import preserved_requirements

        cfg = load_config(get_platform().paths.config_file)
        return preserved_requirements(cfg)
    except Exception:  # noqa: BLE001 - must never break an update
        return ()


def preserve_enabled_features(
    status: UpdateStatus, *, required=None, command_for=None
) -> UpdateStatus:
    """*status* with an upgrade command that keeps every enabled feature's libraries.

    ``uv tool upgrade yazses`` rebuilds the tool environment from its receipt and
    removes whatever the receipt does not list — which is how the tray's "Install
    update" silently deleted an enabled Parakeet engine. A `features enable` from
    this version records its packages in the receipt, but one from an older
    version (or one that took the fallback path) did not, and nothing repaired
    that on the next upgrade. This does: when an enabled, working feature's
    requirement is not on the receipt, the command becomes
    ``uv tool install --upgrade --with … <target>`` (see
    :func:`yazses.system.deps.uv_tool_upgrade_command` for the evidence).

    Unchanged for every other method, for an unchanged receipt, and whenever
    anything here fails. Idempotent: a command it already rewrote is left alone.
    ``required``/``command_for`` are injectable for tests.

    "Is this a uv tool install?" is answered by finding the install's own
    ``uv-receipt.toml`` through ``uv tool dir`` (:func:`deps._uv_tool_receipt`),
    never by a path substring. A substring cannot see ``UV_TOOL_DIR`` and missed
    the Windows default, ``%APPDATA%\\uv\\data\\tools`` (per ``uv help tool dir``),
    so on both this silently did nothing. The receipt is resolved once and handed
    to the command builder, so ``uv tool dir`` runs once per update.
    """
    if status.method != "uv" or status.command != upgrade_command("uv"):
        return status
    try:
        from yazses.system import deps

        receipt = None
        if required is None:
            receipt = deps._uv_tool_receipt()
            if receipt is None:
                return status  # not a uv tool install: nothing it could drop
            packages = _enabled_requirements()
        else:
            packages = tuple(required())
        if command_for is None:
            def command_for(pkgs):
                return deps.uv_tool_upgrade_command(pkgs, receipt=receipt)
        command = command_for(packages) if packages else None
    except Exception:  # noqa: BLE001 - must never break an update
        return status
    if not command:
        return status
    import dataclasses

    return dataclasses.replace(status, command=list(command))


# ---- keeping OpenCV (cv2) whole across an upgrade ---------------------------
#
# `opencv-python` and `opencv-contrib-python` are separate distributions that write
# the same `cv2/` package. Up to 2.43.2 the camera features installed both (the gaze
# extra named the plain build, mediapipe requires contrib). From the release that
# names only contrib, `uv tool upgrade yazses` removes the now-unrequired
# `opencv-python` -- and uninstalling it deletes every file in its RECORD, including
# the ones contrib also wrote. What is left of `cv2/` is a namespace package: `import
# cv2` still exits 0, and `cv2.VideoCapture` is an AttributeError.
#
# Reproduced offline on Linux, Python 3.12, uv 0.12.21, the 5.0.0.93 wheels from the uv
# cache, and a hand-built tool whose 1.0 required both builds and 2.0 contrib only:
# both `uv tool upgrade <tool>` and `uv tool install --upgrade --with … <tool>` exit 0,
# print `- opencv-python==5.0.0.93`, and leave cv2 broken. The same two commands with
# `--reinstall-package opencv-contrib-python` print `~ opencv-contrib-python` beside
# the removal and leave cv2 working. (`uv tool upgrade --help` and `uv tool install
# --help` both list `--reinstall-package` in 0.12.21.)
#
# pip and pipx never remove a dependency that stopped being required, so their
# upgrade cannot cause this; they get the post-upgrade check and its repair command
# only. Kept apart from the Parakeet-preserving step above, and always run *after*
# it: that step recognises the plain `uv tool upgrade yazses`, and a flag added
# first would make it silently do nothing (:func:`resolve_upgrade_command`).

# `CV2_CONTRIB` (the distribution mediapipe requires and the camera features need) and
# `CV2_DISTRIBUTIONS` (every PyPI distribution that writes the top-level `cv2/`
# package) live in `system/opencv_health.py`, which the daemon's start-up check imports
# without this module's network imports; re-exported here for the existing callers.

#: What YazSes needs of cv2 (`VideoCapture` and `cvtColor`). A bare `import cv2`
#: is not a test: the broken package still imports, as a namespace.
_CV2_CHECK = "import cv2; cv2.VideoCapture; cv2.cvtColor"

#: Run by the environment's own interpreter: the OpenCV distributions installed in it.
_CV2_VERSIONS_PROBE = (
    "import importlib.metadata as m, json, sys\n"
    "out = {}\n"
    "for name in sys.argv[1:]:\n"
    "    try:\n"
    "        out[name] = m.version(name)\n"
    "    except m.PackageNotFoundError:\n"
    "        pass\n"
    "print(json.dumps(out))\n"
)

#: Methods whose upgrade rebuilds a Python environment YazSes can inspect.
_PYTHON_ENV_METHODS = ("uv", "pipx", "pip")


def cv2_owners(versions: dict[str, str]) -> list[str]:
    """The installed distributions (of *versions*) that write ``cv2/``. Pure."""
    return [d for d in CV2_DISTRIBUTIONS if d in versions]


def needs_contrib_reinstall(versions: dict[str, str]) -> bool:
    """Contrib is installed beside another ``cv2`` owner. Pure.

    Whichever of them an upgrade removes takes contrib's files with it, so contrib
    has to be reinstalled in the same step. Reinstalling it when nothing is removed
    costs a relink from the cache and changes nothing else.
    """
    return CV2_CONTRIB in versions and len(cv2_owners(versions)) >= 2


def with_contrib_reinstall(command: list[str]) -> list[str]:
    """*command* (a ``uv tool upgrade`` or ``uv tool install``) that also reinstalls
    contrib. Pure and idempotent.

    The flag goes in front of the last argument -- the tool target -- which is where
    both reproduced shapes carried it: ``uv tool upgrade --reinstall-package
    opencv-contrib-python yazses`` and ``uv tool install --upgrade --with …
    --reinstall-package opencv-contrib-python yazses[desktop]``.
    """
    flag = ["--reinstall-package", CV2_CONTRIB]
    for i in range(len(command) - 1):
        if command[i : i + 2] == flag:
            return list(command)
    if command[:3] not in (["uv", "tool", "upgrade"], ["uv", "tool", "install"]):
        return list(command)
    return [*command[:-1], *flag, command[-1]]


def cv2_repair_command(
    method: str, versions: dict[str, str], *, python: str, package: str = "yazses"
) -> list[str]:
    """The command that rewrites a broken ``cv2/`` in place. Pure.

    It reinstalls one owner, with ``--no-deps`` so nothing else moves, pinned to the
    version the environment's metadata reports *after* the upgrade (an installed
    environment has no lock file to read it from). Contrib when it is installed,
    since it is the one the camera features need; otherwise whichever owner is.
    The ``uv`` form was checked against the broken environment of the reproduction
    (offline, from the uv cache); the pip and pipx forms were not run.
    """
    owners = cv2_owners(versions)
    dist = CV2_CONTRIB if CV2_CONTRIB in versions or not owners else owners[0]
    spec = f"{dist}=={versions[dist]}" if dist in versions else dist
    if method == "uv":
        return ["uv", "pip", "install", "--python", python, "--reinstall", "--no-deps", spec]
    if method == "pipx":
        return ["pipx", "runpip", package, "install", "--force-reinstall", "--no-deps", spec]
    return [python, "-m", "pip", "install", "--force-reinstall", "--no-deps", spec]


def _pip_importable() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("pip") is not None
    except (ImportError, ValueError):
        return False


def cv2_repair_here(
    *,
    method: str | None = None,
    versions: dict[str, str] | None = None,
    python: str | None = None,
    has_pip: Callable[[], bool] | None = None,
) -> list[str] | None:
    """:func:`cv2_repair_command` for the environment that is running, or ``None``.

    For the surfaces that find a half-deleted ``cv2`` outside an upgrade -- the
    daemon's start-up check and ``yazses doctor`` -- so they print the same pinned
    repair an upgrade does. ``None`` for an install that is not a Python environment
    YazSes can repair (a snap, a frozen bundle). A ``pip``-classified environment
    with no pip in it (a ``uv venv`` / ``uv sync`` environment, which uv does not seed
    with pip) gets the ``uv pip`` form, because ``python -m pip`` would fail there.
    Every input is injectable for tests.
    """
    method = method if method is not None else detect_install_method()
    if method not in _PYTHON_ENV_METHODS:
        return None
    found = versions if versions is not None else installed_cv2_versions()
    interpreter = python if python is not None else env_python(sys.prefix)
    if method == "pip" and not (has_pip or _pip_importable)():
        method = "uv"
    return cv2_repair_command(method, found, python=interpreter)


def should_verify_cv2(
    owners_before: list[str], works_before: bool | None, camera_enabled
) -> bool:
    """Whether to check ``cv2`` after the upgrade. Pure (*camera_enabled* is a callable,
    asked only when the answer depends on it, so the config is read only then).

    Only when an OpenCV distribution is installed -- otherwise ``cv2`` is nothing the
    upgrade could break -- and either it loaded before the upgrade or a camera feature
    is switched on (it may already have been broken by an earlier upgrade).
    """
    if not owners_before:
        return False
    if works_before:
        return True
    return bool(camera_enabled())


@dataclass(frozen=True)
class OpenCVProbe:
    """How to look at OpenCV in the environment being upgraded. Injectable in tests.

    ``versions(fresh)`` answers ``{distribution: version}`` for the ``cv2`` owners
    present *now* (*fresh*: read by a new process of the environment's interpreter); ``works()`` answers whether that environment's own interpreter can use
    ``cv2`` (None = could not ask); ``camera_enabled()`` whether a camera feature is on.
    """

    python: str
    versions: Callable[[bool], dict[str, str]]
    works: Callable[[], bool | None]
    camera_enabled: Callable[[], bool]


def env_python(prefix: str, *, platform: str | None = None) -> str:
    """The interpreter of the environment at *prefix* (falls back to ``sys.executable``).

    Built from the prefix rather than taken from ``sys.executable``, which on Windows is
    ``pythonw.exe`` in the tray and the settings window -- no console, no output.
    """
    platform = platform if platform is not None else sys.platform
    if platform.startswith("win"):
        candidates = [os.path.join(prefix, "Scripts", "python.exe"),
                      os.path.join(prefix, "python.exe")]
    else:
        candidates = [os.path.join(prefix, "bin", "python"),
                      os.path.join(prefix, "bin", "python3")]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return sys.executable


def _no_window() -> dict:
    """``creationflags`` that keep a probe from flashing a console on Windows."""
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": flag} if flag else {}


def _env_cv2_versions(
    python: str, *, prefix: str, fresh: bool = False, runner=subprocess.run
) -> dict[str, str]:
    """``{distribution: version}`` for the ``cv2`` owners in the environment at *prefix*.

    Asked of that environment's own interpreter, in a fresh process, whenever it is not
    the one running -- or when *fresh* is set, which the after-upgrade read always is:
    a process that started before the upgrade is not the witness to what it left.
    Before the upgrade, in the running environment, the in-process metadata is the
    same answer without a process, and it keeps the common case (no OpenCV at all)
    free. Never raises; an unreadable answer is "none installed".
    """
    running = os.path.normcase(os.path.abspath(sys.prefix))
    if not fresh and os.path.normcase(os.path.abspath(prefix)) == running:
        return installed_cv2_versions()
    try:
        proc = runner(
            [python, "-c", _CV2_VERSIONS_PROBE, *CV2_DISTRIBUTIONS],
            capture_output=True, text=True, timeout=30, **_no_window(),
        )
        data = json.loads(proc.stdout or "{}") if proc.returncode == 0 else {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def _env_cv2_works(python: str, *, runner=subprocess.run) -> bool | None:
    """Can the environment's own interpreter use ``cv2``? None = could not ask.

    ``-P`` (Python 3.11+) keeps the working directory off ``sys.path``, so a stray
    ``cv2.py`` beside wherever the tray was started cannot answer for the package.
    """
    try:
        proc = runner(
            [python, "-P", "-c", _CV2_CHECK],
            capture_output=True, text=True, timeout=60, **_no_window(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.returncode == 0


def _camera_feature_enabled() -> bool:
    """Is a camera feature (one that imports ``cv2``) switched on? False on any error."""
    try:
        from yazses.config import load_config
        from yazses.platform import get_platform
        from yazses.system.features import feature_status

        cfg = load_config(get_platform().paths.config_file)
        return any(f.on and f.wired and uses_cv2(f) for f in feature_status(cfg))
    except Exception:  # noqa: BLE001 - must never break an update
        return False


def default_opencv_probe(prefix: str | None = None) -> OpenCVProbe:
    """The real probe, for the environment at *prefix* (default: the running one)."""
    root = prefix if prefix is not None else sys.prefix
    python = env_python(root)

    def versions(fresh: bool = False) -> dict[str, str]:
        return _env_cv2_versions(python, prefix=root, fresh=fresh)

    return OpenCVProbe(
        python=python,
        versions=versions,
        works=lambda: _env_cv2_works(python),
        camera_enabled=_camera_feature_enabled,
    )


def keep_cv2_whole(status: UpdateStatus, *, opencv: OpenCVProbe | None = None) -> UpdateStatus:
    """*status* whose ``uv`` upgrade also reinstalls contrib when two ``cv2`` owners
    are installed. Unchanged otherwise, and whenever anything here fails.

    Only the two uv tool shapes are touched; pip and pipx never remove a dependency
    on upgrade. Must run after :func:`preserve_enabled_features` -- call
    :func:`resolve_upgrade_command`, which fixes that order, rather than this.
    """
    if status.method != "uv" or not status.command:
        return status
    try:
        probe = opencv or default_opencv_probe()
        if not needs_contrib_reinstall(probe.versions(False)):
            return status
        command = with_contrib_reinstall(list(status.command))
    except Exception:  # noqa: BLE001 - must never break an update
        return status
    if command == status.command:
        return status
    import dataclasses

    return dataclasses.replace(status, command=command)


# ---- a pipx install whose source no longer exists ---------------------------
#
# `pipx install /path/to/checkout` records that *path* as the package source in the
# venv's `pipx_metadata.json`, and `pipx upgrade` re-reads it every time. Delete the
# checkout (a git worktree, a build directory) and `pipx upgrade yazses` prints
# "Unable to parse package spec: <path>" and moves nothing, so the tray's "Install now"
# never changed the version (the exit status it reports varies between pipx versions).
# Checked against pipx 1.4.3 in a throwaway PIPX_HOME: `pipx install --force yazses`
# reinstalls into the same venv, keeps injected packages, rewrites the source to the
# PyPI name, and leaves a `pipx upgrade` that works. It only finds the same venv when
# the install has no `--suffix` and pipx is looking at the PIPX_HOME that holds it;
# otherwise it would install a second copy, so the command is left alone.

def _pipx_main_package(root: str) -> dict | None:
    """The `main_package` record pipx keeps for the venv at *root*, or None when it
    cannot be read -- not a pipx venv, or damaged."""
    try:
        with open(os.path.join(root, "pipx_metadata.json"), encoding="utf-8") as fh:
            record = json.load(fh)["main_package"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return record if isinstance(record, dict) else None


def _pipx_source(prefix: str | None) -> str | None:
    """The package source pipx recorded for the environment at *prefix* (default: the
    running one), or None when it cannot be read."""
    record = _pipx_main_package(prefix if prefix is not None else sys.prefix)
    spec = record.get("package_or_url") if record else None
    return spec.strip() if isinstance(spec, str) and spec.strip() else None


def _pipx_home() -> str | None:
    """The PIPX_HOME that `pipx` itself would use from this process, or None."""
    try:
        out = subprocess.run(
            ["pipx", "environment", "--value", "PIPX_HOME"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    home = out.stdout.strip()
    return home if out.returncode == 0 and home else None


# Comma-separated extra names (PEP 685 normalises them to letters, digits, `-`, `_`, `.`).
_EXTRAS = re.compile(r"[A-Za-z0-9._-]+(?:,[A-Za-z0-9._-]+)*")


# `name[extras] @ location`, spaces around the `@` optional. The name cannot hold a
# slash, so a local path that happens to contain an `@` is not mistaken for one.
_DIRECT_REFERENCE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?)\s*@\s*(.+)")


def _split_extras(spec: str) -> tuple[str, str]:
    """``"path[a,b]"`` -> ``("path", "a,b")``; no trailing extras -> ``(spec, "")``."""
    if spec.endswith("]") and "[" in spec:
        head, _, tail = spec.rpartition("[")
        return head, tail[:-1].replace(" ", "")
    return spec, ""


def stale_pipx_source(spec: str) -> str | None:
    """The extras (``"gaze,desktop"``, possibly empty) to carry across when *spec* is a
    local folder or file that no longer exists; None for every source that is fine.

    Only a source that is *gone* counts. A PyPI name (with extras or a version range)
    upgrades normally, a git/https URL is somebody's deliberate choice, and a local
    path that still exists is a developer's own checkout -- none of those is touched.
    """
    head, extras = _split_extras(spec)
    direct = _DIRECT_REFERENCE.fullmatch(head.strip())
    if direct:
        # A PEP 508 direct reference. pipx records it as `str(Requirement)`, which is
        # `yazses[desktop]@ file:///path` (no space before the `@`). The extras sit on
        # the name, the location after the `@`.
        name, location = direct.group(1), direct.group(2).strip()
        extras = _split_extras(name)[1] or extras
    else:
        location = head.strip()
    if location.startswith("file://"):
        from urllib.parse import unquote, urlparse

        location = unquote(urlparse(location).path)
        if os.name == "nt" and location[:1] == "/" and location[2:3] == ":":
            location = location[1:]  # file:///C:/x -> C:/x
    elif "://" in location or location.startswith("git+"):
        return None
    looks_local = bool(location) and (
        os.path.isabs(location)
        or location.startswith(("~", "."))
        or "/" in location
        or "\\" in location
    )
    if not looks_local:
        return None  # a bare name or a version range: PyPI
    return None if os.path.exists(os.path.expanduser(location)) else extras


def repair_pipx_source(
    status: UpdateStatus,
    *,
    prefix: str | None = None,
    package: str = "yazses",
    pipx_home: Callable[[], str | None] = _pipx_home,
) -> UpdateStatus:
    """*status* whose pipx upgrade becomes a reinstall from PyPI when the install's
    recorded source is gone (see above), keeping the extras it was installed with.

    Unchanged for every other method, for any command it did not itself recognise
    (so it is idempotent), for a readable source that is fine, and whenever anything
    here fails -- an update must never be broken by the look-ahead. Also unchanged
    when the reinstall would not land in this venv: a `--suffix` install, or a venv
    that is not `<PIPX_HOME>/venvs/<package>` for the PIPX_HOME pipx reports here.
    *pipx_home* is injectable for tests; it runs only once the source is known stale.
    """
    if status.method != "pipx" or status.command != upgrade_command("pipx", package):
        return status
    root = prefix if prefix is not None else sys.prefix
    try:
        record = _pipx_main_package(root)
        spec = _pipx_source(root)
        extras = stale_pipx_source(spec) if spec else None
        if extras is None or record is None or record.get("suffix"):
            return status
        if extras and not _EXTRAS.fullmatch(extras):
            # The extras are copied into the command, so anything that is not a list of
            # extra names (a damaged record, a stray `]` or `@`) leaves the command alone.
            return status
        home = pipx_home()
        if not home or os.path.realpath(os.path.join(home, "venvs", package)) != (
            os.path.realpath(root)
        ):
            return status
    except Exception:  # noqa: BLE001 - must never break an update
        return status
    import dataclasses

    target = f"{package}[{extras}]" if extras else package
    command = ["pipx", "install", "--force", target]
    # `yazses update` prints the steps after a failure: they must name the command
    # that was run, not the `pipx upgrade` that cannot work.
    old_step = f"Run:  {' '.join(status.command or ())}"
    new_step = f"Run:  {' '.join(command)}"
    steps = [new_step if step == old_step else step for step in status.steps]
    return dataclasses.replace(status, command=command, steps=steps)


def resolve_upgrade_command(
    status: UpdateStatus,
    *,
    opencv: OpenCVProbe | None = None,
    pipx_prefix: str | None = None,
    pipx_home: Callable[[], str | None] | None = None,
) -> UpdateStatus:
    """The one upgrade command every surface shows and runs. Idempotent.

    ``yazses update``, the Settings window and the tray resolve it before they display
    it, and :func:`run_upgrade_checked` resolves it again before running it, so what
    the user was shown is what runs. The order is load-bearing: the step that keeps
    enabled features' libraries recognises only the *plain* ``uv tool upgrade
    yazses``, so it runs first, and the ``cv2`` step adds its flag to whatever that
    produced (either uv shape).
    """
    status = repair_pipx_source(status, prefix=pipx_prefix, pipx_home=pipx_home or _pipx_home)
    status = preserve_enabled_features(status)
    return keep_cv2_whole(status, opencv=opencv)


def run_upgrade_checked(
    status: UpdateStatus, *, upgrade=None, read_version=None, opencv=None
) -> UpgradeOutcome:
    """Run the upgrade, then *verify* it by re-reading the installed version.

    The exit code alone is not evidence. `uv tool upgrade` exits 0 and prints
    "Nothing to upgrade" when the tool was installed with an exact version pin
    (`uv tool install yazses==2.19.0`), and the pip family behaves the same way for
    a constraint it cannot satisfy. Reporting that as "Updated to 2.20.0" sends the
    user off to restart a daemon that comes back on exactly the version they had —
    which is the failure this function exists to make impossible.

    The same holds for what the upgrade left behind. When an OpenCV distribution is
    installed and ``cv2`` loaded before the upgrade (or a camera feature is on), the
    environment's own interpreter is asked to use ``cv2`` afterwards; if it cannot,
    the outcome carries the exact repair command (:attr:`UpgradeOutcome.cv2_repair`)
    and is not ``ok``. *opencv* is injectable for tests.
    """
    # Resolved here rather than as default arguments: a default binds the function
    # object at definition time, so patching the module attribute in a test (or
    # swapping it at runtime) would never be seen.
    upgrade = upgrade or run_upgrade
    read_version = read_version or installed_version

    probe = None
    verify = False
    if status.method in _PYTHON_ENV_METHODS and status.command:
        try:
            probe = opencv or default_opencv_probe()
            owners = cv2_owners(probe.versions(False))
            works_before = probe.works() if owners else None
            verify = should_verify_cv2(owners, works_before, probe.camera_enabled)
        except Exception:  # noqa: BLE001 - must never break an update
            verify = False

    status = resolve_upgrade_command(status, opencv=probe)
    code = upgrade(status)
    after = read_version()
    repair = None
    if code == 0 and verify and probe is not None:
        try:
            if probe.works() is False:
                repair = cv2_repair_command(
                    status.method, probe.versions(True), python=probe.python
                )
        except Exception:  # noqa: BLE001 - a failed check is reported as no check
            repair = None
    return UpgradeOutcome(
        code=code,
        before=status.current,
        after=after,
        expected=status.latest,
        method=status.method,
        command=status.command,
        cv2_repair=repair,
    )
