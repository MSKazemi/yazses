"""OS-specific file launcher backend."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def launch_file(path: str | Path) -> None:
    """Launch a file with the default OS application."""
    path_str = str(path)
    if sys.platform.startswith("linux"):
        subprocess.run(["xdg-open", path_str], check=True)
    elif sys.platform == "darwin":
        subprocess.run(["open", path_str], check=True)
    elif sys.platform == "win32":
        import os
        os.startfile(path_str)
    else:
        raise NotImplementedError(f"Unsupported platform: {sys.platform}")
