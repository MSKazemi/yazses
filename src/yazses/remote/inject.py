"""Remote-side injector probe — mirrors inject/auto.py.

Used by yazses-agent on the remote machine. Has no audio or STT dependencies.
"""
from __future__ import annotations

import os
import shutil


def get_remote_injector():
    """Return the best available injector for the remote machine.

    Probes for xdotool (X11), ydotool/wtype (Wayland), falls back to clipboard.
    Import is lazy — the agent imports this module, not the full yazses package.
    """
    # Import from yazses.inject if available; if not, the agent may be installed standalone.
    try:
        from yazses.inject.auto import get_injector
        return get_injector()
    except ImportError:
        # Standalone mode: use subprocess-based injection
        return _StandaloneInjector()


class _StandaloneInjector:
    """Minimal subprocess injector for standalone agent deployment."""

    def __init__(self) -> None:
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        if is_wayland:
            self._tool = "ydotool" if shutil.which("ydotool") else ("wtype" if shutil.which("wtype") else None)
        else:
            self._tool = "xdotool" if shutil.which("xdotool") else None
        self._wayland = is_wayland

    def inject(self, text: str) -> None:
        import subprocess
        if not text:
            return
        if self._tool == "xdotool":
            subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "12", "--", text], check=True, timeout=10)
        elif self._tool == "ydotool":
            subprocess.run(["ydotool", "type", "--", text], check=True, timeout=10)
        elif self._tool == "wtype":
            subprocess.run(["wtype", "--", text], check=True, timeout=10)
        else:
            # Last resort: xclip + xdotool paste
            import subprocess as sp
            proc = sp.Popen(["xclip", "-selection", "clipboard"], stdin=sp.PIPE)
            proc.communicate(text.encode())
            sp.run(["xdotool", "key", "ctrl+v"], check=True, timeout=5)

    def inject_backspaces(self, count: int) -> None:
        import subprocess
        if count <= 0:
            return
        if self._tool == "xdotool":
            subprocess.run(["xdotool", "key", "--repeat", str(count), "BackSpace"], check=True, timeout=10)
        elif self._tool == "ydotool":
            # `ydotool key KEY_BACKSPACE` is understood by NEITHER ydotool: 1.x wants
            # numeric keycodes, and 0.1.x types the letter k. run_ydotool_keys knows
            # which is installed -- and that 0.1.x exits 0 when it refuses a command.
            from yazses.inject.ydotool import run_ydotool_keys

            run_ydotool_keys(["KEY_BACKSPACE"] * count, timeout=5)

    def inject_key_sequence(self, keys: list[str]) -> None:
        pass  # Not needed for remote agent
