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

**A spoken item is never cut off by the next step.** When the scan is heard rather than
seen (``announce.py``), each item's name is spoken as it lights. The caller injects how
long that announcement takes (``announce_s``), and an item stays lit for the longer of
``dwell_s`` and its announcement, so the highlight never advances mid-word. The timeline
is still a pure function of time: per-item dwells are fixed when the scanner is built.

**A click selects what was highlighted when the click began, not when it was recognised.**
The detector reports a sound only after ``POST_QUIET_MS`` of quiet behind it, so by the time
the event reaches the scanner the highlight may already have moved on. :meth:`select` takes
the sound's onset time and answers for that instant. A click whose onset lies outside the
scan it is meant for (before it began, after it stopped) selects nothing, a click reported
more than :data:`MAX_SELECT_LAG_S` after it began selects nothing, and one click selects at
most once: a click whose onset is not later than the last selection's selects nothing
(AGENTS.md rule 9 / ADR-021).

**A selection does not end the scan (owner decision, 2026-10-23).** Repeating "scroll down"
used to need a pop before every click. Now the highlight stays on the selected item for its
full dwell, measured from the moment the selection was made, and then steps on as before,
so a second click repeats the item. The scan still stops on a pop, on pause, and after
:data:`MAX_LOOPS` passes with no selection -- counted from the *last* selection. The
timeline becomes a short list of segments, each re-anchored at a selection, and "what was
lit at ``t``?" stays exact for any ``t`` a non-stale click can ask about.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

