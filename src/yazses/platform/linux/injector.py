"""Linux injector — wraps the existing inject.auto.get_injector dispatch."""

from __future__ import annotations

import logging
import os

from yazses.inject.auto import get_injector
from yazses.inject.base import BaseInjector
from yazses.inject.clipboard import ClipboardInjector

log = logging.getLogger(__name__)


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

    def _fell_back(self, what: str, exc: Exception) -> None:
        """Say so in the log, at WARNING.

        Falling back is not a neutral event: the clipboard path overwrites the
        clipboard and is a no-op in terminals, so a user whose primary backend
        fails every time should be able to find out from the log rather than by
        noticing that dictation only works in some windows. This was silent while
        ydotool 0.1.8 refused every command line it was handed and exited 0.
        """
        log.warning(
            "%s backend failed (%s: %s) — using the clipboard fallback",
            type(self._primary).__name__, type(exc).__name__, exc,
        )

    def inject(self, text: str) -> None:
        try:
            self._primary.inject(text)
        except Exception as exc:
            if self._fallback is None:
                raise
            self._fell_back("injection", exc)
            self._fallback.inject(text)

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        try:
            self._primary.inject_backspaces(count)
        except Exception as exc:
            if self._fallback is None:
                raise
            self._fell_back("backspace", exc)
            self._fallback.inject_backspaces(count)

    def inject_key_sequence(self, keys: list[str]) -> None:
        """Delegate to the primary backend, clipboard on failure (#544).

        The backends own their Wayland/X11 tool dispatch — this method used to
        hand-roll its own, which had no fallback path at all and needed the
        one-off YAZSES_INJECTOR special case (#390) to keep an explicit
        unicode selection from losing key combos.
        """
        if not keys:
            return
        try:
            self._primary.inject_key_sequence(keys)
        except Exception as exc:
            if self._fallback is None:
                raise
            self._fell_back("key sequence", exc)
            self._fallback.inject_key_sequence(keys)

    @property
    def backend_name(self) -> str:
        return type(self._primary).__name__
