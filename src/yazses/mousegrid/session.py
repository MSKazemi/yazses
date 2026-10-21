"""The voice mouse grid's state machine (pure) — ADR-v2-030.

One open grid at a time: ``open(region)`` starts at the whole region, every spoken cell
zooms one level into that cell (:func:`yazses.mousegrid.grid.subdivide`), ``back`` zooms
out one level, a click ends the grid, and ``cancel`` ends it without one. The session
decides *what* should happen and *where*; it moves no pointer — :mod:`.runtime` turns a
:class:`Step` into pointer-sink calls.

An open grid claims utterances, so it must not stay open by accident: it closes itself
after :data:`IDLE_TIMEOUT_S` without a grid command. The clock is injected, so the timeout
is tested without sleeping.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from yazses.mousegrid.grammar import GridCommand
from yazses.mousegrid.grid import resolve_point, subdivide

__all__ = ["IDLE_TIMEOUT_S", "MIN_CELL_PX", "GridSession", "Step"]

#: Seconds an open grid waits for its next command before it closes itself.
IDLE_TIMEOUT_S = 30.0

#: A zoom that would make a cell narrower or shorter than this is refused: below one pixel
#: further numbers stop moving the pointer, and the user would hear nothing happen.
MIN_CELL_PX = 1.0

Region = tuple[float, float, float, float]


@dataclass(frozen=True)
class Step:
    """What one grid command decided.

    ``kind``: ``"move"`` (put the pointer at ``point``), ``"click"`` (``button`` ×
    ``count`` at ``point``, then the grid closes), ``"close"`` (closed, no click), or
    ``"refused"`` (nothing happens; ``reason`` says why, the grid stays as it was).
    """

    kind: str
    point: tuple[float, float] | None = None
    button: str = "left"
    count: int = 1
    reason: str = ""


class GridSession:
    """The open grid, if any, and the zoom path into it."""

    def __init__(
        self,
        cols: int = 3,
        rows: int = 3,
        *,
        clock: Callable[[], float] = time.monotonic,
        idle_timeout_s: float = IDLE_TIMEOUT_S,
    ) -> None:
        if cols <= 0 or rows <= 0:
            raise ValueError("cols and rows must be positive")
        self.cols = cols
        self.rows = rows
        self._clock = clock
        self._idle_timeout_s = idle_timeout_s
        self._root: Region | None = None
        self._path: list[int] = []
        self._last_activity = 0.0

    # ---- state ------------------------------------------------------------

    @property
    def cell_count(self) -> int:
        return self.cols * self.rows

    @property
    def active(self) -> bool:
        """True while a grid is open. An idle grid past its timeout reads as closed."""
        if self._root is None:
            return False
        if self._clock() - self._last_activity > self._idle_timeout_s:
            self.close()
            return False
        return True

    @property
    def path(self) -> tuple[int, ...]:
        return tuple(self._path)

    def region(self) -> Region | None:
        """The rectangle the grid is drawn over now (the current zoom level), or None."""
        if not self.active:
            return None
        return self._current()

    def _current(self) -> Region | None:
        if self._root is None:
            return None
        reg = self._root
        for cell in self._path:
            reg = subdivide(reg, cell, self.cols, self.rows)
        return reg

    def point(self) -> tuple[float, float] | None:
        """Centre of the current zoom level, or None while closed."""
        if not self.active or self._root is None:
            return None
        return resolve_point(self._root, self._path, self.cols, self.rows)

    # ---- transitions ------------------------------------------------------

    def open(self, region: Region) -> None:
        """Open (or restart) a grid over ``region`` ``(x, y, w, h)``."""
        x, y, w, h = (float(v) for v in region)
        if w <= 0 or h <= 0:
            raise ValueError("grid region must have a positive size")
        self._root = (x, y, w, h)
        self._path = []
        self._last_activity = self._clock()

    def close(self) -> None:
        self._root = None
        self._path = []

    def apply(self, command: GridCommand) -> Step:
        """Apply one parsed grid command to the open grid."""
        if not self.active or self._root is None:
            return Step("refused", reason="no grid is open")
        self._last_activity = self._clock()
        if command.kind == "cancel":
            self.close()
            return Step("close")
        if command.kind == "back":
            if not self._path:
                return Step("refused", reason="already at the top level")
            self._path.pop()
            return Step("move", point=self.point())
        if command.kind == "click":
            if not self._path:
                # Clicking the middle of the whole screen is almost never what was meant,
                # and an unasked click is the one grid action that cannot be taken back.
                return Step("refused", reason="say a cell number before clicking")
            point = self.point()
            self.close()
            return Step("click", point=point, button=command.button, count=command.count)
        if command.kind == "cells":
            candidate = list(self._path)
            reg = self._current() or self._root
            for cell in command.cells:
                reg = subdivide(reg, cell, self.cols, self.rows)
                if reg[2] < MIN_CELL_PX or reg[3] < MIN_CELL_PX:
                    return Step("refused", reason="the cell is already smaller than a pixel")
                candidate.append(cell)
            self._path = candidate
            return Step("move", point=self.point())
        return Step("refused", reason=f"unknown grid command {command.kind!r}")

    def status(self) -> dict[str, object]:
        """Value-free state for IPC: dimensions, the current rectangle and the depth."""
        reg = self.region()
        return {
            "active": reg is not None,
            "cols": self.cols,
            "rows": self.rows,
            "region": [round(v, 2) for v in reg] if reg is not None else None,
            "depth": len(self._path) if reg is not None else 0,
        }
