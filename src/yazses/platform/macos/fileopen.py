"""macOS file opener: ``open``, which LaunchServices resolves to the default app."""
from __future__ import annotations

import subprocess


class MacosFileOpener:
    def open(self, path: str) -> None:
        subprocess.run(["open", path], check=True)
