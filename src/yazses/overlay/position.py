"""Overlay placement — where the window's top-left corner goes.

Pure integer geometry so it can be tested without a display. The Qt layer feeds
in the cursor position and screen rectangle from ``QCursor.pos()`` /
``QScreen.geometry()``; everything here is plain arithmetic.
"""

from __future__ import annotations

Point = tuple[int, int]
Rect = tuple[int, int, int, int]  # (x, y, width, height)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def place_near_cursor(cursor: Point, size: int, screen: Rect, offset: int) -> Point:
    """Top-left for a ``size``×``size`` overlay offset from the cursor, kept on-screen.

    The overlay sits below-right of the pointer by ``offset`` so it never hides
    the caret. If that would push it off the screen edge, it flips/clamps to stay
    fully visible.
    """
    sx, sy, sw, sh = screen
    cx, cy = cursor

    x = cx + offset
    # Flip to the left of the cursor if we'd overflow the right edge.
    if x + size > sx + sw:
        x = cx - offset - size
    y = cy + offset
    if y + size > sy + sh:
        y = cy - offset - size

    x = _clamp(x, sx, sx + sw - size)
    y = _clamp(y, sy, sy + sh - size)
    return x, y


def place_centered(cursor: Point, size: int, screen: Rect) -> Point:
    """Top-left for a ``size``×``size`` overlay centred on the cursor, kept on-screen.

    For the dwell-click ring, which has to surround the pointer to say "this spot is about
    to be clicked" -- offset placement would draw the warning beside the thing it warns about.
    """
    sx, sy, sw, sh = screen
    x = _clamp(cursor[0] - size // 2, sx, sx + sw - size)
    y = _clamp(cursor[1] - size // 2, sy, sy + sh - size)
    return x, y


def place_fixed(position: str, size: int, screen: Rect, margin: int = 48) -> Point:
    """Top-left for a non-cursor anchor: bottom_center / top_center / corner."""
    sx, sy, sw, sh = screen
    if position == "top_center":
        return sx + (sw - size) // 2, sy + margin
    if position == "corner":
        return sx + sw - size - margin, sy + sh - size - margin
    # Default: bottom_center.
    return sx + (sw - size) // 2, sy + sh - size - margin
