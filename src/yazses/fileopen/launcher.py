"""OS-specific file launcher backend."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def launch_file(path: str | Path) -> None:
    """Launch a file with the default OS application.

    The BSDs go down the ``xdg-open`` path with Linux rather than falling through to
    the error, because ``xdg-utils`` is in ports and pkgsrc exactly as ``xdotool`` and
    ``xclip`` are — the same reasoning that makes ``platform/bsd`` a thin composition
    over the Linux backend instead of a parallel implementation. Without this, the one
    OS family YazSes claims experimental support for got ``Unsupported platform:
    freebsd14`` from this command alone, which is a false statement about a platform
    ``factory.py`` builds a working bundle for.

    The membership test is ``platform.bsd.is_bsd`` rather than a second copy of the
    prefixes: ``sys.platform`` carries the major version (``freebsd14``, never
    ``freebsd``), and that tuple is declared to be the single source of that truth.
    Imported lazily so a file launcher does not pull the platform bundle in at module
    scope; the only caller (``yazses fileopen``) has already built it via
    ``get_platform()`` before it reaches here, so the import is free in practice.
    """
    from yazses.platform.bsd import is_bsd

    path_str = str(path)
    if sys.platform.startswith("linux") or is_bsd():
        subprocess.run(["xdg-open", path_str], check=True)
    elif sys.platform == "darwin":
        subprocess.run(["open", path_str], check=True)
    elif sys.platform == "win32":
        import os
        os.startfile(path_str)
    else:
        raise NotImplementedError(f"Unsupported platform: {sys.platform}")
