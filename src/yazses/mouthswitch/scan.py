"""Mouth-sound classification + scan selector (pure) — ADR-v2-097.

Classify short non-speech mouth sounds and drive a timed scan-and-select cursor. Pure and
deterministic; the acoustic classifier is the lazy extra, the scan cursor is testable with a fake
clock.
"""
from __future__ import annotations


def classify_mouth_sound(features):
    """Classify a short mouth sound → ``pop`` | ``click`` | ``sh`` | ``None``. Pure.

    ``features``: ``duration_ms``, ``centroid_hz``, ``zcr`` (zero-crossing rate), ``burst`` (bool).
    """
    dur = features.get("duration_ms", 0)
    centroid = features.get("centroid_hz", 0)
    zcr = features.get("zcr", 0.0)
    burst = bool(features.get("burst", False))
    if dur > 200:
        if centroid >= 4000 and zcr >= 0.3:
            return "sh"        # sustained high-frequency fricative
        return None
    if burst:
        return "pop" if centroid < 2000 else "click"
    return None


class ScanSelector:
    """A timed scanning selector: the highlight auto-advances; switches move/pick. Pure state."""

    def __init__(self, items, dwell_s: float = 1.2) -> None:
        self._items = list(items)
        self._dwell = dwell_s
        self._idx = 0
        self._last_advance: float | None = None

    def current(self):
        return self._items[self._idx] if self._items else None

    def tick(self, now: float) -> int:
        """Advance the highlight for elapsed dwell intervals; return the current index. Pure state."""
        if self._last_advance is None:
            self._last_advance = now
        if self._items and now - self._last_advance >= self._dwell:
            steps = int((now - self._last_advance) // self._dwell)
            self._idx = (self._idx + steps) % len(self._items)
            self._last_advance += steps * self._dwell
        return self._idx

    def on_switch(self, action: str, now: float = 0.0):
        """Handle a switch: ``advance`` moves the highlight, ``select`` returns the item. Pure state."""
        if not self._items:
            return None
        if action == "advance":
            self._idx = (self._idx + 1) % len(self._items)
            self._last_advance = now
            return None
        if action == "select":
            return self._items[self._idx]
        return None
