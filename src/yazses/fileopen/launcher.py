"""Open a file with the default OS application, through the platform seam."""
from __future__ import annotations

from pathlib import Path


def launch_file(path: str | Path) -> None:
    """Launch a file with the default OS application.

    Which mechanism that is (``xdg-open``, ``open``, ``os.startfile``) is the platform
    layer's answer, not this module's: :func:`yazses.platform.get_file_opener` picks the
    backend, so the OS branch lives once, in ``platform/factory.py`` (AGENTS.md rule 6).

    The BSDs get the Linux opener rather than an error, because ``xdg-utils`` is in ports
    and pkgsrc exactly as ``xdotool`` and ``xclip`` are -- the same reasoning that makes
    ``platform/bsd`` a thin composition over the Linux backend. An OS with no backend
    still raises ``NotImplementedError`` naming ``sys.platform``.

    Imported lazily so a file launcher does not pull the platform package in at module
    scope; the only caller (``yazses fileopen``) has already built it via
    ``get_platform()`` before it reaches here, so the import is free in practice.
    """
    from yazses.platform.factory import get_file_opener

    get_file_opener().open(str(path))
