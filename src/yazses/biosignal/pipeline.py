"""Block-in, accepted-events-out: the composition of every biosignal stage.

The detectors (``emg_onset``, ``artifacts``), the filters, the signal-quality monitor and
the false-positive governor are each small and independently testable. This module is the
one place that fixes their *order*, because the order is the safety argument:

1. **filter** each channel with the chain for its :class:`SignalKind` — an EMG chain is not
   an EEG chain, and a 50/60 Hz mains line sits inside both bands.
2. **quality gate** — a lifted electrode or a mains-saturated channel produces confident
   nonsense, so while the monitor says BAD no *new* event is accepted. This is a gate on
   the output of the detectors, not on their input: their internal state keeps tracking so
   that they are not mid-burst and confused when the signal comes back. An event is judged
   by the time it happened as well as the block that reported it, because a detector can
   report late, after the gate has reopened.
3. **detect** — every detector sees every block, in a fixed order.
4. **govern** — the ledger records what was accepted; the governor compares the recent
   cancelled-activation rate against the configured budget and may *desensitize* (demand
   a higher confidence) or *suspend* the whole pipeline. A switch that fires falsely
   more often than the user tolerates must turn itself down rather than keep firing.

One invariant overrides the gates: **a held squeeze must always be released.** If the gate
closes (BAD quality, suspension) while a squeeze is active, the pipeline emits a synthetic
``SQUEEZE_OFF`` and lets a real ``SQUEEZE_OFF`` through even while gated. A dropped OFF
event is a stuck "dictate" key, which is worse than any false activation.

A second override sits next to it: **a failing detector must not strand a squeeze.** If a
detector raises while a squeeze is held it is removed, and the pipeline releases the
squeeze at once (nothing would ever send that detector's ``SQUEEZE_OFF``). The same goes
for the governor suspending the switches mid-squeeze.

A third override is about *provenance*: a calibration profile made for another board, another
set of electrodes, another sampling rate, or long ago, describes a different signal. The
pipeline checks the profile against the live channels and rate on the first block (and again
if they change, and hourly for age); a profile that is not ``ok`` is **not used** -- the
switches built from it are held off (their squeeze, if any, is released) and the status says
why in plain language. Blink and clench have built-in defaults and are built without the
profile when the mismatch is already known at build time; the squeeze switch has no defaults and
simply stays off. Fail closed, never a guess.

Everything is injected through :class:`PipelineParts`, so a missing optional piece (no
quality monitor, no governor) degrades to "that stage is skipped" and the pipeline can be
driven in tests with plain fakes. Pure: numpy + stdlib and no I/O. Exactly one thread (the
runner's) feeds blocks; the daemon may call :meth:`BiosignalPipeline.note_cancelled` and
:meth:`BiosignalPipeline.governor_release` from another thread, so those and ``process`` are
serialized by one re-entrant lock. The only imports of sibling modules are lazy and live in
:func:`build_parts`.

Intent mapping (:func:`events_to_intents`) yields *labels*, never text, for the same
reason ``activation/intent.py`` gives: a decoder is not a keyboard. Thought decoding stays
rejected (ADR-v2-129); a blink or a jaw clench can only ever say one of a few words the
user wrote into the map themselves.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np

from yazses.activation.intent import ActivationIntent
from yazses.biosignal.types import (
    BioEvent,
    ChannelInfo,
    EventKind,
    SampleBlock,
    SignalKind,
    StreamDetector,
)

if TYPE_CHECKING:
    from yazses.biosignal.fprate import GovernorAction

log = logging.getLogger(__name__)

# Default event → intent-label map. Only the one mapping that has an unambiguous,
# low-consequence meaning ships by default: a *double* blink is deliberate (a spontaneous
# blink is single), and "undo" is reversible. A jaw clench has no default label — the user
# picks what it means, or it stays inert.
DEFAULT_INTENT_MAP: dict[str, str] = {"double_blink": "undo"}

# Seconds of accepted-event history used for the reported rate. A design choice: long
# enough to be stable at a few events a minute, short enough to show a runaway quickly.
RATE_WINDOW_SECONDS = 600.0

_SECONDS_PER_HOUR = 3600.0

# A profile's age changes slowly; re-judging it hourly (stream time) is plenty and keeps the
# per-block path free of date arithmetic. A design choice.
_CALIBRATION_RECHECK_S = 3600.0
# Used when ``[biosignal] calibration_max_age_days`` is absent or unusable. A design choice:
# electrode placement and skin condition drift over weeks, not hours.
DEFAULT_CALIBRATION_MAX_AGE_DAYS = 30.0
_SQUEEZE_EVENTS = (EventKind.SQUEEZE_ON, EventKind.SQUEEZE_OFF)


# ---------------------------------------------------------------------------
# Status


# How far back an event can still be judged against a closed gate, in stream seconds, and how
# many closed stretches are kept. Design choices: longer than any detector's report delay
# (a double blink's is about 1.3 s, a clench's about 1.6 s). When the list is full the oldest
# stretch goes first, and that one is the least likely to matter.
_CLOSED_SPAN_HISTORY_S = 10.0
_CLOSED_SPANS_MAX = 256
_QUALITY_REASON = "signal quality bad"
# integrity.IntegrityReport.reason() starts with this; it decides the refusal's tally.
_STREAM_REASON = "stream integrity"


@dataclass(frozen=True)
class PipelineStatus:
    """Snapshot of the pipeline for IPC / CLI. Immutable, safe to hand to another thread."""

    quality: str = "unknown"          # good | degraded | bad | unknown
    rate_per_hour: float = 0.0        # accepted events, extrapolated from the recent window
    suspended: bool = False
    reason: str = ""                  # why suspended, or why the gate is closed
    desensitized: float = 1.0         # confidence-floor multiplier in force (1.0 = none)
    squeeze_active: bool = False
    blocks: int = 0
    accepted: int = 0
    dropped: int = 0                  # events a gate refused
    detectors: int = 0                # live detectors (failed ones are removed)
    # Why the gates refused events: quality | stream | governor | confidence (pipeline level only;
    # detector-internal suppressions are reported by ``BiosignalPipeline.detector_suppressed``).
    dropped_by_reason: Mapping[str, int] = field(default_factory=dict)
    # ok | stale | mismatch | missing | unchecked (no block seen yet), with a plain-language
    # reason. Never a threshold or a profile value.
    calibration_state: str = "missing"
    calibration_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "quality": self.quality,
            "rate_per_hour": round(self.rate_per_hour, 2),
            "suspended": self.suspended,
            "reason": self.reason,
            "desensitized": self.desensitized,
            "squeeze_active": self.squeeze_active,
            "blocks": self.blocks,
            "accepted": self.accepted,
            "dropped": self.dropped,
            "detectors": self.detectors,
            "dropped_by_reason": dict(self.dropped_by_reason),
            "calibration": {"state": self.calibration_state,
                            "reason": self.calibration_reason},
        }


@dataclass(frozen=True)
class DroppedEvent:
    """An event a gate refused: its kind, stream time and why (no signal data)."""

    kind: EventKind
    reason: str                       # quality | governor | confidence
    t: float = 0.0


@dataclass(frozen=True)
class PipelineResult:
    """What one block produced."""

    events: tuple[BioEvent, ...]
    status: PipelineStatus
    dropped: tuple[DroppedEvent, ...] = ()


# ---------------------------------------------------------------------------
# Calibration provenance


@dataclass(frozen=True)
class CalibrationVerdict:
    """Whether a loaded calibration profile may be used on the live signal."""

    state: str                        # ok | stale | mismatch | missing | unchecked
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    def as_dict(self) -> dict[str, str]:
        return {"state": self.state, "reason": self.reason}


_RECALIBRATE = "run `yazses biosignal calibrate`"
_MISSING_REASON = (f"no calibration found; {_RECALIBRATE}. The squeeze switch stays off "
                   "until then; blink and clench use their built-in defaults.")


def board_id_from_spec(spec: str) -> str:
    """The board identity a calibration stores for a ``[biosignal] source`` spec.

    Must stay in step with how ``yazses biosignal calibrate`` names the board it records:
    ``brainflow:<id>`` (the port is not part of the identity), otherwise the scheme alone.
    ``""`` for an empty spec, which means "board unknown": the board is then not compared.
    """
    text = str(spec or "").strip()
    scheme = text.partition(":")[0].strip().lower()
    if not scheme:
        return ""
    return ":".join(text.split(":")[:2]) if scheme == "brainflow" else scheme


class CalibrationCheck:
    """Judges a loaded profile against the live board, channels, rate and age.

    Wraps ``calibration.profile_matches`` / ``profile_is_stale`` (imported lazily) so the
    pipeline never reuses a profile made for a different montage or long ago. The profile is
    untrusted input: one that cannot be examined is treated as a mismatch, never as fine.
    Each non-ok state is logged once, not per block.
    """

    def __init__(
        self,
        profile: Any,
        *,
        board_id: str = "",
        max_age_days: float = DEFAULT_CALIBRATION_MAX_AGE_DAYS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.profile = profile
        self.board_id = board_id
        age = _float(max_age_days, DEFAULT_CALIBRATION_MAX_AGE_DAYS)
        self.max_age_days = age if age > 0 else DEFAULT_CALIBRATION_MAX_AGE_DAYS
        self._now = now or (lambda: datetime.now(UTC))
        self.verdict: CalibrationVerdict | None = None   # last judgement, None until evaluated
        self._logged: set[str] = set()

    def evaluate(self, channels: Sequence[Any], fs: float) -> CalibrationVerdict:
        verdict = self._judge(channels, fs)
        self.verdict = verdict
        if verdict.state not in self._logged:
            self._logged.add(verdict.state)
            if verdict.state in ("stale", "mismatch"):
                log.warning("Biosignal calibration not used (%s): %s", verdict.state,
                            verdict.reason)
            elif verdict.state == "missing":
                log.info("Biosignal calibration: %s", verdict.reason)
        return verdict

    def _judge(self, channels: Sequence[Any], fs: float) -> CalibrationVerdict:
        profile = self.profile
        if profile is None:
            return CalibrationVerdict("missing", _MISSING_REASON)
        try:
            from yazses.biosignal import calibration

            names = tuple(str(getattr(c, "name", c)) for c in channels)
            board = self.board_id or str(profile.board_id)
            if not calibration.profile_matches(profile, board, names, float(fs)):
                return CalibrationVerdict(
                    "mismatch",
                    f"the saved calibration was made for {self._what_differs(board, names)}; "
                    f"it is not used. {_RECALIBRATE.capitalize()}.")
            if calibration.profile_is_stale(profile, self._now(), self.max_age_days):
                return CalibrationVerdict(
                    "stale",
                    f"the saved calibration is more than {self.max_age_days:g} days old "
                    f"(or its date cannot be trusted); it is not used. "
                    f"{_RECALIBRATE.capitalize()}.")
        except Exception:
            log.debug("calibration profile could not be examined", exc_info=True)
            return CalibrationVerdict(
                "mismatch", "the saved calibration could not be verified against this board; "
                f"it is not used. {_RECALIBRATE.capitalize()}.")
        return CalibrationVerdict("ok", "the saved calibration matches this board and is recent")

    def _what_differs(self, board: str, names: tuple[str, ...]) -> str:
        profile = self.profile
        if str(profile.board_id) != board:
            return "a different board"
        if sorted(profile.channels) != sorted(names):
            return "different electrode channels"
        return "a different sampling rate"


# ---------------------------------------------------------------------------
# Parts


@dataclass
class PipelineOptions:
    """Tunables that are not collaborators."""

    # Events below this confidence are dropped. 0.0 = accept whatever the detector
    # reports; desensitization multiplies this floor (or lifts it from 0).
    min_confidence: float = 0.0
    # Floor used as the base when desensitizing and ``min_confidence`` is 0, so a
    # factor still has something to multiply.
    desensitize_base: float = 0.5
    rate_window_s: float = RATE_WINDOW_SECONDS
    # Events that are never gated by confidence or desensitization: releasing a held
    # squeeze must not depend on how sure the detector is.
    always_pass: tuple[EventKind, ...] = (EventKind.SQUEEZE_OFF,)


@dataclass
class PipelineParts:
    """Every collaborator the pipeline uses; any of them may be absent.

    ``chain_factories`` maps a signal kind to ``factory(fs) -> chain`` where a chain has
    ``process(ndarray) -> ndarray`` and ``reset()``. One chain is made per channel, so
    filter state is never shared between electrodes. ``detectors`` are
    :class:`StreamDetector`; ``quality`` has ``update(block) -> QualityReport``;
    ``ledger`` is a ``fprate.ActivationLedger`` (``record``/``start``/``pause``/
    ``mark_cancelled_latest``); ``governor`` is a ``fprate.BudgetGovernor`` whose
    ``update()`` returns the action to apply.
    """

    detectors: Sequence[StreamDetector] = ()
    chain_factories: Mapping[SignalKind, Callable[[float], Any]] = field(default_factory=dict)
    quality: Any = None
    ledger: Any = None
    governor: Any = None
    options: PipelineOptions = field(default_factory=PipelineOptions)
    clock: Callable[[], float] | None = None   # event-time fallback; default: block time
    # Provenance of the calibration the detectors below were built from. ``calibrated`` are
    # the detectors that actually used profile values: they are held off whenever the check
    # says the profile cannot be used on the live signal. None = no calibration in play.
    calibration: CalibrationCheck | None = None
    calibrated: Sequence[StreamDetector] = ()


# ---------------------------------------------------------------------------
# Helpers


def _name(value: Any) -> str:
    """Upper-case enum-ish name: ``Status.BAD`` -> ``BAD``; strings pass through."""
    return str(getattr(value, "name", value)).upper()


def _float(value: Any, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


_DROP_PREFIXES = ("suppressed_", "rejected_", "dropped_")
_NESTED_COUNTERS = ("stats", "suppressed", "dropped", "rejected")


def _health_of(det: Any) -> dict[str, Any]:
    """A detector's ``health()`` (else its ``stats`` dict) as a plain dict; ``{}`` if none."""
    try:
        fn = getattr(det, "health", None)
        data = fn() if callable(fn) else getattr(det, "stats", None)
    except Exception:
        log.debug("detector health failed for %s", type(det).__name__, exc_info=True)
        return {}
    return dict(data) if isinstance(data, Mapping) else {}


