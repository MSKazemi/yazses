"""Verbatim/autoformat mode command + state (pure) — ADR-v2-078.

Recognize the reserved mode phrases and hold the current mode so the pipeline knows whether to
bypass all formatting. Pure and deterministic; the daemon consults :meth:`VerbatimGate.is_verbatim`.
"""
from __future__ import annotations

import re

_VERBATIM_ON = re.compile(
    r"\b(?:dictate\s+verbatim|verbatim\s+mode|literal\s+mode|stop\s+formatting|raw\s+mode)\b",
    re.IGNORECASE,
)
_VERBATIM_OFF = re.compile(
    r"\b(?:resume\s+formatting|format(?:ting)?\s+mode|auto\s?format|stop\s+verbatim|normal\s+mode)\b",
    re.IGNORECASE,
)


def detect_mode_command(text: str):
    """Return ``"verbatim"`` / ``"auto"`` if ``text`` is a mode command, else ``None``. Pure."""
    t = text or ""
    if _VERBATIM_OFF.search(t):
        return "auto"
    if _VERBATIM_ON.search(t):
        return "verbatim"
    return None


class VerbatimGate:
    """Holds the current formatting mode (``auto`` or ``verbatim``)."""

    def __init__(self, mode: str = "auto") -> None:
        self._mode = "verbatim" if mode == "verbatim" else "auto"

    @property
    def mode(self) -> str:
        return self._mode

    def is_verbatim(self) -> bool:
        """True if formatting should be bypassed for the current burst."""
        return self._mode == "verbatim"

    def handle_command(self, text: str) -> bool:
        """Consume a mode command; returns True if the mode was set by this text. Pure state."""
        cmd = detect_mode_command(text)
        if cmd is None:
            return False
        self._mode = cmd
        return True
