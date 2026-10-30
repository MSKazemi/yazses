"""Hold-to-talk from hand/controller gestures — a pure state machine.

The daemon's keyboard path is press → ``_on_hold_start``, release → ``_on_hold_end``.
A headset has no key, only a tracked hand, and a tracked hand is a worse switch than a
key: it flickers when fingers occlude each other, and it can leave the camera's view
while "pressed". This module turns that unreliable stream of
:class:`~yazses.xr.types.GestureEvent` into the same clean START / STOP edges the
daemon already understands, and makes the failure direction safe: whatever the hand
does, the microphone is never left open.

* **Flicker grace** — a pinch end is not a STOP until ``release_grace_s`` has passed
  without the pinch coming back. A start inside the grace window *continues the same
  utterance* (no STOP/START pair), so a one-frame tracking drop cannot chop a sentence.
* **Debounce** — a press shorter than ``debounce_s`` is chatter and is CANCELled (an
  utterance that never was); a new press within ``debounce_s`` of the *release gesture*
  is ignored. The reference is the release gesture, not the later moment the grace
  expired, so a genuine re-press after a completed STOP always starts a new utterance.
* **Stuck-gesture safety** — a START with no end for ``max_hold_s`` is force-STOPped by
  :meth:`GesturePtt.tick`. A hand that leaves tracking sends *nothing*, so this is the
  only thing that closes the mic; the host must call ``tick`` on a timer.
* **Fail safe toward closing** — stop-direction events (a pinch/squeeze end, or a TAP that
  would toggle off) bypass ``min_confidence`` and are honoured whatever their
  timestamp: one that is out of order is applied at the current internal time, one that
  is implausibly far in the future at ``reference + max_future_s``, and either closes the
  mic at once (no grace).
* **Bounded clock** — once a ``tick`` (or an event) has given the machine a time
  reference, a start-direction event stamped more than ``max_future_s`` beyond it is
  clamped to ``reference + max_future_s``, so a forged stamp cannot park the clock far
  ahead of the host. Before the first tick/event there is no reference, so the first
  event is taken as given: call ``tick(now)`` once at start-up to arm the bound. With
  that, the mic is closed by ``tick(max timestamp seen + max_hold_s + 1)`` for any
  sequence of events and ticks (property-tested).

Time is driven entirely by the numbers handed in (event timestamps and ``tick``), never
by a clock read here, so the machine is deterministic and trivially testable. Action
timestamps are non-decreasing; a STOP is stamped when it became effective (grace
expiry or the hold limit), not when the host happened to call ``tick``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from yazses.xr.types import GestureEvent, GestureKind


class PttMode(Enum):
    """Which gesture drives push-to-talk. Closed; one family per session."""

    HOLD_PINCH = "hold_pinch"
    HOLD_SQUEEZE = "hold_squeeze"
    TOGGLE_TAP = "toggle_tap"


class PttActionKind(Enum):
    START = "start"    # open the mic (the daemon's hold-start)
    STOP = "stop"      # close the mic and transcribe (the daemon's hold-end)
    CANCEL = "cancel"  # close the mic and discard — the utterance never counted


@dataclass(frozen=True)
class PttAction:
    kind: PttActionKind
    timestamp_s: float


# The (start, end) gesture pair for each hold mode. TOGGLE_TAP uses TAP alone.
_HOLD_PAIRS = {
    PttMode.HOLD_PINCH: (GestureKind.PINCH_START, GestureKind.PINCH_END),
    PttMode.HOLD_SQUEEZE: (GestureKind.SQUEEZE_START, GestureKind.SQUEEZE_END),
}


class _Phase(Enum):
    IDLE = "idle"
    ACTIVE = "active"        # gesture held, mic open
    RELEASING = "releasing"  # gesture ended, mic still open until the grace elapses


def _finite_nonneg(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value!r}")
    return float(value)


class GesturePtt:
    """Gesture-driven hold-to-talk. Feed events, call :meth:`tick` on a timer.

    Not thread-safe by itself; the host serialises ``feed``/``tick`` the way the daemon
    serialises its hold callbacks under one lock.
    """

    def __init__(
        self,
        mode: PttMode,
        *,
        debounce_s: float = 0.05,
        release_grace_s: float = 0.12,
        max_hold_s: float = 120.0,
        min_confidence: float = 0.5,
        max_future_s: float = 5.0,
    ) -> None:
        if not isinstance(mode, PttMode):
            raise ValueError(f"mode must be a PttMode, got {mode!r}")
        self._mode = mode
        self._debounce_s = _finite_nonneg("debounce_s", debounce_s)
        self._grace_s = _finite_nonneg("release_grace_s", release_grace_s)
        self._max_hold_s = _finite_nonneg("max_hold_s", max_hold_s)
        if self._max_hold_s == 0.0:
            raise ValueError("max_hold_s must be > 0")
        self._min_confidence = _finite_nonneg("min_confidence", min_confidence)
        if self._min_confidence > 1.0:
            raise ValueError("min_confidence must be within [0, 1]")
        self._max_future_s = _finite_nonneg("max_future_s", max_future_s)
        self._init_state()

    def _init_state(self) -> None:
        self._phase = _Phase.IDLE
        self._time = 0.0                       # furthest time any timer has been advanced to
        self._armed = False                    # True once a tick/event gave a time reference
        self._last_event_s: float | None = None  # ordering clock: last accepted event stamp
        self._started_s = 0.0                  # when the current utterance began
        self._release_at = 0.0                 # grace deadline while RELEASING
        self._idle_since: float | None = None  # debounce reference: the last release gesture/STOP
        self._release_event_s = 0.0            # when the release gesture that began RELEASING came
        self._last_tap_s: float | None = None  # TOGGLE_TAP chatter reference

    # ------------------------------------------------------------------ public

    @property
    def mode(self) -> PttMode:
        return self._mode

    @property
    def is_listening(self) -> bool:
        """True while the mic should be open (including the post-release grace)."""
        return self._phase is not _Phase.IDLE

    def feed(self, event: GestureEvent) -> list[PttAction]:
        """Apply one gesture event; return the actions it (and any due timers) caused.

        Ignored with no effect at all: low-confidence *start-direction* events, gestures of
        another family, and start-direction events older than the last accepted one.
        Stop-direction events are never dropped for confidence or timestamp (see the
        module docstring); a start-direction stamp beyond ``max_future_s`` is clamped.
        """
        pair = _HOLD_PAIRS.get(self._mode)
        if pair is None:
            if event.kind is not GestureKind.TAP:
                return []
            stop_dir = self._phase is not _Phase.IDLE
        elif event.kind not in pair:
            return []
        else:
            stop_dir = event.kind is pair[1]

        if event.confidence < self._min_confidence:
            # A weak release must still close the mic; a weak press must not open it.
            if not stop_dir or self._phase is not _Phase.ACTIVE:
                return []

        ts = event.timestamp_s
        too_late = self._armed and ts > self._time + self._max_future_s
        if stop_dir and (
            too_late or (self._last_event_s is not None and ts < self._last_event_s)
        ):
            # Untrustworthy stamp on a stop: do not let it touch the ordering clock, and
            # close now rather than wait out a grace measured on a bogus time base.
            eff = self._time + self._max_future_s if too_late else self._time
            actions = self._advance(eff)
            t = self._time
            if pair is None:
                self._on_tap(t, actions, force_stop=True)
            else:
                self._on_end(t, actions, immediate=True)
            return actions

        if too_late:
            ts = self._time + self._max_future_s
        if self._last_event_s is not None and ts < self._last_event_s:
            return []
        self._last_event_s = ts

        # A pinch coming back inside the grace window continues the utterance. Checked
        # before the timers run so a restart exactly at the deadline still counts.
        if (
            pair is not None
            and event.kind is pair[0]
            and self._phase is _Phase.RELEASING
            and ts <= self._release_at
            and ts < self._started_s + self._max_hold_s
        ):
            self._time = max(self._time, ts)
            self._phase = _Phase.ACTIVE
            return []

        actions = self._advance(ts)
        t = max(ts, self._time)
        if pair is None:
            self._on_tap(t, actions)
        elif event.kind is pair[0]:
            self._on_start(t, actions)
        else:
            self._on_end(t, actions)
        return actions

    def tick(self, now_s: float) -> list[PttAction]:
        """Advance time; fire a due grace-expiry STOP or the max-hold safety STOP.

        Call this on a timer — it is the only thing that closes the mic when the hand
        stops reporting. A ``now_s`` earlier than time already seen is a no-op.
        """
        if isinstance(now_s, bool) or not isinstance(now_s, (int, float)) or not math.isfinite(now_s):
            raise ValueError(f"now_s must be a finite number, got {now_s!r}")
        return self._advance(float(now_s))

    def reset(self, now_s: float | None = None) -> list[PttAction]:
        """Drop all state (device reconnect, mode change). CANCELs a live utterance.

        The timeline restarts: the next event may carry any timestamp, since a
        reconnecting companion can remap its clock.
        """
        actions: list[PttAction] = []
        if self._phase is not _Phase.IDLE:
            stamp = self._time if now_s is None else max(self._time, float(now_s))
            actions.append(PttAction(PttActionKind.CANCEL, stamp))
        self._init_state()
        return actions

    # ---------------------------------------------------------------- internals

    def _advance(self, now: float) -> list[PttAction]:
        self._armed = True
        if now > self._time:
            self._time = now
        if self._phase is _Phase.IDLE:
            return []
        stop_at = self._started_s + self._max_hold_s
        idle_ref = stop_at
        if self._phase is _Phase.RELEASING and self._release_at <= stop_at:
            stop_at = self._release_at
            idle_ref = self._release_event_s  # debounce is measured from the gesture
        if stop_at > self._time:
            return []
        self._phase = _Phase.IDLE
        self._idle_since = idle_ref
        return [PttAction(PttActionKind.STOP, stop_at)]

    def _on_start(self, t: float, actions: list[PttAction]) -> None:
        if self._phase is not _Phase.IDLE:
            return  # duplicate start while already held
        if self._idle_since is not None and t - self._idle_since < self._debounce_s:
            return  # chatter right after a STOP
        self._phase = _Phase.ACTIVE
        self._started_s = t
        actions.append(PttAction(PttActionKind.START, t))

    def _on_end(self, t: float, actions: list[PttAction], *, immediate: bool = False) -> None:
        if self._phase is not _Phase.ACTIVE:
            return  # end with no start, or a duplicate end
        if t - self._started_s < self._debounce_s:
            # A blip shorter than the debounce is not an utterance.
            self._phase = _Phase.IDLE
            actions.append(PttAction(PttActionKind.CANCEL, t))
            return
        self._phase = _Phase.RELEASING
        self._release_event_s = t
        self._release_at = t if immediate else t + self._grace_s
        actions.extend(self._advance(t))  # grace of 0 stops immediately

    def _on_tap(self, t: float, actions: list[PttAction], *, force_stop: bool = False) -> None:
        if force_stop and self._phase is _Phase.IDLE:
            return
        if (
            not force_stop
            and self._last_tap_s is not None
            and t - self._last_tap_s < self._debounce_s
        ):
            return  # double-registered tap
        self._last_tap_s = t
        if self._phase is _Phase.IDLE:
            self._phase = _Phase.ACTIVE
            self._started_s = t
            actions.append(PttAction(PttActionKind.START, t))
        else:
            self._phase = _Phase.IDLE
            self._idle_since = t
            actions.append(PttAction(PttActionKind.STOP, t))
