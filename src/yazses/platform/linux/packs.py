"""No add-on packs on Linux (ADR-028 §8): a source install uses ``features enable``'s
pip path, and the snap and flatpak have channel-native routes. ``supported()`` is false
until a phase says otherwise. Also used by the BSDs, which reuse the Linux backend."""
from __future__ import annotations

import sys
from pathlib import Path


class UnsupportedPackRuntime:
    def supported(self) -> bool:
        return False

    def is_elevated(self) -> bool:
        return True  # never asked to mount; and if it were, fail closed

    def add_native_dir(self, path: Path) -> object:
        raise OSError("add-on packs are not supported on this platform")

    def embedded_index_path(self) -> Path | None:
        return None

    def probe_command(self, name: str, staged: Path) -> list[str] | None:
        return [sys.executable, "-m", "yazses", "--cli", "packs", "probe", name,
                "--staged", str(staged)]


LinuxPackRuntime = UnsupportedPackRuntime