def _suppression_reason(key: str) -> str | None:
    """Which tally a detector counter belongs to, from its name; None if it is not a drop."""
    k = key.lower()
    if "speech" in k:
        return "speech"
    if "refractory" in k:
        return "refractory"
    if k.startswith(_DROP_PREFIXES) or "dropped" in k or k == "short_bursts":
        return "artifact"
    return None


def _suppressed_counts(health: Mapping[str, Any]) -> dict[str, int]:
    """Sum the drop-like integer counters of a health dict by reason (one nesting level)."""
    out: dict[str, int] = {}

    def visit(items: Mapping[str, Any], nested: bool) -> None:
        for key, value in items.items():
            if isinstance(value, Mapping) and not nested and str(key).lower() in _NESTED_COUNTERS:
                visit(value, True)
            elif isinstance(value, int) and not isinstance(value, bool) and value > 0:
                reason = _suppression_reason(str(key))
                if reason is not None:
                    out[reason] = out.get(reason, 0) + value

    visit(health, False)
    return out


# ---------------------------------------------------------------------------
# Pipeline


class BiosignalPipeline:
    """Filter → quality gate → detectors → governor, one block at a time.

    Exactly one thread (the runner's) feeds blocks. ``process``, ``reset``,
    ``note_cancelled`` and ``governor_release`` share one re-entrant lock so the daemon's
    "that was a mistake" report cannot interleave with a block being processed. ``status``
    is an immutable snapshot.
    """

    def __init__(self, parts: PipelineParts | None = None) -> None:
        self._parts = parts or PipelineParts()
        self._detectors: list[StreamDetector] = list(self._parts.detectors)
        self._chains: dict[tuple[str, SignalKind], Any] = {}
        self._chain_fs: float = 0.0
        self._disabled: set[str] = set()      # components that failed once; logged once
        self._squeeze_active = False
        self._squeeze_since = 0.0
        self._recent: deque[float] = deque()  # times of accepted events
        self._factor = 1.0                    # desensitize factor in force
        self._suspended = False
        self._reason = ""
        self._gate_reason = ""                # why the gate is closed for the latest block
        # Stream time the gate was closed for, as (start, end, why), oldest first. A detector
        # can emit long after what it saw (a double blink about 1.3 s after the second
        # blink), so an event is judged by when it happened as well as when it arrived.
        self._closed_spans: deque[tuple[float, float, str]] = deque(maxlen=_CLOSED_SPANS_MAX)
        self._quality = "unknown"
        self._blocks = 0
        self._accepted = 0
        self._dropped = 0
        self._now = 0.0
        self._lock = threading.RLock()
        # Detectors (by id) that accepted a threshold rescale: the governor's factor is
        # applied *inside* them, so the confidence floor must not apply it a second time.
        self._scaled: set[int] = set()
        self._detector_failed = False
        self._dropped_by_reason: dict[str, int] = {}
        # Detector-internal suppressions banked at each reset (detectors zero their own
        # counters when reset), so the totals survive a stream gap.
        self._banked: dict[str, int] = {}
        self._accounting_paused = False
        self._squeeze_owner: int | None = None    # id() of the detector behind a held squeeze
        check = self._parts.calibration
        self._cal_verdict: CalibrationVerdict | None = check.verdict if check else None
        self._cal_sig: tuple[tuple[str, ...], float] | None = None
        self._cal_checked = -math.inf
        self._cal_blocked = False

    # ---- public ----------------------------------------------------------

    @property
    def status(self) -> PipelineStatus:
        return PipelineStatus(
            quality=self._quality.lower(),
            rate_per_hour=self._rate_per_hour(),
            suspended=self._suspended,
            reason=self._reason or self._gate_reason,
            desensitized=self._factor,
            squeeze_active=self._squeeze_active,
            blocks=self._blocks,
            accepted=self._accepted,
            dropped=self._dropped,
            detectors=len(self._detectors),
            dropped_by_reason=dict(self._dropped_by_reason),
            calibration_state=self._calibration_state()[0],
            calibration_reason=self._calibration_state()[1],
        )

    def _calibration_state(self) -> tuple[str, str]:
        if self._parts.calibration is None:
            return "missing", "no calibration profile in use"
        verdict = self._cal_verdict
        if verdict is None:
            return "unchecked", "the calibration is checked against the first block"
        return verdict.state, verdict.reason

    @property
    def squeeze_active(self) -> bool:
        return self._squeeze_active

    @property
    def ledger(self) -> Any:
        """The activation ledger (``fprate.ActivationLedger``), or None when there is none."""
        return self._parts.ledger

    @property
    def governor(self) -> Any:
        """The false-positive governor (``fprate.BudgetGovernor``), or None."""
        return self._parts.governor

    @property
    def governor_state(self) -> str:
        """``ok`` / ``desensitize`` / ``suspend``, or ``""`` when there is no governor."""
        gov = self._parts.governor
        if gov is None:
            return ""
        state = getattr(gov, "state", None)
        return str(getattr(state, "value", state) or "")

    def reset(self, *, keep_governor_state: bool = True) -> None:
        """Forget stream state (after a gap, a reconnect, or a recalibration).

        Always cleared: filter chains, detector and quality-monitor state, the held-squeeze
        bookkeeping and the rate window. This forgets a held squeeze *without* announcing
        it: the caller owns releasing the squeeze it forwarded (the runner does, before
        calling this).

        ``keep_governor_state`` decides what happens to the false-positive governor's
        verdict. True (the default, and what a stream gap uses): desensitization and
        suspension *stay in force* -- a dropout is not evidence that the false-positive
        problem went away, and forgetting it would let a switch that just earned a
        suspension fire again after any hiccup. False: the governor is released as if the
        user had said "carry on" (factor back to 1, no suspension). Counters and the
        activation ledger are untouched either way; see :meth:`full_reset`.
        """
        with self._lock:
            self._reset_locked(keep_governor_state=keep_governor_state)

    def full_reset(self) -> None:
        """Clear everything :meth:`reset` can, and the session counters too.

        Stream state, the governor's verdict (released), the accepted/dropped counters and
        reason tallies, and the calibration verdict (re-judged on the next block). Not
        cleared: the activation ledger (it is the persistent false-positive record), the
        accounting-pause flag (owned by the daemon), and components that failed and were
        removed or disabled -- a full reset does not bring a crashed detector back. Like
        :meth:`reset` it does not announce a held squeeze.
        """
        with self._lock:
            self._reset_locked(keep_governor_state=False)
            self._blocks = self._accepted = self._dropped = 0
            self._dropped_by_reason.clear()
            self._banked.clear()
            self._cal_sig = None
            self._cal_checked = -math.inf

    def _reset_locked(self, *, keep_governor_state: bool = True) -> None:
        for chain in self._chains.values():
            self._safe(chain, "reset")
        for det in self._detectors:
            # Bank what the reset takes away (detectors zero their own counters; one that
            # keeps them loses nothing, so nothing is banked and nothing double counts).
            before = _suppressed_counts(_health_of(det))
            self._safe(det, "reset")
            after = _suppressed_counts(_health_of(det))
            for reason, n in before.items():
                lost = n - after.get(reason, 0)
                if lost > 0:
                    self._banked[reason] = self._banked.get(reason, 0) + lost
        self._safe(self._parts.quality, "reset")
        self._gate_reason = ""
        self._closed_spans.clear()
        self._squeeze_active = False
        self._squeeze_owner = None
        self._recent.clear()
        if keep_governor_state:
            # A detector may drop its rescale when reset: re-apply the factor in force.
            if self._factor > 1.0:
                self._propagate_scale(self._factor)
        else:
            self._release_governor_locked()

    # ---- ledger exposure while the daemon pauses the switches ------------

    def pause_accounting(self) -> None:
        """Stop the ledger accruing exposure (a global hands-free pause). Idempotent.

        While paused the ledger is held paused on every block, so a pause does not dilute
        the measured false-activation rate with hours in which nothing could fire.
        """
        with self._lock:
            self._accounting_paused = True
            self._account_exposure(True)

    def resume_accounting(self) -> None:
        """Let the ledger accrue exposure again from the next block. Idempotent."""
        with self._lock:
            self._accounting_paused = False

    @property
    def accounting_paused(self) -> bool:
        return self._accounting_paused

    # ---- observability ----------------------------------------------------

    def detector_health(self) -> dict[str, dict[str, Any]]:
        """``{detector name: health()}`` for the live detectors; no signal data.

        Calls a detector's ``health()`` when it has one, otherwise reports its ``stats``
        dict; a detector with neither (or whose call raises) maps to ``{}``. Duplicate type
        names get a ``#2`` suffix.
        """
        with self._lock:
            out: dict[str, dict[str, Any]] = {}
            for det in self._detectors:
                name = type(det).__name__
                key, n = name, 1
                while key in out:
                    n += 1
                    key = f"{name}#{n}"
                out[key] = _health_of(det)
            return out

    def detector_suppressed(self) -> dict[str, int]:
        """Events the detectors themselves held back, by reason, since the last full reset.

        The reason is read from the detector's own counter names (a design choice, so a
        new counter lands somewhere sensible): ``speech``, ``refractory``, or ``artifact``
        for the rest (chewing rhythm, rejected shape, lone blink, short burst). Totals
        survive stream-gap resets.
        """
        with self._lock:
            out = dict(self._banked)
            for det in self._detectors:
                for reason, n in _suppressed_counts(_health_of(det)).items():
                    out[reason] = out.get(reason, 0) + n
            return out

    def process(self, block: SampleBlock) -> PipelineResult:
        """Run one block through every stage; return the accepted events and a status."""
        with self._lock:
            return self._process_locked(block)

    def _process_locked(self, block: SampleBlock) -> PipelineResult:
        self._blocks += 1
        self._detector_failed = False
        self._now = block.t0 + block.duration
        dropped: list[DroppedEvent] = []

        filtered = self._filter(block)
        gate_closed, gate_reason = self._quality_gate(block)
        self._gate_reason = gate_reason if gate_closed else ""
        self._note_gate(block, gate_closed, gate_reason)
        # Which detectors the calibration check holds off (empty when it is fine or absent).
        cal_blocked = self._calibration_gate(block)
        self._account_exposure(gate_closed or self._suspended)

        # Each event is tagged with whether its detector rescales itself (see ``_scaled``)
        # and which detector produced it (to know whose squeeze is held).
        raw_events: list[tuple[BioEvent, bool, int]] = []
        for det in list(self._detectors):
            if id(det) in cal_blocked:
                continue
            scaled = id(det) in self._scaled
            raw_events.extend((e, scaled, id(det)) for e in self._run_detector(det, filtered))
        raw_events.sort(key=lambda item: item[0].t)

        # ``held`` follows the events accepted so far in *this* block, so a squeeze that
        # begins and ends inside one block is seen as such: judging each OFF against the
        # state from before the block would drop it as an orphan and strand the ON.
        accepted: list[BioEvent] = []
        held = self._squeeze_active
        owner = self._squeeze_owner
        for event, scaled, source_id in raw_events:
            verdict = self._admit(event, gate_closed, gate_reason, held, scaled, dropped)
            if verdict is None:
                continue
            accepted.append(verdict)
            if verdict.kind is EventKind.SQUEEZE_ON:
                held = True
                owner = source_id
            elif verdict.kind is EventKind.SQUEEZE_OFF:
                held = False
                owner = None
        self._squeeze_owner = owner

        # A squeeze held by a detector whose calibration can no longer be trusted is not
        # left to a detector that is no longer being run: release it now. (``owner`` None
        # with a squeeze held cannot be attributed, so it is released too: fail closed.)
        cal_release = held and bool(cal_blocked) and (owner is None or owner in cal_blocked)

        # The gate closing under a held squeeze must release it, and so must a detector
        # that died holding one (its own OFF will never come).
        if held and (gate_closed or self._suspended or self._detector_failed or cal_release):
            why = (gate_reason or self._reason
                   or ("detector failed" if self._detector_failed else "")
                   or (f"calibration {self._calibration_state()[0]}" if cal_release else "")
                   or "gate")
            accepted.append(self._synthetic_off(why))

        for event in accepted:
            self._commit(event)
        self._govern()
        # A governor that just suspended the switches must not leave a squeeze held until
        # the next block: release it in this result.
        if self._suspended and self._squeeze_active:
            off = self._synthetic_off(self._reason or "suspended")
            self._commit(off)
            accepted.append(off)
        return PipelineResult(events=tuple(accepted), status=self.status,
                              dropped=tuple(dropped))

    def _calibration_gate(self, block: SampleBlock) -> frozenset[int]:
        """Judge the profile against the live channels/rate; return the detectors to hold off.

        Re-judged on the first block, whenever the channel names or the sampling rate
        change (a reconnect to another board), and about hourly for age. Detectors that
        used profile values are reset when they are held off and again when they come
        back, so neither state leaks across the boundary.
        """
        check = self._parts.calibration
        if check is None:
            return frozenset()
        sig = (tuple(sorted(c.name for c in block.channels)), round(float(block.fs), 6))
        if sig != self._cal_sig or self._now - self._cal_checked >= _CALIBRATION_RECHECK_S:
            try:
                verdict = check.evaluate(block.channels, block.fs)
            except Exception:
                log.warning("Biosignal calibration check failed; treating the profile as "
                            "unusable.", exc_info=True)
                verdict = CalibrationVerdict(
                    "mismatch", "the saved calibration could not be verified; it is not used")
            self._cal_sig, self._cal_checked, self._cal_verdict = sig, self._now, verdict
        current = self._cal_verdict
        blocked = current is not None and not current.ok
        held_off = (frozenset(id(d) for d in self._parts.calibrated if d in self._detectors)
                    if blocked else frozenset())
        if blocked != self._cal_blocked:
            self._cal_blocked = blocked
            for det in self._parts.calibrated:
                if det in self._detectors:
                    self._safe(det, "reset")
        return held_off

    # ---- stages ----------------------------------------------------------

    def _filter(self, block: SampleBlock) -> SampleBlock:
        factories = self._parts.chain_factories
        if not factories:
            return block
        if block.fs != self._chain_fs:
            # Sampling rate changed (reconnect to another board): old coefficients are wrong.
            self._chains.clear()
            self._chain_fs = block.fs
        data = np.asarray(block.data, dtype=float)
        if data.ndim == 1:
            data = data[np.newaxis, :]
        out = np.array(data, copy=True)
        for row, info in enumerate(block.channels[: data.shape[0]]):
            chain = self._chain_for(info, block.fs)
            if chain is None:
                continue
            try:
                result = np.asarray(chain.process(data[row]), dtype=float)
            except Exception:
                self._disable(f"filter:{info.name}", "filter chain failed; channel left unfiltered")
                self._chains[(info.name, info.kind)] = None
                continue
            if result.shape == out[row].shape:
                out[row] = result
            else:
                self._disable(f"filter-shape:{info.name}",
                              "filter chain changed the block length; channel left unfiltered")
                self._chains[(info.name, info.kind)] = None
        return SampleBlock(data=out, fs=block.fs, channels=block.channels, t0=block.t0)

    def _chain_for(self, info: ChannelInfo, fs: float) -> Any:
        key = (info.name, info.kind)
        if key in self._chains:
            return self._chains[key]
        factory = self._parts.chain_factories.get(info.kind)
        chain = None
        if factory is not None:
            try:
                chain = factory(fs)
            except Exception:
                self._disable(f"chain:{info.kind.value}", "could not build a filter chain")
        self._chains[key] = chain
        return chain

    def _quality_gate(self, raw_block: SampleBlock) -> tuple[bool, str]:
        monitor = self._parts.quality
        if monitor is None or "quality" in self._disabled:
            return False, ""
        try:
            report = monitor.update(raw_block)
        except Exception:
            self._disable("quality", "signal-quality monitor failed; quality gate off")
            return False, ""
        overall = _name(getattr(report, "overall", "unknown"))
        self._quality = overall
        # `bad_during_update`: a block can span many evaluations; a bad stretch inside it that
        # has scrolled out of the window by the end must still cost its events (a replay source
        # feeds 12 s at a time, and "GOOD at the end" is not "GOOD throughout").
        closed = (overall == "BAD" or bool(getattr(report, "suppress_events", False))
                  or bool(getattr(report, "bad_during_update", False)))
        # A closed stream-integrity gate (integrity.IntegrityGate) names its own reason, so
        # status says "stream gap" rather than blaming the electrodes.
        why = str(getattr(report, "integrity_reason", "") or "") or _QUALITY_REASON
        return closed, (why if closed else "")

    def _note_gate(self, block: SampleBlock, closed: bool, why: str) -> None:
        """Remember the stream time this block's gate was closed for, and forget what is too
        old for any detector to still be reporting (or ahead of a clock that stepped back)."""
        spans = self._closed_spans
        start, end = float(block.t0), float(block.t0 + block.duration)
        while spans and (spans[0][1] < end - _CLOSED_SPAN_HISTORY_S or spans[0][0] > end):
            spans.popleft()
        while spans and spans[-1][0] > end:
            spans.pop()
        if closed:
            spans.append((start, end, why))

    def _closed_when_it_happened(self, event: BioEvent) -> str | None:
        """Why the gate was closed over ``event``'s own time span, or None if it was open.

        A double blink spans both blinks (``detail["interval_s"]`` back from its timestamp):
        a pair whose first half fell in a closed stretch is not a pair anyone can trust.
        """
        end = _float(event.t, 0.0)
        interval = (event.detail or {}).get("interval_s", 0.0)
        start = end - max(_float(interval, 0.0), 0.0)
        for span_start, span_end, why in self._closed_spans:
            if span_start <= end and start < span_end:
                return why
        return None

    def _run_detector(self, det: StreamDetector, block: SampleBlock) -> list[BioEvent]:
        key = f"detector:{type(det).__name__}:{id(det)}"
        try:
            return list(det.process(block))
        except Exception:
            log.warning("Biosignal detector %s failed; removing it. "
                        "Other detectors continue.", type(det).__name__, exc_info=True)
            self._disabled.add(key)
            self._detector_failed = True
            self._scaled.discard(id(det))
            if det in self._detectors:
                self._detectors.remove(det)
            return []

    def _admit(
        self,
        event: BioEvent,
        gate_closed: bool,
        gate_reason: str,
        held: bool,
        scaled: bool = False,
        dropped: list[DroppedEvent] | None = None,
    ) -> BioEvent | None:
        """Apply the gates to one event. Returns the event to accept, or None.

        ``held`` is whether a squeeze is forwarded-and-unreleased *at this event*
        (including events accepted earlier in the same block). A refused event is tallied
        by reason and appended to ``dropped``.
        """
        opts = self._parts.options
        # Keep squeeze bookkeeping honest even for events we refuse to forward.
        if event.kind in opts.always_pass:
            if event.kind is EventKind.SQUEEZE_OFF and not held:
                return None          # orphan OFF (we never forwarded the ON): nothing to release
            return event
        if self._suspended:
            self._refuse(event, "governor", dropped)
            return None
        why = gate_reason if gate_closed else self._closed_when_it_happened(event)
        if why is not None:
            self._refuse(event, "stream" if why.startswith(_STREAM_REASON) else "quality", dropped)
            log.debug("Biosignal event %s dropped: %s", event.kind.value, why)
            return None
        floor = self._confidence_floor(scaled)
        if event.kind is EventKind.SQUEEZE_ON and held:
            return event             # level change while held: the runner decides if it matters
        if _float(event.confidence, 0.0) < floor:
            # Desensitization raised the floor only for a detector that did not rescale itself.
            self._refuse(event, "governor" if self._factor > 1.0 and not scaled
                         else "confidence", dropped)
            return None
        return event

    def _refuse(self, event: BioEvent, reason: str, dropped: list[DroppedEvent] | None) -> None:
        self._dropped += 1
        self._dropped_by_reason[reason] = self._dropped_by_reason.get(reason, 0) + 1
        if dropped is not None:
            dropped.append(DroppedEvent(kind=event.kind, reason=reason, t=_float(event.t, 0.0)))

    def _confidence_floor(self, scaled: bool = False) -> float:
        """Minimum confidence for an event to be accepted.

        Desensitization has two mechanisms and each event gets exactly one: a detector that
        took the threshold rescale (``scaled``) has already become less sensitive, so
        multiplying the floor too would punish it twice; any other detector is desensitized
        here by raising the floor.
        """
        opts = self._parts.options
        base = opts.min_confidence
        if self._factor > 1.0 and not scaled:
            base = base if base > 0 else opts.desensitize_base
            base = base * self._factor
        return min(base, 1.0)

    def _commit(self, event: BioEvent) -> None:
        if event.kind is EventKind.SQUEEZE_ON:
            if not self._squeeze_active:
                self._squeeze_since = event.t
            self._squeeze_active = True
        elif event.kind is EventKind.SQUEEZE_OFF:
            self._squeeze_active = False
            self._squeeze_owner = None
        self._accepted += 1
        if event.kind not in (EventKind.SQUEEZE_OFF,):
            self._recent.append(event.t)
        ledger = self._parts.ledger
        if ledger is not None and "ledger" not in self._disabled:
            try:
                ledger.record(event)
            except Exception:
                self._disable("ledger", "activation ledger failed; false-positive accounting off")

    def _govern(self) -> None:
        """Consult the governor; apply DESENSITIZE / SUSPEND / OK to the pipeline state."""
        governor = self._parts.governor
        if governor is None or "governor" in self._disabled:
            return
        try:
            action = self._ask_governor(governor)
        except Exception:
            self._disable("governor", "false-positive governor failed; no automatic suspension")
            return
        if action is None:
            return
        self._apply_action(action)

    def _apply_action(self, action: Any) -> None:
        """Apply a ``GovernorAction`` to the pipeline state (also used by a user release)."""
        kind = _name(getattr(action, "kind", "OK"))
        if kind == "SUSPEND":
            if not self._suspended:
                log.warning("Biosignal switches suspended: %s", getattr(action, "reason", ""))
            self._suspended = True
            self._reason = str(getattr(action, "reason", "") or "false-positive budget exceeded")
        elif kind == "DESENSITIZE":
            self._suspended = False
            self._reason = ""
            factor = max(1.0, _float(getattr(action, "factor", 1.0), 1.0))
            if factor != self._factor:      # the governor repeats itself every block
                self._factor = factor
                self._propagate_scale(factor)
        else:
            self._suspended = False
            self._reason = ""
            if self._factor != 1.0:
                self._factor = 1.0
                self._propagate_scale(1.0)

    def _ask_governor(self, governor: Any) -> Any:
        """``BudgetGovernor.update()`` re-evaluates its own ledger and returns the action."""
        fn = getattr(governor, "update", None)
        return fn() if callable(fn) else None

    def _propagate_scale(self, factor: float) -> None:
        """Tell detectors that can rescale their own thresholds; others rely on the floor.

        A detector is recorded in ``_scaled`` only while its hook works, so the confidence
        floor covers exactly the detectors the rescale did not reach.
        """
        for det in self._detectors:
            self._scaled.discard(id(det))
            for name in ("set_sensitivity_scale", "set_threshold_scale"):
                fn = getattr(det, name, None)
                if callable(fn):
                    try:
                        fn(factor)
                        self._scaled.add(id(det))
                    except Exception:
                        self._disable(f"scale:{type(det).__name__}",
                                      "detector rejected a threshold rescale")
                    break

    # ---- bookkeeping -----------------------------------------------------

    def _account_exposure(self, gated: bool) -> None:
        """Tell the ledger when the trigger is live, so rates are per *active* hour.

        A gated period (bad signal, suspension) is not exposure: counting it would make
        the measured false-activation rate look better than it is.
        """
        ledger = self._parts.ledger
        if ledger is None or "ledger" in self._disabled:
            return
        gated = gated or self._accounting_paused    # a global pause is not exposure either
        try:
            if gated:
                ledger.pause()
            else:
                ledger.start()
        except Exception:
            self._disable("ledger", "activation ledger failed; false-positive accounting off")

    def note_cancelled(self, kind: EventKind | None = None) -> bool:
        """The user cancelled / undid the latest activation: a false positive.

        The daemon calls this (via the runner) when a trigger-initiated action is undone
        inside the ledger's grace window. Returns True if the ledger matched one.
        """
        ledger = self._parts.ledger
        if ledger is None or "ledger" in self._disabled:
            return False
        with self._lock:
            try:
                matched = ledger.mark_cancelled_latest(kind) is not None
            except Exception:
                self._disable("ledger", "activation ledger failed; false-positive accounting off")
                return False
            self._govern()
        return matched

    def governor_release(self) -> GovernorAction:
        """The user said "carry on": drop any desensitization or suspension at once.

        Returns the governor's resulting action (OK when there is no governor). If the
        switches were suspended, the next block resumes them; the sensitivity factor is
        reset on the detectors now.
        """
        with self._lock:
            return self._release_governor_locked()

    def _release_governor_locked(self) -> GovernorAction:
        governor = self._parts.governor
        action: Any = None
        if governor is not None and "governor" not in self._disabled:
            try:
                action = governor.release()
            except Exception:
                self._disable("governor", "false-positive governor failed on release")
        if action is None:
            from yazses.biosignal.fprate import GovernorAction

            action = GovernorAction.ok()
        self._apply_action(action)
        return action  # type: ignore[no-any-return]

    def _synthetic_off(self, reason: str) -> BioEvent:
        return BioEvent(kind=EventKind.SQUEEZE_OFF, t=self._now, confidence=1.0,
                        detail={"synthetic": True, "reason": reason})

    def _rate_per_hour(self) -> float:
        window = self._parts.options.rate_window_s
        cutoff = self._now - window
        while self._recent and self._recent[0] < cutoff:
            self._recent.popleft()
        if not self._recent:
            return 0.0
        span = min(window, max(self._now - self._recent[0], 1.0))
        return len(self._recent) * _SECONDS_PER_HOUR / span

    def _disable(self, key: str, message: str) -> None:
        if key in self._disabled:
            return
        self._disabled.add(key)
        log.warning("Biosignal pipeline: %s (%s); continuing without it.", message, key,
                    exc_info=True)

    @staticmethod
    def _safe(obj: Any, method: str) -> None:
        fn = getattr(obj, method, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                log.debug("biosignal reset of %r failed", obj, exc_info=True)


# ---------------------------------------------------------------------------
# Events -> intents


def _event_key(kind: EventKind) -> str:
    return kind.value


def events_to_intents(
    events: Sequence[BioEvent],
    vocabulary_map: Mapping[Any, str] | None = None,
    *,
    source: str = "biosignal",
) -> list[ActivationIntent]:
    """Map accepted events to :class:`ActivationIntent` labels. Pure.

    ``vocabulary_map`` keys are an :class:`EventKind` or its value string
    (``"double_blink"``); values are the label the user chose. ``None`` means
    :data:`DEFAULT_INTENT_MAP`. An event with no entry, or an empty label, produces no
    intent — inert by default. Squeeze events are modes, not intents, and are never
    mapped. Labels only: this never builds free text.
    """
    mapping = DEFAULT_INTENT_MAP if vocabulary_map is None else vocabulary_map
    lookup: dict[str, str] = {}
    for key, label in mapping.items():
        name = key.value if isinstance(key, EventKind) else str(key).strip().lower()
        text = str(label or "").strip()
        if text:
            lookup[name] = text
    out: list[ActivationIntent] = []
    for event in events:
        if event.kind in _SQUEEZE_EVENTS:
            continue
        chosen = lookup.get(_event_key(event.kind))
        if not chosen:
            continue
        confidence = min(max(_float(event.confidence, 0.0), 0.0), 1.0)
        out.append(ActivationIntent(label=chosen, confidence=confidence,
                                    source=f"{source}:{event.kind.value}"))
    return out


def intent_vocabulary(vocabulary_map: Mapping[Any, str] | None = None) -> tuple[str, ...]:
    """Every label :func:`events_to_intents` can emit — the source's declared vocabulary."""
    mapping = DEFAULT_INTENT_MAP if vocabulary_map is None else vocabulary_map
    seen: dict[str, None] = {}
    for key, label in mapping.items():
        name = key.value if isinstance(key, EventKind) else str(key).strip().lower()
        if name in {k.value for k in _SQUEEZE_EVENTS}:
            continue
        text = str(label or "").strip()
        if text:
            seen.setdefault(text, None)
    return tuple(seen)


# ---------------------------------------------------------------------------
# Default wiring (lazy sibling imports)


@dataclass
class PartsRequest:
    """What :func:`build_parts` should assemble. Every switch defaults to off."""

    fs: float
    mains_hz: float = 50.0
    double_blink: bool = False
    jaw_clench: bool = False
    emg: bool = False
    graded_emg: bool = False
    max_cancelled_per_hour: float = 0.0       # 0 = no governor
    calibration_file: str = ""
    speech_guard: Callable[[], bool] | None = None
    channels: tuple[ChannelInfo, ...] = ()
    # Keep an activation ledger even without a governor (the daemon wants one so the
    # false-positive counters survive a restart and `yazses biosignal report` has data).
    with_ledger: bool = False
    # ``[biosignal] source``: names the board the calibration must have been made for (see
    # :func:`board_id_from_spec`). Empty = board unknown, so only channels and rate are compared.
    source_spec: str = ""
    # ``[biosignal] calibration_max_age_days``: an older profile is not used.
    calibration_max_age_days: float = DEFAULT_CALIBRATION_MAX_AGE_DAYS
    # ``[biosignal] min_event_confidence``: events below it are dropped (0 = accept all).
    min_event_confidence: float = 0.0


def build_parts(request: PartsRequest) -> PipelineParts:
    """Assemble real collaborators from the sibling modules, skipping what is missing.

    Each optional piece is imported inside its own ``try`` so that a module (or an
    optional backend) that is absent costs only that piece, with the reason logged.
    """
    kinds = {c.kind for c in request.channels} if request.channels else set(SignalKind)
    parts = PipelineParts()
    parts.options = PipelineOptions(
        min_confidence=min(max(float(request.min_event_confidence), 0.0), 1.0))

    # filters
    try:
        from yazses.biosignal import filters

        factories: dict[SignalKind, Callable[[float], Any]] = {}
        if SignalKind.EMG in kinds:
            factories[SignalKind.EMG] = lambda f: filters.build_emg_chain(f, request.mains_hz)
        if SignalKind.EEG in kinds:
            factories[SignalKind.EEG] = lambda f: filters.build_eeg_chain(f, request.mains_hz)
        if SignalKind.EOG in kinds:
            factories[SignalKind.EOG] = lambda f: filters.build_eog_chain(f)
        parts.chain_factories = factories
    except Exception:
        log.warning("Biosignal filters unavailable; signals will not be filtered.", exc_info=True)

    # quality
    try:
        from yazses.biosignal.quality import SignalQualityMonitor

        parts.quality = SignalQualityMonitor()
    except Exception:
        log.warning("Biosignal quality monitor unavailable; no quality gate.", exc_info=True)

    # governor + ledger
    if request.max_cancelled_per_hour > 0 or request.with_ledger:
        try:
            from yazses.biosignal.fprate import (
                ActivationLedger,
                BudgetGovernor,
                FalsePositiveBudget,
            )

            ledger = ActivationLedger()
            parts.ledger = ledger
            if request.max_cancelled_per_hour > 0:
                parts.governor = BudgetGovernor(ledger, FalsePositiveBudget(
                    max_cancelled_per_hour=request.max_cancelled_per_hour, enabled=True))
        except Exception:
            log.warning("Biosignal false-positive governor unavailable; "
                        "the rate budget is not enforced.", exc_info=True)

    # A calibration only matters to the switches that need it; it is read at most once.
    # It is judged against the live board, channels, rate and age before any value is
    # taken from it: a profile that fails is not used at all (fail closed).
    needs_profile = request.double_blink or request.jaw_clench or request.emg
    profile = _load_profile(request) if needs_profile else None
    check: CalibrationCheck | None = None
    if needs_profile:
        check = CalibrationCheck(
            profile, board_id=board_id_from_spec(request.source_spec),
            max_age_days=request.calibration_max_age_days)
        if request.channels:           # known now; otherwise judged on the first block
            check.evaluate(request.channels, request.fs)
    parts.calibration = check
    verdict = check.verdict if check is not None else None
    if verdict is not None and not verdict.ok:
        profile = None                 # known unusable: defaults for blink/clench, EMG off

    detectors: list[StreamDetector] = []
    calibrated: list[StreamDetector] = []
    if request.double_blink:
        det, used = _build_blink_detector(request, profile)
        if det is not None:
            detectors.append(det)
            if used:
                calibrated.append(det)
    if request.jaw_clench:
        det, used = _build_jaw_detector(request, profile)
        if det is not None:
            detectors.append(det)
            if used:
                calibrated.append(det)
    if request.emg:
        if verdict is not None and verdict.state in ("stale", "mismatch"):
            log.info("EMG switch off: %s", verdict.reason)
            det = None
        else:
            det = _build_emg_detector(request, profile)
        if det is not None:
            detectors.append(det)
            calibrated.append(det)         # no defaults exist: always profile-derived
    parts.detectors = detectors
    parts.calibrated = calibrated
    return parts


def _load_profile(request: PartsRequest) -> Any:
    """The calibration profile, or None. Optional here: blink and clench have defaults."""
    try:
        from yazses.biosignal import calibration

        path = request.calibration_file.strip() or str(calibration.default_profile_path())
        return calibration.load_profile(path)
    except Exception:
        log.debug("Biosignal calibration profile unavailable.", exc_info=True)
        return None


def _positive(value: Any) -> float | None:
    """A finite value > 0 as a float, else None (profiles are untrusted input)."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) and out > 0 else None


def _wrap_speech_guard(guard: Callable[[], bool] | None) -> Callable[[], bool]:
    """Add the speech guard's hangover when ``biosignal.speechguard`` exists.

    A bare "is the daemon recording right now" flag goes false the instant the user
    stops, but the jaw is still moving for a moment; the guard keeps answering "speaking"
    for a short hangover. Without it (module absent) the raw flag is used as before.
    """
    if guard is None:
        return lambda: False
    try:
        from yazses.biosignal.speechguard import SpeechGuard

        if isinstance(guard, SpeechGuard):
            return guard
        try:
            return SpeechGuard([guard])
        except TypeError:           # an older signature taking the one callable directly
            return SpeechGuard(guard)  # type: ignore[arg-type]
    except Exception:
        log.debug("speech guard hangover unavailable; using the raw flag.", exc_info=True)
        return guard


def _build_blink_detector(
    request: PartsRequest, profile: Any
) -> tuple[StreamDetector | None, bool]:
    """Double-blink detector, thresholds from the user's calibration when they have one.

    Returns ``(detector, used_calibration)``.
    """
    try:
        from yazses.biosignal.artifacts import BlinkDetector

        amplitude = _positive(getattr(profile, "blink_amplitude", None))
        factory = getattr(BlinkDetector, "from_calibration", None)
        if amplitude is not None and callable(factory):
            try:
                return factory(request.fs, amplitude, double_only=True), True
            except Exception:
                log.warning("Blink calibration unusable; using default thresholds.",
                            exc_info=True)
        return BlinkDetector(request.fs, double_only=True), False
    except Exception:
        log.warning("Double-blink detector unavailable.", exc_info=True)
        return None, False


def _build_jaw_detector(
    request: PartsRequest, profile: Any
) -> tuple[StreamDetector | None, bool]:
    """Jaw-clench detector with a speech guard, calibrated when the profile has a clench.

    Returns ``(detector, used_calibration)``.
    """
    try:
        from yazses.biosignal.artifacts import JawClenchDetector

        guard = _wrap_speech_guard(request.speech_guard)
        power = _positive(getattr(profile, "clench_power", None))
        factory = getattr(JawClenchDetector, "from_calibration", None)
        if power is not None and callable(factory):
            try:
                return factory(request.fs, power, speech_guard=guard), True
            except Exception:
                log.warning("Clench calibration unusable; using default thresholds.",
                            exc_info=True)
        return JawClenchDetector(request.fs, speech_guard=guard), False
    except Exception:
        log.warning("Jaw-clench detector unavailable.", exc_info=True)
        return None, False


def _build_emg_detector(request: PartsRequest, profile: Any) -> StreamDetector | None:
    """EMG onset needs a per-person calibration; without one the switch stays off.

    Fixed microvolt thresholds are meaningless across people (pressure.py), so an
    uncalibrated EMG detector would be guessing -- it is refused rather than guessed.
    ``profile`` is the already-judged profile (None when missing or unusable).
    """
    try:
        from yazses.biosignal.emg_onset import (
            EmgOnsetDetector,
            GradedEmgDetector,
            OnsetThresholds,
        )

        if profile is None:
            log.info("EMG switch off: no usable calibration profile "
                     "(run the calibration first).")
            return None
        if profile.mvc_rms is None:
            log.info("EMG switch off: the calibration has no maximum-contraction phase.")
            return None
        baseline, mvc = float(profile.baseline_rms), float(profile.mvc_rms)
        if request.graded_emg:
            return GradedEmgDetector.from_calibration(baseline, mvc)
        return EmgOnsetDetector(OnsetThresholds.from_calibration(baseline, mvc))
    except Exception:
        log.warning("EMG onset detector unavailable.", exc_info=True)
    return None
