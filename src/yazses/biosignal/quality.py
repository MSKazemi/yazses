"""Signal-quality gate: is this electrode trustworthy enough for a detector to act on?

A detector fed a disconnected, railed or hum-swamped channel does not fail loudly — it
*triggers*. The research note in ``docs/research/muscle-brain-control.md`` puts the best
published blink switch at 0.10 false positives per minute, roughly 50 phantom activations
per workday, and that is on a *clean* signal. A loose electrode is the cheapest way to
multiply that number, so every detector in this package sits behind this monitor and the
pipeline drops events while :func:`suppress_events` is true.

This is an artifact-grade guard, not a decoder: it never tries to interpret what the
signal means (decoding thoughts stays rejected, ADR-v2-129), only whether it is
physically plausible biosignal at all.

## What is checked, per channel, over a sliding window

========== ===========================================================================
flatline   standard deviation near zero: unplugged lead, dead channel, stuck ADC
saturation samples beyond a µV limit, at a configured ADC rail, or a flat-topped
           plateau at the window extreme (clipping)
mains      50/60 Hz band power as a share of broadband power (FFT of the window)
drift      share of variance explained by a cubic trend, with a minimum amplitude, so
           the check cannot fire on a quiet, almost-flat channel
noise      high robust amplitude (MAD) on EEG/EOG, sustained variance bursts, and
           heavy tails *accompanying* bursts (loose electrode, cable sway)
dropout    gaps in ``t0`` continuity between blocks (packet loss) and non-finite
           samples (NaN/inf from a driver)
lead-off   an abrupt level step followed by a flat tail (electrode lifted or popped off);
           a flat tail with no step is not blamed on contact
motion     (montage level, needs >= 2 judgeable channels) slow level excursions that hit
           ALL of them in the same moments: the user or the cable moved, which is a
           different fix from one badly seated electrode, so it replaces the per-channel
           burst/noise verdict instead of being added to it
========== ===========================================================================

Each check returns a value, a status and a penalty; the channel status is the worst of
them and the score is ``1 - max(penalty)``. Score bands: GOOD >= 0.75, DEGRADED in
[0.25, 0.75), BAD < 0.25.

``ChannelQuality.contact_score`` in [0, 1] is the same arithmetic restricted to the checks
that describe the electrode-skin interface (flat, clipping, hum, drift, noise, lead-off):
transport faults (packet loss, NaN) and shared movement are not the electrode's fault and
do not lower it. It is a derived display number, not a measured impedance.

## Honesty about the thresholds

None of the numeric defaults in :class:`QualityThresholds` is taken from a paper or has
been validated on recordings from a specific board: they are engineering choices with the
reasoning stated next to each one, and they are meant to be tuned against real sessions.
The exceptions are intentional asymmetries that follow from the physics, e.g. EMG is
exempt from the noise checks because a squeeze *is* a sustained broadband burst, and a
blink *is* a heavy-tailed transient, so kurtosis alone never marks a channel bad.

## Hysteresis

Entering BAD is immediate (safety first); leaving it needs ``recover_windows``
consecutive clean evaluations, one evaluation per ``hop_s`` of new signal. The monitor
also *starts* in BAD ("warming up") so a detector never acts before the window has
filled and has been judged. Status never flaps between BAD and usable on one lucky
window.

Evaluations sit on an absolute grid (the first at ``min_fill_s`` of signal, then every
``hop_s``) and :meth:`SignalQualityMonitor.update` runs EVERY grid point that a block
spans, in order, each on the window that ended there. The hysteresis counters therefore
advance exactly as if the same signal had arrived in tiny blocks: the final status does not
depend on how the source chunked the stream (a replay source may deliver 12 s at once). The
returned report is the LAST evaluation; ``worst_since_last_update`` records the worst
overall status seen across all evaluations of that call so a pipeline can drop events from
a transient bad stretch inside one big block.

Pure logic: numpy + stdlib only, no I/O, no threads. Feed it :class:`SampleBlock` s in
order via :meth:`SignalQualityMonitor.update`.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum

import numpy as np

from yazses.biosignal.types import SampleBlock, SignalKind

__all__ = [
    "ChannelQuality",
    "QualityReport",
    "QualityStatus",
    "QualityThresholds",
    "Reason",
    "SignalQualityMonitor",
    "WorstQuality",
    "assess_channel",
    "burst_fraction",
    "common_mode_fraction",
    "drift_metrics",
    "excess_kurtosis",
    "explain",
    "flatline_std",
    "lead_off_metrics",
    "mains_ratio",
    "nonfinite_fraction",
    "robust_sigma",
    "saturation_fraction",
    "segment_excursions",
    "suppress_events",
]

_EPS = 1e-12


class QualityStatus(Enum):
    """Trust level of a channel (or of the whole montage)."""

    GOOD = "good"
    DEGRADED = "degraded"   # usable, but expect more false positives / misses
    BAD = "bad"             # a detector must not act on this


class Reason:
    """Stable machine-readable reason codes carried in ``ChannelQuality.reasons``."""

    WARMING_UP = "warming_up"
    RECOVERING = "recovering"
    FLATLINE = "flatline"
    SATURATION = "saturation"
    MAINS = "mains_interference"
    DRIFT = "drift"
    NOISE = "noise"
    DROPOUT = "dropout"
    NONFINITE = "nonfinite"
    LEAD_OFF = "lead_off"
    MOTION = "motion_artifact"
    TOO_FEW_CHANNELS = "too_few_channels"
    REQUIRED_MISSING = "required_channel_unusable"


@dataclass(frozen=True)
class QualityThresholds:
    """Every tunable of the monitor, with the reasoning for each default.

    All ``*_degraded`` / ``*_bad`` pairs mean: at or beyond ``degraded`` the channel is
    DEGRADED, at or beyond ``bad`` it is BAD (for the one lower-is-worse pair, flatline,
    the comparison is reversed). Maps keyed by :class:`SignalKind` exempt any kind that
    is absent from them.
    """

    # --- windowing and hysteresis ---------------------------------------------------
    window_s: float = 4.0            # long enough for a cubic trend to resolve < ~0.5 Hz
    hop_s: float = 0.25              # one evaluation per this much new signal
    min_fill_s: float = 2.0          # do not judge (stay BAD "warming up") before this
    recover_windows: int = 4         # consecutive clean evaluations needed to leave BAD
    enter_windows: int = 1           # consecutive BAD evaluations needed to enter BAD
    min_usable_channels: int = 1     # overall is BAD below this many non-BAD channels
    required_channels: tuple[str, ...] = ()   # overall is BAD if any of these is BAD
    min_samples: int = 16            # fewer finite samples than this: cannot judge

    # --- flatline: standard deviation in µV, LOWER is worse -------------------------
    # A live amplifier input always carries at least thermal/ADC noise of the order of a
    # microvolt; a standard deviation under a fraction of that means nothing is moving.
    flat_degraded_uv: float = 0.5
    flat_bad_uv: float = 0.1

    # --- saturation -----------------------------------------------------------------
    # Excursion limit in µV, applied to the median-centred window (a static electrode
    # offset is normal and must not count). Design choices: scalp EEG and even blinks
    # sit well below 500 µV; EOG is larger by construction; surface EMG is the biggest.
    saturation_uv: Mapping[SignalKind, float] = field(
        default_factory=lambda: {
            SignalKind.EEG: 500.0,
            SignalKind.EOG: 2000.0,
            SignalKind.EMG: 10000.0,
        }
    )
    adc_limit_uv: float | None = None    # board's full scale in µV, if known; else off
    saturation_frac_degraded: float = 0.005
    saturation_frac_bad: float = 0.05

    # --- mains interference ---------------------------------------------------------
    # Fraction of broadband (>= 1 Hz) power inside +-half-width of the mains line.
    # Both 50 and 60 Hz are tried unless narrowed; the worse one counts.
    mains_hz: tuple[float, ...] = (50.0, 60.0)
    mains_half_width_hz: float = 1.0
    mains_ratio_degraded: float = 0.3
    mains_ratio_bad: float = 0.7

    # --- drift ----------------------------------------------------------------------
    # Variance share of a cubic trend over the window; only counted when the trend
    # itself spans at least drift_min_p2p_uv, so a near-flat channel cannot trip it.
    drift_ratio_degraded: float = 0.85
    drift_ratio_bad: float = 0.97
    drift_min_p2p_uv: float = 50.0

    # --- broadband noise (EEG/EOG only; EMG is exempt, a squeeze is a burst) --------
    # (degraded, bad) robust sigma in µV from the MAD, which a few blinks cannot move.
    noise_sigma_uv: Mapping[SignalKind, tuple[float, float]] = field(
        default_factory=lambda: {
            SignalKind.EEG: (40.0, 100.0),
            SignalKind.EOG: (150.0, 400.0),
        }
    )
    burst_segments: int = 8
    burst_factor: float = 5.0           # a segment this many times the median std is a burst
    burst_frac_degraded: float = 0.4    # a blink touches 1-2 of 8 segments; sway touches many
    kurtosis_degraded: float = 50.0     # excess kurtosis; blinks alone are heavy-tailed,
    kurtosis_burst_frac: float = 0.3    # so it only counts together with this burst share
    # Bursts and kurtosis can only DEGRADE a channel, never mark it BAD: they overlap with
    # exactly the transients the detectors exist to find.

    # --- dropout (packet loss) and non-finite samples -------------------------------
    gap_tolerance_s: float = 0.02       # t0 jitter below this is not packet loss
    dropout_frac_degraded: float = 0.01
    dropout_frac_bad: float = 0.2
    nonfinite_frac_degraded: float = 0.001
    nonfinite_frac_bad: float = 0.1

    # --- lead-off / pop: an abrupt step followed by a flat tail ---------------------
    # A lifted or popped electrode jumps to a new level and then stops carrying signal.
    # "Flat" reuses ``flat_degraded_uv`` per short segment; the step must exceed this many
    # robust sigmas of the live part so a signal that merely goes quiet is not blamed on
    # contact. All four numbers are design choices, untuned on recordings.
    leadoff_segment_s: float = 0.05
    leadoff_step_sigma: float = 6.0
    leadoff_flat_s_degraded: float = 0.3
    leadoff_flat_s_bad: float = 0.8

    # --- common-mode motion: ALL judgeable channels excursing in the same moments ----
    # The window is cut into ~``motion_segment_s`` pieces; a piece is an excursion on a
    # channel when its mean sits more than ``motion_level_factor`` typical piece stds from
    # the channel's median piece mean. The score is the share of pieces that are
    # excursions on every judgeable channel at once. A triple blink fills ~0.4 of a 4 s
    # window on frontal channels, hence the degraded level; only sustained movement
    # reaches bad. EMG is not exempt because a squeeze is a burst of variance, not a level
    # shift. Design choices, untuned.
    motion_segment_s: float = 0.25
    motion_level_factor: float = 4.0
    motion_frac_degraded: float = 0.4
    motion_frac_bad: float = 0.75
    motion_min_channels: int = 2

    def __post_init__(self) -> None:
        if self.window_s <= 0 or self.hop_s <= 0 or self.min_fill_s <= 0:
            raise ValueError("window_s, hop_s and min_fill_s must be positive")
        if self.min_fill_s > self.window_s:
            raise ValueError("min_fill_s cannot exceed window_s")
        if self.recover_windows < 1 or self.enter_windows < 1:
            raise ValueError("recover_windows and enter_windows must be >= 1")
        if self.flat_bad_uv > self.flat_degraded_uv:
            raise ValueError("flat_bad_uv must be <= flat_degraded_uv (lower is worse)")
        if self.leadoff_segment_s <= 0 or self.motion_segment_s <= 0:
            raise ValueError("leadoff_segment_s and motion_segment_s must be positive")
        if self.leadoff_flat_s_bad < self.leadoff_flat_s_degraded:
            raise ValueError("leadoff_flat_s_bad must be >= leadoff_flat_s_degraded")
        if self.motion_frac_bad < self.motion_frac_degraded:
            raise ValueError("motion_frac_bad must be >= motion_frac_degraded")
        if self.motion_min_channels < 2:
            raise ValueError("motion_min_channels must be >= 2 (one channel cannot be common-mode)")

    def saturation_limit(self, kind: SignalKind) -> float:
        return float(self.saturation_uv.get(kind, math.inf))


DEFAULT_THRESHOLDS = QualityThresholds()


@dataclass(frozen=True)
class ChannelQuality:
    """Verdict for one channel. ``metrics`` holds the raw numbers behind it.

    ``contact_score`` in [0, 1] summarises the electrode-skin interface only (see the
    module docstring); 0.0 while warming up, when nothing has been judged.
    """

    name: str
    status: QualityStatus
    reasons: tuple[str, ...] = ()
    score: float = 1.0
    metrics: Mapping[str, float] = field(default_factory=dict)
    contact_score: float = 1.0


@dataclass(frozen=True)
class WorstQuality:
    """The worst overall verdict among the evaluations of one :meth:`update` call.

    ``reasons`` are the montage reasons plus those of every non-GOOD channel at that
    evaluation, de-duplicated; ``t`` is its end time; ``evaluations`` is how many grid
    points the call judged (0 only for a warm-up report, which judged none).
    """

    status: QualityStatus
    reasons: tuple[str, ...] = ()
    t: float = 0.0
    evaluations: int = 1


@dataclass(frozen=True)
class QualityReport:
    """Verdict for the whole montage at one moment."""

    channels: tuple[ChannelQuality, ...]
    overall: QualityStatus
    usable_channels: tuple[str, ...]
    reasons: tuple[str, ...] = ()
    missing_required: tuple[str, ...] = ()
    dropout_fraction: float = 0.0
    t: float = 0.0   # end time of the LAST evaluation, source clock
    # Worst overall status seen across the evaluations of the call that produced this
    # report (one big block spans many). None on a hand-built report. A call that crosses no
    # evaluation point returns the previous report object unchanged, so this field then
    # still describes that earlier call: read it once per distinct report object.
    worst_since_last_update: WorstQuality | None = None

    @property
    def suppress_events(self) -> bool:
        return suppress_events(self)

    @property
    def bad_during_update(self) -> bool:
        """True when ANY evaluation of the producing call was BAD, not just the last.

        Drop events detected in that call's block when this is true: a bad stretch inside
        a large block is invisible in ``overall`` once it has scrolled past the hysteresis.
        """
        worst = self.worst_since_last_update
        return self.overall is QualityStatus.BAD or (
            worst is not None and worst.status is QualityStatus.BAD
        )

    @property
    def score(self) -> float:
        """Mean channel score; 0.0 with no channels."""
        if not self.channels:
            return 0.0
        return float(np.mean([c.score for c in self.channels]))

    def channel(self, name: str) -> ChannelQuality | None:
        for c in self.channels:
            if c.name == name:
                return c
        return None


def suppress_events(report: QualityReport | None) -> bool:
    """True when detector events must be dropped: no report yet, or overall BAD."""
    return report is None or report.overall is QualityStatus.BAD


# --------------------------------------------------------------------------------------
# Pure metrics. Each takes a 1-D window in µV and returns a plain float.
# --------------------------------------------------------------------------------------


def nonfinite_fraction(x: np.ndarray) -> float:
    """Share of samples that are NaN or infinite."""
    if x.size == 0:
        return 0.0
    return float(1.0 - np.count_nonzero(np.isfinite(x)) / x.size)


def flatline_std(x: np.ndarray) -> float:
    """Standard deviation in µV; near zero means the channel is not moving at all."""
    if x.size == 0:
        return 0.0
    return float(np.std(x))


def robust_sigma(x: np.ndarray) -> float:
    """Gaussian-equivalent sigma from the median absolute deviation (1.4826 x MAD)."""
    if x.size == 0:
        return 0.0
    med = np.median(x)
    return float(1.4826 * np.median(np.abs(x - med)))


def excess_kurtosis(x: np.ndarray) -> float:
    """Excess kurtosis (0 for a Gaussian); 0.0 for a constant window."""
    if x.size < 4:
        return 0.0
    c = x - x.mean()
    m2 = float(np.mean(c * c))
    if m2 <= _EPS:
        return 0.0
    return float(np.mean(c**4) / (m2 * m2) - 3.0)


def saturation_fraction(
    x: np.ndarray, limit_uv: float, adc_limit_uv: float | None = None
) -> float:
    """Share of samples that are railed or beyond ``limit_uv``.

    Counted: ``|x - median| >= limit_uv``; samples within 0.1% of ``adc_limit_uv`` when
    given; and a flat-topped plateau (three or more identical samples) at the window
    maximum or minimum when that plateau sits more than 3 robust sigmas from the median
    or holds at least 2% of the window, which is what clipping looks like and what
    ordinary quantised noise does not.
    """
    n = x.size
    if n == 0:
        return 0.0
    med = float(np.median(x))
    hit = np.abs(x - med) >= limit_uv
    if adc_limit_uv:
        hit |= np.abs(x) >= 0.999 * adc_limit_uv
    sigma = robust_sigma(x)
    if sigma > 0.0:
        for extreme in (float(x.max()), float(x.min())):
            at = np.abs(x - extreme) <= 1e-9 * max(1.0, abs(extreme))
            count = int(np.count_nonzero(at))
            # Far from the centre, or so many samples that quantisation cannot explain it
            # (heavy clipping inflates the robust sigma, so the first test alone misses it).
            if count >= 3 and (abs(extreme - med) > 3.0 * sigma or count / n >= 0.02):
                hit |= at
    return float(np.count_nonzero(hit) / n)


def mains_ratio(
    x: np.ndarray, fs: float, mains_hz: float, half_width_hz: float = 1.0
) -> float:
    """Power within ``mains_hz`` +- half-width as a share of power from 1 Hz to Nyquist.

    Hann-windowed FFT of the whole window. Returns 0.0 when the line is above (or too
    near) Nyquist and so cannot be observed at this sampling rate.
    """
    n = x.size
    if n < 8 or fs <= 0.0:
        return 0.0
    bin_hz = fs / n
    width = max(half_width_hz, 2.0 * bin_hz)   # Hann main lobe is +-2 bins
    if mains_hz + width >= fs / 2.0:
        return 0.0
    seg = (x - x.mean()) * np.hanning(n)
    power = np.abs(np.fft.rfft(seg)) ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    total = float(power[freqs >= 1.0].sum())
    if total <= _EPS:
        return 0.0
    band = float(power[np.abs(freqs - mains_hz) <= width].sum())
    return min(1.0, band / total)


def drift_metrics(x: np.ndarray) -> tuple[float, float]:
    """``(variance share, peak-to-peak µV)`` of a cubic trend fitted to the window."""
    n = x.size
    if n < 16:
        return 0.0, 0.0
    var = float(np.var(x))
    if var <= _EPS:
        return 0.0, 0.0
    t = np.linspace(-1.0, 1.0, n)
    trend = np.polyval(np.polyfit(t, x, 3), t)
    return min(1.0, float(np.var(trend)) / var), float(np.ptp(trend))


def burst_fraction(x: np.ndarray, n_segments: int = 8, factor: float = 5.0) -> float:
    """Share of equal sub-segments whose std exceeds ``factor`` x the median segment std.

    A single blink touches one or two segments; cable sway or a loose electrode touches
    many. Returns 0.0 if the window is too short to split into >= 3 usable segments.
    """
    n_seg = min(n_segments, x.size // 8)
    if n_seg < 3:
        return 0.0
    stds = np.array([np.std(s) for s in np.array_split(x, n_seg)])
    ref = max(float(np.median(stds)), 1e-9)
    return float(np.count_nonzero(stds > factor * ref) / n_seg)


def lead_off_metrics(
    x: np.ndarray,
    fs: float,
    segment_s: float = 0.05,
    flat_uv: float = 0.5,
    min_live_s: float = 0.2,
) -> tuple[float, float]:
    """``(flat tail seconds, step in robust sigmas)`` of an abrupt step then a flat tail.

    The window is cut into short segments aligned to its end. The *tail* is the run of
    trailing segments whose std is at most ``flat_uv`` (nothing is moving); it counts only
    when the live part before it (at least ``min_live_s``, median segment std above
    ``flat_uv``) ends in a level step: the tail mean differs from the median of the last
    few live segment means by the returned number of robust sigmas of the live part. A
    window that is flat throughout, or one that merely goes quiet without a step, returns
    ``(0.0, 0.0)`` and is left to the flatline check. Callers decide how large a step
    counts; the step is returned so it can be reported.
    """
    seg = max(4, int(round(segment_s * fs)))
    n_seg = x.size // seg
    if fs <= 0.0 or n_seg < 8:
        return 0.0, 0.0
    segs = x[x.size - n_seg * seg :].reshape(n_seg, seg)
    sd = segs.std(axis=1)
    mu = segs.mean(axis=1)
    k = 0
    while k < n_seg and sd[n_seg - 1 - k] <= flat_uv:
        k += 1
    live = n_seg - k
    if k == 0 or live < max(4, math.ceil(min_live_s * fs / seg)):
        return 0.0, 0.0
    if float(np.median(sd[:live])) <= flat_uv:
        return 0.0, 0.0
    sigma = max(robust_sigma(segs[:live].ravel()), flat_uv)
    ref = float(np.median(mu[max(0, live - 5) : live]))
    step = abs(float(mu[live:].mean()) - ref) / sigma
    return k * seg / fs, float(step)


def segment_excursions(x: np.ndarray, n_segments: int, factor: float = 4.0) -> np.ndarray:
    """Boolean mask over ``n_segments`` equal pieces: which sit far from the window's level.

    A piece is an excursion when ``|piece mean - median of the quiet pieces' means|`` exceeds
    ``factor`` times the median std of the quiet half of the pieces (the channel's own
    resting noise). Level, not
    variance, so an EMG squeeze (a burst of variance around zero) is not an excursion
    while cable or head movement (a slow shift of the baseline) is. Non-finite samples
    are replaced by the window median first. Returns all-False for a window too short to
    split into 3 pieces of 2 samples.
    """
    n_seg = min(n_segments, x.size // 2)
    if n_seg < 3:
        return np.zeros(max(n_segments, 0), dtype=bool)
    ok = np.isfinite(x)
    if not ok.any():
        return np.zeros(n_seg, dtype=bool)
    clean = np.where(ok, x, np.median(x[ok]))
    parts = np.array_split(clean, n_seg)
    mu = np.array([p.mean() for p in parts])
    sd = np.array([p.std() for p in parts])
    # Reference level and noise come from the QUIET half (piece std at or below the
    # median), so movement that fills up to about half the window cannot drag them along.
    quiet = sd <= np.median(sd)
    ref = max(float(np.median(sd[quiet])), 1e-9)
    return np.abs(mu - float(np.median(mu[quiet]))) > factor * ref


def common_mode_fraction(masks: Sequence[np.ndarray]) -> float:
    """Share of segments flagged on EVERY mask at once (0.0 for fewer than two masks).

    One bad electrode flags its own mask and nobody else's, so it scores zero here; shared
    movement flags the same segments everywhere. Masks of unequal length score 0.0.
    """
    if len(masks) < 2:
        return 0.0
    n = len(masks[0])
    if n == 0 or any(len(m) != n for m in masks):
        return 0.0
    return float(np.count_nonzero(np.logical_and.reduce(masks)) / n)


# --------------------------------------------------------------------------------------
# Grading
# --------------------------------------------------------------------------------------


def _grade(
    value: float,
    degraded: float,
    bad: float | None,
    *,
    lower_is_worse: bool = False,
) -> tuple[QualityStatus, float]:
    """Map a metric to ``(status, penalty)`` with penalty in [0, 1].

    Penalty bands line up with the score bands: GOOD < 0.25, DEGRADED in [0.25, 0.75),
    BAD >= 0.75. ``bad=None`` means the check can degrade but never fail the channel.
    """
    if lower_is_worse:
        assert bad is not None
        if value <= bad:
            return QualityStatus.BAD, 0.75 + 0.25 * min(1.0, (bad - value) / max(bad, _EPS))
        if value <= degraded:
            return QualityStatus.DEGRADED, 0.25 + 0.5 * (degraded - value) / max(degraded - bad, _EPS)
        return QualityStatus.GOOD, 0.0
    if bad is not None and value >= bad:
        return QualityStatus.BAD, 0.75 + 0.25 * min(1.0, (value - bad) / max(bad, _EPS))
    if value >= degraded:
        span = (bad - degraded) if bad is not None else max(degraded, _EPS)
        frac = min(1.0, (value - degraded) / max(span, _EPS))
        return QualityStatus.DEGRADED, 0.25 + 0.5 * frac
    return QualityStatus.GOOD, 0.25 * value / max(degraded, _EPS)


_SEVERITY = {QualityStatus.GOOD: 0, QualityStatus.DEGRADED: 1, QualityStatus.BAD: 2}


# Checks that describe the electrode-skin interface; they alone feed ``contact_score``.
# Packet loss and NaN are transport faults and MOTION is shared movement: none of them is
# evidence about how one electrode is seated.
_CONTACT_REASONS = frozenset(
    {Reason.FLATLINE, Reason.SATURATION, Reason.MAINS, Reason.DRIFT, Reason.NOISE, Reason.LEAD_OFF}
)

_Result = tuple[str, QualityStatus, float]   # (reason, status, penalty)


def assess_channel(
    name: str,
    kind: SignalKind,
    x: np.ndarray,
    fs: float,
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
    *,
    gap_fraction: float = 0.0,
) -> ChannelQuality:
    """Run every check on one channel's window (µV) and return its verdict.

    ``gap_fraction`` is the share of the window lost to packet loss; it is a property of
    the transport, supplied by the caller (the monitor derives it from ``t0``).
    """
    results, metrics, judged = _assess_results(
        kind, x, fs, thresholds, gap_fraction=gap_fraction
    )
    return _assemble(name, results, metrics, judged=judged)


def _assess_results(
    kind: SignalKind,
    x: np.ndarray,
    fs: float,
    thresholds: QualityThresholds,
    *,
    gap_fraction: float,
) -> tuple[list[_Result], dict[str, float], bool]:
    """The per-check results behind :func:`assess_channel`; ``judged`` is False when too
    few finite samples remained to look at the waveform at all."""
    thr = thresholds
    x = np.asarray(x, dtype=np.float64).ravel()
    metrics: dict[str, float] = {}
    results: list[_Result] = []

    nf = nonfinite_fraction(x)
    metrics["nonfinite_frac"] = nf
    metrics["gap_frac"] = gap_fraction
    st, pen = _grade(nf, thr.nonfinite_frac_degraded, thr.nonfinite_frac_bad)
    results.append((Reason.NONFINITE, st, pen))
    st, pen = _grade(gap_fraction, thr.dropout_frac_degraded, thr.dropout_frac_bad)
    results.append((Reason.DROPOUT, st, pen))

    finite = x[np.isfinite(x)]
    if finite.size < thr.min_samples:
        # Cannot judge the waveform at all.
        results.append((Reason.NONFINITE, QualityStatus.BAD, 1.0))
        return results, metrics, False

    std = flatline_std(finite)
    metrics["std_uv"] = std
    st, pen = _grade(std, thr.flat_degraded_uv, thr.flat_bad_uv, lower_is_worse=True)
    results.append((Reason.FLATLINE, st, pen))
    flat_bad = st is QualityStatus.BAD

    sat = saturation_fraction(finite, thr.saturation_limit(kind), thr.adc_limit_uv)
    metrics["saturation_frac"] = sat
    st, pen = _grade(sat, thr.saturation_frac_degraded, thr.saturation_frac_bad)
    results.append((Reason.SATURATION, st, pen))

    if not flat_bad:   # spectral / trend / noise statistics of a dead channel are meaningless
        worst_ratio, worst_hz = 0.0, 0.0
        for hz in thr.mains_hz:
            r = mains_ratio(finite, fs, hz, thr.mains_half_width_hz)
            if r > worst_ratio:
                worst_ratio, worst_hz = r, hz
        metrics["mains_ratio"] = worst_ratio
        metrics["mains_hz"] = worst_hz
        st, pen = _grade(worst_ratio, thr.mains_ratio_degraded, thr.mains_ratio_bad)
        results.append((Reason.MAINS, st, pen))

        # Lead-off first: a step then a flat tail looks like a strong cubic trend, and the
        # drift advice ("let it settle") would be wrong for an electrode that came off.
        flat_s, step_sigma = lead_off_metrics(
            finite, fs, thr.leadoff_segment_s, thr.flat_degraded_uv
        )
        if step_sigma < thr.leadoff_step_sigma:
            flat_s = 0.0
        metrics["leadoff_flat_s"] = flat_s
        metrics["leadoff_step_sigma"] = step_sigma
        st_lo, pen_lo = _grade(flat_s, thr.leadoff_flat_s_degraded, thr.leadoff_flat_s_bad)
        results.append((Reason.LEAD_OFF, st_lo, pen_lo))

        d_ratio, d_p2p = drift_metrics(finite)
        metrics["drift_ratio"] = d_ratio
        metrics["drift_p2p_uv"] = d_p2p
        d_value = d_ratio if d_p2p >= thr.drift_min_p2p_uv else 0.0
        if st_lo is not QualityStatus.GOOD:
            d_value = 0.0   # attributed to the lead-off, not reported twice
        st, pen = _grade(d_value, thr.drift_ratio_degraded, thr.drift_ratio_bad)
        results.append((Reason.DRIFT, st, pen))

        noise_limits = thr.noise_sigma_uv.get(kind)
        if noise_limits is not None:
            sigma = robust_sigma(finite)
            bursts = burst_fraction(finite, thr.burst_segments, thr.burst_factor)
            kurt = excess_kurtosis(finite)
            metrics.update(noise_sigma_uv=sigma, burst_frac=bursts, kurtosis=kurt)
            st, pen = _grade(sigma, noise_limits[0], noise_limits[1])
            st_b, pen_b = _grade(bursts, thr.burst_frac_degraded, None)
            if kurt >= thr.kurtosis_degraded and bursts >= thr.kurtosis_burst_frac:
                st_b, pen_b = QualityStatus.DEGRADED, max(pen_b, 0.5)
            if _SEVERITY[st_b] > _SEVERITY[st]:
                st, pen = st_b, pen_b
            results.append((Reason.NOISE, st, max(pen, pen_b)))

    return results, metrics, True


def _assemble(
    name: str,
    results: list[_Result],
    metrics: dict[str, float],
    *,
    judged: bool = True,
) -> ChannelQuality:
    worst = max((_SEVERITY[s] for _, s, _ in results), default=0)
    status = (QualityStatus.GOOD, QualityStatus.DEGRADED, QualityStatus.BAD)[worst]
    # Report the checks that caused the verdict: the failing ones at the worst level, then
    # the milder ones, without duplicates, worst first.
    reasons: list[str] = []
    for sev in (2, 1):
        for reason, s, _ in results:
            if _SEVERITY[s] == sev and reason not in reasons:
                reasons.append(reason)
    max_pen = max((p for _, _, p in results), default=0.0)
    score = float(min(1.0, max(0.0, 1.0 - max_pen)))
    if status is QualityStatus.BAD:
        score = min(score, 0.25 - 1e-9)
    # Contact: the same arithmetic over the interface checks only. Nothing to look at
    # (too few valid samples) means no evidence of contact at all.
    if judged:
        contact_pen = max((p for r, _, p in results if r in _CONTACT_REASONS), default=0.0)
        contact = float(min(1.0, max(0.0, 1.0 - contact_pen)))
    else:
        contact = 0.0
    metrics = dict(metrics)
    metrics["contact_score"] = contact
    return ChannelQuality(name, status, tuple(reasons), score, metrics, contact)


# --------------------------------------------------------------------------------------
# Streaming monitor
# --------------------------------------------------------------------------------------


def _worst_reasons(report: QualityReport) -> tuple[str, ...]:
    """Montage reasons then those of every non-GOOD channel, de-duplicated, in order."""
    out: list[str] = list(report.reasons)
    for ch in report.channels:
        if ch.status is QualityStatus.GOOD:
            continue
        for r in ch.reasons:
            if r not in out:
                out.append(r)
    return tuple(out)


@dataclass
class _ChannelState:
    """Hysteresis state of one channel. Starts BAD: nothing is trusted before it is judged."""

    status: QualityStatus = QualityStatus.BAD
    ok_streak: int = 0
    bad_streak: int = 0


class SignalQualityMonitor:
    """Sliding-window quality judge with hysteresis.

    Feed blocks in time order with :meth:`update`; it returns the current
    :class:`QualityReport`. Evaluations sit on a fixed grid of ``hop_s`` of signal (the
    first at ``min_fill_s``) and a call runs every grid point its block spans, so a 12 s
    block is judged hop by hop exactly like 48 blocks of 0.25 s would be. A call that
    crosses no grid point returns the previous report object, so it is cheap enough to
    call on every block. Cost grows linearly with the block length (one window assessment
    per hop per channel). The monitor is not thread-safe.
    """

    def __init__(self, thresholds: QualityThresholds | None = None) -> None:
        self.thresholds = thresholds or DEFAULT_THRESHOLDS
        self._fs = 0.0
        self._channels: tuple[tuple[str, SignalKind], ...] = ()
        self._buf = np.empty((0, 0), dtype=np.float64)
        self._states: list[_ChannelState] = []
        self._gaps: deque[tuple[float, float]] = deque()   # (gap end time, gap length s)
        self._expected_t = 0.0
        self._last_t0 = 0.0
        self._have_clock = False
        self._pos = 0            # samples seen since the buffer was last cleared
        self._next_eval = 0      # absolute ``_pos`` of the next evaluation point
        self._evaluated = False
        self._report: QualityReport | None = None

    # -- public ---------------------------------------------------------------------

    @property
    def report(self) -> QualityReport | None:
        """The latest report, or None before the first :meth:`update`."""
        return self._report

    @property
    def suppress_events(self) -> bool:
        """True until the signal has been judged usable, and whenever it is not."""
        return suppress_events(self._report)

    def reset(self) -> None:
        """Forget everything; the next block starts a fresh warm-up."""
        self._fs = 0.0
        self._channels = ()
        self._buf = np.empty((0, 0), dtype=np.float64)
        self._states = []
        self._gaps.clear()
        self._expected_t = 0.0
        self._last_t0 = 0.0
        self._have_clock = False
        self._pos = 0
        self._next_eval = 0
        self._evaluated = False
        self._report = None

    def update(self, block: SampleBlock) -> QualityReport:
        """Ingest a block and return the report of its LAST evaluation.

        Every evaluation point inside the block is judged in order, each on the window that
        ended there, so hysteresis is exact for any block size. The returned report's
        ``t`` and reasons are the last evaluation's; ``worst_since_last_update`` carries
        the worst overall status across all of them.
        """
        thr = self.thresholds
        data = np.asarray(block.data, dtype=np.float64)
        if data.ndim == 1:
            data = data.reshape(1, -1)
        if data.ndim != 2 or data.shape[0] != len(block.channels):
            raise ValueError(
                f"block.data must be (n_channels, n_samples) matching {len(block.channels)} "
                f"channels, got shape {data.shape}"
            )
        if block.fs <= 0:
            raise ValueError("block.fs must be positive")

        layout = tuple((c.name, c.kind) for c in block.channels)
        if layout != self._channels or block.fs != self._fs:
            self.reset()
            self._channels = layout
            self._fs = float(block.fs)
            self._buf = np.empty((len(layout), 0), dtype=np.float64)
            self._states = [_ChannelState() for _ in layout]

        n = data.shape[1]
        fs = self._fs
        t_end = block.t0 + n / fs
        if n == 0:
            return self._report or self._warmup_report(t_end)

        self._track_gap(block.t0, n, fs)

        cap = max(1, math.ceil(thr.window_s * fs))
        min_fill = min(cap, max(1, math.ceil(thr.min_fill_s * fs)))
        hop = max(1, round(thr.hop_s * fs))
        if self._pos == 0:
            self._next_eval = min_fill   # fresh start, or the buffer was just cleared

        base = self._pos - self._buf.shape[1]   # absolute position of full[:, 0]
        full = np.concatenate([self._buf, data], axis=1)
        self._pos += n
        self._buf = full[:, -cap:]

        report: QualityReport | None = None
        worst: QualityReport | None = None
        count = 0
        while self._next_eval <= self._pos:
            e = self._next_eval
            self._next_eval += hop
            window = full[:, max(0, e - base - cap) : e - base]
            t_eval = t_end - (self._pos - e) / fs
            report = self._evaluate(window, t_eval)
            count += 1
            if worst is None or _SEVERITY[report.overall] >= _SEVERITY[worst.overall]:
                worst = report
        self._prune_gaps(t_end)

        if report is None or worst is None:
            if self._evaluated and self._report is not None:
                return self._report   # no grid point crossed: nothing new was judged
            self._report = self._warmup_report(t_end)
            return self._report
        self._evaluated = True
        self._report = replace(
            report,
            worst_since_last_update=WorstQuality(
                worst.overall, _worst_reasons(worst), worst.t, count
            ),
        )
        return self._report

    # -- internals ------------------------------------------------------------------

    def _track_gap(self, t0: float, n: int, fs: float) -> None:
        """Record packet loss from ``t0`` continuity. A source that never sets ``t0``
        (always 0.0) is treated as gap-free rather than as one endless jump."""
        thr = self.thresholds
        no_clock = t0 == 0.0 and self._last_t0 == 0.0
        if self._have_clock and not no_clock:
            gap = t0 - self._expected_t
            if gap > max(thr.gap_tolerance_s, 2.0 / fs):
                self._gaps.append((t0, gap))
                if gap >= thr.window_s:   # everything buffered is stale
                    self._buf = np.empty((len(self._channels), 0), dtype=np.float64)
                    self._pos = 0
                    self._next_eval = 0
                    self._evaluated = False
                    for st in self._states:
                        st.status, st.ok_streak, st.bad_streak = QualityStatus.BAD, 0, 0
            # A negative gap (overlap / replay) is ignored rather than trusted.
        self._expected_t = t0 + n / fs
        self._last_t0 = t0
        self._have_clock = True

    def _prune_gaps(self, t_end: float) -> None:
        # Pruned after the evaluations of a call, not before: an evaluation inside a big
        # block must still see the gaps that were in ITS window.
        horizon = t_end - self.thresholds.window_s
        while self._gaps and self._gaps[0][0] <= horizon:
            self._gaps.popleft()

    def _dropout_fraction(self, t: float | None = None) -> float:
        """Share of the window ending at ``t`` (default: now) lost to packet loss."""
        win = self.thresholds.window_s
        if t is None:
            lost = sum(length for _, length in self._gaps)
        else:
            lost = sum(length for end, length in self._gaps if t - win < end <= t)
        return float(min(1.0, lost / win))

    def _warmup_report(self, t_end: float) -> QualityReport:
        have = self._buf.shape[1] / self._fs if self._fs else 0.0
        chans = tuple(
            ChannelQuality(
                name,
                QualityStatus.BAD,
                (Reason.WARMING_UP,),
                0.0,
                {"buffered_s": have, "needed_s": self.thresholds.min_fill_s},
                0.0,
            )
            for name, _ in self._channels
        )
        return QualityReport(
            chans,
            QualityStatus.BAD,
            (),
            (Reason.WARMING_UP,),
            dropout_fraction=self._dropout_fraction(),
            t=t_end,
            worst_since_last_update=WorstQuality(
                QualityStatus.BAD, (Reason.WARMING_UP,), t_end, 0
            ),
        )

    def _evaluate(self, window: np.ndarray, t_eval: float) -> QualityReport:
        thr = self.thresholds
        gap_frac = self._dropout_fraction(t_eval)
        assessed = [
            _assess_results(kind, window[i], self._fs, thr, gap_fraction=gap_frac)
            for i, (_, kind) in enumerate(self._channels)
        ]
        motion = self._common_mode(window, assessed)
        smoothed: list[ChannelQuality] = []
        for i, (name, _) in enumerate(self._channels):
            results, metrics, judged = assessed[i]
            if motion is not None and i in motion[0]:
                self._attribute_motion(results, motion[1], motion[2])
            raw = _assemble(name, results, metrics, judged=judged)
            smoothed.append(self._apply_hysteresis(self._states[i], raw))

        usable = tuple(c.name for c in smoothed if c.status is not QualityStatus.BAD)
        missing = tuple(r for r in thr.required_channels if r not in usable)
        reasons: list[str] = []
        if len(usable) < thr.min_usable_channels:
            overall = QualityStatus.BAD
            reasons.append(Reason.TOO_FEW_CHANNELS)
        elif missing:
            overall = QualityStatus.BAD
            reasons.append(Reason.REQUIRED_MISSING)
        elif any(c.status is not QualityStatus.GOOD for c in smoothed):
            overall = QualityStatus.DEGRADED
        else:
            overall = QualityStatus.GOOD
        if any(Reason.MOTION in c.reasons for c in smoothed):
            reasons.append(Reason.MOTION)
        return QualityReport(
            tuple(smoothed),
            overall,
            usable,
            tuple(reasons),
            missing,
            gap_frac,
            t_eval,
        )

    def _common_mode(
        self,
        window: np.ndarray,
        assessed: list[tuple[list[_Result], dict[str, float], bool]],
    ) -> tuple[set[int], QualityStatus, float] | None:
        """Common-mode movement across the judgeable channels, or None.

        Judgeable = enough finite samples and not flat: a dead channel cannot witness
        movement, and with only one witness left the cause cannot be told from a single bad
        electrode, so nothing is attributed. Returns ``(channel indices, status, penalty)``
        only when the share of segments hit on all of them reaches the degraded level; the
        share itself is stored as the ``motion_frac`` metric of each judged channel.
        """
        thr = self.thresholds
        idx = [
            i
            for i, (_, m, judged) in enumerate(assessed)
            if judged and m.get("std_uv", 0.0) > thr.flat_bad_uv
        ]
        if len(idx) < thr.motion_min_channels:
            return None
        n_seg = max(3, round(window.shape[1] / max(1.0, thr.motion_segment_s * self._fs)))
        masks = [segment_excursions(window[i], n_seg, thr.motion_level_factor) for i in idx]
        frac = common_mode_fraction(masks)
        st, pen = _grade(frac, thr.motion_frac_degraded, thr.motion_frac_bad)
        for i in idx:
            assessed[i][1]["motion_frac"] = frac
        if st is QualityStatus.GOOD:
            return None
        return set(idx), st, pen

    @staticmethod
    def _attribute_motion(
        results: list[_Result], status: QualityStatus, penalty: float
    ) -> None:
        """Blame shared movement instead of this electrode.

        When every judgeable electrode was disturbed at the same moments, a NOISE verdict
        on one of them is the movement, not a loose electrode: it is folded into the
        MOTION result, which keeps the harsher of the two so attribution never makes the
        verdict more lenient, and the advice names the real cause.
        """
        for r in results:
            if r[0] == Reason.NOISE and (_SEVERITY[r[1]], r[2]) > (_SEVERITY[status], penalty):
                status, penalty = r[1], r[2]
        results[:] = [r for r in results if r[0] != Reason.NOISE]
        results.append((Reason.MOTION, status, penalty))

    def _apply_hysteresis(self, state: _ChannelState, raw: ChannelQuality) -> ChannelQuality:
        thr = self.thresholds
        if state.status is QualityStatus.BAD:
            if raw.status is QualityStatus.BAD:
                state.ok_streak = 0
                return raw
            state.ok_streak += 1
            if state.ok_streak >= thr.recover_windows:
                state.status, state.ok_streak, state.bad_streak = raw.status, 0, 0
                return raw
            metrics = dict(raw.metrics)
            metrics["clean_windows"] = float(state.ok_streak)
            metrics["clean_windows_needed"] = float(thr.recover_windows)
            return ChannelQuality(
                raw.name,
                QualityStatus.BAD,
                (Reason.RECOVERING,),
                min(raw.score, 0.2),
                metrics,
                raw.contact_score,
            )
        if raw.status is QualityStatus.BAD:
            state.bad_streak += 1
            if state.bad_streak >= thr.enter_windows:
                state.status, state.ok_streak, state.bad_streak = QualityStatus.BAD, 0, 0
                return raw
            return ChannelQuality(
                raw.name,
                QualityStatus.DEGRADED,
                raw.reasons,
                min(raw.score, 0.5),
                raw.metrics,
                raw.contact_score,
            )
        state.bad_streak = 0
        state.status = raw.status
        return raw


# --------------------------------------------------------------------------------------
# Plain-language explanations for a doctor / CLI command
# --------------------------------------------------------------------------------------


_MAX_EXPLAIN_LINES = 6


def _fix_text(
    reason: str, ch: ChannelQuality, report: QualityReport, tag: str = ""
) -> str | None:
    """One actionable sentence for one problem on one channel.

    ``tag`` (the channel's contact score, on its first line only) goes right after the name.
    Deliberately no raw amplitudes: they are the user's biosignal, and the sentence is
    meant to be pasted into a bug report. Shares of a window (clipped samples, hum power)
    are fine, they cannot be turned back into a waveform.
    """
    name, m = ch.name, ch.metrics
    who = f"channel {name}{tag}"
    bad = ch.status is QualityStatus.BAD
    if reason == Reason.FLATLINE:
        return (
            f"{who} is flat — check the electrode contact and that the lead is "
            "plugged into the right pin of the board"
        )
    if reason == Reason.LEAD_OFF:
        return (
            f"{who} jumped and then went flat, as when an electrode lifts or pops off — "
            "press it back on, check the clip or snap, and wipe the skin dry first"
        )
    if reason == Reason.SATURATION:
        return (
            f"{who} is {'railing' if bad else 'touching its limits'} "
            f"({m.get('saturation_frac', 0.0):.1%} of samples clipped) — the electrode is "
            "probably loose or has lost gel contact; re-seat it, clean and lightly moisten "
            "the skin, and check the gain setting"
        )
    if reason == Reason.MAINS:
        hz = m.get("mains_hz", 0.0)
        hum = f"{hz:g} Hz mains hum" if hz else "mains hum"
        return (
            f"{who} is dominated by {hum} ({m.get('mains_ratio', 0.0):.0%} of its "
            "power) — keep leads short and away from chargers and power adapters, check the "
            "reference/ground electrode contact, and run a laptop on battery to test"
        )
    if reason == Reason.DRIFT:
        return (
            f"{who} has a slowly wandering baseline — the electrode is settling or "
            "moving, or the gel is drying; let it settle, secure the lead, and avoid pulling "
            "on the cable"
        )
    if reason == Reason.NOISE:
        return (
            f"{who} shows large erratic noise — likely a loose electrode or a "
            "swaying cable; secure the cable to clothing, re-seat the electrode, and keep "
            "still while it recovers"
        )
    if reason == Reason.NONFINITE:
        if m.get("std_uv") is None:
            return (
                f"{who} has too few valid samples (NaN or missing values from the "
                "device) — check the cable and driver, then reconnect the board"
            )
        return (
            f"{who} delivers invalid (NaN) samples — check the cable and driver, "
            "then reconnect the board"
        )
    if reason == Reason.RECOVERING:
        got, need = m.get("clean_windows", 0.0), m.get("clean_windows_needed", 0.0)
        return (
            f"{who} looks clean again but is held back until it stays clean "
            f"({got:.0f}/{need:.0f} checks) — hold still for a moment"
        )
    if reason == Reason.WARMING_UP:
        return None   # reported once, at montage level
    return None   # DROPOUT and MOTION are reported once, at montage level


def _motion_text(report: QualityReport) -> str:
    hit = [c.name for c in report.channels if Reason.MOTION in c.reasons]
    names = ", ".join(hit)
    return (
        f"channels {names} were disturbed at the same moments — that is head, jaw or cable "
        "movement rather than one bad electrode; keep still, and secure the cable to your "
        "clothing so it cannot swing"
    )


def explain(report: QualityReport) -> list[str]:
    """Plain-language findings and fixes, most important first, at most 6 lines.

    One line per (channel, problem), grouped by channel with the worst channel first; the
    first line of a non-GOOD channel carries its contact score. Movement that hit every
    channel at once and packet loss are link/body properties and get one line each. When
    there are more problems than room, the last line names the channels it left out. No raw
    amplitudes appear (privacy rule). Intended for a doctor/CLI command.
    """
    lines: list[str] = []
    if report.overall is QualityStatus.GOOD:
        lines.append(
            f"Signal quality is good on all {len(report.channels)} channel(s); "
            "detectors are active."
        )
        return lines

    if Reason.WARMING_UP in report.reasons:
        need = next(
            (c.metrics.get("needed_s", 0.0) for c in report.channels if c.metrics), 0.0
        )
        lines.append(
            f"Collecting signal to judge its quality (about {need:g} s); detectors stay "
            "paused until then."
        )
        return lines

    if report.overall is QualityStatus.BAD:
        lines.append("Signal is not usable right now: detector events are being dropped.")
    else:
        lines.append(
            "Signal is usable but degraded: expect more false triggers or missed events."
        )
    if Reason.TOO_FEW_CHANNELS in report.reasons:
        lines.append(
            f"Only {len(report.usable_channels)} of {len(report.channels)} channel(s) are "
            "usable; fix the channels below."
        )
    if report.missing_required:
        lines.append(
            "Required channel(s) unusable: " + ", ".join(report.missing_required) + "."
        )

    ordered = sorted(
        report.channels, key=lambda c: (-_SEVERITY[c.status], c.score)
    )
    problems: list[tuple[str, str]] = []   # (channel name, sentence)
    seen_dropout = False
    if Reason.MOTION in report.reasons:
        # The shared cause comes first: it explains the channel lines that follow.
        first = next(c.name for c in report.channels if Reason.MOTION in c.reasons)
        problems.append((first, _motion_text(report)))
    for ch in ordered:
        if ch.status is QualityStatus.GOOD:
            continue
        tag = f" (contact {ch.contact_score:.0%})"
        for reason in ch.reasons:
            if reason == Reason.DROPOUT:
                seen_dropout = True
                continue
            if reason == Reason.MOTION:
                continue   # one montage-level line, already added above
            text = _fix_text(reason, ch, report, tag)
            if text:
                problems.append((ch.name, text))
                tag = ""
    link: str | None = None
    if seen_dropout or report.dropout_fraction >= (
        DEFAULT_THRESHOLDS.dropout_frac_degraded
    ):
        link = (
            f"The data link is losing samples ({report.dropout_fraction:.0%} of the last "
            "window missing) — move the receiver closer, use a USB extension to keep the "
            "dongle away from the computer, and avoid a crowded 2.4 GHz band"
        )
    room = _MAX_EXPLAIN_LINES - len(lines) - (1 if link else 0)
    if len(problems) > room:
        shown = problems[: max(0, room - 1)]
        left_out = list(dict.fromkeys(n for n, _ in problems[len(shown):]))
        lines.extend(t for _, t in shown)
        lines.append(
            f"…and {len(problems) - len(shown)} more problem(s) on channel(s) "
            + ", ".join(left_out)
            + " — fix the ones above first."
        )
    else:
        lines.extend(t for _, t in problems)
    if link:
        lines.append(link)
    return lines[:_MAX_EXPLAIN_LINES]
