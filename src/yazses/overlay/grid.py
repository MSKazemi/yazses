"""The overlay's half of the Voice Mouse Grid (ADR-v2-030): what to draw, and the poller.

The daemon owns the grid; the overlay only draws it. This module is the pure part —
:func:`parse_grid_status` turns the daemon's ``mousegrid`` IPC reply into a
:class:`GridSnapshot`, and :func:`grid_cells` lays out the numbered cells to paint — plus
:class:`GridPoller`, which asks the daemon for that reply on a background thread. Nothing
here imports Qt; ``grid_widget.py`` is the thin painter.

The poller runs only when ``[mousegrid] enabled`` is true (``overlay/app.py`` checks), so an
overlay without the feature sends exactly the IPC it always sent.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass

from yazses.mousegrid.grid import subdivide

__all__ = ["GridPoller", "GridSnapshot", "grid_cells", "next_grid_interval", "parse_grid_status"]

_ACTIVE_INTERVAL_S = 0.08  # ~12 Hz while a grid is open: a zoom should redraw promptly
_IDLE_INTERVAL_S = 0.3     # otherwise: quick enough that "mouse grid" appears at once


@dataclass(frozen=True)
class GridSnapshot:
    """What the overlay needs to draw a grid; inactive by default."""

    active: bool = False
    region: tuple[float, float, float, float] | None = None
    cols: int = 3
    rows: int = 3


def _positive_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return default
    return value


def parse_grid_status(info: object) -> GridSnapshot:
    """The daemon's ``mousegrid`` status reply as a :class:`GridSnapshot`. Defensive, pure.

    Anything malformed — not a dict, a region that is not four finite numbers with a positive
    size — reads as *no grid*, so a bad reply can only hide the grid, never draw a wrong one.
    """
    if not isinstance(info, dict) or info.get("active") is not True:
        return GridSnapshot()
    raw = info.get("region")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return GridSnapshot()
    try:
        x, y, w, h = (float(v) for v in raw)
    except (TypeError, ValueError):
        return GridSnapshot()
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        return GridSnapshot()
    return GridSnapshot(
        active=True,
        region=(x, y, w, h),
        cols=_positive_int(info.get("cols"), 3),
        rows=_positive_int(info.get("rows"), 3),
    )


def grid_cells(snap: GridSnapshot) -> list[tuple[int, tuple[float, float, float, float]]]:
    """``[(number, (x, y, w, h)), ...]`` for every cell, in the daemon's numbering. Pure.

    Uses the same :func:`subdivide` the daemon resolves a spoken number with, so the number
    painted on a cell is the number that moves the pointer there.
    """
    if not snap.active or snap.region is None:
        return []
    return [
        (n, subdivide(snap.region, n, snap.cols, snap.rows))
        for n in range(1, snap.cols * snap.rows + 1)
    ]


def next_grid_interval(snap: GridSnapshot) -> float:
    """Seconds until the next grid poll. Pure."""
    return _ACTIVE_INTERVAL_S if snap.active else _IDLE_INTERVAL_S


class GridPoller:
    """Polls the daemon's ``mousegrid`` status on a daemon thread.

    ``screen`` is the overlay's own screen rectangle. It is sent (``action="screen"``)
    whenever a status reply says the daemon has none — at start, and again after a daemon
    restart — so a grid can open where the daemon cannot read the display layout (macOS).
    """

    def __init__(self, client: object, screen: tuple[int, int, int, int] | None = None) -> None:
        self._client = client
        self._screen = screen
        self._lock = threading.Lock()
        self._latest = GridSnapshot()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def latest(self) -> GridSnapshot:
        with self._lock:
            return self._latest

    def poll_once(self) -> GridSnapshot:
        """One round trip; never raises. Exposed so tests need no thread."""
        client = self._client
        try:
            info = client.call("mousegrid", action="status")  # type: ignore[attr-defined]
            if (self._screen is not None and isinstance(info, dict)
                    and info.get("screen_reported") is False):
                client.call(  # type: ignore[attr-defined]
                    "mousegrid", action="screen", region=list(self._screen)
                )
            snap = parse_grid_status(info)
        except Exception:  # noqa: BLE001 - daemon down or restarting: draw nothing
            snap = GridSnapshot()
        with self._lock:
            self._latest = snap
        return snap

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="overlay-grid", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            snap = self.poll_once()
            self._stop.wait(next_grid_interval(snap))
