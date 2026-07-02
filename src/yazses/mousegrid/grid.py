"""Voice mouse grid subdivision (pure) — ADR-v2-030.

Coarse-to-fine pointer targeting: a screen region is split into a ``cols × rows`` grid of
numbered cells (1-based, row-major); selecting a cell zooms into it; a sequence of selections
resolves to a click point. Pure geometry; rendering + clicking live elsewhere.
"""
from __future__ import annotations


def subdivide(region, cell: int, cols: int = 3, rows: int = 3):
    """Return the sub-rectangle ``(x, y, w, h)`` for 1-based ``cell`` (row-major).

    ``region`` is ``(x, y, w, h)``. Raises ``ValueError`` if the cell is out of range or the
    grid dimensions are non-positive. Pure.
    """
    if cols <= 0 or rows <= 0:
        raise ValueError("cols and rows must be positive")
    if not 1 <= cell <= cols * rows:
        raise ValueError(f"cell {cell} out of range 1..{cols * rows}")
    x, y, w, h = region
    r, c = divmod(cell - 1, cols)
    cw, ch = w / cols, h / rows
    return (x + c * cw, y + r * ch, cw, ch)


def resolve_point(region, path, cols: int = 3, rows: int = 3):
    """Apply a sequence of 1-based cell selections and return the center ``(x, y)``.

    Each step in ``path`` zooms into that cell of the current region. An empty path returns
    the center of ``region``. Pure.
    """
    reg = region
    for cell in path:
        reg = subdivide(reg, cell, cols, rows)
    x, y, w, h = reg
    return (x + w / 2, y + h / 2)
