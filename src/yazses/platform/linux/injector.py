"""Linux injector — wraps the existing inject.auto.get_injector dispatch."""

from __future__ import annotations

import os
import shutil
import subprocess

from yazses.inject.auto import get_injector
from yazses.inject.base import BaseInjector
from yazses.inject.clipboard import ClipboardInjector
from yazses.inject.ydotool import ydotool_key_args


def _xdotool_key_str(combo: str) -> str:
    """Convert 'ctrl+z' → 'ctrl+z', 'shift+Left' → 'shift+Left' for xdotool."""
    return combo.replace("meta", "super")




class LinuxInjector:
    """InjectorBackend that auto-selects the best Linux backend at construction.

    Tries the focus-aware backend first (xdotool / ydotool / wtype) and falls
    back to clipboard-paste if that backend fails at runtime.
    """

    def __init__(self, fallback_to_clipboard: bool | None = None) -> None:
        """*fallback_to_clipboard* ``None`` reads ``YAZSES_INJECT_FALLBACK``.

        `[injection] fallback_to_clipboard` has been documented and defaulted to
        true since injection shipped -- it appears in seventeen places across the
        docs and the example configs people copy -- and nothing read it. The
        fallback was built unconditionally, so a user who turned it off was
        silently overruled.

        Turning it off is a real remedy, not a preference. `xdotool.py` records the
        failure: a timeout can fire *after* xdotool has already typed part of the
        text, this class reads that as "the backend is broken", the clipboard paste
        types the text a second time, and the streaming commit then deletes a span
        computed from the first copy. Someone who has met that wants the primary
        backend to fail loudly instead.
        """
        if fallback_to_clipboard is None:
            fallback_to_clipboard = (
                os.environ.get("YAZSES_INJECT_FALLBACK", "1").strip().lower()
                not in {"0", "false", "no", "off"}
            )
        self._primary: BaseInjector = get_injector()
        self._fallback: ClipboardInjector | None = None
        if fallback_to_clipboard and not isinstance(self._primary, ClipboardInjector):
            self._fallback = ClipboardInjector()
        self._is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))

    def inject(self, text: str) -> None:
        try:
            self._primary.inject(text)
        except Exception:
            if self._fallback is None:
                raise
            self._fallback.inject(text)

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        try:
            self._primary.inject_backspaces(count)
        except Exception:
            if self._fallback is None:
                raise
            self._fallback.inject_backspaces(count)

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        if self._is_wayland:
            if shutil.which("ydotool"):
                for combo in keys:
                    # ydotool's `key` ignores symbolic names; use numeric keycodes.
                    subprocess.run(
                        ["ydotool", "key"] + ydotool_key_args(combo),
                        check=True,
                        timeout=5,
                    )
                return
            if shutil.which("wtype"):
                for combo in keys:
                    parts = combo.split("+")
                    args: list[str] = ["wtype"]
                    for p in parts[:-1]:
                        args += ["-M", p]
                    args += ["-k", parts[-1]]
                    for p in parts[:-1]:
                        args += ["-m", p]
                    subprocess.run(args, check=True, timeout=5)
                return
        else:
            if shutil.which("xdotool"):
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers"] + [_xdotool_key_str(k) for k in keys],
                    check=True,
                    timeout=5,
                )
                return
        # Clipboard fallback has no key-sequence capability; silently skip.

    @property
    def backend_name(self) -> str:
        return type(self._primary).__name__