__all__ = [
    "DEFAULT_INTERVAL_S",
    "DEFAULT_SCAN_ITEMS",
    "MAX_ANNOUNCE_S",
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
#: The longest an announcement may hold one item lit. A label that would take longer to
#: say is a configuration mistake, and a scan that never moves is worse than a clipped word.
MAX_ANNOUNCE_S = MAX_INTERVAL_S


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
    """What the scan shows at one instant. ``index`` is ``-1`` while not scanning.

    ``step`` counts highlight steps since the scan started (``-1`` while not scanning), so a
    caller can tell "a new step began" from "the same item is still lit" even when the
    index repeats -- a one-item scan, say.
    """

    scanning: bool
    index: int
    item: ScanItem | None
    step: int = -1


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


def _announce_seconds(announce_s: Callable[[ScanItem], float] | None, item: ScanItem) -> float:
    """How long announcing ``item`` takes, sanitised: ``0.0`` for anything unusable. Pure."""
    if announce_s is None:
        return 0.0
    try:
        seconds = float(announce_s(item))
    except Exception:  # an estimate that fails must not stop the scan from being built
        return 0.0
    if not math.isfinite(seconds) or seconds <= 0.0:
        return 0.0
    return min(MAX_ANNOUNCE_S, seconds)


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

    ``announce_s`` (optional) says how long announcing an item takes; that item then stays
    lit for ``max(interval_s, announce_s(item))``. Without it every item gets ``interval_s``.
    """

    def __init__(self, items: Sequence[ScanItem], interval_s: float = DEFAULT_INTERVAL_S,
                 max_loops: int = MAX_LOOPS,
                 announce_s: Callable[[ScanItem], float] | None = None) -> None:
        self._items = tuple(items)
        self._interval = scan_interval(interval_s)
        self._max_loops = max(1, int(max_loops))
        #: Seconds each item stays lit: never shorter than the interval, never mid-word.
        self._dwells = tuple(
            max(self._interval, _announce_seconds(announce_s, item)) for item in self._items
        )
        #: Every item on the plain interval: the original fixed-step arithmetic applies.
        self._uniform = all(d == self._interval for d in self._dwells)
        self._cycle = sum(self._dwells)
        #: Bumped by every :meth:`start`, so a caller can tell one scan from the next.
        self._generation = 0
        #: The latest scan as ``[start, end)``; ``end`` is None while it runs.
        self._start: float | None = None
        self._end: float | None = None
        #: The latest scan's timeline: ``(t0, first index, first step)`` per segment, oldest
        #: first. A scan starts with one at item 0; every selection adds one at its item.
        self._segments: list[tuple[float, int, int]] = []
        #: The onset of the latest scan's last selection: one click selects at most once.
        self._last_onset: float | None = None

    @property
    def items(self) -> tuple[ScanItem, ...]:
        return self._items

    @property
    def interval_s(self) -> float:
        return self._interval

    @property
    def dwells(self) -> tuple[float, ...]:
        """Seconds each item stays lit, in item order."""
        return self._dwells

    @property
    def generation(self) -> int:
        """How many scans have been started; identifies the latest one."""
        return self._generation

    @property
    def scanning(self) -> bool:
        return self._start is not None and self._end is None

    @property
    def span_s(self) -> float:
        """How long a scan runs after its start, or its last selection, before it stops."""
        if self._uniform:
            return self._max_loops * len(self._items) * self._interval
        return self._max_loops * self._cycle

    # ------------------------------------------------------------------ start / stop

    def start(self, now: float) -> bool:
        """Start a fresh scan at the first item. False (and nothing starts) with no items."""
        if not self._items:
            return False
        self._start, self._end, self._last_onset = float(now), None, None
        self._segments = [(float(now), 0, 0)]
        self._generation += 1
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

    def _anchor(self) -> float | None:
        """When the latest scan last started or selected: its passes count from here."""
        return self._segments[-1][0] if self._segments else None

    def _expire(self, now: float) -> None:
        """End a scan that has run its loops; the end is when it ran out, not when asked."""
        anchor = self._anchor()
        if anchor is not None and self._end is None and now - anchor >= self.span_s:
            self._end = anchor + self.span_s

    def _locate(self, elapsed: float, base: int = 0) -> tuple[int, int]:
        """``(index, step)`` lit ``elapsed`` seconds (>= 0) into a segment lit at ``base``. Pure.

        ``step`` counts from the segment's start: its first item is step 0.
        """
        n = len(self._items)
        if self._uniform:
            step = int(elapsed // self._interval)
            return (base + step) % n, step
        loops = int(elapsed // self._cycle)
        offset = elapsed - loops * self._cycle
        reached = 0.0
        for j in range(n):
            reached += self._dwells[(base + j) % n]
            if offset < reached:
                return (base + j) % n, loops * n + j
        # Float rounding at the very end of a cycle: that instant belongs to the next one.
        return base % n, (loops + 1) * n

    def _position(self, t: float) -> tuple[int, int] | None:
        """``(index, step)`` lit at ``t`` in the latest scan, or None if it did not cover ``t``.

        ``step`` counts from the scan's start and only ever grows, across segments.
        """
        if self._start is None or not self._items or not self._segments:
            return None
        anchor = self._segments[-1][0]
        end = self._end if self._end is not None else anchor + self.span_s
        if t < self._start or t >= end:
            return None
        for t0, base, step0 in reversed(self._segments):
            if t >= t0:
                index, step = self._locate(t - t0, base)
                return index, step0 + step
        return None  # older than the history kept (see `_prune`): no live click asks that

    def _prune(self, now: float) -> None:
        """Forget segments only a stale click could ask about; always keep the latest."""
        horizon = now - 2 * MAX_SELECT_LAG_S
        while len(self._segments) > 1 and self._segments[1][0] <= horizon:
            del self._segments[0]

    def index_at(self, t: float) -> int | None:
        """The item lit at time ``t`` in the latest scan, or None if no scan covered ``t``."""
        position = self._position(t)
        return None if position is None else position[0]

    def tick(self, now: float) -> int | None:
        """Bring the scan up to ``now``; the lit index, or None when not scanning."""
        self._expire(now)
        return self.index_at(now) if self.scanning else None

    def view(self, now: float) -> ScanView:
        """What to draw (or announce) at ``now``."""
        self._expire(now)
        position = self._position(now) if self.scanning else None
        if position is None:
            return ScanView(False, -1, None)
        index, step = position
        return ScanView(True, index, self._items[index], step)

    # ------------------------------------------------------------------ select

    def select(self, onset: float, now: float) -> ScanItem | None:
        """The item lit when the click began, or None.

        None when: no scan covered ``onset`` (the click began before the scan or after it
        stopped), the click is reported more than :data:`MAX_SELECT_LAG_S` after it began,
        or its onset is not later than the last selection's (one click, one select).

        A selection made while the scan runs re-anchors it at ``now`` on the selected item:
        that item stays lit for its full dwell, then the highlight steps on, and the
        inactivity stop counts its passes from here. A click that began just before a stop
        still lands, but does not restart a scan that was stopped.
        """
        self._expire(now)
        if now - onset > MAX_SELECT_LAG_S:
            return None
        if self._last_onset is not None and onset <= self._last_onset:
            return None
        position = self._position(onset)
        if position is None:
            return None
        index = position[0]
        self._last_onset = onset
        if self.scanning:
            current = self._position(now)
            next_step = (current[1] if current is not None else position[1]) + 1
            self._segments.append((max(float(now), self._segments[-1][0]), index, next_step))
            self._prune(now)
        return self._items[index]
