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


def next_interval(state: str) -> float:
    """Seconds to wait before the next poll, given the current daemon state."""
    return _FAST_INTERVAL_S if state == "recording" else _SLOW_INTERVAL_S


def parse_status(info: dict) -> StatusSnapshot:
    """Convert a ``status`` reply dict into a :class:`StatusSnapshot` (defensive)."""
    def _f(key: str, default: float) -> float:
        try:
            return float(info.get(key, default))
        except (TypeError, ValueError):
            return default

    state = info.get("state")
    return StatusSnapshot(
        state=state if isinstance(state, str) else "idle",
        audio_level=_f("audio_level", 0.0),
        vad_threshold=_f("vad_threshold", 0.01),
        reachable=True,
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
                interval = next_interval(snap.state)
            except Exception:
                # Daemon not up yet (or a transient error). Keep trying until the
                # boot window closes, then mark unreachable and slow-poll forever.
                if not booted and time.monotonic() > boot_deadline:
                    self._set(StatusSnapshot(reachable=False))
                else:
                    self._set(StatusSnapshot(state="idle", reachable=False))
            self._stop.wait(interval)
