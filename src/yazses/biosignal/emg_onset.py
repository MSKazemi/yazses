"""Streaming EMG onset/offset detection: a one-muscle switch with explicit guards.

``platform/emg/pressure.py`` answers "how hard is the muscle squeezed?" for one
envelope reading at a time. This module is the missing front half for a *stream*: raw
multichannel EMG blocks in, ``SQUEEZE_ON`` / ``SQUEEZE_OFF`` events out, with every way
a surface-EMG switch is known to misfire handled by a named, tunable guard.

## What it computes

0. **Artifact stage** (before everything else, on the raw samples, see "Artifact stage"
   below): a step, a pop or a saturation blanks the detector for a settle time.
1. **Band-limit** each EMG-kind channel (second-order high-pass + low-pass, block-
   continuous). This strips the baseline wander and DC offset of a shifting electrode
   and the out-of-band noise that the Teager operator would otherwise amplify.
2. **TKEO**, ψ(x[n]) = x[n]² − x[n−1]·x[n+1] (the operator defined in ``pressure.py``),
   carried across block boundaries so a block edge never invents an energy value.
3. **Rectify and smooth per channel**: the rectified TKEO (the operator can go slightly
   negative on noise, so it is rectified first, exactly as ``pressure.envelope`` does) is
   smoothed with a short causal moving average (default 30 ms) *separately for each channel*,
   so the channels can be compared before they are combined.
4. **Combine** channels: the mean of the per-channel envelopes (mean and moving average
   commute, so this is the same envelope as smoothing the mean). Averaging makes one noisy
   electrode less able to trigger the switch alone — and a dead flat channel dilutes the
   mean, so wire only channels that carry signal.
5. **Decide** with a double-threshold (hysteresis) state machine, gated by channel agreement.

Everything is sample-by-sample recursion or a carried tail, so the output is identical
for any block size — one block of an hour or a thousand blocks of 100 ms.

## The 35–125 ms onset window

Classical threshold/TKEO onset detectors land at **35–125 ms**
(Liu, Ying, Rymer & Zhou, PLOS ONE 2015 — see ``docs/research/muscle-brain-control.md``),
faster than human reaction time, which is why a muscle can serve as a trigger at all.
The budget here is spent deliberately. A moving average smears a burst by its own
length, so the confirmation wait is ``min_burst_s`` (40 ms default, the figure
``pressure.py`` uses for its hold) *plus* the smoothing window (30 ms): that is how long
the envelope must stay up for a physical burst of ``min_burst_s`` to be believed.
Add the smoothing group delay (half the window, 15 ms) and the default lands near
85 ms, inside the window. Each ``SQUEEZE_ON`` carries ``detail['latency_ms']``: an
*estimate* of the time from physical onset to the event, equal to that wait plus the
group delay (the band-pass filter's own group delay is not included).

## The guards, and why each exists

* **Hysteresis (``k_on`` > ``k_off``)** — one threshold chatters when the envelope sits
  on it. The switch turns on high and turns off lower, so noise on the edge cannot
  toggle it.
* **Minimum burst (``min_burst_s``)** — a cable knock or an ADC glitch is a spike, not a
  contraction. A physical burst must last this long (plus the smoothing smear, see
  above) above the *off* level before it is believed; a shorter one is silently rejected (counted in ``rejected_bursts``).
* **Merge gap (``merge_gap_s``)** — a sustained squeeze flickers: the envelope dips for
  a few samples mid-hold. Releasing only after the envelope stays below the off level
  for this long keeps one squeeze from becoming several. It adds this much to the
  release latency, which is the price of not cutting the microphone mid-sentence.
* **Refractory (``refractory_s``)** — right after a release the muscle rebounds and the
  envelope rings. A hold-off after ``SQUEEZE_OFF`` stops the tail of one squeeze from
  starting the next.
* **Adaptive baseline** — skin conductance, sweat and electrode drift move the relaxed
  noise floor during a session. The baseline follows it slowly (``baseline_tau_s``),
  but only from samples that are clearly relaxed (below the off level) and only while
  idle, and it is clamped to a multiple of its calibrated value so it cannot wander
  away on its own. It **freezes** while a squeeze is pending, active, ending, or
  stuck: if it adapted during a long hold, the hold would raise its own threshold and
  the switch would release a muscle that is still contracted.
* **Maximum-hold watchdog (``max_hold_s``)** — a lifted electrode or a failed contact
  can read "squeezed" forever. After this long the detector forces ``SQUEEZE_OFF``
  (``detail['reason'] == 'max_hold'``) so a stuck sensor cannot hold the microphone open
  indefinitely, then enters a *stuck* state and stays silent until the envelope has
  been below the off level for ``STUCK_CLEAR_S``. Without that latch a stuck sensor
  would simply re-arm and re-trigger after each refractory period. A permanently stuck
  signal therefore stays silent until ``reset()`` or recalibration; it is never
  silently adopted as the new "relaxed".
* **Channel agreement (``min_channel_fraction``)** — the mean envelope can be pushed over the
  on level by one channel alone (a bad electrode, a cable tug on one lead, motion at one
  site). With several EMG channels a burst may therefore only *start* (and be confirmed)
  while at least this fraction of the channels individually exceed the on level
  (``ceil``-style: ``count >= fraction * n_channels``); a burst that the mean sees but the
  channels do not agree on is dropped, counted in ``stats['rejected_disagreement']`` and
  never emitted. A single-channel setup is unaffected (one channel is always in
  agreement). Design choice, not a measured operating point: with the default 0.5, two
  channels need one over the on level (it does not protect a 2-channel montage from a
  single bad electrode: use ``1.0`` for that) and four channels need two. The vote is
  taken at burst start and confirmation only; once a squeeze is open the mean envelope
  alone decides when it ends, so a good squeeze is not cut by one channel dropping out.
* **Artifact blanking (``settle_after_step_s``)** — see "Artifact stage".
* **Discontinuity** — a forward jump in ``SampleBlock.t0`` means samples were lost. The
  detector closes any open squeeze (``reason == 'gap'``) and restarts its filters
  rather than carry state across data it never saw.

## Artifact stage

A large DC step (electrode shift, cable tug), a pop, or a saturated amplifier is not a
contraction, but the second-order high-pass *rings* on it and the Teager operator squares
that ring, so without a guard it crosses the on level for tens of milliseconds and, with
the smoothing smear, can pass the minimum-burst test: a phantom ``SQUEEZE_ON`` /
``SQUEEZE_OFF`` pair. A real switch must not do that, so the raw samples (per channel,
before the filters) are checked for three things:

* **jump** — one sample-to-sample jump larger than ``jump_ratio`` times the RMS of the
  preceding ``jump_context_s`` of sample-to-sample differences (a robust, median-based
  estimate, floored at the relaxed
  noise level, ``sqrt(2 * sqrt(baseline))``) *and* followed by calm: the spread of the next
  ``step_window_s`` is below a twentieth of the jump. A pop or the edge of a step leaves
  the noise floor behind; the onset of a strong burst is just as large in the samples that
  follow, so a hard squeeze is not mistaken for a pop. The verdict is therefore given one
  window (10 ms) after the jump. A short pulse is caught on its falling edge.
  Limit: a *sparse* motor-unit spike that large against a quiet floor looks like a pop
  too, and a pulse below ``jump_ratio`` times the floor is left to the minimum-burst test.
* **mean_shift** — the mean of the last ``step_window_s`` differs from the mean of the
  window before it by more than ``step_ratio`` times the larger spread (standard
  deviation) *inside* either window (floored at the relaxed noise level). EMG is close to
  zero-mean, so an excursion that is large relative to the spread inside both windows is
  a level change, not a burst: this catches steps and slow ramps whose single-sample jumps
  are small.
* **saturation** — only when ``rail_limit_uv`` is given: any sample at or beyond it. The
  detector cannot know an amplifier's range, so railing is opt-in; a step *into* the rail
  is caught by the jump test regardless.

An artifact **blanks** the detector for ``settle_after_step_s`` seconds. During blanking
no event can begin (a pending burst is dropped), the baseline is not adapted from the
transient (the state machine is not stepped), a squeeze that is open is closed with
``reason == 'artifact'`` (and ``detail['artifact']`` naming the cause) so it is never left
held, and a graded detector sees a relaxed envelope. A new artifact during blanking
extends it. The default settle time is a *design choice* sized to the high-pass
ring-down: the Butterworth high-pass at ``f`` Hz decays with time constant
``1 / (2 * pi * f / sqrt(2))`` (11 ms at 20 Hz); the default is 25 time constants (the ring
has fallen by ``exp(-25)``, about 1e-11, so even a 1e5-fold step is below the noise) plus the
smoothing window, 0.31 s at the defaults. Blanking trades that much dead time per
artifact for never acting on one; every blanking is counted in ``stats['blanked_steps']``.
The artifact thresholds use the *calibrated* baseline, not the adaptive one, so the
decisions are independent of how the stream is cut into blocks. All three tests are
design choices (``step_ratio=8``, ``jump_ratio=100``), validated on synthetic signals only;
``math.inf`` switches a test off.

## Calibration

Thresholds are multiples of a per-person, per-session baseline; nothing is guessed in
microvolts (see ``pressure.py``). TKEO has units of µV² and, for broadband noise, its
mean is close to the signal variance, so the envelope is on the scale of RMS². The
calibration helpers therefore take RMS values *measured on the band-limited signal*
(use :func:`bandlimited_rms`) and square them. That approximation is a design choice
here, not a result from the literature: calibrate on the same pipeline you run.

Dormant by default: nothing in this module reads a device or a config key. This is an
artifact-grade switch for muscle bursts; it does not decode intent (thought decoding
stays rejected, ADR-v2-129).
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from yazses.biosignal.filters import Biquad, SosFilter, design_highpass, design_lowpass
from yazses.biosignal.types import BioEvent, EventKind, SampleBlock, SignalKind
from yazses.platform.emg.pressure import (
    DEFAULT_HARD_FRACTION,
    DEFAULT_LIGHT_FRACTION,
    GradedSqueeze,
    PressureThresholds,
    SqueezeLevel,
)

__all__ = [
    "STUCK_CLEAR_S",
    "EmgOnsetDetector",
    "GradedEmgDetector",
    "OnsetState",
    "OnsetThresholds",
    "bandlimited_rms",
]

# How long the envelope must stay below the off level before a stuck sensor is
# trusted again. One second is a design choice: long enough that a flickering stuck
# contact cannot re-arm itself, short enough that a genuinely freed electrode recovers.
STUCK_CLEAR_S = 1.0

# Lowest sensible on-threshold, as a multiple of the baseline envelope. The smoothed
# rectified-TKEO of pure noise fluctuates by a large fraction of its mean over a 50 ms
# window, so a threshold nearer the baseline fires on noise. A design choice.
MIN_K_ON = 3.0
MIN_K_OFF = 1.5

# Conventional surface-EMG band, high-pass and low-pass corners in Hz. A design choice
# of this module. The upper corner is capped below Nyquist at construction.
DEFAULT_BAND = (20.0, 450.0)
_MAX_HIGH_FRACTION = 0.45  # low-pass corner never above this fraction of fs

# Artifact stage defaults (all design choices, see the module docstring).
DEFAULT_STEP_RATIO = 8.0
DEFAULT_JUMP_RATIO = 100.0
# A jump is an artifact (not a burst onset) only if the signal then goes calm: the spread of
# the following window is below the jump divided by this. A burst's next samples are as large
# as the burst itself (spread about a fifth of its largest jump); a pop or a step leaves the
# noise floor behind (about 1/200 of the jump). A design choice between those two.
_CALM_AFTER_JUMP = 20.0
_MAD_TO_SIGMA = 0.6744897501960817  # median |x| of a unit Gaussian
_STEP_WINDOW_S = 0.01
_JUMP_CONTEXT_S = 0.1
# Settle time = this many high-pass time constants (+ the smoothing window).
_RING_TIME_CONSTANTS = 25.0
_ARTIFACT_CHUNK = 512  # evaluate this many new samples at once (bounds the window views)


class OnsetState(Enum):
    """Where the onset state machine is. Exposed for diagnostics and tests."""

    IDLE = "idle"
    PENDING = "pending"        # above the on level, not yet a confirmed burst
    ACTIVE = "active"          # SQUEEZE_ON emitted, muscle held
    ENDING = "ending"          # below the off level, waiting out the merge gap
    REFRACTORY = "refractory"  # hold-off after SQUEEZE_OFF
    STUCK = "stuck"            # watchdog fired; silent until the envelope clears


@dataclass(frozen=True)
class OnsetThresholds:
    """Everything the state machine needs, in one person's/session's units.

    ``baseline`` is the relaxed-noise envelope (mean rectified TKEO, µV²).
    ``k_on`` / ``k_off`` are multiples of the *current* baseline, so the thresholds
    follow the adaptive baseline. Times are seconds.
    """

    baseline: float
    k_on: float = 4.0
    k_off: float = 2.0
    min_burst_s: float = 0.04
    merge_gap_s: float = 0.06
    refractory_s: float = 0.10
    max_hold_s: float = 20.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.baseline) or self.baseline <= 0:
            raise ValueError("baseline must be a positive, finite envelope value")
        if not self.k_off > 1.0:
            raise ValueError("k_off must be above 1: at or below the baseline the switch never releases")
        if not self.k_on > self.k_off:
            raise ValueError("k_on must exceed k_off: hysteresis needs two distinct levels")
        for name in ("min_burst_s", "merge_gap_s", "refractory_s"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.max_hold_s <= self.min_burst_s:
            raise ValueError("max_hold_s must exceed min_burst_s")

    @classmethod
    def from_calibration(
        cls,
        baseline_rms: float,
        mvc_rms: float,
        *,
        on_fraction: float = 0.10,
        off_fraction: float = 0.04,
        min_burst_s: float = 0.04,
        merge_gap_s: float = 0.06,
        refractory_s: float = 0.10,
        max_hold_s: float = 20.0,
    ) -> OnsetThresholds:
        """Derive thresholds from this person's relaxed and maximum-contraction RMS (µV).

        Both RMS values should be measured on the band-limited signal
        (:func:`bandlimited_rms`). They are squared to envelope units (see the module
        docstring). The on level sits ``on_fraction`` of the way from the relaxed floor
        to the maximum contraction, never below ``MIN_K_ON`` × baseline; the off level
        ``off_fraction`` of the way, never below ``MIN_K_OFF`` × baseline and always
        halfway-or-less between the baseline and the on level.

        Raises ValueError when the maximum contraction is not clearly above the
        relaxed floor — placing thresholds anyway would give a switch that fires at
        random, the same refusal ``pressure.calibrate`` makes.
        """
        if not (math.isfinite(baseline_rms) and baseline_rms > 0):
            raise ValueError("baseline_rms must be a positive, finite value")
        if not (math.isfinite(mvc_rms) and mvc_rms > 0):
            raise ValueError("mvc_rms must be a positive, finite value")
        floor = baseline_rms ** 2
        ceiling = mvc_rms ** 2
        span = ceiling - floor
        k_on = max(MIN_K_ON, (floor + on_fraction * span) / floor)
        if span <= 0 or k_on * floor >= ceiling:
            raise ValueError(
                "maximum contraction is not clearly above the relaxed baseline — "
                "check electrode placement and re-run calibration"
            )
        k_off = max(MIN_K_OFF, (floor + off_fraction * span) / floor)
        k_off = min(k_off, 1.0 + 0.5 * (k_on - 1.0))
        return cls(
            baseline=floor,
            k_on=k_on,
            k_off=k_off,
            min_burst_s=min_burst_s,
            merge_gap_s=merge_gap_s,
            refractory_s=refractory_s,
            max_hold_s=max_hold_s,
        )


# ---------------------------------------------------------------------------
# Block-continuous band-pass (shared with filters.SosFilter)
# ---------------------------------------------------------------------------


def _design_band(band: tuple[float, float] | None, fs: float) -> tuple[Biquad, ...]:
    """Sections for the band, with the upper corner capped safely below Nyquist.

    One second-order Butterworth high-pass at ``lo`` and one low-pass at ``hi`` (the same
    RBJ sections this module used to build privately: Q = 1/sqrt(2)); a degenerate band
    yields fewer sections rather than an error, exactly as before.
    """
    if band is None:
        return ()
    lo, hi = band
    hi = min(hi, _MAX_HIGH_FRACTION * fs)
    sections: list[Biquad] = []
    if 0 < lo < hi:
        sections.extend(design_highpass(lo, fs, 2))
    if 0 < hi < 0.5 * fs and hi > lo:
        sections.extend(design_lowpass(hi, fs, 2))
    return tuple(sections)


class _BandFilter:
    """The band-pass over several channels, state carried across blocks.

    A thin adapter over :class:`yazses.biosignal.filters.SosFilter`: it keeps this module's
    "no sections means pass-through" rule, and the steady-state start on the first sample
    (a raw EMG stream rides on a DC offset of arbitrary size; starting from zero state would
    turn it into a step the high-pass rings on for a long time) is ``SosFilter``'s. Input
    must be finite, which ``EmgOnsetDetector.process`` and ``bandlimited_rms`` guarantee.
    """

    def __init__(self, sections: tuple[Biquad, ...], n_channels: int) -> None:
        self._n_channels = n_channels
        self._sos = SosFilter(sections) if sections else None

    def process(self, x: np.ndarray) -> np.ndarray:
        if self._sos is None:
            return x
        return self._sos.process(x)


def _find_artifacts(
    z: np.ndarray,
    first: int,
    *,
    window: int,
    context: int,
    sigma: float,
    step_ratio: float,
    jump_ratio: float,
) -> list[tuple[int, str]]:
    """Samples of ``z[:, first:]`` where a jump or a mean shift is detected.

    ``z`` is ``(n_channels, n)`` raw data with a per-channel reference already removed
    (this only keeps the sums small); ``first`` is the index of the first sample to judge,
    earlier columns being carried history. Returns ``(index into z, reason)`` pairs, sorted;
    ``'jump'`` wins over ``'mean_shift'`` at the same sample. Pure and block-independent: a
    sample's verdict depends only on the ``max(2 * window - 1, context + 1)`` samples
    before it, each window being reduced on its own (no running sums).
    """
    n_ch, length = z.shape
    hist = max(2 * window - 1, context + window + 1)
    floor = sigma
    jump_floor = math.sqrt(2.0) * sigma
    found: dict[int, str] = {}
    for a in range(first, length, _ARTIFACT_CHUNK):
        b = min(a + _ARTIFACT_CHUNK, length)
        lo = max(a - hist, 0)
        seg = z[:, lo:b]
        ends = np.arange(a - lo, b - lo)

        # Both tests need the jump or the shift to clear ``ratio * floor`` at the very
        # least (the spread is never below the floor), so the costlier spread/median
        # estimates are only made for the few candidates that do; the verdict is the same.

        # -- mean shift: two adjacent windows, level change vs. spread inside them
        ok = ends[ends >= 2 * window - 1]
        if ok.size and np.isfinite(step_ratio):
            sw = sliding_window_view(seg, window, axis=1)  # (n_ch, L - w + 1, w)
            now, prev = ok - window + 1, ok - 2 * window + 1
            shift = np.abs(sw[:, now].mean(axis=2) - sw[:, prev].mean(axis=2))
            for c, k in zip(*np.nonzero(shift > step_ratio * floor), strict=True):
                spread = max(float(sw[c, now[k]].std()), float(sw[c, prev[k]].std()), floor)
                if shift[c, k] > step_ratio * spread:
                    found[lo + int(ok[k])] = "mean_shift"

        # -- jump: one sample against the recent differences, then calm. The verdict on
        # the jump at sample n is given at e = n + window, once the window after it is in.
        ok = ends[ends >= context + window + 1]
        if ok.size and np.isfinite(jump_ratio):
            n = ok - window
            d = np.diff(seg, axis=1)
            cur = np.abs(d[:, n - 1])
            cw = sliding_window_view(d, context, axis=1)  # (n_ch, L - 1 - c + 1, c)
            later = sliding_window_view(seg, window, axis=1)
            for c, k in zip(*np.nonzero(cur > jump_ratio * jump_floor), strict=True):
                # Median, not RMS: a pop's own rising edge sits in the context of its
                # falling edge and would inflate an RMS by the very jump compared against.
                # median|d| / 0.6745 is the standard deviation of Gaussian differences.
                ctx = float(np.median(np.abs(cw[c, n[k] - 1 - context]))) / _MAD_TO_SIGMA
                if cur[c, k] > jump_ratio * max(ctx, jump_floor) and (
                    float(later[c, n[k] + 1].std()) < cur[c, k] / _CALM_AFTER_JUMP
                ):
                    found[lo + int(ok[k])] = "jump"
    return sorted(found.items())


def bandlimited_rms(
    data: np.ndarray,
    fs: float,
    band: tuple[float, float] | None = DEFAULT_BAND,
    *,
    skip_s: float = 0.5,
) -> float:
    """RMS (µV) of ``data`` after the detector's own band-pass: the calibration input.

    ``data`` is ``(n_samples,)`` or ``(n_channels, n_samples)``. The first ``skip_s``
    seconds are dropped so the filter's start-up is not measured. Use this for both the
    relaxed recording and the maximum-contraction recording, then pass the results to
    :meth:`OnsetThresholds.from_calibration`.
    """
    x = np.nan_to_num(np.atleast_2d(np.asarray(data, dtype="float64")),
                      nan=0.0, posinf=0.0, neginf=0.0)
    filtered = _BandFilter(_design_band(band, fs), x.shape[0]).process(x)
    start = min(int(round(skip_s * fs)), max(filtered.shape[1] - 1, 0))
    seg = filtered[:, start:]
    if seg.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(seg ** 2)))


# ---------------------------------------------------------------------------
# The detector
# ---------------------------------------------------------------------------


class EmgOnsetDetector:
    """Streaming double-threshold EMG onset/offset detector (a ``StreamDetector``).

    ``process`` accepts any block size and any channel mix; only ``SignalKind.EMG``
    rows are read. Events carry the time the detector *committed* (the confirmed onset,
    or the end of the merge gap); the underlying edge time is in ``detail``.

    Beyond the thresholds, the keyword arguments are: ``min_channel_fraction`` (channel
    agreement, default 0.5), ``settle_after_step_s`` (blanking time after an artifact;
    ``None`` = the high-pass ring-down default), ``step_ratio`` / ``jump_ratio`` /
    ``step_window_s`` / ``jump_context_s`` (artifact tests) and ``rail_limit_uv`` (opt-in
    saturation level). All are documented in the module docstring. :attr:`stats` exposes
    the counters of what was rejected or cut short. A squeeze open when an artifact hits is
    closed with ``reason == 'artifact'`` (``detail['artifact']`` names the cause); if the
    muscle is still contracted when the blanking ends, a fresh ``SQUEEZE_ON`` follows.
    """

    # Stream state, (re)initialised by _restart_stream().
    _prev: np.ndarray | None
    _tail: np.ndarray
    _anchor: float | None
    _expected_t: float | None
    _n_in: int
    _n_env: int
    _last_env: float
    _state: OnsetState
    _t_cross: float
    _t_on: float
    _t_drop: float
    _t_free: float
    _t_clear: float | None
    _peak: float
    _gap_sum: float
    _gap_n: int
    _cur_ch: np.ndarray
    _t_disagree: float | None
    _disagree_open: bool
    _art_ref: np.ndarray | None
    _art_hist: np.ndarray
    _art_queue: deque[tuple[int, str]]
    _blank_until: int
    _blank_why: str

    def __init__(
        self,
        thresholds: OnsetThresholds,
        *,
        band: tuple[float, float] | None = DEFAULT_BAND,
        smooth_s: float = 0.03,
        settle_s: float = 0.5,
        baseline_tau_s: float = 5.0,
        baseline_limits: tuple[float, float] = (0.25, 4.0),
        adapt_baseline: bool = True,
        min_channel_fraction: float = 0.5,
        settle_after_step_s: float | None = None,
        step_ratio: float = DEFAULT_STEP_RATIO,
        jump_ratio: float = DEFAULT_JUMP_RATIO,
        step_window_s: float = _STEP_WINDOW_S,
        jump_context_s: float = _JUMP_CONTEXT_S,
        rail_limit_uv: float | None = None,
    ) -> None:
        if smooth_s <= 0:
            raise ValueError("smooth_s must be > 0")
        if baseline_tau_s <= 0:
            raise ValueError("baseline_tau_s must be > 0")
        lo, hi = baseline_limits
        if not 0 < lo <= 1.0 <= hi:
            raise ValueError("baseline_limits must satisfy 0 < low <= 1 <= high")
        if not 0.0 < min_channel_fraction <= 1.0:
            raise ValueError("min_channel_fraction must be in (0, 1]")
        if settle_after_step_s is not None and not settle_after_step_s >= 0.0:
            raise ValueError("settle_after_step_s must be >= 0 (or None for the ring-down default)")
        if not (step_ratio > 0 and jump_ratio > 0):
            raise ValueError("step_ratio and jump_ratio must be > 0 (math.inf disables a test)")
        if step_window_s <= 0 or jump_context_s <= 0:
            raise ValueError("step_window_s and jump_context_s must be > 0")
        if rail_limit_uv is not None and not (math.isfinite(rail_limit_uv) and rail_limit_uv > 0):
            raise ValueError("rail_limit_uv must be a positive, finite value (or None)")
        self._min_frac = float(min_channel_fraction)
        self._settle_step_s = settle_after_step_s
        self._step_ratio = float(step_ratio)
        self._jump_ratio = float(jump_ratio)
        self._step_window_s = step_window_s
        self._jump_context_s = jump_context_s
        self._rail = rail_limit_uv
        self._step_w = 4
        self._jump_c = 8
        self._art_settle_n = 1
        self._th = thresholds
        self._band = band
        self._smooth_s = smooth_s
        self._settle_s = max(settle_s, smooth_s)
        self._tau = baseline_tau_s
        self._limits = baseline_limits
        self._adapt = adapt_baseline
        self._fs = 0.0
        self._rows: tuple[int, ...] = ()
        self._names: tuple[str, ...] = ()
        self._filter: _BandFilter | None = None
        self._smooth_n = 1
        self._settle_n = 0
        self.rejected_bursts = 0
        self._blanked_steps = 0
        self._rejected_disagreement = 0
        self._max_hold_trips = 0
        self._baseline = thresholds.baseline
        self._restart_stream()

    # -- public surface -----------------------------------------------------

    @property
    def stats(self) -> dict[str, int]:
        """Diagnostic counters since construction or :meth:`reset` (a fresh copy each call).

        ``rejected_bursts`` — bursts shorter than the minimum burst, dropped silently;
        ``blanked_steps`` — artifact episodes (step, pop, saturation) that blanked the
        detector (a new artifact inside an open blanking extends it and is not recounted);
        ``rejected_disagreement`` — bursts the mean envelope saw but too few channels
        agreed on (``min_channel_fraction``); ``max_hold_trips`` — maximum-hold watchdog
        firings. Counters only ever describe what was *not* emitted or was cut short; they
        never gate behaviour.
        """
        return {
            "rejected_bursts": self.rejected_bursts,
            "blanked_steps": self._blanked_steps,
            "rejected_disagreement": self._rejected_disagreement,
            "max_hold_trips": self._max_hold_trips,
        }

    @property
    def blanked(self) -> bool:
        """True while an artifact is blanking the detector (diagnostics)."""
        return self._n_env <= self._blank_until

    @property
    def thresholds(self) -> OnsetThresholds:
        return self._th

    @property
    def baseline(self) -> float:
        """The current (adaptive) relaxed-noise envelope."""
        return self._baseline

    @property
    def state(self) -> OnsetState:
        return self._state

    @property
    def active(self) -> bool:
        """True between a SQUEEZE_ON and its SQUEEZE_OFF."""
        return self._state in (OnsetState.ACTIVE, OnsetState.ENDING)

    @property
    def envelope_value(self) -> float:
        """The latest smoothed combined envelope (0.0 before the first sample)."""
        return self._last_env

    def reset(self) -> None:
        """Forget the stream, the baseline adaptation and any open squeeze."""
        self._baseline = self._th.baseline
        self.rejected_bursts = 0
        self._blanked_steps = 0
        self._rejected_disagreement = 0
        self._max_hold_trips = 0
        self._restart_stream()
        self._on_reset()

    def process(self, block: SampleBlock) -> Sequence[BioEvent]:
        events: list[BioEvent] = []
        rows = tuple(
            i for i, ch in enumerate(block.channels) if ch.kind is SignalKind.EMG
        )
        if not rows or block.n_samples == 0 or block.fs <= 0:
            return events
        fs = float(block.fs)
        names = tuple(block.channels[i].name for i in rows)
        if fs != self._fs or rows != self._rows or names != self._names:
            events.extend(self._abort("reconfigure"))
            self._configure(fs, rows, names)
        elif self._expected_t is not None and block.t0 > self._expected_t + 2.5 / fs:
            # Forward jump on the source clock: samples were lost.
            events.extend(self._abort("gap"))
        assert self._filter is not None

        data = np.asarray(block.data, dtype="float64")
        x = np.nan_to_num(data[list(rows)], nan=0.0, posinf=0.0, neginf=0.0)
        if self._anchor is None:
            self._anchor = float(block.t0)
        self._queue_artifacts(x)
        self._n_in += x.shape[1]
        self._expected_t = self._anchor + self._n_in / fs

        env, env_ch = self._envelope(self._filter.process(x))
        for k, e in enumerate(env.tolist()):
            self._n_env += 1
            m = self._n_env
            new_blank = self._poll_artifacts(m)
            if m <= self._settle_n:
                self._last_env = e
                continue
            t = self._anchor + m / fs
            self._last_env = e
            if m <= self._blank_until:
                # Blanked: the state machine is not stepped (no event can begin, the
                # baseline cannot learn the transient) and a graded detector is shown a
                # relaxed envelope rather than the ring.
                if new_blank:
                    events.extend(self._enter_blanking(t))
                self._observe(0.0)
                continue
            self._cur_ch = env_ch[:, k]
            self._observe(e)
            events.extend(self._step(e, t))
        return events

    # -- artifact stage -----------------------------------------------------

    def _queue_artifacts(self, x: np.ndarray) -> None:
        """Find jumps, mean shifts and saturation in the new raw samples ``x``.

        Detections are queued by *global raw sample index* and consumed by
        :meth:`_poll_artifacts` as the envelope (which trails the raw stream by one
        sample) catches up, so the verdict never depends on the block boundaries.
        """
        if self._art_ref is None:
            self._art_ref = x[:, :1].copy()
        xd = x - self._art_ref
        first = self._art_hist.shape[1]
        z = np.concatenate([self._art_hist, xd], axis=1) if first else xd
        base = self._n_in - first
        found = _find_artifacts(
            z,
            first,
            window=self._step_w,
            context=self._jump_c,
            sigma=math.sqrt(self._th.baseline),
            step_ratio=self._step_ratio,
            jump_ratio=self._jump_ratio,
        )
        new = [(base + i, why) for i, why in found]
        if self._rail is not None:
            hit = np.nonzero((np.abs(x) >= self._rail).any(axis=0))[0]
            new.extend((self._n_in + int(j), "saturation") for j in hit.tolist())
            new.sort(key=lambda item: item[0])
        self._art_queue.extend(new)
        keep = max(2 * self._step_w - 1, self._jump_c + self._step_w + 1)
        self._art_hist = z[:, -keep:]

    def _poll_artifacts(self, m: int) -> bool:
        """Arm blanking for queued detections up to raw index ``m``; True if a new episode."""
        new = False
        q = self._art_queue
        while q and q[0][0] <= m:
            idx, why = q.popleft()
            if self._blank_until < m and not new:
                new = True
                self._blanked_steps += 1
                self._blank_why = why
            self._blank_until = max(self._blank_until, idx + self._art_settle_n)
        return new

    def _enter_blanking(self, t: float) -> list[BioEvent]:
        """Start of a blanking episode: close an open squeeze, drop a pending burst."""
        out: list[BioEvent] = []
        if self.active:
            off = self._th.k_off * self._baseline
            out.append(self._release(t, off, "artifact", t, 1.0, artifact=self._blank_why))
            self._state = OnsetState.IDLE
        elif self._state is OnsetState.PENDING:
            self._state = OnsetState.IDLE
        self._t_disagree = None
        return out

    # -- signal path --------------------------------------------------------

    def _envelope(self, filtered: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Per-channel rectified TKEO (carried) smoothed causally, then their mean.

        Returns ``(combined, per_channel)``: ``(n,)`` and ``(n_channels, n)``. Keeping the
        channels apart until after the smoothing lets the state machine ask how many of
        them individually exceed the on level.
        """
        n_ch = filtered.shape[0]
        z = filtered if self._prev is None else np.concatenate([self._prev, filtered], axis=1)
        self._prev = z[:, -2:]
        if z.shape[1] < 3:
            return np.zeros(0, dtype="float64"), np.zeros((n_ch, 0), dtype="float64")
        psi = z[:, 1:-1] ** 2 - z[:, :-2] * z[:, 2:]
        r = np.abs(psi)

        n = self._smooth_n
        full = np.concatenate([self._tail, r], axis=1) if self._tail.shape[1] else r
        m = full.shape[1] - r.shape[1]
        cs = np.concatenate([np.zeros((n_ch, 1)), np.cumsum(full, axis=1)], axis=1)
        end = np.arange(m + 1, full.shape[1] + 1)
        start = np.maximum(end - n, 0)
        per = (cs[:, end] - cs[:, start]) / (end - start)
        self._tail = full[:, -(n - 1):] if n > 1 else np.zeros((n_ch, 0), dtype="float64")
        per = np.asarray(per, dtype="float64")
        return per.mean(axis=0), per

    # -- state machine ------------------------------------------------------

    def _step(self, e: float, t: float) -> list[BioEvent]:
        th = self._th
        half = 0.5 / self._fs  # timing tolerance: half a sample
        on = th.k_on * self._baseline
        off = th.k_off * self._baseline
        out: list[BioEvent] = []
        st = self._state

        if st is OnsetState.IDLE:
            if e >= on:
                # A crossing the channels disagreed on is suppressed until the envelope
                # has dropped below the off level (one episode, counted once).
                if not self._disagree_open:
                    self._state = OnsetState.PENDING
                    self._t_cross = t
                    self._t_disagree = None
                    self._peak = e
                    out.extend(self._maybe_confirm(e, t, on, half))
            else:
                if e < off:
                    self._disagree_open = False
                    if self._adapt:
                        self._adapt_baseline(e)

        elif st is OnsetState.PENDING:
            self._peak = max(self._peak, e)
            if e < off:
                self._state = OnsetState.IDLE
                self.rejected_bursts += 1
            elif t - self._t_cross > th.max_hold_s:
                self._enter_stuck()
            elif not self._agree(on):
                # Too few channels over the on level although the mean is: one bad
                # electrode is not a squeeze. Tolerate a merge gap of it (single-channel
                # envelopes ripple), then drop the burst as a disagreement.
                if self._t_disagree is None:
                    self._t_disagree = t
                if t - self._t_disagree >= th.merge_gap_s - half:
                    self._state = OnsetState.IDLE
                    self._t_disagree = None
                    self._disagree_open = True
                    self._rejected_disagreement += 1
            else:
                self._t_disagree = None
                out.extend(self._maybe_confirm(e, t, on, half))

        elif st in (OnsetState.ACTIVE, OnsetState.ENDING):
            self._peak = max(self._peak, e)
            if t - self._t_on >= th.max_hold_s - half:
                out.append(self._release(t, off, "max_hold", t, 1.0))
                self._enter_stuck()
            elif st is OnsetState.ACTIVE:
                if e < off:
                    self._state = OnsetState.ENDING
                    self._t_drop = t
                    self._gap_sum, self._gap_n = e, 1
            else:  # ENDING
                if e >= off:
                    self._state = OnsetState.ACTIVE
                else:
                    self._gap_sum += e
                    self._gap_n += 1
                    if t - self._t_drop >= th.merge_gap_s - half:
                        mean_gap = self._gap_sum / self._gap_n
                        conf = 0.5 + 0.5 * math.tanh(1.0 - mean_gap / off)
                        out.append(self._release(t, off, "release", self._t_drop, conf))
                        self._state = OnsetState.REFRACTORY
                        self._t_free = t + th.refractory_s

        elif st is OnsetState.REFRACTORY:
            if t >= self._t_free - half:
                self._state = OnsetState.IDLE

        else:  # STUCK
            if e < off:
                if self._t_clear is None:
                    self._t_clear = t
                elif t - self._t_clear >= STUCK_CLEAR_S - half:
                    self._state = OnsetState.REFRACTORY
                    self._t_free = t + th.refractory_s
            else:
                self._t_clear = None
        return out

    def _maybe_confirm(self, e: float, t: float, on: float, half: float) -> list[BioEvent]:
        elapsed = t - self._t_cross
        if elapsed < self._dwell_s() - half or not self._agree(on):
            return []
        if not self._confirm_ok(elapsed):
            return []
        self._state = OnsetState.ACTIVE
        self._t_on = t
        ratio = self._peak / on
        detail: dict[str, object] = {
            "latency_ms": (elapsed + self._smooth_delay_s()) * 1000.0,
            "peak_envelope": self._peak,
            "threshold": on,
            "onset_t": self._t_cross,
            "baseline": self._baseline,
            "channels_over": self._channels_over(on),
            "n_channels": len(self._rows),
        }
        self._annotate_on(detail)
        return [self._event(EventKind.SQUEEZE_ON, t, 0.5 + 0.5 * math.tanh(ratio - 1.0), detail)]

    def _release(
        self,
        t: float,
        off: float,
        reason: str,
        edge_t: float,
        confidence: float,
        *,
        artifact: str | None = None,
    ) -> BioEvent:
        detail: dict[str, object] = {
            "reason": reason,
            "peak_envelope": self._peak,
            "threshold": off,
            "edge_t": edge_t,
            "duration_s": edge_t - self._t_cross,
            "baseline": self._baseline,
        }
        if artifact is not None:
            detail["artifact"] = artifact
        self._annotate_off(detail)
        return self._event(EventKind.SQUEEZE_OFF, t, confidence, detail)

    def _enter_stuck(self) -> None:
        self._state = OnsetState.STUCK
        self._t_clear = None
        self._max_hold_trips += 1

    def _channels_over(self, on: float) -> int:
        """How many EMG channels individually have their envelope at or over ``on``."""
        if len(self._rows) <= 1:
            return len(self._rows)
        return int(np.count_nonzero(self._cur_ch >= on))

    def _agree(self, on: float) -> bool:
        """Enough channels over the on level (always True for a single channel)."""
        n = len(self._rows)
        if n <= 1:
            return True
        return self._channels_over(on) >= self._min_frac * n - 1e-9

    def _adapt_baseline(self, e: float) -> None:
        alpha = 1.0 - math.exp(-1.0 / (self._fs * self._tau))
        b0 = self._th.baseline
        lo, hi = self._limits
        self._baseline = min(max(self._baseline + alpha * (e - self._baseline), lo * b0), hi * b0)

    def _dwell_s(self) -> float:
        """Envelope dwell that confirms a burst: min_burst_s plus the smoothing smear."""
        return self._th.min_burst_s + self._smooth_n / self._fs

    def _smooth_delay_s(self) -> float:
        return (self._smooth_n - 1) / 2.0 / self._fs

    def _event(
        self, kind: EventKind, t: float, confidence: float, detail: dict[str, object]
    ) -> BioEvent:
        return BioEvent(
            kind=kind,
            t=t,
            confidence=min(max(confidence, 0.0), 1.0),
            channel="+".join(self._names),
            detail=detail,
        )

    # -- lifecycle ----------------------------------------------------------

    def _configure(self, fs: float, rows: tuple[int, ...], names: tuple[str, ...]) -> None:
        self._fs = fs
        self._rows = rows
        self._names = names
        self._smooth_n = max(1, int(round(self._smooth_s * fs)))
        self._settle_n = max(int(round(self._settle_s * fs)), self._smooth_n)
        self._filter = _BandFilter(_design_band(self._band, fs), len(rows))
        self._step_w = max(4, int(round(self._step_window_s * fs)))
        self._jump_c = max(8, int(round(self._jump_context_s * fs)))
        self._art_settle_n = max(1, int(math.ceil(self._artifact_settle_s() * fs)))
        self._restart_stream(keep_filter=True)
        self._on_configure(fs)

    def _artifact_settle_s(self) -> float:
        """Blanking time after an artifact: the configured value or the ring-down default."""
        if self._settle_step_s is not None:
            return self._settle_step_s
        lo = self._band[0] if self._band is not None else 0.0
        if lo > 0:
            tau = math.sqrt(2.0) / (2.0 * math.pi * lo)  # 2nd-order Butterworth, zeta = 1/sqrt 2
            return _RING_TIME_CONSTANTS * tau + self._smooth_s
        return self._smooth_s + 0.05  # no high-pass, so nothing rings; cover the smear

    def _abort(self, reason: str) -> list[BioEvent]:
        """Close an open squeeze (never leave the mic open on lost data) and restart."""
        events: list[BioEvent] = []
        if self.active:
            t = self._expected_t if self._expected_t is not None else self._t_on
            off = self._th.k_off * self._baseline
            events.append(self._release(t, off, reason, t, 1.0))
        self._restart_stream()
        if self._fs > 0:
            self._filter = _BandFilter(_design_band(self._band, self._fs), len(self._rows))
        return events

    def _restart_stream(self, *, keep_filter: bool = False) -> None:
        """Drop everything tied to the data seen so far; keep config and baseline."""
        if not keep_filter:
            self._filter = None
            if self._fs > 0:
                self._filter = _BandFilter(_design_band(self._band, self._fs), len(self._rows))
        self._prev = None
        self._tail = np.zeros((len(self._rows), 0), dtype="float64")
        self._cur_ch = np.zeros(len(self._rows), dtype="float64")
        self._t_disagree = None
        self._disagree_open = False
        self._art_ref = None
        self._art_hist = np.zeros((len(self._rows), 0), dtype="float64")
        self._art_queue = deque()
        self._blank_until = -1
        self._blank_why = ""
        self._anchor = None
        self._expected_t = None
        self._n_in = 0
        self._n_env = 0
        self._last_env = 0.0
        self._state = OnsetState.IDLE
        self._t_cross = 0.0
        self._t_on = 0.0
        self._t_drop = 0.0
        self._t_free = 0.0
        self._t_clear = None
        self._peak = 0.0
        self._gap_sum = 0.0
        self._gap_n = 0

    # -- extension hooks (GradedEmgDetector) --------------------------------

    def _on_configure(self, fs: float) -> None:
        """Called when the sampling rate or channel set is (re)established."""

    def _on_reset(self) -> None:
        """Called at the end of reset()."""

    def _observe(self, e: float) -> None:
        """Called with every settled smoothed-envelope sample, before the decision."""

    def _confirm_ok(self, elapsed: float) -> bool:
        """Extra condition for confirming a burst, beyond the minimum duration."""
        return True

    def _annotate_on(self, detail: dict[str, object]) -> None:
        """Add fields to the SQUEEZE_ON detail."""

    def _annotate_off(self, detail: dict[str, object]) -> None:
        """Add fields to the SQUEEZE_OFF detail."""


