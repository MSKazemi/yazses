"""One XR voice-input session — the pure composition of the ``yazses.xr`` modules.

A host (the future daemon wiring) owns the transport and the clock and drives this
object; the session owns no thread, no socket and reads no clock. It joins the pieces
that were built and tested one by one::

    frame bytes --wire--> ClockMap rebase --+--> RayFilter --> SampleRetention   (rays)
                                            +--> PanelRegistry                   (panels)
                                            +--> GesturePtt                      (gestures)

    word onset --> raycast retained rays against live panels --> binding
               --> confirm.decide(panel at onset vs panel at end) --> grounded snapshot

**Driving it.** ``feed_frame(data, desktop_now_s)`` for every companion frame and
``tick(now_s)`` on a timer (the stuck-gesture safety lives in ``tick``: a hand that
leaves tracking sends nothing, so only the timer closes the mic). The companion should
re-send each ``panel`` frame periodically; a panel not refreshed within
``panel_stale_after_s`` is dropped by ``tick``.

**A hostile or broken companion cannot hurt the session.** ``feed_frame`` never raises
for anything the companion sends: a refused frame becomes a ``FRAME_REJECTED`` event
whose ``detail`` is a *canonical category* ("unknown frame type"), never an excerpt of
the payload (the wire layer echoes up to 40 characters of a bad value in its messages;
that echo is cut here). Rejections are counted; after ``misbehave_after`` consecutive
ones the per-frame events stop and a single ``COMPANION_MISBEHAVING`` is emitted, then
repeated at most once per ``misbehave_interval_s``. A device-clock jump is a rejection
too, and it persists (a stepped clock is refused until the host calls :meth:`reset`),
so ``COMPANION_MISBEHAVING`` is the host's cue to ask for a re-pair and ``reset()``.

**Bounded everywhere.** Retained rays: ``retention_max_samples`` and
``retention_window_s``. Panels: ``max_panels``. Filters: one per ``RaySource`` (four).
Event lists are returned, never accumulated. Nothing is logged, and no coordinate or
timestamp appears in an event's ``detail``.

**Privacy.** Rays are held only in memory for ``retention_window_s`` (ADR-025); this
module never persists them. That default (8.0 s) is longer than ``SampleRetention``'s
2.0 s on purpose (see :class:`SessionConfig`) and is an open owner decision.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum

from yazses.grounding.contracts import TargetSnapshot
from yazses.xr.anchors import DictationTarget, PanelRegistry
from yazses.xr.binding import (
    BindingOutcome,
    BindingResult,
    PanelObservation,
    bind_demonstrative,
    nearest_rival,
    sustained_departure,
)
from yazses.xr.confirm import ConfirmDecision, ConfirmPolicy, ConfirmReason, Evidence, decide
from yazses.xr.grounded import panel_space, to_target_snapshot
from yazses.xr.privacy import SampleRetention
from yazses.xr.ptt import GesturePtt, PttAction, PttActionKind, PttMode
from yazses.xr.raycast import nearest_hit
from yazses.xr.smoothing import RayFilter
from yazses.xr.types import GestureEvent, Panel, PanelHit, RaySource, XrSample
from yazses.xr.wire import (
    DEFAULT_MAX_BYTES,
    ClockMap,
    PanelGone,
    PanelUpdate,
    WireError,
    decode_frame,
    rebase,
)

__all__ = [
    "ResolutionSource",
    "SessionConfig",
    "SessionEvent",
    "SessionEventKind",
    "SessionResolution",
    "SessionStats",
    "XrSession",
]

# --------------------------------------------------------------------------- events


class SessionEventKind(Enum):
    """What happened. Closed; a new kind is a reviewed diff."""

    PTT_START = "ptt_start"
    PTT_STOP = "ptt_stop"
    PTT_CANCEL = "ptt_cancel"
    PANEL_ADDED = "panel_added"
    PANEL_REMOVED = "panel_removed"
    FRAME_REJECTED = "frame_rejected"
    COMPANION_MISBEHAVING = "companion_misbehaving"


_PTT_KIND = {
    PttActionKind.START: SessionEventKind.PTT_START,
    PttActionKind.STOP: SessionEventKind.PTT_STOP,
    PttActionKind.CANCEL: SessionEventKind.PTT_CANCEL,
}

_DETAIL_MAX = 120


@dataclass(frozen=True)
class SessionEvent:
    """One small, log-safe fact for the host. ``timestamp_s`` is on the desktop clock.

    ``panel_id`` is set for panel events (it was validated by the wire layer: printable,
    at most 128 characters). ``detail`` is a canonical phrase, at most 120 characters,
    and is never taken from a frame's payload.
    """

    kind: SessionEventKind
    timestamp_s: float
    panel_id: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp_s, (int, float)) or isinstance(self.timestamp_s, bool) \
                or not math.isfinite(self.timestamp_s):
            raise ValueError("SessionEvent.timestamp_s must be a finite number")
        if len(self.detail) > _DETAIL_MAX:
            raise ValueError(f"SessionEvent.detail is limited to {_DETAIL_MAX} characters")


@dataclass(frozen=True)
class SessionStats:
    """Counters for the host's health display. All are cumulative since the last reset()."""

    frames_accepted: int = 0
    frames_rejected: int = 0
    consecutive_rejections: int = 0
    events_suppressed: int = 0   # FRAME_REJECTED events withheld by the rate limits


