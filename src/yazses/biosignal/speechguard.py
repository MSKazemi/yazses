"""Speech guard: "is the user talking right now?" for the jaw-clench switch.

``docs/research/muscle-brain-control.md`` names talking as the fatal confound for a
jaw-clench switch inside a *dictation* tool: the masseter and temporalis are active
while you speak, so the very product this switch lives in is the thing most likely to
trigger it. :class:`~yazses.biosignal.artifacts.JawClenchDetector` therefore takes a
``speech_guard: Callable[[], bool]`` and stays silent while it returns true; the runner
exposes the same hook as ``RunnerCallbacks.speech_active``. This module is the
implementation of that callable. It is pure (no audio, no daemon imports), thread-safe
and clock-injected, so it is testable without a microphone.

## What it combines

Any number of zero-argument *sources*, each answering one question about the present:
"a dictation turn is recording", "the VAD says speech", "TTS is playing" (the speakers'
own voice also moves the user's jaw if they subvocalise along, and loud read-back can
leak into other channels). The guard is true while *any* source is true, plus a
``hangover_s`` tail after the last true reading, because jaw muscles stay active for a
moment after the last phoneme and the VAD itself closes late. ``hangover_s`` (default
0.5 s) and ``lead_s`` (default 0.25 s) are engineering choices, not measured values;
tune them against real sessions (see ``docs/research/muscle-brain-control.md``).

``lead_s`` is a pre-roll for retrospective queries (:meth:`SpeechGuard.was_speaking`):
a recording flag or VAD rises some tens of milliseconds *after* the lips start moving,
so a jaw burst that began just before the flag rose is still speech. Rising edges are
back-dated by ``lead_s`` when asking "was there speech between t0 and t1?". The plain
call ``guard()`` can only look backwards, so there ``hangover_s`` is what holds it up.

## Why it fails closed

A source that raises counts as *speaking* (logged once, then at most once a minute with
a count). The costs are asymmetric: a suppressed clench costs the user one retry, while a
clench that opens the microphone in the middle of a sentence corrupts a dictation and may
type text into the wrong place. This mirrors the detector's own handling of a raising
guard. It also satisfies the spirit of AGENTS.md rule 9 (a guard is judged on how rarely
it fires): the guard only holds on a specific, checkable signal (a source says the user is
speaking), never a heuristic, and the release is simply to stop talking.

## The watchdog

Fail-closed has a failure mode of its own: a source wedged at ``True`` (a recording flag
never cleared, a VAD stuck open, a source raising forever) would suppress the switch
indefinitely, and for a user who relies on the switch that is a lock-out. A source that has
been continuously true (or erroring) for longer than ``max_stuck_s`` (default 120 s, a
design choice) is *ignored* until it reports false once, and that is logged once per
episode and visible in :meth:`SpeechGuard.snapshot`. A genuinely long monologue is the
price: pass a larger ``max_stuck_s`` to :meth:`SpeechGuard.add_source` for a source that
legitimately stays true long (``math.inf`` disables the watchdog for that source). Other
sources, such as the VAD, still suppress during real speech.

## Visibility

:meth:`SpeechGuard.suppressed_fraction` is the share of recent time the guard was
suppressing, so a user (or ``doctor``) can see when the guard eats every clench, which
usually means a mis-set VAD threshold rather than a user who never stops talking.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_HANGOVER_S = 0.5
DEFAULT_LEAD_S = 0.25
DEFAULT_MAX_STUCK_S = 120.0
DEFAULT_WINDOW_S = 60.0
# Between two polls longer than this the guard was not being asked, so that stretch
# says nothing about suppression and is excluded from the fraction.
_MAX_POLL_GAP_S = 1.0
_ERROR_LOG_INTERVAL_S = 60.0
_HISTORY_S = 300.0
_MAX_SEGMENTS = 512


@dataclass
class _SourceState:
    """Mutable per-source bookkeeping, guarded by ``SpeechGuard._lock``."""

    name: str
    fn: Callable[[], bool]
    max_stuck_s: float
    polls: int = 0
    last_value: bool | None = None  # raw value of the last poll (True on error)
    last_true_t: float | None = None  # last poll at which the source counted as true
    true_since: float | None = None  # start of the current continuous true/error run
    stuck: bool = False  # currently ignored by the watchdog
    stuck_episodes: int = 0
    errored: bool = False  # the last poll raised
    error_count: int = 0
    last_error_log_t: float | None = None
    errors_since_log: int = 0


class SpeechGuard:
    """Thread-safe, clock-injected "is the user speaking?" callable.

    ``guard()`` is true while any source is true or was true within ``hangover_s``.
    Sources are called outside the internal lock, so a slow or re-entrant source cannot
    deadlock a concurrent ``snapshot()``.
    """

    def __init__(
        self,
        sources: Sequence[Callable[[], bool]] = (),
        *,
        hangover_s: float = DEFAULT_HANGOVER_S,
        lead_s: float = DEFAULT_LEAD_S,
        max_stuck_s: float = DEFAULT_MAX_STUCK_S,
        window_s: float = DEFAULT_WINDOW_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if hangover_s < 0 or lead_s < 0:
            raise ValueError("hangover_s and lead_s must be >= 0")
        if max_stuck_s <= 0:
            raise ValueError("max_stuck_s must be > 0 (use math.inf to disable)")
        if window_s <= 0:
            raise ValueError("window_s must be > 0")
        self.hangover_s = float(hangover_s)
        self.lead_s = float(lead_s)
        self.max_stuck_s = float(max_stuck_s)
        self.window_s = float(window_s)
        self._clock = clock
        self._lock = threading.RLock()
        self._sources: dict[str, _SourceState] = {}
        # Last time any source was effectively true, and the union of speech segments
        # [start, end] (start = first true poll; end = last true poll of the run).
        self._last_true_any: float | None = None
        self._segments: deque[list[float]] = deque(maxlen=_MAX_SEGMENTS)
        # Suppression history as [t_start, t_end, value] runs of contiguous polls.
        self._runs: deque[list[Any]] = deque(maxlen=4096)
        self._last_poll_t: float | None = None
        self._last_result: bool | None = None
        for i, fn in enumerate(sources):
            self.add_source(f"source{i}", fn)

    # -- source management ---------------------------------------------------------

    def add_source(
        self, name: str, fn: Callable[[], bool], *, max_stuck_s: float | None = None
    ) -> None:
        """Register a named source. ``max_stuck_s`` overrides the guard-wide watchdog."""
        limit = self.max_stuck_s if max_stuck_s is None else float(max_stuck_s)
        if limit <= 0:
            raise ValueError("max_stuck_s must be > 0 (use math.inf to disable)")
        with self._lock:
            if name in self._sources:
                raise ValueError(f"speech source {name!r} already registered")
            self._sources[name] = _SourceState(name=name, fn=fn, max_stuck_s=limit)

    def remove_source(self, name: str) -> bool:
        """Drop a source; returns whether it existed."""
        with self._lock:
            return self._sources.pop(name, None) is not None

    @property
    def source_names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._sources)

    # -- the guard -----------------------------------------------------------------

    def __call__(self) -> bool:
        """True when the user is, or just was, speaking: suppress the switch."""
        with self._lock:
            states = list(self._sources.values())
        readings: list[tuple[_SourceState, bool, BaseException | None]] = []
        for st in states:
            try:
                readings.append((st, bool(st.fn()), None))
            except Exception as exc:  # fail closed: unreadable source means "assume talking"
                readings.append((st, True, exc))
        now = self._clock()
        with self._lock:
            speaking_now = False
            for st, value, err in readings:
                if self._update_source(st, now, value, err):
                    speaking_now = True
            if speaking_now:
                self._note_speech(now)
            result = speaking_now or (
                self._last_true_any is not None and now - self._last_true_any <= self.hangover_s
            )
            self._note_poll(now, result)
            return result

    def _update_source(
        self, st: _SourceState, now: float, value: bool, exc: BaseException | None
    ) -> bool:
        """Fold one reading into ``st``; returns whether it counts as speaking now."""
        st.polls += 1
        st.last_value = value
        errored = exc is not None
        st.errored = errored
        if exc is not None:
            st.error_count += 1
            self._log_error(st, now, exc)
        if not value:
            st.true_since = None
            if st.stuck:
                log.info("speech source %r is false again; watchdog re-armed", st.name)
            st.stuck = False
            return False
        if st.true_since is None:
            st.true_since = now
        if not st.stuck and now - st.true_since > st.max_stuck_s:
            st.stuck = True
            st.stuck_episodes += 1
            log.warning(
                "speech source %r has been %s for over %.0f s; ignoring it until it "
                "reports false (watchdog)",
                st.name,
                "erroring" if errored else "true",
                st.max_stuck_s,
            )
        if st.stuck:
            return False
        st.last_true_t = now
        return True

    def _log_error(self, st: _SourceState, now: float, exc: BaseException) -> None:
        st.errors_since_log += 1
        last = st.last_error_log_t
        if last is not None and now - last < _ERROR_LOG_INTERVAL_S:
            return
        if last is None:
            log.warning(
                "speech source %r raised; treating as speaking (fail closed)",
                st.name,
                exc_info=exc,
            )
        else:
            log.warning(
                "speech source %r raised %d more times; still treating as speaking",
                st.name,
                st.errors_since_log,
                exc_info=exc,
            )
        st.last_error_log_t = now
        st.errors_since_log = 0

    def _note_speech(self, now: float) -> None:
        self._last_true_any = now
        seg = self._segments[-1] if self._segments else None
        if seg is not None and now - seg[1] <= self.hangover_s + _MAX_POLL_GAP_S:
            seg[1] = now
        else:
            self._segments.append([now, now])
        horizon = now - _HISTORY_S
        while len(self._segments) > 1 and self._segments[0][1] < horizon:
            self._segments.popleft()

    def _note_poll(self, now: float, result: bool) -> None:
        last_t = self._last_poll_t
        if last_t is not None and now - last_t <= _MAX_POLL_GAP_S and self._runs:
            run = self._runs[-1]
            if run[2] == result:
                run[1] = now
            else:
                # State changed between polls: hold the previous state until this poll.
                self._runs.append([last_t, now, result])
        else:
            self._runs.append([now, now, result])
        self._last_poll_t = now
        self._last_result = result
        horizon = now - self.window_s
        while len(self._runs) > 1 and self._runs[0][1] < horizon:
            self._runs.popleft()

    # -- retrospective / diagnostic queries -------------------------------------------

    def was_speaking(self, t_start: float, t_end: float | None = None) -> bool:
        """Was there speech overlapping ``[t_start, t_end]`` (guard-clock seconds)?

        Rising edges are back-dated by ``lead_s`` and the tail extended by
        ``hangover_s``. Only reflects what ``__call__`` has observed; it does not poll.
        """
        with self._lock:
            end = self._clock() if t_end is None else t_end
            for start, last in self._segments:
                if start - self.lead_s <= end and last + self.hangover_s >= t_start:
                    return True
            return False

    def suppressed_fraction(self, window_s: float | None = None) -> float | None:
        """Share of observed time in the last ``window_s`` the guard was suppressing.

        Time-weighted over contiguous polls; stretches with no polling are excluded.
        ``None`` when nothing has been observed in the window.
        """
        span = self.window_s if window_s is None else float(window_s)
        if span <= 0:
            raise ValueError("window_s must be > 0")
        with self._lock:
            now = self._clock()
            lo = now - span
            total = 0.0
            held = 0.0
            for t0, t1, value in self._runs:
                a, b = max(t0, lo), min(t1, now)
                if b <= a:
                    continue
                total += b - a
                if value:
                    held += b - a
            if total <= 0.0:
                return None
            return held / total

    def snapshot(self, *, poll: bool = False) -> dict[str, Any]:
        """Status for ``doctor``/status output. Passive unless ``poll=True``."""
        speaking: bool | None = self() if poll else None
        with self._lock:
            now = self._clock()
            sources: dict[str, dict[str, Any]] = {}
            for name, st in self._sources.items():
                sources[name] = {
                    "value": st.last_value,
                    "last_true_t": st.last_true_t,
                    "last_true_age_s": None if st.last_true_t is None else now - st.last_true_t,
                    "true_for_s": None if st.true_since is None else now - st.true_since,
                    "stuck": st.stuck,
                    "stuck_episodes": st.stuck_episodes,
                    "max_stuck_s": st.max_stuck_s,
                    "errored": st.errored,
                    "error_count": st.error_count,
                    "polls": st.polls,
                }
            return {
                "speaking": speaking if poll else self._last_result,
                "hangover_s": self.hangover_s,
                "lead_s": self.lead_s,
                "window_s": self.window_s,
                "last_speech_t": self._last_true_any,
                "last_speech_age_s": (
                    None if self._last_true_any is None else now - self._last_true_any
                ),
                "suppressed_fraction": self.suppressed_fraction(),
                "sources": sources,
            }


def from_daemon_flags(
    is_recording: Callable[[], bool],
    vad_active: Callable[[], bool] | None = None,
    tts_active: Callable[[], bool] | None = None,
    **kw: Any,
) -> SpeechGuard:
    """Build the guard the daemon hands the biosignal runner as ``speech_active``.

    Sources are named ``recording``, ``vad`` and ``tts``; ``**kw`` goes to
    :class:`SpeechGuard` (``hangover_s``, ``lead_s``, ``max_stuck_s``, ``window_s``,
    ``clock``). All sources share the guard-wide ``max_stuck_s`` watchdog; a dictation
    turn that legitimately runs longer than that is still covered by ``vad``. To give
    ``recording`` its own limit, pass ``max_stuck_s`` here or build the guard by hand
    with :meth:`SpeechGuard.add_source`.
    """
    guard = SpeechGuard((), **kw)
    guard.add_source("recording", is_recording)
    if vad_active is not None:
        guard.add_source("vad", vad_active)
    if tts_active is not None:
        guard.add_source("tts", tts_active)
    return guard
