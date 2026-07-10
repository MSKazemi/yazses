"""Author, contact, and project links — the single source of truth surfaced in
the running app (``yazses about``, the ``--help`` epilog, and ``yazses doctor``).

Keep these in step with ``pyproject.toml`` ([project] authors) and
``snap/snapcraft.yaml`` (contact / website / source-code / issues) so every
distribution channel points people at the same author and the same place to
report issues or request features.
"""

from __future__ import annotations

import os
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

APP_NAME = "YazSes"
TAGLINE = "Local, offline voice dictation — hold a key, speak, release."

# ASCII wordmark shown by `yazses about` (and the top of `yazses --help`). Plain
# ASCII only, so it renders in any terminal/codepage; suppressed on non-TTY or
# when NO_COLOR is set (see banner()).
BANNER_ART = r"""
 __   __         ___
 \ \ / /_ _ ___ / __| ___ ___
  \ V / _` |_ /\__ \/ -_|_-<
   |_|\__,_/__||___/\___/__/
""".strip("\n")

AUTHOR = "Mohsen Seyedkazemi Ardebili"
EMAIL = "mohsen.seyedkazemi@gmail.com"

WEBSITE = "https://mskazemi.github.io/yazses/"
SOURCE = "https://github.com/MSKazemi/yazses"
ISSUES = "https://github.com/MSKazemi/yazses/issues"
# Where to propose a new feature — GitHub Discussions if enabled, otherwise a
# labelled issue works just as well.
FEATURES = "https://github.com/MSKazemi/yazses/issues/new"


def version() -> str:
    """Installed package version, or ``dev`` when running from a source tree
    without an installed distribution."""
    try:
        return _pkg_version("yazses")
    except PackageNotFoundError:
        return "dev"


def _supports_banner() -> bool:
    """True when the ASCII banner should be drawn: an interactive stdout and
    NO_COLOR not requested. False in pipes, redirects, or plain-output mode so the
    art never garbles logs or non-UTF-8 captures."""
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def banner(*, force: bool | None = None) -> str:
    """The branded header for `yazses about`: ASCII wordmark + tagline + version.

    Falls back to a plain ``APP_NAME vX.Y — TAGLINE`` line when the terminal can't
    show the art (non-TTY / NO_COLOR), so piped or logged output stays clean. Pass
    ``force=True``/``False`` to override the auto-detection (used by tests)."""
    show_art = _supports_banner() if force is None else force
    ver = version()
    if show_art:
        return f"{BANNER_ART}\n\n {APP_NAME} {ver} — {TAGLINE}"
    return f"{APP_NAME} {ver} — {TAGLINE}"


def contact_lines() -> list[str]:
    """Plain ``label: value`` lines for author + contact, reused by ``doctor``
    and any other plaintext surface."""
    return [
        f"Author:   {AUTHOR} <{EMAIL}>",
        f"Website:  {WEBSITE}",
        f"Source:   {SOURCE}",
        f"Issues:   {ISSUES}",
        f"Features: {FEATURES}",
    ]