class ResolutionSource(Enum):
    PINNED = "pinned"   # the user's explicit DictationTarget
    RAY = "ray"         # bound from where the retained rays pointed
    NONE = "none"       # no target; fall back to keyboard focus


@dataclass(frozen=True)
class SessionResolution:
    """The answer to "where does this word point?".

    ``panel_id`` is None unless a target was found (pinned, or bound from rays).
    ``decision`` says whether to confirm before acting. ``snapshot`` is the best
    supporting pointing sample as a grounding target (None when there is no panel or no
    sample hit it). ``binding``, ``panel_at_onset`` and ``panel_at_end`` are the evidence
    behind the answer, for the host's diagnostics.
    """

    panel_id: str | None
    source: ResolutionSource
    decision: ConfirmDecision
    snapshot: TargetSnapshot | None
    binding: BindingResult
    panel_at_onset: str | None = None
    panel_at_end: str | None = None


# ----------------------------------------------------------------------- reason text

# The wire layer's messages sometimes echo a short excerpt of the offending value
# (``unknown frame type 'abc'``). Only these fixed leading phrases are ever reported.
_KNOWN_REASONS = (
    "frame too large",
    "frame is not valid UTF-8",
    "frame must be bytes or str",
    "frame must be a JSON object",
    "frame is nested too deeply",
    "invalid JSON",
    "duplicate key",
    "non-finite number literal",
    "integer too large",
    "unsupported version",
    "unknown frame type",
    "unknown source",
    "unknown kind",
    "bad fields",
    "device clock jumped",
    "frame maps before the desktop clock's origin",
)
_INVALID_FRAME = re.compile(r"^invalid (sample|gesture|panel|panel_gone) frame")
# "<field> must be ..." / "<field> is outside ..." — field names are fixed by the wire
# code (never hostile); the tail is restricted to lowercase words so no value can ride along.
_FIELD_REASON = re.compile(r"^[a-z_]{1,16}(?:\[\d\])? (?:must|is) [a-z]+(?: [a-z]+){0,5}")


def _canonical_reason(text: str) -> str:
    """Map a ``WireError`` message to a canonical phrase that carries no payload text."""
    for known in _KNOWN_REASONS:
        if text.startswith(known):
            return known
    m = _INVALID_FRAME.match(text)
    if m is not None:
        return m.group(0)
    m = _FIELD_REASON.match(text)
    if m is not None:
        return m.group(0)
    return "malformed frame"


# ----------------------------------------------------------------------------- config


