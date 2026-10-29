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
========== ===========================================================================

Each check returns a value, a status and a penalty; the channel status is the worst of
them and the score is ``1 - max(penalty)``. Score bands: GOOD >= 0.75, DEGRADED in
[0.25, 0.75), BAD < 0.25.

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

Pure logic: numpy + stdlib only, no I/O, no threads. Feed it :class:`SampleBlock` s in
order via :meth:`SignalQualityMonitor.update`.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
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
    "assess_channel",
    "burst_fraction",
    "drift_metrics",
    "excess_kurtosis",
    "explain",
    "flatline_std",
    "mains_ratio",
    "nonfinite_fraction",
    "robust_sigma",
    "saturation_fraction",
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

    def __post_init__(self) -> None:
        if self.window_s <= 0 or self.hop_s <= 0 or self.min_fill_s <= 0:
            raise ValueError("window_s, hop_s and min_fill_s must be positive")
        if self.min_fill_s > self.window_s:
            raise ValueError("min_fill_s cannot exceed window_s")
        if self.recover_windows < 1 or self.enter_windows < 1:
            raise ValueError("recover_windows and enter_windows must be >= 1")
        if self.flat_bad_uv > self.flat_degraded_uv:
            raise ValueError("flat_bad_uv must be <= flat_degraded_uv (lower is worse)")

    def saturation_limit(self, kind: SignalKind) -> float:
        return float(self.saturation_uv.get(kind, math.inf))


DEFAULT_THRESHOLDS = QualityThresholds()


@dataclass(frozen=True)
class ChannelQuality:
    """Verdict for one channel. ``metrics`` holds the raw numbers behind it."""

    name: str
    status: QualityStatus
    reasons: tuple[str, ...] = ()
    score: float = 1.0
    metrics: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityReport:
    """Verdict for the whole montage at one moment."""

    channels: tuple[ChannelQuality, ...]
    overall: QualityStatus
    usable_channels: tuple[str, ...]
    reasons: tuple[str, ...] = ()
    missing_required: tuple[str, ...] = ()
    dropout_fraction: float = 0.0
    t: float = 0.0   # end time of the newest sample, source clock

    @property
    def suppress_events(self) -> bool:
        return suppress_events(self)

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
    thr = thresholds
    x = np.asarray(x, dtype=np.float64).ravel()
    metrics: dict[str, float] = {}
    results: list[tuple[str, QualityStatus, float]] = []   # (reason, status, penalty)

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
        return _assemble(name, results, metrics)

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

        d_ratio, d_p2p = drift_metrics(finite)
        metrics["drift_ratio"] = d_ratio
        metrics["drift_p2p_uv"] = d_p2p
        d_value = d_ratio if d_p2p >= thr.drift_min_p2p_uv else 0.0
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

    return _assemble(name, results, metrics)


