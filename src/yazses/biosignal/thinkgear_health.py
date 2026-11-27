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

## What a run showed (local diagnostics)

The machine also adds each session's reads up into a :class:`HealthTally`, which a source
turns into a :class:`ProtocolHealth` for ``yazses biosignal check-source``: counts, reason
codes and one duration. It is a statement about the *protocol* (contact reports, rejected
packets, whether any read was trusted), never about the waveform, a gesture or device
support, and it holds no sample, port, address or timestamp.

Pure: standard library only, no I/O, no clock of its own, no threads.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
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
    "HealthTally",
    "PacketReport",
    "ProtocolHealth",
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

    def category(self) -> str:
        """Which kind of problem holds the events, or ``""`` when trusted."""
        return _CATEGORIES[self]


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

_CATEGORIES: dict[HealthReason, str] = {
    HealthReason.UNKNOWN_CONTACT: "contact unknown",
    HealthReason.NO_CONTACT: "contact contaminated",
    HealthReason.CONTACT_CONTAMINATED: "contact contaminated",
    HealthReason.CONTACT_STALE: "contact stale",
    HealthReason.CORRUPT_PACKET: "corrupt framing",
    HealthReason.TRANSPORT_STALLED: "stream integrity failure",
    HealthReason.CLOCK_INVALID: "stream integrity failure",
    HealthReason.REARMING: "rearm in progress",
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


@dataclass
class HealthTally:
    """One session's reads added up. Counts, reason codes and one duration only.

    A contact report is counted once per packet that carries one. ``held_reads`` counts the
    untrusted reads under the reason each was held for; ``trust_breaks`` counts the fault
    epochs under the reason that opened each (including one seen on a read with no bytes).
    ``longest_report_gap_s`` is the longest stretch of the host's monotonic clock, from the
    first read on, in which no contact report arrived.
    """

    reads: int = 0                    # serial reads that carried bytes
    trusted_reads: int = 0
    raw_samples: int = 0
    zero_reports: int = 0
    contaminated_reports: int = 0     # nonzero and not 200
    no_contact_reports: int = 0       # 200
    rejected_packets: int = 0
    skipped_bytes: int = 0
    longest_report_gap_s: float = 0.0
    held_reads: dict[str, int] = field(default_factory=dict)
    trust_breaks: dict[str, int] = field(default_factory=dict)
    last_trusted: bool = False
    last_reason: str = "unknown_contact"

    @property
    def quality_reports(self) -> int:
        return self.zero_reports + self.contaminated_reports + self.no_contact_reports


@dataclass(frozen=True)
class ProtocolHealth:
    """What a ThinkGear run observed about the protocol, for a local diagnostic report.

    Never evidence that the waveform is usable, that a gesture works or that a device is
    supported. Holds no sample, port, address or timestamp.
    """

    tally: HealthTally
    packets_ok: int = 0
    bad_checksum: int = 0
    bad_length: int = 0
    malformed: int = 0

    @property
    def result(self) -> str:
        """``not_observed``, ``no_contact_report``, ``never_trusted`` or ``trusted_reads_seen``."""
        t = self.tally
        if t.reads == 0:
            return "not_observed"
        if t.quality_reports == 0:
            return "no_contact_report"
        if t.trusted_reads == 0:
            return "never_trusted"
        return "trusted_reads_seen"

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self.tally)
        out["longest_report_gap_s"] = round(self.tally.longest_report_gap_s, 1)
        out.update(
            packets_ok=self.packets_ok, bad_checksum=self.bad_checksum,
            bad_length=self.bad_length, malformed=self.malformed,
            # Packets carry no sequence number: after any loss the count is unknowable.
            lost_samples=("unknown" if self.tally.rejected_packets or self.tally.skipped_bytes
                          else "none detected"),
            result=self.result,
        )
        return out

    def lines(self) -> list[str]:
        """The summary in words, for a terminal."""
        t = self.tally
        out = ["ThinkGear protocol health (what this run observed; not evidence of a usable "
               "waveform,", "a working gesture or device support):"]
        if t.reads == 0:
            out.append(f"  Result: {_RESULTS[self.result]}")
            return out
        out.append(f"  serial reads with bytes: {t.reads}, trusted: {t.trusted_reads}")
        if t.quality_reports:
            out.append(f"  contact reports (POOR_SIGNAL 0x02): {t.quality_reports} seen "
                       f"(zero {t.zero_reports}, contaminated {t.contaminated_reports}, "
                       f"no skin contact {t.no_contact_reports})")
        else:
            out.append("  contact reports (POOR_SIGNAL 0x02): none seen")
        out.append(f"  longest stretch without a contact report: "
                   f"{t.longest_report_gap_s:.1f} s (host clock; events are held past "
                   f"{CONTACT_TTL_S:g} s)")
        rejected = self.bad_checksum + self.bad_length + self.malformed
        out.append(f"  packets: {self.packets_ok} accepted, {rejected} rejected "
                   f"(bad checksum {self.bad_checksum}, bad length {self.bad_length}, "
                   f"malformed {self.malformed}); {t.skipped_bytes} byte(s) skipped")
        if t.rejected_packets or t.skipped_bytes:
            out.append("  lost samples: unknown (packets carry no sequence number)")
        out.append(f"  raw samples delivered: {t.raw_samples}")
        for title, counts in (("reads held, by reason", t.held_reads),
                              ("trust broke, by reason", t.trust_breaks)):
            if counts:
                listed = ", ".join(f"{k} {n}" for k, n in sorted(counts.items()))
                out.append(f"  {title}: {listed}")
        if t.last_trusted:
            out.append("  latest verdict: trusted")
        else:
            reason = HealthReason(t.last_reason)
            out.append(f"  latest verdict: not trusted ({reason.value}: {reason.describe()})")
        out.append(f"  Result: {_RESULTS[self.result]}")
        out.append("  Note: t0 counts delivered samples at the nominal "
                   f"{THINKGEAR_FS:g} Hz, so the rate_t0 clause is not a")
        out.append("  measurement of throughput; rate_arrival is.")
        return out


