"""Block-in, accepted-events-out: the composition of every biosignal stage.

The detectors (``emg_onset``, ``artifacts``), the filters, the signal-quality monitor and
the false-positive governor are each small and independently testable. This module is the
one place that fixes their *order*, because the order is the safety argument:

1. **filter** each channel with the chain for its :class:`SignalKind` — an EMG chain is not
   an EEG chain, and a 50/60 Hz mains line sits inside both bands.
2. **quality gate** — a lifted electrode or a mains-saturated channel produces confident
   nonsense, so while the monitor says BAD no *new* event is accepted. This is a gate on
   the output of the detectors, not on their input: their internal state keeps tracking so
   that they are not mid-burst and confused when the signal comes back.
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
_SQUEEZE_EVENTS = (EventKind.SQUEEZE_ON, EventKind.SQUEEZE_OFF)


# ---------------------------------------------------------------------------
# Status


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
        }


@dataclass(frozen=True)
class PipelineResult:
    """What one block produced."""

    events: tuple[BioEvent, ...]
    status: PipelineStatus


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

    # ---- public ----------------------------------------------------------

    @property
    def status(self) -> PipelineStatus:
        return PipelineStatus(
            quality=self._quality.lower(),
            rate_per_hour=self._rate_per_hour(),
            suspended=self._suspended,
            reason=self._reason,
            desensitized=self._factor,
            squeeze_active=self._squeeze_active,
            blocks=self._blocks,
            accepted=self._accepted,
            dropped=self._dropped,
            detectors=len(self._detectors),
        )

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

    def reset(self) -> None:
        """Forget all stream state (after a gap, a reconnect, or a recalibration).

        This forgets a held squeeze *without* announcing it: the caller owns releasing the
        squeeze it forwarded (the runner does, before calling this).
        """
        with self._lock:
            self._reset_locked()

    def _reset_locked(self) -> None:
        for chain in self._chains.values():
            self._safe(chain, "reset")
        for det in self._detectors:
            self._safe(det, "reset")
        self._safe(self._parts.quality, "reset")
        self._squeeze_active = False
        self._recent.clear()

    def process(self, block: SampleBlock) -> PipelineResult:
        """Run one block through every stage; return the accepted events and a status."""
        with self._lock:
            return self._process_locked(block)

    def _process_locked(self, block: SampleBlock) -> PipelineResult:
        self._blocks += 1
        self._detector_failed = False
        self._now = block.t0 + block.duration

        filtered = self._filter(block)
        gate_closed, gate_reason = self._quality_gate(block)
        self._account_exposure(gate_closed or self._suspended)

        # Each event is tagged with whether its detector rescales itself (see ``_scaled``).
        raw_events: list[tuple[BioEvent, bool]] = []
        for det in list(self._detectors):
            scaled = id(det) in self._scaled
            raw_events.extend((e, scaled) for e in self._run_detector(det, filtered))
        raw_events.sort(key=lambda pair: pair[0].t)

        # ``held`` follows the events accepted so far in *this* block, so a squeeze that
        # begins and ends inside one block is seen as such: judging each OFF against the
        # state from before the block would drop it as an orphan and strand the ON.
        accepted: list[BioEvent] = []
        held = self._squeeze_active
        for event, scaled in raw_events:
            verdict = self._admit(event, gate_closed, gate_reason, held, scaled)
            if verdict is None:
                continue
            accepted.append(verdict)
            if verdict.kind is EventKind.SQUEEZE_ON:
                held = True
            elif verdict.kind is EventKind.SQUEEZE_OFF:
                held = False

        # The gate closing under a held squeeze must release it, and so must a detector
        # that died holding one (its own OFF will never come).
        if held and (gate_closed or self._suspended or self._detector_failed):
            why = (gate_reason or self._reason
                   or ("detector failed" if self._detector_failed else "gate"))
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
        return PipelineResult(events=tuple(accepted), status=self.status)

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
        closed = overall == "BAD" or bool(getattr(report, "suppress_events", False))
        return closed, ("signal quality bad" if closed else "")

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
    ) -> BioEvent | None:
        """Apply the gates to one event. Returns the event to accept, or None.

        ``held`` is whether a squeeze is forwarded-and-unreleased *at this event*
        (including events accepted earlier in the same block).
        """
        opts = self._parts.options
        # Keep squeeze bookkeeping honest even for events we refuse to forward.
        if event.kind in opts.always_pass:
            if event.kind is EventKind.SQUEEZE_OFF and not held:
                return None          # orphan OFF (we never forwarded the ON): nothing to release
            return event
        if self._suspended:
            self._dropped += 1
            return None
        if gate_closed:
            self._dropped += 1
            log.debug("Biosignal event %s dropped: %s", event.kind.value, gate_reason)
            return None
        floor = self._confidence_floor(scaled)
        if event.kind is EventKind.SQUEEZE_ON and held:
            return event             # level change while held: the runner decides if it matters
        if _float(event.confidence, 0.0) < floor:
            self._dropped += 1
            return None
        return event

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
        governor = self._parts.governor
        with self._lock:
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


def build_parts(request: PartsRequest) -> PipelineParts:
    """Assemble real collaborators from the sibling modules, skipping what is missing.

    Each optional piece is imported inside its own ``try`` so that a module (or an
    optional backend) that is absent costs only that piece, with the reason logged.
    """
    kinds = {c.kind for c in request.channels} if request.channels else set(SignalKind)
    parts = PipelineParts()

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
    profile = _load_profile(request) if (
        request.double_blink or request.jaw_clench) else None

    detectors: list[StreamDetector] = []
    if request.double_blink:
        det = _build_blink_detector(request, profile)
        if det is not None:
            detectors.append(det)
    if request.jaw_clench:
        det = _build_jaw_detector(request, profile)
        if det is not None:
            detectors.append(det)
    if request.emg:
        det = _build_emg_detector(request)
        if det is not None:
            detectors.append(det)
    parts.detectors = detectors
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


def _build_blink_detector(request: PartsRequest, profile: Any) -> StreamDetector | None:
    """Double-blink detector, thresholds from the user's calibration when they have one."""
    try:
        from yazses.biosignal.artifacts import BlinkDetector

        amplitude = _positive(getattr(profile, "blink_amplitude", None))
        factory = getattr(BlinkDetector, "from_calibration", None)
        if amplitude is not None and callable(factory):
            try:
                return factory(request.fs, amplitude, double_only=True)  # type: ignore[no-any-return]
            except Exception:
                log.warning("Blink calibration unusable; using default thresholds.",
                            exc_info=True)
        return BlinkDetector(request.fs, double_only=True)
    except Exception:
        log.warning("Double-blink detector unavailable.", exc_info=True)
        return None


