"""Background poller that mirrors the daemon's ``status`` for the overlay.

Mirrors the tray's polling pattern (``tray/app.py``) but at an adaptive cadence:
poll fast while recording (so the rings track the voice) and slowly otherwise
(so an idle overlay is nearly free). The IPC call and threading are isolated
here; ``next_interval`` and ``parse_status`` are pure and tested directly.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

# Adaptive poll cadence (seconds).
_FAST_INTERVAL_S = 0.05   # 20 Hz while recording — drives ring intensity
_SLOW_INTERVAL_S = 0.25   # 4 Hz otherwise — quick enough to catch recording start
# How long to keep retrying a daemon that has never answered before giving up.
_BOOT_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class StatusSnapshot:
    """What the overlay needs from one ``status`` reply."""

    state: str = "idle"
    audio_level: float = 0.0
    vad_threshold: float = 0.01
    reachable: bool = True
    #: How far a Head-Pointer dwell-click is from firing, 0..1; 0 means none in progress.
    dwell_progress: float = 0.0
    #: True while a dwell-click can start building: dwell is on and the pointer has travelled
    #: since the last click. The ring is not on screen yet, but it may be within one frame.
    dwell_armed: bool = False
    #: Mouth-Sound Switch scan: the item labels and the lit index while a scan runs, else
    #: ``()`` and ``-1``. A click selects what is lit, so this is polled fast while scanning.
    scan_items: tuple[str, ...] = ()
    scan_index: int = -1

    @property
    def scanning(self) -> bool:
        return 0 <= self.scan_index < len(self.scan_items)


def next_interval(
    state: str, dwell_progress: float = 0.0, dwell_armed: bool = False,
    scanning: bool = False,
) -> float:
    """Seconds to wait before the next poll, given the current daemon state.

    Fast while a dwell is building as well as while recording: the ring that warns of a
    click is only useful if it advances smoothly *before* the click. And fast while one *can*
    start building (``dwell_armed``): polling at the slow rate until progress was already above
    zero meant the ring could be first seen up to a slow interval after it began -- for a short
    dwell, after the click it was meant to announce.

    And fast while a Mouth-Sound Switch scan runs (``scanning``): the user clicks on the item
    they *see* lit, and the daemon selects the one lit when the click began, so every
    millisecond the drawn highlight lags the real one is a window for selecting the wrong item.
    """
    if state == "recording" or dwell_progress > 0.0 or dwell_armed or scanning:
        return _FAST_INTERVAL_S
    return _SLOW_INTERVAL_S


def _dwell_progress(info: dict) -> float:
    """The Head-Pointer's dwell fraction from a ``status`` reply, or 0.0. Defensive."""
    block = info.get("headpointer")
    if not isinstance(block, dict):
        return 0.0
    try:
        value = float(block.get("dwell_progress", 0.0))
    except (TypeError, ValueError):
        return 0.0
    if value != value or value <= 0.0:  # NaN, or nothing in progress
        return 0.0
    return min(1.0, value)


def _dwell_armed(info: dict) -> bool:
    """Whether the Head-Pointer says a dwell can start building. Strictly ``True`` only."""
    block = info.get("headpointer")
    return isinstance(block, dict) and block.get("dwell_armed") is True


def _scan(info: dict) -> tuple[tuple[str, ...], int]:
    """``(labels, lit index)`` from a ``status`` reply's ``mouthswitch`` block. Defensive.

    Anything malformed reads as *no scan* -- ``((), -1)`` -- so a bad reply can only hide
    the highlight, never light a wrong item.
    """
    block = info.get("mouthswitch")
    if not isinstance(block, dict) or block.get("scanning") is not True:
        return (), -1
    items = block.get("items")
    index = block.get("index")
    if not isinstance(items, (list, tuple)) or not all(isinstance(i, str) for i in items):
        return (), -1
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(items):
        return (), -1
    return tuple(items), index


def parse_status(info: dict) -> StatusSnapshot:
    """Convert a ``status`` reply dict into a :class:`StatusSnapshot` (defensive)."""
    def _f(key: str, default: float) -> float:
        try:
            return float(info.get(key, default))
        except (TypeError, ValueError):
            return default

    state = info.get("state")
    scan_items, scan_index = _scan(info)
    return StatusSnapshot(
        state=state if isinstance(state, str) else "idle",
        audio_level=_f("audio_level", 0.0),
        vad_threshold=_f("vad_threshold", 0.01),
        reachable=True,
        dwell_progress=_dwell_progress(info),
        dwell_armed=_dwell_armed(info),
        scan_items=scan_items,
        scan_index=scan_index,
    )


class StatusPoller:
    """Polls ``status`` on a daemon thread; exposes the latest snapshot."""

    def __init__(self, client: object) -> None:
        # ``client`` is any object with ``.call(method) -> dict`` (the IPC client).
        self._client = client
        self._lock = threading.Lock()
        self._latest = StatusSnapshot(reachable=False)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def latest(self) -> StatusSnapshot:
        with self._lock:
            return self._latest

    def _set(self, snap: StatusSnapshot) -> None:
        with self._lock:
            self._latest = snap

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="overlay-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        import time

        boot_deadline = time.monotonic() + _BOOT_TIMEOUT_S
        booted = False
        while not self._stop.is_set():
            interval = _SLOW_INTERVAL_S
            try:
                info = self._client.call(  # type: ignore[attr-defined]
                    "status", consume_notifications=False
                )
                snap = parse_status(info if isinstance(info, dict) else {})
                self._set(snap)
                booted = True
                interval = next_interval(
                    snap.state, snap.dwell_progress, snap.dwell_armed, snap.scanning
                )
            except Exception:
                # Daemon not up yet (or a transient error). Keep trying until the
                # boot window closes, then mark unreachable and slow-poll forever.
                if not booted and time.monotonic() > boot_deadline:
                    self._set(StatusSnapshot(reachable=False))
                else:
                    self._set(StatusSnapshot(state="idle", reachable=False))
            self._stop.wait(interval)
