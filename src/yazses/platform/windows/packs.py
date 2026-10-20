"""Windows add-on pack runtime (ADR-028 §2). Importable on any OS: every Win32 call is
inside a method.

Deliberately light: the PyInstaller runtime hook imports this before ``main`` runs, in
every YazSes process, so it pulls in nothing beyond ``os``, ``sys`` and ``pathlib`` until
a method is called.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from yazses.platform.base import PACK_INDEX_NAME

#: The console binary the spec builds beside ``YazSesApp.exe`` (packaging/windows/yazses.spec).
_CLI_EXE = "yazses-cli.exe"


class WindowsPackRuntime:
    def supported(self) -> bool:
        return True

    def is_elevated(self) -> bool:
        """Token elevation, read by the same probe ``doctor`` uses. ``None`` (could not
        tell) counts as elevated: the safe answer is "do not load user-writable code"."""
        from yazses.platform.windows.permissions import is_elevated

        try:
            answer = is_elevated()
        except Exception:  # noqa: BLE001 - an unanswerable question fails closed
            return True
        return True if answer is None else bool(answer)

    def add_native_dir(self, path: Path) -> object:
        add = getattr(os, "add_dll_directory", None)
        if add is None:
            raise OSError("os.add_dll_directory is not available in this Python")
        return add(str(path))

    def embedded_index_path(self) -> Path | None:
        base = getattr(sys, "_MEIPASS", None)
        if not getattr(sys, "frozen", False) or not base:
            return None
        return Path(base) / PACK_INDEX_NAME

    def probe_command(self, name: str, staged: Path) -> list[str] | None:
        tail = ["--cli", "packs", "probe", name, "--staged", str(staged)]
        if getattr(sys, "frozen", False):
            exe = Path(sys.executable).with_name(_CLI_EXE)
            return [str(exe), *tail]
        return [sys.executable, "-m", "yazses", *tail]
