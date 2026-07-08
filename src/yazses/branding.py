"""Author, contact, and project links — the single source of truth surfaced in
the running app (``yazses about``, the ``--help`` epilog, and ``yazses doctor``).

Keep these in step with ``pyproject.toml`` ([project] authors) and
``snap/snapcraft.yaml`` (contact / website / source-code / issues) so every
distribution channel points people at the same author and the same place to
report issues or request features.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

APP_NAME = "YazSes"
TAGLINE = "Local, offline voice dictation — hold a key, speak, release."

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
