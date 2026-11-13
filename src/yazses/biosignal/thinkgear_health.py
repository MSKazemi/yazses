"""ThinkGear source health: a pure, fail-closed contact/transport state (ADR-v2-155).

A NeuroSky ThinkGear stream carries two kinds of fact. The raw 0x80 rows are the
waveform the blink and jaw detectors read. The 0x02 POOR_SIGNAL rows say whether the
headset itself saw contamination: **zero** means none was flagged, **any nonzero** value
means some was, and 200 means the electrodes are not touching skin. The protocol also
has no sample sequence number, so a packet rejected by its checksum is a hole of unknown
size: :mod:`yazses.biosignal.thinkgear` never fills it, and this module never pretends
to know how many samples it held.

This module decides, **per serial read**, whether the samples that read produced can be
trusted at all. It is the extra veto ADR-v2-155 adds in front of the existing stream
integrity guard and the waveform quality monitor; it is never a detector and never
turns a vendor score into an event.

## The policy (frozen at G0, #827; engineering thresholds, not validated values)

* Unknown contact is untrusted: before the first explicit ``POOR_SIGNAL=0`` nothing is
  admitted, however clean the waveform looks.
* Any nonzero ``POOR_SIGNAL``, any rejected packet (bad checksum, bad length, malformed
  row) and any skipped framing byte taints the **whole** read, even when a later report
  in the same read says zero. A final good value never rescues an earlier bad one, and
  the zero reports of a tainted read are not counted as rearm evidence.
* A report older than :data:`CONTACT_TTL_S` (3.0 s of the injected monotonic clock)
  closes the gate. A clock that goes backwards or is not finite is not proof of
  freshness and closes it too.
* Rearming after any unhealthy or unknown state needs :data:`REARM_GOOD_REPORTS` (two)
  separate zero reports **and** :data:`REARM_CLEAN_SAMPLE_S` (1.0 s, i.e. 512 samples at
  the nominal rate) of contiguous clean raw samples counted only while the latest known
  quality is zero. The read that completes the rearm stays vetoed; the next clean read
  is the first that can be admitted. A transport stall while rearming
  (:data:`TRANSPORT_STALL_S`, the stream guard's own stall threshold) restarts it.

Changing any of these needs a reviewed follow-up with measured evidence, never tuning
on evaluation data (ADR-v2-155 decision 4).

## What a clock TTL cannot tell you

It says a report *arrived* recently, not that the headset *sampled* recently: a
Bluetooth link can buffer. The arrival-rate, stall and backlog checks of
:mod:`yazses.biosignal.integrity` and the runner stay in force for exactly that reason.

## Shape

:class:`ThinkGearHealth` is fed parser-derived facts only: per accepted packet its raw
sample count and its POOR_SIGNAL value (:class:`PacketReport`, in wire order), plus the
parser's reject and skipped-byte deltas for the read, and the monotonic time the read
happened. It returns an immutable :class:`BatchHealth` that holds counts and reasons
only: no samples, no timestamps, no port, no device address.

Pure: standard library only, no I/O, no clock of its own, no threads.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

__all__ = [
    "CONTACT_TTL_S",
    "POOR_SIGNAL_NO_CONTACT",
    "REARM_CLEAN_SAMPLE_S",
    "REARM_GOOD_REPORTS",
    "THINKGEAR_FS",
    "TRANSPORT_STALL_S",
    "BatchHealth",
    "HealthReason",
    "HealthState",
    "PacketReport",
    "ThinkGearHealth",
]

# ---- the G0 policy (#827): conservative engineering thresholds, UNTESTED on hardware ----

#: A contact report older than this (seconds of the injected monotonic clock) closes the gate.
CONTACT_TTL_S = 3.0
#: Separate, fresh ``POOR_SIGNAL=0`` reports needed after any unhealthy or unknown state.
REARM_GOOD_REPORTS = 2
#: Contiguous clean raw signal needed after any unhealthy or unknown state.
REARM_CLEAN_SAMPLE_S = 1.0
#: The ASIC's nominal raw output rate ("512 times a second", NeuroSky protocol document).
THINKGEAR_FS = 512.0
#: No bytes for this long while rearming breaks the contiguity of the clean run. Not a new
#: number: it is ``integrity.STALL_S`` (not imported, to keep this module stdlib-only;
#: a test pins the two together).
TRANSPORT_STALL_S = 1.5
#: "200 ... the ThinkGear electrodes aren't contacting a person's skin".
POOR_SIGNAL_NO_CONTACT = 200


class HealthState(str, Enum):
    """Where the source stands. Only READY can admit, and only from the next clean read."""

    UNKNOWN = "unknown"          # no explicit zero report yet in this session
    UNTRUSTED = "untrusted"      # a fault was seen; waiting for a fresh zero report
    REARMING = "rearming"        # zero reports arriving; counting the clean run
    READY = "ready"              # rearmed; clean reads are admitted


class HealthReason(str, Enum):
    """Why a read was (not) trusted. Plain codes for status lines and tests."""

    UNKNOWN_CONTACT = "unknown_contact"          # no POOR_SIGNAL=0 seen yet
    NO_CONTACT = "no_contact"                    # POOR_SIGNAL=200: electrodes off the skin
    CONTACT_CONTAMINATED = "contact_contaminated"  # any other nonzero POOR_SIGNAL
    CONTACT_STALE = "contact_stale"              # last report older than CONTACT_TTL_S
    CORRUPT_PACKET = "corrupt_packet"            # parser reject or skipped framing bytes
    TRANSPORT_STALLED = "transport_stalled"      # no bytes for TRANSPORT_STALL_S while rearming
    CLOCK_INVALID = "clock_invalid"              # the monotonic clock went back or is not finite
    REARMING = "rearming"                        # healthy so far, rearm not complete
    TRUSTED = "trusted"

    def describe(self) -> str:
        return _DESCRIPTIONS[self]


_DESCRIPTIONS: dict[HealthReason, str] = {
    HealthReason.UNKNOWN_CONTACT: "the headset has not reported electrode contact yet",
    HealthReason.NO_CONTACT: "the headset reports no skin contact",
    HealthReason.CONTACT_CONTAMINATED: "the headset reports signal contamination",
    HealthReason.CONTACT_STALE: "the headset's contact report is too old",
    HealthReason.CORRUPT_PACKET: "corrupt or lost packets; the number of lost samples is "
                                 "unknown",
    HealthReason.TRANSPORT_STALLED: "the serial stream stalled",
    HealthReason.CLOCK_INVALID: "the monotonic clock is unusable, so freshness is unknown",
    HealthReason.REARMING: "recovering: waiting for fresh contact reports and clean signal",
    HealthReason.TRUSTED: "",
}


@dataclass(frozen=True)
class PacketReport:
    """One checksum-valid packet as the health machine sees it: no sample values."""

    raw_samples: int
    poor_signal: int | None = None


@dataclass(frozen=True)
class BatchHealth:
    """The immutable verdict for one serial read. Counts and reasons only.

    ``session`` changes on every fresh ``start()`` and ``epoch`` counts the fault epochs
    entered in that session, so ``(session, epoch)`` changes whenever trust was broken --
    including by a read that carried no raw samples at all. ``state`` is the state *after*
    this read; ``trusted`` is the verdict *for* it (a read that completes the rearm is in
    state READY and still not trusted). ``sample_gap_unknown`` is True when packets were
    lost: how many samples they held cannot be known.
    """

    session: int
    epoch: int
    trusted: bool
    state: HealthState
    reason: HealthReason
    raw_samples: int
    nonzero_quality_reports: int
    zero_quality_reports: int
    rejected_packet_delta: int
    skipped_byte_delta: int
    last_poor_signal: int | None
    consecutive_good_reports: int
    continuous_good_samples: int
    sample_gap_unknown: bool

    def describe(self) -> str:
        """One plain-language line, or ``""`` when trusted. No values from the signal."""
        return "" if self.trusted else f"source health: {self.reason.value} " \
                                       f"({self.reason.describe()})"

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["state"] = self.state.value
        out["reason"] = self.reason.value
        return out


def _finite(x: float) -> bool:
    try:
        return math.isfinite(x)
    except TypeError:
        return False


class ThinkGearHealth:
    """The per-read contact/transport state machine of spec §3. Not thread-safe.

    :meth:`observe_batch` judges one serial read; :meth:`observe_idle` lets a read that
    returned no bytes age the state (a report going stale, a stall while rearming).
    :meth:`invalidate` (stop, disconnect) and :meth:`reset` (a fresh start: new session)
    clear every bit of trust.
    """

    def __init__(self, fs: float = THINKGEAR_FS) -> None:
        fs = float(fs)
        if not _finite(fs) or fs <= 0:
            raise ValueError("fs must be finite and > 0")
        self.rearm_samples = math.ceil(REARM_CLEAN_SAMPLE_S * fs)
        self.session = 1
        self.epoch = 0
        self._clear()

    # ---- lifecycle -----------------------------------------------------------

    def reset(self) -> None:
        """A fresh transport session: nothing from the previous one is trusted."""
        self.session += 1
        self.epoch = 0
        self._clear()

    def invalidate(self) -> None:
        """Stop / disconnect / unavailable: back to UNKNOWN, counters and clocks cleared."""
        self._clear()

    def _clear(self) -> None:
        self.state = HealthState.UNKNOWN
        self.reason = HealthReason.UNKNOWN_CONTACT
        self._good_reports = 0
        self._good_samples = 0
        self._last_poor: int | None = None
        self._last_report_t: float | None = None
        self._last_data_t: float | None = None
        self._last_now: float | None = None

    # ---- the transitions -----------------------------------------------------

    def observe_idle(self, now: float) -> None:
        """A read that returned no bytes: only the clock moved."""
        fault = self._timing_fault(now)
        if fault is not None:
            self._enter_untrusted(fault)
        self._note_time(now)

    def observe_batch(
        self, now: float, packets: Sequence[PacketReport], rejected_packets: int,
        skipped_bytes: int,
    ) -> BatchHealth:
        """Judge one serial read: its accepted packets in wire order and the parser's
        reject / skipped-byte deltas for it. Returns the verdict for that read."""
        raw_total = 0
        nonzero = zeros = 0
        no_contact = junk = False
        first_zero: int | None = None
        for i, pk in enumerate(packets):
            n = pk.raw_samples
            if not isinstance(n, int) or n < 0:
                junk = True
                n = 0
            raw_total += n
            value = pk.poor_signal
            if value is None:
                continue
            self._last_poor = value
            if value == 0:
                zeros += 1
                if first_zero is None:
                    first_zero = i
            else:
                nonzero += 1
                no_contact = no_contact or value == POOR_SIGNAL_NO_CONTACT
        if not isinstance(rejected_packets, int) or rejected_packets < 0:
            junk, rejected_packets = True, 0
        if not isinstance(skipped_bytes, int) or skipped_bytes < 0:
            junk, skipped_bytes = True, 0

        # Faults in priority order: frame validity, then contact, then timing.
        fault: HealthReason | None
        timing = self._timing_fault(now)
        if junk or rejected_packets or skipped_bytes:
            fault = HealthReason.CORRUPT_PACKET
        elif no_contact:
            fault = HealthReason.NO_CONTACT
        elif nonzero:
            fault = HealthReason.CONTACT_CONTAMINATED
        else:
            fault = timing
        if timing is HealthReason.CLOCK_INVALID:
            fault = fault or timing
        self._note_time(now)
        if _finite(now) and timing is not HealthReason.CLOCK_INVALID:
            self._last_data_t = now
            if zeros or nonzero:
                self._last_report_t = now

        trusted = False
        if fault is not None:
            self._enter_untrusted(fault)
        elif self.state in (HealthState.UNKNOWN, HealthState.UNTRUSTED):
            if first_zero is not None:
                # Samples before the first zero were taken under unknown/bad quality.
                after = sum(max(p.raw_samples, 0) for p in packets[first_zero + 1:])
                self.state = HealthState.REARMING
                self.reason = HealthReason.REARMING
                self._good_reports = zeros
                self._good_samples = after
                self._maybe_ready()
            elif self.state is HealthState.UNKNOWN:
                self.reason = HealthReason.UNKNOWN_CONTACT
        elif self.state is HealthState.REARMING:
            self._good_reports += zeros
            self._good_samples += raw_total
            self.reason = HealthReason.REARMING
            self._maybe_ready()
        else:                                          # READY at the start of this read
            self._good_reports += zeros
            self._good_samples += raw_total
            self.reason = HealthReason.TRUSTED
            trusted = True

        return BatchHealth(
            session=self.session, epoch=self.epoch, trusted=trusted, state=self.state,
            reason=self.reason, raw_samples=raw_total, nonzero_quality_reports=nonzero,
            zero_quality_reports=zeros, rejected_packet_delta=rejected_packets,
            skipped_byte_delta=skipped_bytes, last_poor_signal=self._last_poor,
            consecutive_good_reports=self._good_reports,
            continuous_good_samples=self._good_samples,
            sample_gap_unknown=bool(rejected_packets or skipped_bytes or junk),
        )

    # ---- internals -----------------------------------------------------------

    def _maybe_ready(self) -> None:
        # The read that gets here stays vetoed: READY admits from the *next* clean read.
        if (self._good_reports >= REARM_GOOD_REPORTS
                and self._good_samples >= self.rearm_samples):
            self.state = HealthState.READY

    def _timing_fault(self, now: float) -> HealthReason | None:
        if not _finite(now) or (self._last_now is not None and now < self._last_now):
            return HealthReason.CLOCK_INVALID
        if self.state in (HealthState.READY, HealthState.REARMING):
            if self._last_report_t is None or now - self._last_report_t > CONTACT_TTL_S:
                return HealthReason.CONTACT_STALE
        if (self.state is HealthState.REARMING and self._last_data_t is not None
                and now - self._last_data_t > TRANSPORT_STALL_S):
            return HealthReason.TRANSPORT_STALLED
        return None

    def _note_time(self, now: float) -> None:
        if not _finite(now):
            return
        if self._last_now is not None and now < self._last_now:
            # A clock that went back: every stored time is in its future and means nothing.
            self._last_report_t = None
            self._last_data_t = None
        self._last_now = now

    def _enter_untrusted(self, reason: HealthReason) -> None:
        if self.state is not HealthState.UNTRUSTED:
            self.epoch += 1
        self.state = HealthState.UNTRUSTED
        self.reason = reason
        self._good_reports = 0
        self._good_samples = 0
