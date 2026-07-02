"""Spoken window/workspace command grammar (pure) — ADR-v2-070.

Map a spoken layout command to a :class:`WmAction`. Pure and deterministic; the per-compositor
backend that executes the action lives behind the ``windowctl`` extra.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HALF = {"left": "left", "right": "right", "up": "top", "top": "top",
         "down": "bottom", "bottom": "bottom"}


@dataclass(frozen=True)
class WmAction:
    """A window-manager action: ``kind`` with an optional ``arg``.

    kinds: ``snap`` (arg = left/right/top/bottom/top-left/…), ``maximize``, ``minimize``,
    ``fullscreen``, ``center``, ``close``, ``workspace`` (arg = int), ``workspace_rel`` (arg = ±1).
    """
    kind: str
    arg: object = None


def parse_wm_command(text: str):
    """Parse a spoken window/workspace command into a :class:`WmAction`, or ``None``. Pure."""
    t = (text or "").lower().strip()

    # Corners (quarters) first, so "top left" isn't consumed as a half.
    m = re.search(r"\b(top|bottom|up|down)\s+(left|right)\b", t)
    if m and re.search(r"\b(move|snap|tile|window|quarter|corner)\b", t):
        vert = "top" if m.group(1) in ("top", "up") else "bottom"
        return WmAction("snap", f"{vert}-{m.group(2)}")

    # Halves: "move window left half" / "snap left" / "tile right".
    m = re.search(r"\b(?:move(?:\s+window)?|snap|tile)\b[^\n]*?\b(left|right|up|top|down|bottom)\b", t)
    if m:
        return WmAction("snap", _HALF[m.group(1)])

    if re.search(r"\bmaximi[sz]e\b", t):
        return WmAction("maximize")
    if re.search(r"\bminimi[sz]e\b", t):
        return WmAction("minimize")
    if re.search(r"\bfull\s?screen\b", t):
        return WmAction("fullscreen")
    if re.search(r"\bcent(?:er|re)\b", t):
        return WmAction("center")
    if re.search(r"\bclose\s+(?:the\s+)?window\b", t):
        return WmAction("close")

    if re.search(r"\bnext\s+(?:workspace|desktop)\b", t):
        return WmAction("workspace_rel", 1)
    if re.search(r"\b(?:previous|prev|last)\s+(?:workspace|desktop)\b", t):
        return WmAction("workspace_rel", -1)
    m = re.search(r"\b(?:workspace|desktop)\s+(\d+)\b", t)
    if m:
        return WmAction("workspace", int(m.group(1)))

    return None
