"""Single-switch scanning for Mouth-Sound Switch Access — the pure state machine (ADR-v2-097).

What the user sees: a short row of items (by default Enter, Undo, Scroll up, Scroll down,
Click). One of them is highlighted, and the highlight steps to the next on a fixed interval.
One mouth sound starts or stops the scan; a tongue click runs the highlighted item. That is
*single-switch* scanning, the standard access method for a user with one reliable signal:
the scan does the moving, the switch only says "this one".

This module holds the parts that decide *which* item a click means, with no audio, no thread
and no clock of its own -- every method takes ``now`` (or the click's onset time), so a test
drives it with plain numbers:

* :class:`SwitchScanner` -- the items, the highlight index as a function of time, start/stop,
  an automatic stop after :data:`MAX_LOOPS` full cycles with no selection, and :meth:`select`.
* :func:`parse_scan_items` -- the ``[mouthswitch] scan_items`` list read defensively into
  :class:`ScanItem` values (a pointer item, or a command phrase for the existing grammar).
* :func:`scan_interval` -- ``dwell_s`` clamped to a usable range.

**A click selects what was highlighted when the click began, not when it was recognised.**
The detector reports a sound only after ``POST_QUIET_MS`` of quiet behind it, so by the time
the event reaches the scanner the highlight may already have moved on. :meth:`select` takes
the sound's onset time and answers for that instant. A click whose onset lies outside the
scan it is meant for (before it began, after it stopped) selects nothing, and one scan
selects at most once: after a selection the scan stops, so a stray second click cannot run
a second item (AGENTS.md rule 9 / ADR-021).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "DEFAULT_INTERVAL_S",
    "DEFAULT_SCAN_ITEMS",
    "MAX_INTERVAL_S",
    "MAX_LOOPS",
    "MAX_SELECT_LAG_S",
    "MIN_INTERVAL_S",
    "POINTER_ITEMS",
    "SCROLL_NOTCHES",
    "ScanItem",
    "ScanView",
    "SwitchScanner",
    "normalise_label",
    "parse_scan_items",
    "scan_interval",
]

#: The owner's default set (2026-10-22): three commands from the existing grammar and two
#: pointer operations on the existing pointer sink. No item here needs a new action.
DEFAULT_SCAN_ITEMS: tuple[str, ...] = ("enter", "undo", "scroll up", "scroll down", "click")

#: Wheel notches per "scroll" item. Notches on X11 and Windows, lines on macOS; the XDG
#: portal takes the same number in its own axis unit (``pointer/base.py``).
SCROLL_NOTCHES = 3

#: Item names that are pointer operations rather than command phrases: ``(op, dy)``.
POINTER_ITEMS: dict[str, tuple[str, int]] = {
    "click": ("click", 0),
    "scroll up": ("scroll", -SCROLL_NOTCHES),
    "scroll down": ("scroll", SCROLL_NOTCHES),
}

DEFAULT_INTERVAL_S = 1.2
#: Faster than this, nobody can react to a highlight; slower, a five-item scan takes a minute.
MIN_INTERVAL_S = 0.5
MAX_INTERVAL_S = 10.0
#: Full cycles with no selection before the scan stops by itself, so a scan nobody is
#: watching does not keep a stray click armed for ever.
MAX_LOOPS = 3
#: A click reported this long after its onset is stale (a stalled worker), and selects nothing.
MAX_SELECT_LAG_S = 2.0


@dataclass(frozen=True)
class ScanItem:
    """One thing the scan offers.

    ``label`` is what the overlay shows and, for a command, the phrase handed to the
    existing command grammar. ``kind`` is ``"command"`` or ``"pointer"``; a pointer item
    carries ``op`` (``"click"`` or ``"scroll"``) and ``dy`` (scroll notches, ``+`` = down).
    """

    label: str
    kind: str
    op: str = ""
    dy: int = 0


@dataclass(frozen=True)
class ScanView:
    """What the scan shows at one instant. ``index`` is ``-1`` while not scanning."""

    scanning: bool
    index: int
    item: ScanItem | None


def normalise_label(raw: object) -> str:
    """Lower-case, single-spaced, trimmed. ``""`` for anything that is not a string. Pure."""
    if not isinstance(raw, str):
        return ""
    return " ".join(raw.lower().split())


def parse_scan_items(raw: object) -> tuple[list[ScanItem], list[str]]:
    """``[mouthswitch] scan_items`` → ``(items, problems)``. Pure, total.

    A pointer name becomes a pointer item; anything else is a command phrase, which the
    runtime checks against the grammar before offering it. Non-strings, blanks and
    duplicates are skipped with a problem line. A value that is not a list at all, or a
    list with nothing usable, falls back to :data:`DEFAULT_SCAN_ITEMS` -- a scan with no
    items cannot be started, and an empty list is never what someone meant.
    """
    problems: list[str] = []
    entries: Sequence[object]
    if isinstance(raw, (list, tuple)):
        entries = raw
    else:
        problems.append("scan_items is not a list; using the defaults")
        entries = DEFAULT_SCAN_ITEMS
    items: list[ScanItem] = []
    seen: set[str] = set()
    for entry in entries:
        label = normalise_label(entry)
        if not label:
            problems.append(f"scan item {entry!r} is not a phrase; skipped")
            continue
        if label in seen:
            problems.append(f"scan item {label!r} is listed twice; kept once")
            continue
        seen.add(label)
        pointer = POINTER_ITEMS.get(label)
        if pointer is not None:
            items.append(ScanItem(label, "pointer", op=pointer[0], dy=pointer[1]))
        else:
            items.append(ScanItem(label, "command"))
    if not items and entries is not DEFAULT_SCAN_ITEMS:
        problems.append("scan_items has no usable item; using the defaults")
        return parse_scan_items(DEFAULT_SCAN_ITEMS)[0], problems
    return items, problems


def scan_interval(value: object) -> float:
    """``dwell_s`` as seconds per highlight step, clamped to a usable range. Pure."""
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_INTERVAL_S
    if not math.isfinite(seconds):
        return DEFAULT_INTERVAL_S
    return min(MAX_INTERVAL_S, max(MIN_INTERVAL_S, seconds))


class SwitchScanner:
    """A single-switch scan: the highlight steps on a fixed interval, one click selects.

    Pure state; every method takes the time it is asked about. The highlighted index is a
    function of time since :meth:`start`, so asking "what was lit at ``t``?" for a moment
    in the recent past is exact, not an estimate.
    """

    def __init__(self, items: Sequence[ScanItem], interval_s: float = DEFAULT_INTERVAL_S,
                 max_loops: int = MAX_LOOPS) -> None:
        self._items = tuple(items)
        self._interval = scan_interval(interval_s)
        self._max_loops = max(1, int(max_loops))
        #: The latest scan as ``[start, end)``; ``end`` is None while it runs.
        self._start: float | None = None
        self._end: float | None = None
        #: True once the latest scan has produced its one selection.
        self._spent = False

    @property
    def items(self) -> tuple[ScanItem, ...]:
        return self._items

    @property
    def interval_s(self) -> float:
        return self._interval

    @property
    def scanning(self) -> bool:
        return self._start is not None and self._end is None

    @property
    def span_s(self) -> float:
        """How long a scan runs with no selection before it stops by itself."""
        return self._max_loops * len(self._items) * self._interval

    # ------------------------------------------------------------------ start / stop

    def start(self, now: float) -> bool:
        """Start a fresh scan at the first item. False (and nothing starts) with no items."""
        if not self._items:
            return False
        self._start, self._end, self._spent = float(now), None, False
        return True

    def stop(self, now: float) -> None:
        """Stop the running scan, if any. A click that began before ``now`` may still land."""
        start = self._start
        if start is not None and self._end is None:
            self._end = max(start, float(now))

    def toggle(self, now: float) -> bool:
        """Start when stopped, stop when running. Returns whether it is scanning now."""
        if self.scanning:
            self.stop(now)
            return False
        return self.start(now)

    # ------------------------------------------------------------------ time

    def _expire(self, now: float) -> None:
        """End a scan that has run its loops; the end is when it ran out, not when asked."""
        start = self._start
        if start is not None and self._end is None and now - start >= self.span_s:
            self._end = start + self.span_s

    def index_at(self, t: float) -> int | None:
        """The item lit at time ``t`` in the latest scan, or None if no scan covered ``t``."""
        if self._start is None or not self._items:
            return None
        end = self._end if self._end is not None else self._start + self.span_s
        if t < self._start or t >= end:
            return None
        return int((t - self._start) // self._interval) % len(self._items)

    def tick(self, now: float) -> int | None:
        """Bring the scan up to ``now``; the lit index, or None when not scanning."""
        self._expire(now)
        return self.index_at(now) if self.scanning else None

    def view(self, now: float) -> ScanView:
        """What to draw at ``now``."""
        index = self.tick(now)
        if index is None:
            return ScanView(False, -1, None)
        return ScanView(True, index, self._items[index])

    # ------------------------------------------------------------------ select

    def select(self, onset: float, now: float) -> ScanItem | None:
        """The item lit when the click began, or None; a selection stops the scan.

        None when: no scan covered ``onset`` (the click began before the scan or after it
        stopped), this scan already selected once, or the click is reported more than
        :data:`MAX_SELECT_LAG_S` after it began.
        """
        self._expire(now)
        if self._spent or now - onset > MAX_SELECT_LAG_S:
            return None
        index = self.index_at(onset)
        if index is None:
            return None
        self._spent = True
        self.stop(now)
        return self._items[index]