def _positive(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite number > 0, got {value!r}")


def _positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be an integer >= 1, got {value!r}")


@dataclass(frozen=True)
class SessionConfig:
    """Tunables, all validated. Defaults are starting points to measure, not validated values.

    ``retention_window_s`` (8.0 s, with ``retention_max_samples`` 720) is deliberately
    LONGER than :class:`~yazses.xr.privacy.SampleRetention`'s own 2.0 s default: a spoken
    sentence is recognised *after* it ends, so the rays at a word's onset must still be
    held when the transcript arrives, and a long sentence outlasts 2 s. ADR-025 says
    "a few seconds"; 8 s stretches that. OPEN PRIVACY DECISION FOR THE OWNER: how long
    pointing rays may be held in memory (they never leave it) is a privacy trade-off
    against long-sentence binding, and has not been decided or measured. Until it is,
    treat 8.0 s / 720 as a provisional default, not a policy.
    ``primary_source`` restricts binding to one ray kind; None uses every retained ray.

    The next four tune the confirm policy's evidence rules (see
    :class:`~yazses.xr.confirm.ConfirmPolicy`); like every default here they are starting
    points to MEASURE, not validated values. ``error_budget_deg`` is the angular error the
    policy assumes of the tracker (rays closer than this to a neighbouring panel are held;
    0 turns the rule off), ``settle_s`` how long the gaze must have rested on the bound
    panel since leaving another one (0 turns the rule off), ``min_departure_s`` how long a
    look at a different panel must last at the end of the utterance to count as a changed
    target, and ``history_s`` how far before the word the binder looks for the panel the
    gaze came from.
    """

    ptt_mode: PttMode = PttMode.HOLD_PINCH
    max_hold_s: float = 120.0
    max_frame_bytes: int = DEFAULT_MAX_BYTES
    max_panels: int = 64
    panel_stale_after_s: float = 30.0
    retention_window_s: float = 8.0
    retention_max_samples: int = 720
    pin_ttl_s: float = 60.0
    lead_s: float = 0.4
    lag_s: float = 0.2
    max_ray_distance_m: float = 10.0
    edge_tolerance_s: float = 0.25
    primary_source: RaySource | None = None
    error_budget_deg: float = 3.0
    settle_s: float = 0.3
    min_departure_s: float = 0.5
    history_s: float = 1.5
    smooth: bool = True
    misbehave_after: int = 20
    misbehave_interval_s: float = 10.0
    reject_events_per_window: int = 5
    reject_window_s: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.ptt_mode, PttMode):
            raise ValueError("ptt_mode must be a PttMode")
        if self.primary_source is not None and not isinstance(self.primary_source, RaySource):
            raise ValueError("primary_source must be a RaySource or None")
        for name in ("max_hold_s", "panel_stale_after_s", "retention_window_s", "pin_ttl_s",
                     "max_ray_distance_m", "edge_tolerance_s", "misbehave_interval_s",
                     "reject_window_s"):
            _positive(name, getattr(self, name))
        for name in ("max_frame_bytes", "max_panels", "retention_max_samples",
                     "misbehave_after", "reject_events_per_window"):
            _positive_int(name, getattr(self, name))
        _positive("history_s", self.history_s)
        for name in ("lead_s", "lag_s", "error_budget_deg", "settle_s", "min_departure_s"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not math.isfinite(v) or v < 0:
                raise ValueError(f"{name} must be a finite number >= 0, got {v!r}")


def _finite_time(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


# ---------------------------------------------------------------------------- session


class XrSession:
    """Pure, injected-clock XR session. Not thread-safe; the host serialises its calls."""

    def __init__(self, config: SessionConfig | None = None) -> None:
        cfg = config if config is not None else SessionConfig()
        self._cfg = cfg
        self._clock = ClockMap()
        self._ptt = GesturePtt(cfg.ptt_mode, max_hold_s=cfg.max_hold_s)
        self._registry = PanelRegistry(cfg.max_panels, cfg.panel_stale_after_s)
        self._target = DictationTarget(self._registry)
        self._retention = SampleRetention(cfg.retention_window_s, cfg.retention_max_samples)
        self._filters: dict[RaySource, RayFilter] = {}
        self._geometry_version: dict[str, int] = {}   # panel_id -> epoch of its last change
        self._epoch = 0                                # never repeats, even across re-adds
        self._now: float | None = None
        self._init_counters()

    def _init_counters(self) -> None:
        self._accepted = 0
        self._rejected = 0
        self._consecutive = 0
        self._suppressed = 0
        self._last_misbehave_s: float | None = None
        self._reject_window_start = 0.0
        self._reject_window_count = 0

    # ----------------------------------------------------------------- read-outs

    @property
    def is_listening(self) -> bool:
        """True while the mic should be open (the push-to-talk state machine's view)."""
        return self._ptt.is_listening

    @property
    def stats(self) -> SessionStats:
        return SessionStats(self._accepted, self._rejected, self._consecutive, self._suppressed)

    @property
    def sample_count(self) -> int:
        return len(self._retention)

    def panels(self) -> tuple[Panel, ...]:
        """Held panels in stable ``panel_id`` order (including any not yet expired)."""
        return self._registry.panels()

    def pinned(self) -> str | None:
        """The pinned panel id at the latest known time, or None."""
        return None if self._now is None else self._target.current(self._now)

    # -------------------------------------------------------------------- frames

    def feed_frame(self, data: bytes | str, desktop_now_s: float) -> list[SessionEvent]:
        """Apply one companion frame; return the events it caused. Never raises for ``data``.

        ``desktop_now_s`` is the host's monotonic clock at arrival (a bad value there is
        a host bug and raises ``ValueError``). Any problem with the frame itself —
        malformed, hostile, a stepped device clock — becomes a ``FRAME_REJECTED`` event.
        """
        now = _finite_time("desktop_now_s", desktop_now_s)
        self._advance(now)
        try:
            frame = rebase(decode_frame(data, max_bytes=self._cfg.max_frame_bytes), self._clock, now)
        except WireError as exc:
            return self._reject(_canonical_reason(str(exc)), now)
        except Exception:  # a decoder bug must not become a companion-triggered crash
            return self._reject("internal decode error", now)
        try:
            events = self._apply(frame, now)
        except Exception:  # defence in depth: validated frames should never get here
            return self._reject("internal apply error", now)
        self._accepted += 1
        self._consecutive = 0
        return events

    def _apply(self, frame: object, now: float) -> list[SessionEvent]:
        if isinstance(frame, XrSample):
            self._on_sample(frame, now)
            return []
        if isinstance(frame, GestureEvent):
            return self._ptt_events(self._ptt.feed(frame))
        if isinstance(frame, PanelUpdate):
            return self._on_panel(frame.panel, now)
        if isinstance(frame, PanelGone):
            return self._on_panel_gone(frame.panel_id, now)
        raise TypeError("unhandled frame type")  # unreachable; caught as an apply error

    def _on_sample(self, sample: XrSample, now: float) -> None:
        if self._cfg.smooth:
            filt = self._filters.get(sample.source)
            if filt is None:
                filt = self._filters[sample.source] = RayFilter()
            sample = filt.update(sample)
        # ``now_s`` anchors the future-stamp check to the desktop clock, not to the newest
        # retained ray: after a long pause the next honest ray must not look "ahead".
        self._retention.add(sample, now_s=now)

    def _on_panel(self, panel: Panel, now: float) -> list[SessionEvent]:
        before = {p.panel_id: p for p in self._registry.panels()}
        self._registry.upsert(panel, now)
        after = {p.panel_id for p in self._registry.panels()}
        events: list[SessionEvent] = []
        for pid in sorted(set(before) - after):  # evicted at capacity
            self._forget_geometry(pid)
            events.append(SessionEvent(SessionEventKind.PANEL_REMOVED, now, pid, "evicted: panel limit"))
        old = before.get(panel.panel_id)
        if old is None:
            events.append(SessionEvent(SessionEventKind.PANEL_ADDED, now, panel.panel_id))
        if old != panel:
            self._epoch += 1
            self._geometry_version[panel.panel_id] = self._epoch
        return events

    def _on_panel_gone(self, panel_id: str, now: float) -> list[SessionEvent]:
        if not self._registry.remove(panel_id):
            return []
        self._forget_geometry(panel_id)
        return [SessionEvent(SessionEventKind.PANEL_REMOVED, now, panel_id, "closed by companion")]

    def _forget_geometry(self, panel_id: str) -> None:
        self._geometry_version.pop(panel_id, None)

    def _ptt_events(self, actions: list[PttAction]) -> list[SessionEvent]:
        return [SessionEvent(_PTT_KIND[a.kind], a.timestamp_s) for a in actions]

    # ------------------------------------------------------------------ rejection

    def _reject(self, reason: str, now: float) -> list[SessionEvent]:
        self._rejected += 1
        self._consecutive += 1
        cfg = self._cfg
        if self._consecutive >= cfg.misbehave_after:
            self._suppressed += 1
            last = self._last_misbehave_s
            if last is None or now - last >= cfg.misbehave_interval_s or now < last:
                self._last_misbehave_s = now
                return [SessionEvent(
                    SessionEventKind.COMPANION_MISBEHAVING, now, None,
                    f"{self._consecutive} consecutive frames rejected; last: {reason}"[:_DETAIL_MAX],
                )]
            return []
        if now - self._reject_window_start >= cfg.reject_window_s or now < self._reject_window_start:
            self._reject_window_start = now
            self._reject_window_count = 0
        if self._reject_window_count >= cfg.reject_events_per_window:
            self._suppressed += 1
            return []
        self._reject_window_count += 1
        return [SessionEvent(SessionEventKind.FRAME_REJECTED, now, None, reason[:_DETAIL_MAX])]

    # ----------------------------------------------------------------------- time

    def _advance(self, now: float) -> None:
        if self._now is None or now > self._now:
            self._now = now

    def tick(self, now_s: float) -> list[SessionEvent]:
        """Advance time: expire stale panels and rays, and run the push-to-talk timers.

        Call on a timer (about 10 Hz is plenty). A hand that leaves tracking sends
        nothing, so a STOP from the grace or max-hold limit comes only from here.
        """
        now = _finite_time("now_s", now_s)
        self._advance(now)
        events = self._ptt_events(self._ptt.tick(now))
        for pid in self._registry.expire(now):
            self._forget_geometry(pid)
            events.append(SessionEvent(SessionEventKind.PANEL_REMOVED, now, pid, "stale"))
        self._retention.prune(self._now if self._now is not None else now)
        return events

    # ----------------------------------------------------------------- pin / reset

    def pin_panel(self, panel_id: str, *, ttl_s: float | None = None, now_s: float | None = None) -> None:
        """Make ``panel_id`` the explicit dictation target; it wins over where the rays pointed.

        ``KeyError`` if the panel is not held and fresh. ``now_s`` defaults to the latest
        time the session has seen.
        """
        if now_s is None:
            if self._now is None:
                raise KeyError(panel_id)
            now = self._now
        else:
            now = _finite_time("now_s", now_s)
        self._target.pin(panel_id, now, self._cfg.pin_ttl_s if ttl_s is None else ttl_s)

    def unpin(self) -> None:
        self._target.unpin()

    def reset(self) -> list[SessionEvent]:
        """Forget everything (device reconnect, re-pair, mode change). Returns what ended.

        A live utterance is CANCELled, every held panel is reported removed, the retained
        rays are dropped and the device clock mapping is cleared, so a companion that
        rebooted can start a fresh timeline.
        """
        stamp = self._now if self._now is not None else 0.0
        events = self._ptt_events(self._ptt.reset(stamp))
        for p in self._registry.panels():
            events.append(SessionEvent(SessionEventKind.PANEL_REMOVED, stamp, p.panel_id, "session reset"))
            self._registry.remove(p.panel_id)
        self._target.unpin()
        self._retention.clear()
        self._filters.clear()
        self._geometry_version.clear()
        self._clock.reset()
        self._init_counters()
        return events

    # -------------------------------------------------------------- demonstratives

    def resolve_demonstrative(
        self,
        word_onset_s: float,
        utterance_end_s: float,
        *,
        destructive: bool = False,
    ) -> SessionResolution:
        """Where does the word spoken at ``word_onset_s`` point? Pure read; changes no state.

        Times are on the desktop clock (the recogniser's word times mapped by the host).
        A pinned target wins and needs no confirmation (it was chosen explicitly, not by
        a ray). Otherwise the retained rays are cast against the live panels, bound by
        :func:`~yazses.xr.binding.bind_demonstrative`, and the confirm policy compares the
        panel under the ray nearest the onset with the one nearest ``utterance_end_s``
        (a side with no sample within ``edge_tolerance_s`` counts as unknown, not changed).
        """
        onset = _finite_time("word_onset_s", word_onset_s)
        end = _finite_time("utterance_end_s", utterance_end_s)
        if onset < 0 or end < onset:
            raise ValueError("need 0 <= word_onset_s <= utterance_end_s")
        if not isinstance(destructive, bool):
            raise ValueError("destructive must be a bool")
        cfg = self._cfg
        now = self._now
        if now is None:
            none = BindingResult(BindingOutcome.NONE, None, 0.0, "no data received yet")
            return SessionResolution(None, ResolutionSource.NONE, decide(
                outcome="none", margin=0.0, confidence=0.0, destructive=destructive,
                panel_at_onset=None, panel_at_end=None), None, none)

        live = tuple(p for p in self._registry.panels() if self._registry.is_fresh(p.panel_id, now))
        cast = [
            (s, nearest_hit(s.ray, live, cfg.max_ray_distance_m))
            for s in self._retention.snapshot(now)
            if cfg.primary_source is None or s.source is cfg.primary_source
        ]

        lo, hi = onset - cfg.lead_s, onset + cfg.lag_s
        window = [(s, h) for s, h in cast if lo <= s.timestamp_s <= hi]
        # The binder gets every cast ray, not only the window: the rays just outside the
        # window tell it how long each in-window ray was held (its sample interval).
        observations = [self._observe(s, h, live, lo <= s.timestamp_s <= hi) for s, h in cast]
        binding = bind_demonstrative(observations, onset, lead_s=cfg.lead_s, lag_s=cfg.lag_s,
                                     history_s=cfg.history_s)

        at_onset = self._panel_near(cast, onset)
        at_end = self._panel_near(cast, end)

        pinned = self._target.current(now)
        if pinned is not None:
            panel_id: str | None = pinned
            source = ResolutionSource.PINNED
            decision = ConfirmDecision(False, ConfirmReason.NONE)
        else:
            panel_id = binding.panel_id
            source = ResolutionSource.RAY if panel_id is not None else ResolutionSource.NONE
            decision = decide(
                outcome=binding.outcome.value,
                margin=binding.margin,
                confidence=binding.confidence,
                destructive=destructive,
                panel_at_onset=at_onset,
                panel_at_end=at_end,
                evidence=self._evidence(binding, observations, onset, end),
                policy=ConfirmPolicy(
                    error_budget_deg=cfg.error_budget_deg,
                    settle_s=cfg.settle_s,
                    min_departure_s=cfg.min_departure_s,
                ),
            )
        snapshot = self._best_snapshot(window, panel_id, onset)
        return SessionResolution(panel_id, source, decision, snapshot, binding, at_onset, at_end)

    def _observe(
        self, sample: XrSample, hit: PanelHit | None, live: tuple[Panel, ...], in_window: bool
    ) -> PanelObservation:
        """One cast ray as an observation; inside the binding window it also carries the
        distance to the nearest *other* panel (outside it nothing reads the rival, so the
        per-panel geometry is skipped)."""
        rival = None if hit is None or not in_window else nearest_rival(
            sample.ray, hit.panel_id, live, self._cfg.max_ray_distance_m)
        if rival is None:
            return PanelObservation(sample.timestamp_s, hit, sample.confidence)
        return PanelObservation(sample.timestamp_s, hit, sample.confidence, rival[0], rival[1])

    @staticmethod
    def _evidence(
        binding: BindingResult, observations: list[PanelObservation], onset: float, end: float
    ) -> Evidence:
        """The binder's checkable facts, plus how long the gaze has since rested elsewhere."""
        if binding.panel_id is None:
            return Evidence()
        panel, seconds = sustained_departure(observations, binding.panel_id, onset, end)
        return Evidence(
            panel_id=binding.panel_id,
            top_share=binding.top_share,
            runner_up=binding.candidates[1] if len(binding.candidates) > 1 else None,
            rival_id=binding.rival_id,
            rival_deg=binding.rival_deg,
            prior_panel=binding.prior_panel,
            settled_s=binding.settled_s,
            departure_s=seconds,
            departure_panel=panel,
        )

    def _panel_near(self, cast: list[tuple[XrSample, PanelHit | None]], t: float) -> str | None:
        """Panel under the sample closest to ``t`` (within the edge tolerance), else None."""
        best: tuple[XrSample, PanelHit | None] | None = None
        for pair in cast:
            if best is None or abs(pair[0].timestamp_s - t) < abs(best[0].timestamp_s - t):
                best = pair
        if best is None or abs(best[0].timestamp_s - t) > self._cfg.edge_tolerance_s:
            return None
        return best[1].panel_id if best[1] is not None else None

    def _best_snapshot(
        self,
        window: list[tuple[XrSample, PanelHit | None]],
        panel_id: str | None,
        onset: float,
    ) -> TargetSnapshot | None:
        """The in-window ray on ``panel_id`` nearest the onset (higher confidence on a tie)."""
        if panel_id is None:
            return None
        best: tuple[XrSample, PanelHit] | None = None
        for s, h in window:
            if h is None or h.panel_id != panel_id:
                continue
            if best is None or (abs(s.timestamp_s - onset), -s.confidence) < (
                abs(best[0].timestamp_s - onset), -best[0].confidence
            ):
                best = (s, h)
        if best is None:
            return None
        panel = self._registry.get(panel_id)
        space = panel_space(panel_id, self._geometry_version.get(panel_id, 0))
        return to_target_snapshot(best[0], best[1], panel, space=space)