def _assemble(
    name: str,
    results: list[tuple[str, QualityStatus, float]],
    metrics: dict[str, float],
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
    return ChannelQuality(name, status, tuple(reasons), score, dict(metrics))


# --------------------------------------------------------------------------------------
# Streaming monitor
# --------------------------------------------------------------------------------------


@dataclass
class _ChannelState:
    """Hysteresis state of one channel. Starts BAD: nothing is trusted before it is judged."""

    status: QualityStatus = QualityStatus.BAD
    ok_streak: int = 0
    bad_streak: int = 0


class SignalQualityMonitor:
    """Sliding-window quality judge with hysteresis.

    Feed blocks in time order with :meth:`update`; it returns the current
    :class:`QualityReport`. At most one evaluation happens per ``hop_s`` of new signal
    (and per call); calls in between return the previous report, so it is cheap enough
    to call on every block. The monitor is not thread-safe.
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
        self._since_eval = 0
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
        self._since_eval = 0
        self._evaluated = False
        self._report = None

    def update(self, block: SampleBlock) -> QualityReport:
        """Ingest a block and return the current report."""
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
        self._buf = np.concatenate([self._buf, data], axis=1)[:, -cap:]
        self._since_eval += n

        min_fill = min(cap, max(1, math.ceil(thr.min_fill_s * fs)))
        if self._buf.shape[1] < min_fill:
            self._evaluated = False
            self._report = self._warmup_report(t_end)
            return self._report

        hop = max(1, round(thr.hop_s * fs))
        if self._evaluated and self._report is not None and self._since_eval < hop:
            return self._report

        self._since_eval = 0
        self._evaluated = True
        self._report = self._evaluate(t_end)
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
                    self._since_eval = 0
                    self._evaluated = False
                    for st in self._states:
                        st.status, st.ok_streak, st.bad_streak = QualityStatus.BAD, 0, 0
            # A negative gap (overlap / replay) is ignored rather than trusted.
        self._expected_t = t0 + n / fs
        self._last_t0 = t0
        self._have_clock = True
        horizon = self._expected_t - thr.window_s
        while self._gaps and self._gaps[0][0] <= horizon:
            self._gaps.popleft()

    def _dropout_fraction(self) -> float:
        lost = sum(length for _, length in self._gaps)
        return float(min(1.0, lost / self.thresholds.window_s))

    def _warmup_report(self, t_end: float) -> QualityReport:
        have = self._buf.shape[1] / self._fs if self._fs else 0.0
        chans = tuple(
            ChannelQuality(
                name,
                QualityStatus.BAD,
                (Reason.WARMING_UP,),
                0.0,
                {"buffered_s": have, "needed_s": self.thresholds.min_fill_s},
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
        )

    def _evaluate(self, t_end: float) -> QualityReport:
        thr = self.thresholds
        gap_frac = self._dropout_fraction()
        smoothed: list[ChannelQuality] = []
        for i, (name, kind) in enumerate(self._channels):
            raw = assess_channel(
                name, kind, self._buf[i], self._fs, thr, gap_fraction=gap_frac
            )
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
        return QualityReport(
            tuple(smoothed),
            overall,
            usable,
            tuple(reasons),
            missing,
            gap_frac,
            t_end,
        )

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
            )
        if raw.status is QualityStatus.BAD:
            state.bad_streak += 1
            if state.bad_streak >= thr.enter_windows:
                state.status, state.ok_streak, state.bad_streak = QualityStatus.BAD, 0, 0
                return raw
            return ChannelQuality(
                raw.name, QualityStatus.DEGRADED, raw.reasons, min(raw.score, 0.5), raw.metrics
            )
        state.bad_streak = 0
        state.status = raw.status
        return raw


# --------------------------------------------------------------------------------------
# Plain-language explanations for a doctor / CLI command
# --------------------------------------------------------------------------------------


def _fix_text(reason: str, ch: ChannelQuality, report: QualityReport) -> str | None:
    name, m = ch.name, ch.metrics
    bad = ch.status is QualityStatus.BAD
    if reason == Reason.FLATLINE:
        return (
            f"channel {name} is flat — check the electrode contact and that the lead is "
            "plugged into the right pin of the board"
        )
    if reason == Reason.SATURATION:
        return (
            f"channel {name} is {'railing' if bad else 'touching its limits'} "
            f"({m.get('saturation_frac', 0.0):.1%} of samples clipped) — the electrode is "
            "probably loose or has lost gel contact; re-seat it, clean and lightly moisten "
            "the skin, and check the gain setting"
        )
    if reason == Reason.MAINS:
        hz = m.get("mains_hz", 0.0)
        hum = f"{hz:g} Hz mains hum" if hz else "mains hum"
        return (
            f"channel {name} is dominated by {hum} ({m.get('mains_ratio', 0.0):.0%} of its "
            "power) — keep leads short and away from chargers and power adapters, check the "
            "reference/ground electrode contact, and run a laptop on battery to test"
        )
    if reason == Reason.DRIFT:
        return (
            f"channel {name} has a slowly wandering baseline "
            f"({m.get('drift_p2p_uv', 0.0):.0f} µV drift) — the electrode is settling or "
            "moving, or the gel is drying; let it settle, secure the lead, and avoid pulling "
            "on the cable"
        )
    if reason == Reason.NOISE:
        return (
            f"channel {name} shows large erratic noise — likely a loose electrode or a "
            "swaying cable; secure the cable to clothing, re-seat the electrode, and keep "
            "still while it recovers"
        )
    if reason == Reason.NONFINITE:
        if m.get("std_uv") is None:
            return (
                f"channel {name} has too few valid samples (NaN or missing values from the "
                "device) — check the cable and driver, then reconnect the board"
            )
        return (
            f"channel {name} delivers invalid (NaN) samples — check the cable and driver, "
            "then reconnect the board"
        )
    if reason == Reason.RECOVERING:
        got, need = m.get("clean_windows", 0.0), m.get("clean_windows_needed", 0.0)
        return (
            f"channel {name} looks clean again but is held back until it stays clean "
            f"({got:.0f}/{need:.0f} checks) — hold still for a moment"
        )
    if reason == Reason.WARMING_UP:
        return None   # reported once, at montage level
    return None   # DROPOUT is a transport property, reported once, at montage level


def explain(report: QualityReport) -> list[str]:
    """Plain-language findings and fixes, most important first.

    One line per (channel, problem), plus one line each for packet loss and warm-up
    (which belong to the link, not to a channel). Intended for a doctor/CLI command.
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
    seen_dropout = False
    for ch in ordered:
        if ch.status is QualityStatus.GOOD:
            continue
        for reason in ch.reasons:
            if reason == Reason.DROPOUT:
                seen_dropout = True
                continue
            text = _fix_text(reason, ch, report)
            if text:
                lines.append(text)
    if seen_dropout or report.dropout_fraction >= (
        DEFAULT_THRESHOLDS.dropout_frac_degraded
    ):
        lines.append(
            f"The data link is losing samples ({report.dropout_fraction:.0%} of the last "
            "window missing) — move the receiver closer, use a USB extension to keep the "
            "dongle away from the computer, and avoid a crowded 2.4 GHz band"
        )
    return lines