_RESULTS: dict[str, str] = {
    "not_observed": "NOT OBSERVED. No bytes arrived, so nothing about the protocol was checked.",
    "no_contact_report": "UNQUALIFIED, needs investigation. No contact report was seen, so "
                         "every event would be held.",
    "never_trusted": "UNQUALIFIED, needs investigation. No read was trusted (trust needs two "
                     "zero reports and 1 s of clean samples).",
    "trusted_reads_seen": "trusted reads were seen. This covers the protocol only.",
}


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
        self._new_tally()
        self._clear()

    # ---- lifecycle -----------------------------------------------------------

    def reset(self) -> None:
        """A fresh transport session: nothing from the previous one is trusted."""
        self.session += 1
        self.epoch = 0
        self._new_tally()
        self._clear()

    def invalidate(self) -> None:
        """Stop / disconnect / unavailable: back to UNKNOWN, counters and clocks cleared.
        :attr:`tally` is kept, so a finished run can still be described."""
        self._clear()

    def _new_tally(self) -> None:
        # Diagnostics only: nothing here is read when a verdict is decided.
        self.tally = HealthTally()
        self._gap_mark: float | None = None

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
        self._tally_gap(now, reported=False)
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

        self._tally_gap(now, reported=bool(zeros or nonzero))
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

        self._tally_read(trusted, raw_total, zeros, packets, rejected_packets, skipped_bytes)
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

    def _tally_gap(self, now: float, *, reported: bool) -> None:
        if not _finite(now):
            return
        if self._gap_mark is None or now < self._gap_mark:
            self._gap_mark = now
        self.tally.longest_report_gap_s = max(self.tally.longest_report_gap_s,
                                              now - self._gap_mark)
        if reported:
            self._gap_mark = now

    def _tally_read(self, trusted: bool, raw_total: int, zeros: int,
                    packets: Sequence[PacketReport], rejected: int, skipped: int) -> None:
        t = self.tally
        t.reads += 1
        t.raw_samples += raw_total
        no_contact = sum(1 for p in packets if p.poor_signal == POOR_SIGNAL_NO_CONTACT)
        reported = sum(1 for p in packets if p.poor_signal is not None)
        t.zero_reports += zeros
        t.no_contact_reports += no_contact
        t.contaminated_reports += reported - zeros - no_contact
        t.rejected_packets += rejected
        t.skipped_bytes += skipped
        t.last_trusted = trusted
        t.last_reason = self.reason.value
        if trusted:
            t.trusted_reads += 1
        else:
            t.held_reads[self.reason.value] = t.held_reads.get(self.reason.value, 0) + 1

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
            breaks = self.tally.trust_breaks
            breaks[reason.value] = breaks.get(reason.value, 0) + 1
        self.tally.last_trusted = False
        self.tally.last_reason = reason.value
        self.state = HealthState.UNTRUSTED
        self.reason = reason
        self._good_reports = 0
        self._good_samples = 0
