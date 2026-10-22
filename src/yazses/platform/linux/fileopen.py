"""Linux file opener: ``xdg-open``. The BSDs use it too (``xdg-utils`` is in ports and pkgsrc)."""
from __future__ import annotations

import subprocess


class LinuxFileOpener:
    def open(self, path: str) -> None:
        subprocess.run(["xdg-open", path], check=True)