def _build_jaw_detector(request: PartsRequest, profile: Any) -> StreamDetector | None:
    """Jaw-clench detector with a speech guard, calibrated when the profile has a clench."""
    try:
        from yazses.biosignal.artifacts import JawClenchDetector

        guard = _wrap_speech_guard(request.speech_guard)
        power = _positive(getattr(profile, "clench_power", None))
        factory = getattr(JawClenchDetector, "from_calibration", None)
        if power is not None and callable(factory):
            try:
                return factory(request.fs, power, speech_guard=guard)  # type: ignore[no-any-return]
            except Exception:
                log.warning("Clench calibration unusable; using default thresholds.",
                            exc_info=True)
        return JawClenchDetector(request.fs, speech_guard=guard)
    except Exception:
        log.warning("Jaw-clench detector unavailable.", exc_info=True)
        return None


def _build_emg_detector(request: PartsRequest) -> StreamDetector | None:
    """EMG onset needs a per-person calibration; without one the switch stays off.

    Fixed microvolt thresholds are meaningless across people (pressure.py), so an
    uncalibrated EMG detector would be guessing — it is refused rather than guessed.
    """
    try:
        from yazses.biosignal import calibration
        from yazses.biosignal.emg_onset import (
            EmgOnsetDetector,
            GradedEmgDetector,
            OnsetThresholds,
        )

        path = request.calibration_file.strip() or str(calibration.default_profile_path())
        profile = calibration.load_profile(path)
        if profile is None:
            log.info("EMG switch off: no calibration profile at %s "
                     "(run the calibration first).", path)
            return None
        if profile.mvc_rms is None:
            log.info("EMG switch off: the calibration has no maximum-contraction phase.")
            return None
        baseline, mvc = float(profile.baseline_rms), float(profile.mvc_rms)
        if request.graded_emg:
            return GradedEmgDetector.from_calibration(baseline, mvc)
        return EmgOnsetDetector(OnsetThresholds.from_calibration(baseline, mvc))
    except FileNotFoundError:
        log.info("EMG switch off: calibration profile not found.")
    except Exception:
        log.warning("EMG onset detector unavailable.", exc_info=True)
    return None
