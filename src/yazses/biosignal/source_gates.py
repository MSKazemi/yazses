"""One constructor for a guarded biosignal source and its event gate (ADR-v2-155 §3, §6).

Every live consumer of a biosignal stream -- the daemon's runner, ``yazses biosignal
monitor`` and ``yazses biosignal field-test`` -- must judge a block by the same rules, or
a field test can score a stream the daemon would refuse. This module is the one place
those rules are put together:

* :func:`guard_source` wraps any source in the stream-integrity
  :class:`~yazses.biosignal.integrity.IntegrityGuard`, with the arrival-rate check on for
  live hardware only (a replay delivers faster than real time by design);
* :func:`compose_quality_gate` builds the ``PipelineParts.quality`` drop-in: the existing
  :class:`~yazses.biosignal.integrity.IntegrityGate` around the waveform quality monitor,
  and -- for a source that reports its own health, today only ThinkGear -- the
  :class:`SourceHealthGate` around that.

For every other source (synthetic, file, BrainFlow, LSL, BITalino, Myo) the result is
exactly what the callers built by hand before: the guard, and a plain ``IntegrityGate``.

## The source-health gate

:class:`SourceHealthGate` adds one veto in front of the two existing gates and never
replaces them. A block is admitted only when the source's own verdict for *that block*
(``guard.health_for(block)``, carried across a sanitized copy) is trusted **and** the
stream-integrity gate is open **and** the waveform quality monitor allows it. A block
with no verdict -- unknown provenance -- is vetoed, and so is any block the gate cannot
judge because something raised: a source-health gate error fails closed, it never turns
the gate off.

The report asks the pipeline to reset its detector and filter state at both edges of an
untrusted stretch. At its start (a new fault epoch or session), so a double blink cannot
pair a blink from before a contact loss with one after it, even when the loss arrived in
a serial read that carried no samples at all. And at the first trusted block after it,
so nothing the detectors and filters saw while the source was untrusted, unknown or
rearming can contribute to an event admitted afterwards. The second edge is needed because
a detector reports a gesture *later* than the samples that formed it (filter delay plus
its own peak search: about 0.17 s for a blink here), so judging the event by its reported
times against the vetoed blocks can let a pair whose first blink came from a rearming
read through.

Duck-typed on purpose: the gate reads ``trusted``, ``reason``, ``session``, ``epoch`` and
``describe()`` from the verdict, so it does not import a device module.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yazses.biosignal import integrity as _integrity
from yazses.biosignal.integrity import IntegrityGuard
from yazses.biosignal.types import BlockSource, SampleBlock

log = logging.getLogger(__name__)

__all__ = [
    "HEALTH_SCHEMES",
    "REPLAY_SCHEMES",
    "SourceHealthGate",
    "SourceHealthReport",
    "compose_quality_gate",
    "guard_source",
    "is_live",
    "needs_source_health",
    "scheme_of",
]

#: Sources that deliver recorded or generated data as fast as asked: no arrival-rate check.
REPLAY_SCHEMES = frozenset({"synthetic", "file"})
#: Sources whose own per-read health verdict must gate events (ADR-v2-155).
HEALTH_SCHEMES = frozenset({"thinkgear"})

# Reasons that describe the transport rather than the electrode contact are reported under
# the pipeline's existing "stream" refusal category (it keys on this prefix).
_TRANSPORT_REASONS = frozenset({"corrupt_packet", "transport_stalled", "clock_invalid"})
_STREAM_PREFIX = "stream integrity"


def scheme_of(spec: str) -> str:
    """``"thinkgear:/dev/rfcomm0"`` -> ``"thinkgear"`` (lower-case, stripped)."""
    return str(spec or "").partition(":")[0].strip().lower()


def is_live(spec: str) -> bool:
    """True for a source that streams from hardware in real time."""
    return scheme_of(spec) not in REPLAY_SCHEMES


def guard_source(
    source: BlockSource, spec: str, *, clock: Callable[[], float] = time.monotonic,
) -> IntegrityGuard:
    """``source`` inside the stream-integrity guard every consumer uses."""
    # Looked up on the module at call time (here and below), as the callers did before, so
    # a test that substitutes the integrity classes still reaches every caller.
    return _integrity.IntegrityGuard(source, check_arrival_rate=is_live(spec), clock=clock)


def needs_source_health(source: Any, spec: str = "") -> bool:
    """Whether ``source`` (the unguarded one) must be gated by its own health verdict.

    By scheme, so a ThinkGear spec gets the gate even if its source somehow lacks the
    verdict (it then vetoes everything: fail closed), and by capability, so a source that
    offers ``health_for`` is never left ungated.
    """
    inner = source.inner if isinstance(source, _integrity.IntegrityGuard) else source
    return scheme_of(spec) in HEALTH_SCHEMES or callable(getattr(type(inner), "health_for", None))


def compose_quality_gate(guard: IntegrityGuard, quality: Any, spec: str = "") -> Any:
    """The ``PipelineParts.quality`` for a guarded source: ``IntegrityGate(guard, quality)``,
    wrapped in a :class:`SourceHealthGate` when the source reports its own health."""
    gate = _integrity.IntegrityGate(guard, quality)
    if needs_source_health(guard.inner, spec):
        return SourceHealthGate(guard, gate)
    return gate


@dataclass(frozen=True)
class SourceHealthReport:
    """What :class:`SourceHealthGate` returns. The three fields the pipeline gate reads,
    an explicit reason, and the verdict that decided it. Anything else is read from the
    inner (integrity-gated) report, so existing readers keep working."""

    overall: Any
    suppress_events: bool
    bad_during_update: bool
    integrity_reason: str = ""
    source_health: Any = None
    source_vetoed: bool = False
    reset_detector_state: bool = False
    inner: Any = None

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name in _REPORT_FIELDS:
            raise AttributeError(name)
        inner = self.__dict__.get("inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)


_REPORT_FIELDS = frozenset({"overall", "suppress_events", "bad_during_update",
                            "integrity_reason", "source_health", "source_vetoed",
                            "reset_detector_state", "inner"})


class SourceHealthGate:
    """``PipelineParts.quality`` drop-in: the source's own per-block health veto on top of
    an inner gate (an :class:`IntegrityGate`), which it never bypasses.

    ``report`` and ``reset()`` are the inner gate's, so code reading
    ``parts.quality.report`` (the monitor) is unchanged.
    """

    def __init__(self, guard: IntegrityGuard, inner: Any) -> None:
        self.guard = guard
        self.inner = inner
        self._last_key: tuple[Any, ...] | None = None
        self._last_trusted = False      # nothing is trusted before the first block
        self._warned: set[str] = set()

    @property
    def report(self) -> Any:
        return getattr(self.inner, "report", None)

    def reset(self) -> None:
        # The signal judgement only; the source's health is a fact about the device.
        reset = getattr(self.inner, "reset", None)
        if callable(reset):
            reset()

    def update(self, block: SampleBlock) -> SourceHealthReport:
        inner_report: Any = None
        inner_failed = False
        try:
            inner_report = self.inner.update(block)
        except Exception:
            inner_failed = True
            self._warn_once("inner", "Biosignal stream/quality gate failed; events are "
                            "held (fail closed).")
        try:
            health = self.guard.health_for(block)
        except Exception:
            health = None
            self._warn_once("health", "Biosignal source-health lookup failed; events are "
                            "held (fail closed).")

        trusted = health is not None and getattr(health, "trusted", False) is True
        key: tuple[Any, ...] = (("unknown",) if health is None else
                                (getattr(health, "session", None), getattr(health, "epoch", None)))
        # Reset at the start of a fault epoch / session, and at the first trusted block
        # after any untrusted one (see the module docstring: a detector's event times lag
        # its samples, so only a clean slate keeps rearming samples out of an event).
        reset_state = ((self._last_key is not None and key != self._last_key)
                       or (trusted and not self._last_trusted))
        self._last_key = key
        self._last_trusted = trusted

        if inner_failed or inner_report is None:
            inner_closed, inner_overall, inner_why = True, "BAD", ""
            inner_bad_during = True
        else:
            inner_overall = getattr(inner_report, "overall", "unknown")
            inner_closed = (_is_bad(inner_overall)
                            or bool(getattr(inner_report, "suppress_events", False)))
            inner_bad_during = bool(getattr(inner_report, "bad_during_update", False))
            inner_why = str(getattr(inner_report, "integrity_reason", "") or "")

        reasons = []
        if not trusted:
            reasons.append(_health_reason(health))
        if inner_why:
            reasons.append(inner_why)
        elif inner_failed:
            reasons.append(f"{_STREAM_PREFIX}: the gate failed")
        # A transport reason first: the pipeline files a refusal by the prefix it reads.
        reasons.sort(key=lambda r: not r.startswith(_STREAM_PREFIX))
        closed = (not trusted) or inner_closed
        return SourceHealthReport(
            overall="BAD" if closed else inner_overall,
            suppress_events=closed,
            bad_during_update=(not trusted) or inner_bad_during,
            integrity_reason="; ".join(r for r in reasons if r),
            source_health=health,
            source_vetoed=not trusted,
            reset_detector_state=reset_state,
            inner=inner_report,
        )

    def _warn_once(self, key: str, message: str) -> None:
        if key in self._warned:
            log.debug("%s", message, exc_info=True)
            return
        self._warned.add(key)
        log.warning("%s", message, exc_info=True)


def _is_bad(overall: Any) -> bool:
    return str(getattr(overall, "name", overall)).upper() == "BAD"


def _health_reason(health: Any) -> str:
    """Plain reason for a vetoed block; transport faults read as stream integrity."""
    if health is None:
        return "source health: unknown provenance (no verdict for this block)"
    reason = getattr(health, "reason", None)
    code = str(getattr(reason, "value", reason) or "unknown")
    try:
        text = str(reason.describe()) if reason is not None else ""
    except Exception:
        text = ""
    detail = f"{code} ({text})" if text else code
    if code in _TRANSPORT_REASONS:
        return f"{_STREAM_PREFIX}: source {detail}"
    return f"source health: {detail}"
