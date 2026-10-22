"""Windows file opener: ``os.startfile``, the shell's own "open" verb.

Importable on any OS: ``os.startfile`` exists only on Windows, so it is looked up when a
file is opened, not at import.
"""
from __future__ import annotations

import os


class WindowsFileOpener:
    def open(self, path: str) -> None:
        os.startfile(path)  # type: ignore[attr-defined]  # Windows-only