# ---------------------------------------------------------------------------
# Graded wrapper: light = dictate, hard = command, exactly as pressure.py defines
# ---------------------------------------------------------------------------

_LEVEL_RANK = {SqueezeLevel.RELAXED: 0, SqueezeLevel.LIGHT: 1, SqueezeLevel.HARD: 2}


class GradedEmgDetector(EmgOnsetDetector):
    """:class:`EmgOnsetDetector` that also reports *how hard*, via ``GradedSqueeze``.

    The smoothed envelope is fed to ``GradedSqueeze`` (light/hard thresholds from
    ``PressureThresholds``), and ``SQUEEZE_ON`` carries ``detail['level']``
    (``'light'`` or ``'hard'``) and ``detail['mode']`` — ``LEVEL_MODE`` from
    ``pressure.py`` (light -> ``'full_text'`` dictate, hard -> ``'command'``).

    A burst is only confirmed once ``GradedSqueeze`` has settled on a non-relaxed level,
    so a burst that clears the on level but never reaches the light level never starts
    dictation (``pressure.py``: light "starts well above the noise floor so a resting
    twitch cannot trigger"). The level is read at confirmation time: a slow ramp to a
    hard squeeze can be reported as light if it is still climbing when the burst is
    confirmed. ``level_settle_s`` trades that many milliseconds of extra latency for
    reading the level later in the ramp; the default is 0 (no extra latency).
    Because confirmation also waits for the light level, a gentle squeeze reports a later
    ``latency_ms`` than the plain detector would (the estimate includes that wait).
    ``SQUEEZE_OFF`` carries the highest level reached as ``detail['level']``.
    """

    def __init__(
        self,
        thresholds: OnsetThresholds,
        levels: PressureThresholds,
        *,
        level_hold_s: float = 0.04,
        level_settle_s: float = 0.0,
        **kwargs: object,
    ) -> None:
        if level_hold_s < 0 or level_settle_s < 0:
            raise ValueError("level_hold_s and level_settle_s must be >= 0")
        self._levels = levels
        self._level_hold_s = level_hold_s
        self._level_settle_s = level_settle_s
        self._squeeze: GradedSqueeze | None = None
        self._peak_rank = 0
        super().__init__(thresholds, **kwargs)  # type: ignore[arg-type]

    @classmethod
    def from_calibration(
        cls,
        baseline_rms: float,
        mvc_rms: float,
        *,
        light_fraction: float = DEFAULT_LIGHT_FRACTION,
        hard_fraction: float = DEFAULT_HARD_FRACTION,
        **kwargs: object,
    ) -> GradedEmgDetector:
        """Build onset thresholds *and* light/hard levels from the same calibration.

        Same scale and the same fractions as ``pressure.calibrate``, but on the squared
        band-limited RMS values, so both stages share one set of units.
        """
        thresholds = OnsetThresholds.from_calibration(baseline_rms, mvc_rms)
        floor = baseline_rms ** 2
        span = mvc_rms ** 2 - floor
        levels = PressureThresholds(
            light=floor + span * light_fraction,
            hard=floor + span * hard_fraction,
        )
        return cls(thresholds, levels, **kwargs)  # type: ignore[arg-type]

    @property
    def level(self) -> SqueezeLevel:
        """The level ``GradedSqueeze`` currently reports."""
        return self._squeeze.level if self._squeeze else SqueezeLevel.RELAXED

    # -- hooks --------------------------------------------------------------

    def _on_configure(self, fs: float) -> None:
        hold = max(1, int(round(self._level_hold_s * fs)))
        self._squeeze = GradedSqueeze(self._levels, hold_samples=hold)
        self._peak_rank = 0

    def _on_reset(self) -> None:
        if self._fs > 0:
            self._on_configure(self._fs)

    def _observe(self, e: float) -> None:
        if self._squeeze is not None:
            self._squeeze.update(e)
        if self._state in (OnsetState.ACTIVE, OnsetState.ENDING):
            self._peak_rank = max(self._peak_rank, _LEVEL_RANK[self.level])

    def _confirm_ok(self, elapsed: float) -> bool:
        return (
            self.level is not SqueezeLevel.RELAXED
            and elapsed >= self._dwell_s() + self._level_settle_s - 0.5 / self._fs
        )

    def _annotate_on(self, detail: dict[str, object]) -> None:
        sq = self._squeeze
        level = sq.level if sq else SqueezeLevel.RELAXED
        detail["level"] = level.value
        detail["mode"] = sq.mode if sq else None
        self._peak_rank = _LEVEL_RANK[level]

    def _annotate_off(self, detail: dict[str, object]) -> None:
        by_rank = {v: k for k, v in _LEVEL_RANK.items()}
        detail["level"] = by_rank[self._peak_rank].value
