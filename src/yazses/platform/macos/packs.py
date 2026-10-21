"""No add-on packs in the macOS ``.app`` yet: it needs its own ADR-028 addendum
(notarisation of each pack, the Intel-Mac deadline). ``supported()`` is false.

Standalone rather than reusing the Linux class: the frozen bundles exclude the other
OSes' ``platform`` packages, so a cross-OS import here would fail inside the ``.app``.
"""
from __future__ import annotations

import sys
from pathlib import Path


class MacosPackRuntime:
    def supported(self) -> bool:
        return False

    def is_elevated(self) -> bool:
        return True  # never asked to mount; and if it were, fail closed

    def add_native_dir(self, path: Path) -> object:
        raise OSError("add-on packs are not supported in the macOS app yet")

    def embedded_index_path(self) -> Path | None:
        return None

    def probe_command(self, name: str, staged: Path) -> list[str] | None:
        return [sys.executable, "-m", "yazses", "--cli", "packs", "probe", name,
                "--staged", str(staged)]

    def base_native_candidates(self, name: str) -> list[Path]:
        return []  # no pack loader in the .app: a binding pack is refused

    def load_base_native(self, path: Path) -> tuple[object, str | None]:
        raise OSError("add-on packs are not supported in the macOS app yet")

    def loaded_native_paths(self, name: str) -> list[Path] | None:
        return None
