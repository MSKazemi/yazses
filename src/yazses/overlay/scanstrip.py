"""The overlay's half of the Mouth-Sound Switch (ADR-v2-097): where the scan strip goes.

The daemon owns the scan; the overlay only draws it, from the ``mouthswitch`` block of the
``status`` reply it already polls (``poller.parse_status``) -- no IPC method of its own.
This module is the pure layout: one row of equal cells, centred at the top of the screen,
the lit one marked. ``scan_widget.py`` is the thin Qt painter. Nothing here imports Qt.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CELL_H", "CELL_W", "GAP", "TOP_MARGIN", "StripLayout", "strip_layout"]

#: Big on purpose: the user reads the highlight from wherever they sit, often at a distance.
CELL_W = 180
CELL_H = 72
GAP = 12
TOP_MARGIN = 24


@dataclass(frozen=True)
class StripLayout:
    """Where the strip window goes, and each cell inside it (window-local coordinates)."""

    window: tuple[int, int, int, int]
    cells: tuple[tuple[str, tuple[int, int, int, int], bool], ...]


def strip_layout(
    labels: tuple[str, ...], index: int, screen: tuple[int, int, int, int]
) -> StripLayout | None:
    """The strip for ``labels`` with ``index`` lit, on ``screen`` ``(x, y, w, h)``. Pure.

    None when there is nothing to draw (no labels, or an index outside them). A strip
    wider than the screen shrinks its cells to fit rather than running off the edge.
    """
    n = len(labels)
    if n == 0 or not 0 <= index < n:
        return None
    sx, sy, sw, _sh = screen
    cell_w = min(CELL_W, max(1, (sw - (n + 1) * GAP) // n))
    width = n * cell_w + (n + 1) * GAP
    height = CELL_H + 2 * GAP
    left = sx + max(0, (sw - width) // 2)
    top = sy + TOP_MARGIN
    cells = tuple(
        (label, (GAP + i * (cell_w + GAP), GAP, cell_w, CELL_H), i == index)
        for i, label in enumerate(labels)
    )
    return StripLayout(window=(left, top, width, height), cells=cells)
