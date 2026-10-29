"""Artifact-grade EEG switches: blink, double-blink and jaw clench.

The research note (``docs/research/muscle-brain-control.md``) is blunt about what a
consumer EEG headband can give a computer as a *reliable* command: blinks and jaw
clenches, and neither is a brain signal. They are eye and muscle artifacts leaking into
the scalp electrodes. ADR-v2-129 keeps "thought" decoding rejected; this module reads
only those two artifacts, as switches, and says out loud how often they will be wrong.

## The false-positive budget this module is written against

The best blink switch in the cited literature (Li et al. 2018, doc ref ``eogswitch``)
reached 99.5% accuracy at 1.3 s response with **0.10 false positives per minute**. That
sounds small and is not: 0.10/min is 6 per hour, ~48 in an eight-hour day -- the docs'
"~50 phantom activations per workday". For a dictation tool that opens a microphone,
50 phantom mic-openings a day is a defect, and the EMG electrode strictly dominates it.
So these detectors are *opt-in extras for people who already wear a headband*, and they
are built to move the false-positive rate down, not to claim a rate:

* **A lone blink is involuntary, so it is not emitted.** With ``double_only=True`` (the
  default) a blink only becomes an event when a second one follows within
  ``double_window_s``; the pair is the deliberate gesture (``EventKind.DOUBLE_BLINK``).
  This is a design choice that *should* cut involuntary triggers, because spontaneous
  blinks rarely come twice inside a fraction of a second. How much it cuts is a
  hypothesis to measure on the user's own recordings, not a number this file asserts.
* **Talking is the fatal confound for jaw clench** (docs: "confounded by chewing -- and
  by talking, fatal in a dictation tool"). The jaw detector therefore takes a
  ``speech_guard`` callable and stays silent while the user is talking (plus a
  hangover), and it rejects bursts repeating at a chewing cadence.
* **Thresholds are relative to the person**, never a fixed microvolt number: both
  detectors track a robust running baseline (median and MAD) and fire on deviation
  from it. Amplitude varies by an order of magnitude across people and electrode
  placement, the same reason ``platform/emg/pressure.py`` calibrates instead of guessing.
* **Every event carries a confidence and a ``detail`` dict** (amplitude, width, z-score)
  so the integrator can gate on it, and both detectors keep counters of what they
  suppressed, so a false-positive audit has data.

## Streaming contract

Both classes implement ``StreamDetector``. They are block-size independent: all adaptive
state advances on a fixed grid of *absolute sample counts* (a 100 ms hop), never on block
boundaries, so feeding the same signal in blocks of 7 or 7000 samples yields the same
events. An excursion or burst that straddles a block boundary is carried in state.
``reset()`` returns a detector to its just-constructed state.

Everything is numpy + stdlib. Filters are FIR (``np.convolve`` with carried history)
because scipy is not a base dependency.

Nothing in this module does I/O, opens a network connection, or starts a thread.
"""

from __future__ import annotations

import logging
import math
import warnings
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from yazses.biosignal.types import (
    BioEvent,
    EventKind,
    SampleBlock,
    SignalKind,
    StreamDetector,
)

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_BLINK_CHANNELS",
    "DEFAULT_JAW_CHANNELS",
    "ArtifactBank",
    "BlinkDetector",
    "JawClenchDetector",
    "chewing_rhythm_suppressed",
]

FloatArray = NDArray[np.float64]

# Frontal sites see blinks largest; AF7/AF8 are what a Muse-style headband has.
DEFAULT_BLINK_CHANNELS: tuple[str, ...] = ("Fp1", "Fp2", "AF7", "AF8")
# Temporalis (the jaw-closing muscle) sits under the temporal electrodes; the frontal
# ones pick it up too. TP9/TP10 are the behind-the-ear sites of a Muse-style headband.
DEFAULT_JAW_CHANNELS: tuple[str, ...] = (
    "T7", "T8", "TP9", "TP10", "F7", "F8", "AF7", "AF8", "Fp1", "Fp2",
)

# MAD -> standard deviation for a Gaussian. A definition, not a tuning knob.
_MAD_TO_SIGMA = 1.4826
# Adaptive state advances on this grid of absolute sample counts (see module docstring).
_HOP_S = 0.1
# set_sensitivity_scale() is clamped to this range: 1 = the configured thresholds, 4 = the
# loosest the false-positive governor may push them (a design choice -- beyond a few times
# the configured thresholds a detector is effectively off, and "off" is the governor's job).
_SCALE_MIN = 1.0
_SCALE_MAX = 4.0

# Blink calibration (design choices, not measured operating points; see from_calibration):
# the minimum accepted blink peak is this fraction of the user's own calibrated blink
# amplitude, but never below this many microvolts, so a tiny or noisy calibration cannot
# make the detector hair-trigger. The floor only ever RAISES the threshold: the robust
# z-score test (``amplitude_k``) still applies on top of it.
_CAL_BLINK_FRACTION = 0.5
# A candidate within the double-blink window whose peak is below this fraction of the
# previous blink's peak is treated as that blink's filter rebound (design choice).
_RINGING_RATIO = 0.35
# The speech guard is read at most once per this much signal time (a design choice).
_SPEECH_POLL_S = 0.1
# An opposite-polarity hump closer than this to a blink is its overshoot (design choice).
_OVERSHOOT_S = 0.3
_CAL_BLINK_FLOOR_UV = 10.0
# Jaw calibration: the burst-power floor is this fraction of the in-band power estimated
# from the user's calibrated ``clench_power`` (0.25 = about -6 dB, the same size as the
# default ``on_db``). Like the blink floor it can only raise the threshold.
_CAL_CLENCH_FRACTION = 0.25


# --------------------------------------------------------------------------- helpers


def _odd(n: int) -> int:
    n = max(1, int(n))
    return n if n % 2 == 1 else n + 1


class _ChannelSelector:
    """Pick the rows a detector reads, once, and keep reading the same rows.

    Locking the choice on the first block that has a match is what lets a detector keep
    per-channel filter history across blocks. If a locked channel later disappears, the
    detector is told to start over rather than silently reading different electrodes.
    """

    def __init__(
        self,
        names: Sequence[str] | None,
        *,
        always_kinds: frozenset[SignalKind],
        any_kinds: frozenset[SignalKind],
    ) -> None:
        self._names_ci = None if names is None else frozenset(n.lower() for n in names)
        self._always = always_kinds
        self._any = any_kinds
        self._locked: tuple[str, ...] | None = None

    @property
    def names(self) -> tuple[str, ...]:
        return self._locked or ()

    def reset(self) -> None:
        self._locked = None

    def _wanted(self, name: str, kind: SignalKind) -> bool:
        if self._names_ci is None:
            return kind in self._any
        return name.lower() in self._names_ci or kind in self._always

    def select(self, block: SampleBlock) -> tuple[FloatArray | None, bool]:
        """Return ``(rows, lost)``. ``rows`` is None when nothing matches (yet) or lost."""
        data = np.asarray(block.data, dtype=np.float64)
        if data.ndim != 2 or data.shape[0] != len(block.channels):
            raise ValueError(
                f"block.data must be (n_channels, n_samples) matching block.channels; "
                f"got shape {data.shape} for {len(block.channels)} channels"
            )
        index = {c.name: i for i, c in enumerate(block.channels)}
        if self._locked is None:
            chosen = tuple(c.name for c in block.channels if self._wanted(c.name, c.kind))
            if not chosen:
                return None, False
            self._locked = chosen
        try:
            rows = [index[n] for n in self._locked]
        except KeyError:
            return None, True
        return data[rows], False


def _combine(rows: FloatArray, last: float) -> tuple[FloatArray, float]:
    """Collapse channels to one series with a per-sample median.

    The median (not the mean) lets one railed or unplugged electrode out-vote nothing.
    Non-finite samples are ignored per sample; if every channel is non-finite the
    previous value is held, so a dropout is a flat spot, not a spike.
    """
    if np.isfinite(rows).all():
        series = rows[0].copy() if rows.shape[0] == 1 else np.median(rows, axis=0)
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            series = np.nanmedian(rows, axis=0)
        good = np.isfinite(series)
        idx = np.maximum.accumulate(np.where(good, np.arange(series.size), -1))
        series = np.where(idx >= 0, series[np.maximum(idx, 0)], last)
    return series.astype(np.float64, copy=False), float(series[-1]) if series.size else last


class _StreamFIR:
    """Causal FIR with carried history: exact across any block split.

    History starts as the first sample held constant, so a large DC offset at start-up
    is not a step. With zero-DC-gain taps that held history filters to exactly zero.
    """

    def __init__(self, taps: FloatArray) -> None:
        self._taps = taps
        self._tail: FloatArray | None = None

    def reset(self) -> None:
        self._tail = None

    def apply(self, x: FloatArray) -> FloatArray:
        m = self._taps.size
        if self._tail is None:
            self._tail = np.repeat(x[:, :1], m - 1, axis=1)
        buf = np.concatenate([self._tail, x], axis=1)
        out = np.empty_like(x)
        for c in range(x.shape[0]):
            out[c] = np.convolve(buf[c], self._taps, mode="valid")
        self._tail = buf[:, buf.shape[1] - (m - 1):]
        return out


def _bandpass_taps(fs: float, lo_hz: float, hi_hz: float, ntaps: int) -> FloatArray:
    """Hamming-windowed-sinc band-pass with exactly zero DC gain."""
    mid = (ntaps - 1) / 2.0
    n = np.arange(ntaps) - mid

    def lowpass(fc: float) -> FloatArray:
        return (2.0 * fc / fs) * np.sinc(2.0 * fc / fs * n)

    taps = (lowpass(hi_hz) - lowpass(lo_hz)) * np.hamming(ntaps)
    taps -= taps.mean()
    return taps.astype(np.float64)


def _check_positive(**values: float) -> None:
    for name, v in values.items():
        if not v > 0:
            raise ValueError(f"{name} must be > 0, got {v!r}")


def _positive_or_none(value: float | None) -> float | None:
    """A usable calibration number, or None (missing, NaN, zero, negative, not a number)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0.0 else None


def _clamp_scale(scale: float) -> float:
    """Validate and clamp a sensitivity scale to ``[_SCALE_MIN, _SCALE_MAX]``."""
    try:
        v = float(scale)
    except (TypeError, ValueError):
        raise ValueError(f"sensitivity scale must be a number, got {scale!r}") from None
    if not math.isfinite(v):
        raise ValueError(f"sensitivity scale must be finite, got {scale!r}")
    return min(max(v, _SCALE_MIN), _SCALE_MAX)


def _moving_average(x: FloatArray, n: int) -> FloatArray:
    """Centred moving average of odd length ``n`` with edge replication (same length)."""
    if n <= 1 or x.size == 0:
        return x
    h = n // 2
    padded = np.concatenate([np.full(h, x[0]), x, np.full(h, x[-1])])
    return np.convolve(padded, np.full(n, 1.0 / n), mode="valid")


# ------------------------------------------------------------------------------ blink


@dataclass
class _Blink:
    t: float
    confidence: float
    detail: dict


class BlinkDetector:
    """Blink and double-blink from frontal EEG/EOG channels.

    A blink is a large, slow, one-sided deflection (roughly 100-400 ms wide) far above
    the channel's own noise. The detector:

    1. Collapses the selected channels to one series (per-sample median).
    2. Tracks a robust baseline and scale: the median and MAD of the last
       ``baseline_s`` seconds. A blink occupies a small fraction of that window, so it
       barely moves either statistic -- which is why median/MAD and not mean/std.
    3. Opens an *excursion* when the deviation reaches ``0.5 * amplitude_k`` robust
       sigmas and closes it once the signal has been back below that for a few
       samples. An excursion must reach ``amplitude_k`` sigmas to count.
    4. Measures the excursion's full width at half maximum and its rise and fall
       times. It must rise **and** fall (both edges at least ``min_edge_s``), and the
       width must lie in ``[min_width_s, max_width_s]``. A step (eye-position shift,
       electrode shift) never falls back and is aborted by length; a one-sample pop has
       no measurable edges and is too narrow. Either polarity is accepted, because the
       sign of a blink depends on the montage.
    5. Enforces ``refractory_s`` between blinks.

    With ``double_only=True`` (default) a blink is held as pending and only a second
    blink within ``double_window_s`` produces an event, ``DOUBLE_BLINK``, timestamped at
    the second blink's peak. A lone blink is never emitted. With ``double_only=False``
    every blink also yields ``BLINK`` (and a pair still yields ``DOUBLE_BLINK``).

    ``confidence`` is a monotone score in [0, 1] from how far the peak clears the
    threshold and how central the width is in its window. It is a ranking aid for the
    integrator's gate, **not** a calibrated probability.

    ``detail`` carries ``amplitude_uv`` (signed peak above baseline), ``z_score`` (peak
    in robust sigmas), ``width_s`` (FWHM), ``rise_s``, ``fall_s`` and ``scale_uv``;
    a ``DOUBLE_BLINK`` carries ``interval_s``, ``first`` and ``second``.

    Warm-up: no event is produced until ``warmup_s`` seconds of signal have been seen.
    Samples that would themselves open an excursion are trimmed out of the warm-up
    baseline, and the baseline is frozen while an excursion is open, so a blink never
    shifts the baseline or inflates the scale that the *next* blink is judged against.

    **Several blinks in one excursion.** An excursion ends only when the signal has been
    below the opening level for a few samples. A band-passed (high-passed) blink rings:
    it has an opposite-sign overshoot and a slow tail, and with quiet electrodes that tail
    stays above the opening level, so a blink pair 0.5 s apart arrives as ONE excursion.
    The first version judged one blink per excursion (its largest peak), so the other blink
    of the pair was swallowed -- or the peak that won was a narrow overshoot lobe that failed
    the width test, losing both. This was the "pair at 8 s is missed, the same pair at 12 s
    is caught" bug: it depended on the noise realisation (does the tail dip under the
    opening level between the blinks?), not on the warm-up or the baseline window.
    An excursion is now split at deep valleys of its smoothed envelope (see
    ``_split_blinks``) and each piece is judged on its own. The valley must fall below
    half of the lower neighbouring peak AND the peaks must be at least ``refractory_s``
    apart, so a single blink's own overshoot lobe (a fraction of a second after the main
    lobe) is merged into it rather than counted as a second blink.

    A candidate that comes within ``double_window_s`` of a blink more than ~3x larger and
    barely clears the threshold is that blink's filter rebound and is rejected
    (``stats['rejected_ringing']``); otherwise one blink could pose as a pair.

    ``min_amplitude_uv`` is an optional absolute floor (µV above baseline) on top of the
    ``amplitude_k`` test; ``BlinkDetector.from_calibration`` sets it from the user's own
    calibrated blink amplitude. ``set_sensitivity_scale`` scales ``amplitude_k`` and
    ``min_amplitude_uv`` together.
    """

    def __init__(
        self,
        fs: float,
        *,
        channels: Sequence[str] | None = DEFAULT_BLINK_CHANNELS,
        amplitude_k: float = 6.0,
        min_width_s: float = 0.10,
        max_width_s: float = 0.40,
        refractory_s: float = 0.20,
        double_only: bool = True,
        double_window_s: float = 0.6,
        baseline_s: float = 8.0,
        warmup_s: float = 2.0,
        min_scale_uv: float = 1.0,
        min_edge_s: float = 0.02,
        min_amplitude_uv: float = 0.0,
    ) -> None:
        if not min_amplitude_uv >= 0.0:
            raise ValueError(f"min_amplitude_uv must be >= 0, got {min_amplitude_uv!r}")
        _check_positive(
            fs=fs, amplitude_k=amplitude_k, min_width_s=min_width_s,
            max_width_s=max_width_s, refractory_s=refractory_s,
            double_window_s=double_window_s, baseline_s=baseline_s,
            warmup_s=warmup_s, min_scale_uv=min_scale_uv, min_edge_s=min_edge_s,
        )
        if min_width_s >= max_width_s:
            raise ValueError("min_width_s must be < max_width_s")
        if warmup_s > baseline_s:
            raise ValueError("warmup_s must be <= baseline_s")
        self.fs = float(fs)
        # ``amplitude_k`` / ``min_amplitude_uv`` are the EFFECTIVE thresholds; the
        # configured ones are kept so set_sensitivity_scale() is never cumulative.
        self._cfg_amplitude_k = float(amplitude_k)
        self._cfg_min_amplitude_uv = float(min_amplitude_uv)
        self._sens_scale = 1.0
        self.amplitude_k = self._cfg_amplitude_k
        self.min_amplitude_uv = self._cfg_min_amplitude_uv
        self.min_width_s = float(min_width_s)
        self.max_width_s = float(max_width_s)
        self.refractory_s = float(refractory_s)
        self.double_only = bool(double_only)
        self.double_window_s = float(double_window_s)
        self.min_scale_uv = float(min_scale_uv)
        self.min_edge_s = float(min_edge_s)

        self._selector = _ChannelSelector(
            channels,
            always_kinds=frozenset({SignalKind.EOG}),
            any_kinds=frozenset({SignalKind.EEG, SignalKind.EOG}),
        )
        self._lo_k = max(1.5, 0.5 * self.amplitude_k)
        self._hop = max(1, round(_HOP_S * self.fs))
        self._win_n = max(self._hop, round(baseline_s * self.fs))
        self._warm_n = min(self._win_n, max(self._hop, round(warmup_s * self.fs)))
        self._close_n = max(2, round(0.04 * self.fs))
        # Long enough for a blink pair plus its ringing tail (~1 s measured on the
        # synthetic source through the EEG band-pass); a step that never returns is still
        # cut off, just a little later than before (was 3x max_width_s).
        self._abort_n = max(2, round(5.0 * self.max_width_s * self.fs))
        self._min_edge_n = max(1, round(self.min_edge_s * self.fs))
        # FWHM is measured on a 20 ms moving average: one mains period at 50 Hz, so
        # mains ripple cannot break the contiguous half-maximum walk into pieces.
        self._wid_n = _odd(round(0.02 * self.fs))
        # Valleys between blinks are looked for on a 100 ms envelope.
        self._env_n = _odd(round(_HOP_S * self.fs))
        self._reset_state()

    # -- sensitivity --------------------------------------------------------------

    @property
    def sensitivity_scale(self) -> float:
        """The current threshold multiplier (1.0 = configured thresholds)."""
        return self._sens_scale

    def set_sensitivity_scale(self, scale: float) -> None:
        """Multiply the amplitude thresholds by ``scale`` (clamped to [1, 4]).

        ``scale > 1`` makes the detector LESS sensitive: both ``amplitude_k`` (robust
        sigmas) and ``min_amplitude_uv`` are multiplied, so the effect is the same whether
        the sigma or the absolute test is the binding one. The scale is applied to the
        configured thresholds, not to the current ones, so calling it twice with 2.0
        gives 2x, not 4x. ``scale <= 1`` restores the configured thresholds -- a
        governor may desensitise a detector but cannot make it more sensitive than the
        user configured. It survives ``reset()``. Raises ``ValueError`` for a non-finite
        or non-numeric scale.
        """
        self._sens_scale = _clamp_scale(scale)
        self.amplitude_k = self._cfg_amplitude_k * self._sens_scale
        self.min_amplitude_uv = self._cfg_min_amplitude_uv * self._sens_scale
        self._lo_k = max(1.5, 0.5 * self.amplitude_k)

    @classmethod
    def from_calibration(
        cls,
        fs: float,
        blink_amplitude_uv: float | None,
        *,
        fraction: float = _CAL_BLINK_FRACTION,
        floor_uv: float = _CAL_BLINK_FLOOR_UV,
        **kw: Any,
    ) -> BlinkDetector:
        """Build a detector whose minimum blink size follows the user's own blinks.

        ``blink_amplitude_uv`` is ``CalibrationProfile.blink_amplitude``: the median peak
        deviation, in microvolts, of the *smoothed rectified* signal during the guided
        blinks. Smoothing and rectifying under-read a raw peak, so this is a conservative
        estimate of the raw blink height.

        The detector's ``min_amplitude_uv`` becomes ``max(fraction * blink_amplitude_uv,
        floor_uv)`` (design choices: half of the user's own blink, and never below
        ``floor_uv`` so a tiny or noisy calibration cannot make the detector hair-trigger).
        This floor only ever raises the bar: the robust z-score test still applies, so a
        calibration can make the detector stricter than its default, never looser than
        its noise-relative threshold. When ``blink_amplitude_uv`` is None, NaN, zero or
        negative the result is exactly ``BlinkDetector(fs, **kw)``. An explicit
        ``min_amplitude_uv`` in ``kw`` wins over the calibration.
        """
        if not 0.0 < fraction <= 1.0:
            raise ValueError(f"fraction must be in (0, 1], got {fraction!r}")
        if not floor_uv >= 0.0:
            raise ValueError(f"floor_uv must be >= 0, got {floor_uv!r}")
        amp = _positive_or_none(blink_amplitude_uv)
        if amp is not None and "min_amplitude_uv" not in kw:
            kw["min_amplitude_uv"] = max(fraction * amp, float(floor_uv))
        return cls(fs, **kw)

    # -- state ------------------------------------------------------------------

    def _reset_state(self) -> None:
        self._selector.reset()
        self._ring = np.zeros(self._win_n, dtype=np.float64)
        self._ring_pos = 0
        self._ring_count = 0
        self._n = 0
        self._base: float | None = None
        self._scale = self.min_scale_uv
        self._last_value = 0.0
        # excursion
        self._active = False
        self._rejected = False
        self._below = 0
        self._ex_t0 = 0.0
        self._ex_d: list[float] = []
        self._ex_z: list[float] = []
        # blink pairing
        self._last_blink_t: float | None = None
        self._last_blink_z = 0.0
        self._last_blink_sign = 0.0
        self._pending: _Blink | None = None
        self.stats: dict[str, int] = {
            "blinks": 0,
            "double_blinks": 0,
            "lone_blinks_dropped": 0,
            "rejected_width": 0,
            "rejected_edges": 0,
            "rejected_amplitude": 0,
            "rejected_refractory": 0,
            "rejected_too_long": 0,
            "rejected_ringing": 0,
        }

    def reset(self) -> None:
        """Forget the baseline, any open excursion and any pending blink."""
        self._reset_state()

    # -- public ------------------------------------------------------------------

    def process(self, block: SampleBlock) -> list[BioEvent]:
        if block.fs != self.fs:
            raise ValueError(f"block.fs={block.fs} does not match detector fs={self.fs}")
        rows, lost = self._selector.select(block)
        if lost:
            log.warning("blink: a locked channel vanished from the stream; resetting")
            self._reset_state()
            return []
        if rows is None or rows.shape[1] == 0:
            return []
        x, self._last_value = _combine(rows, self._last_value)

        events: list[BioEvent] = []
        total = x.size
        i = 0
        while i < total:
            seg_len = min(total - i, self._hop - (self._n % self._hop))
            seg = x[i:i + seg_len]
            if self._base is not None:
                events.extend(self._scan(seg, block.t0 + i / self.fs))
            if not self._active:  # frozen while an excursion is open (see class docstring)
                self._push(seg)
            self._n += seg_len
            if self._n % self._hop == 0:
                self._update_baseline()
            i += seg_len
        return events

    # -- baseline ----------------------------------------------------------------

    def _push(self, seg: FloatArray) -> None:
        idx = (self._ring_pos + np.arange(seg.size)) % self._win_n
        self._ring[idx] = seg
        self._ring_pos = int((self._ring_pos + seg.size) % self._win_n)
        self._ring_count = min(self._win_n, self._ring_count + seg.size)

    def _update_baseline(self) -> None:
        if self._ring_count < self._warm_n:
            return
        filling = self._ring_count < self._win_n
        valid = self._ring[: self._ring_count] if filling else self._ring
        base = float(np.median(valid))
        mad = float(np.median(np.abs(valid - base)))
        if filling:
            # While the window is still short a single blink is a large share of it.
            # Anything that would open an excursion must not define "baseline": trim it
            # once and re-estimate (only if enough samples remain to be meaningful).
            trim = max(1.5, 0.5 * self._cfg_amplitude_k) * max(_MAD_TO_SIGMA * mad, self.min_scale_uv)
            keep = valid[np.abs(valid - base) <= trim]
            if keep.size >= max(8, valid.size // 2):
                base = float(np.median(keep))
                mad = float(np.median(np.abs(keep - base)))
        self._base = base
        self._scale = max(_MAD_TO_SIGMA * mad, self.min_scale_uv)

    # -- excursion state machine --------------------------------------------------

    def _scan(self, seg: FloatArray, t_seg0: float) -> list[BioEvent]:
        assert self._base is not None
        d = seg - self._base
        z = d / self._scale
        az = np.abs(z)
        lo = self._lo_k
        if not self._active and float(az.max()) < lo:
            self._rejected = False
            return []
        out: list[BioEvent] = []
        for j in range(seg.size):
            a = float(az[j])
            if not self._active:
                if self._rejected:
                    if a < lo:
                        self._rejected = False
                    continue
                if a >= lo:
                    self._active = True
                    self._below = 0
                    self._ex_t0 = t_seg0 + j / self.fs
                    self._ex_d = [float(d[j])]
                    self._ex_z = [float(z[j])]
                continue
            self._ex_d.append(float(d[j]))
            self._ex_z.append(float(z[j]))
            self._below = self._below + 1 if a < lo else 0
            if self._below >= self._close_n:
                self._active = False
                out.extend(self._close_excursion())
            elif len(self._ex_z) > self._abort_n:
                self._active = False
                self._rejected = True
                self.stats["rejected_too_long"] += 1
                self._ex_d, self._ex_z = [], []
        return out

    def _close_excursion(self) -> list[BioEvent]:
        z = np.asarray(self._ex_z)
        d = np.asarray(self._ex_d)
        t0 = self._ex_t0
        self._ex_d, self._ex_z = [], []
        az = np.abs(z)
        pieces = self._split_blinks(az)
        # Pieces whose raw peak never clears amplitude_k are noise bumps on a ringing tail,
        # not blink candidates. If NOTHING clears it the excursion counts as one
        # amplitude rejection (as it did when one excursion meant one candidate).
        pieces = [(a, b) for a, b in pieces if float(az[a:b].max()) >= self.amplitude_k]
        if not pieces:
            self.stats["rejected_amplitude"] += 1
            return []
        out: list[BioEvent] = []
        for a, b in pieces:
            out.extend(self._judge_blink(az[a:b], d[a:b], t0 + a / self.fs))
        return out

    def _split_blinks(self, az: FloatArray) -> list[tuple[int, int]]:
        """Split one excursion into one half-open index range per blink candidate.

        Peaks are found on a 100 ms moving average of ``|z|``. Two neighbouring peaks are
        separate blinks only if (a) they are at least ``refractory_s`` apart and (b) the
        envelope between them falls to at most half of the lower peak. Otherwise the
        smaller is merged into the larger. (b) keeps a blink's own overshoot lobe -- which
        crosses zero within ~0.1 s of the main lobe -- in one piece (the 100 ms average
        fills the zero crossing), while the quiet stretch between two blinks, where the
        tail has decayed, splits them. Both numbers are design choices; (a) reuses the
        detector's own minimum blink spacing. A single piece is returned for a clean blink.
        """
        n = az.size
        if n < 3:
            return [(0, n)]
        env = _moving_average(az, self._env_n)
        up = np.concatenate([[True], env[1:] >= env[:-1]])
        down = np.concatenate([env[:-1] > env[1:], [True]])
        sep_n = max(1, round(self.refractory_s * self.fs))
        kept: list[int] = []
        for i in np.flatnonzero(up & down).tolist():
            v = env[i]
            while True:
                if not kept:
                    kept.append(i)
                    break
                j = kept[-1]
                valley = float(env[j:i + 1].min())
                if i - j >= sep_n and valley <= 0.5 * min(float(env[j]), float(v)):
                    kept.append(i)
                    break
                if v <= env[j]:
                    break  # absorbed into the larger peak on its left
                kept.pop()  # the new peak dominates; re-test it against the one before
        cuts = [j + int(np.argmin(env[j:i + 1])) for j, i in zip(kept, kept[1:], strict=False)]
        edges = [0, *cuts, n]
        return [(a, b) for a, b in zip(edges, edges[1:], strict=False) if b > a]

    def _judge_blink(self, az_raw: FloatArray, d: FloatArray, t_start: float) -> list[BioEvent]:
        """Accept or reject one blink candidate and feed the double-blink pairing."""
        pk_raw = int(np.argmax(az_raw))
        peak_z = float(az_raw[pk_raw])
        if peak_z < self.amplitude_k:
            self.stats["rejected_amplitude"] += 1
            return []
        # Width on a 20 ms average (mains ripple must not split the half-max walk); the
        # amplitude and the reported z-score stay on the raw peak.
        az = _moving_average(az_raw, self._wid_n)
        pk = int(np.argmax(az))
        half = float(az[pk]) / 2.0
        lo_i = pk
        while lo_i > 0 and az[lo_i - 1] >= half:
            lo_i -= 1
        hi_i = pk
        while hi_i < az.size - 1 and az[hi_i + 1] >= half:
            hi_i += 1
        width_s = (hi_i - lo_i + 1) / self.fs
        rise_s = (pk - lo_i) / self.fs
        fall_s = (hi_i - pk) / self.fs
        if (pk - lo_i) < self._min_edge_n or (hi_i - pk) < self._min_edge_n:
            self.stats["rejected_edges"] += 1
            return []
        if not (self.min_width_s <= width_s <= self.max_width_s):
            self.stats["rejected_width"] += 1
            return []
        if abs(float(d[pk_raw])) < self.min_amplitude_uv:
            self.stats["rejected_amplitude"] += 1
            return []
        t_peak = t_start + pk / self.fs
        if self._last_blink_t is not None and t_peak - self._last_blink_t < self.refractory_s:
            self.stats["rejected_refractory"] += 1
            return []
        if (
            self._last_blink_t is not None
            and t_peak - self._last_blink_t <= self.double_window_s
            and peak_z < _RINGING_RATIO * self._last_blink_z
        ):
            # A hump that barely clears the threshold right after a much larger blink is
            # the band-pass filter's slow rebound, not a second blink: counting it made
            # one blink look like a deliberate pair (seen on the synthetic source).
            self.stats["rejected_ringing"] += 1
            return []
        sign = 1.0 if float(d[pk_raw]) >= 0.0 else -1.0
        if (
            self._last_blink_t is not None
            and t_peak - self._last_blink_t < _OVERSHOOT_S
            and sign != self._last_blink_sign
        ):
            # A hump of the OPPOSITE polarity within ~0.3 s of a blink is the band-pass
            # filter's overshoot lobe, not a second blink (a 60 uV blink split into +39/-39
            # lobes 0.23 s apart and read as a pair). Only the short interval is judged by
            # polarity: through the same filter a real pair's reported peaks can be either
            # lobe, so a longer interval must stay accepted whatever the signs.
            self.stats["rejected_ringing"] += 1
            return []
        self._last_blink_t = t_peak
        self._last_blink_z = peak_z
        self._last_blink_sign = sign

        mid = 0.5 * (self.min_width_s + self.max_width_s)
        half_range = 0.5 * (self.max_width_s - self.min_width_s)
        shape = float(np.clip(1.0 - abs(width_s - mid) / half_range, 0.0, 1.0))
        amp = float(np.clip(peak_z / (2.0 * self.amplitude_k), 0.0, 1.0))
        confidence = float(np.clip(amp * (0.5 + 0.5 * shape), 0.0, 1.0))
        detail = {
            "amplitude_uv": float(d[pk_raw]),
            "z_score": peak_z,
            "width_s": width_s,
            "rise_s": rise_s,
            "fall_s": fall_s,
            "scale_uv": self._scale,
        }
        channel = ",".join(self._selector.names)
        self.stats["blinks"] += 1
        blink = _Blink(t=t_peak, confidence=confidence, detail=detail)
        out: list[BioEvent] = []
        if not self.double_only:
            out.append(BioEvent(EventKind.BLINK, t_peak, confidence, channel, dict(detail)))
        prev = self._pending
        if prev is not None and 0.0 < t_peak - prev.t <= self.double_window_s:
            self._pending = None
            self.stats["double_blinks"] += 1
            out.append(
                BioEvent(
                    EventKind.DOUBLE_BLINK,
                    t_peak,
                    min(prev.confidence, confidence),
                    channel,
                    {
                        "interval_s": t_peak - prev.t,
                        "first": prev.detail,
                        "second": dict(detail),
                        "z_score": min(prev.detail["z_score"], peak_z),
                        "amplitude_uv": detail["amplitude_uv"],
                        "width_s": width_s,
                    },
                )
            )
        else:
            if prev is not None:
                self.stats["lone_blinks_dropped"] += 1
            self._pending = blink
        return out


# ------------------------------------------------------------------------- jaw clench


def chewing_rhythm_suppressed(
    onsets: Sequence[float],
    *,
    min_hz: float = 1.0,
    max_hz: float = 2.0,
    repeats: int = 3,
    tolerance: float = 0.3,
) -> bool:
    """True if the last ``repeats`` burst onsets repeat at a chewing cadence.

    Chewing is rhythmic, roughly 1-2 Hz (the cadence the task names; ``tolerance``
    widens each edge by a fraction to allow for human jitter -- a design choice).
    A deliberate clench is a single, isolated burst. The check is on onset *intervals*:
    every one of the ``repeats - 1`` most recent intervals must lie in
    ``[1 / (max_hz * (1 + tolerance)), 1 / (min_hz * (1 - tolerance))]``.

    Trade-off, stated plainly: three deliberate clenches at one per second are also
    suppressed, and the first ``repeats - 1`` bursts of a chewing sequence cannot be
    known to be chewing when they happen (see ``JawClenchDetector(chew_holdoff_s=...)``).
    """
    if repeats < 2:
        raise ValueError("repeats must be >= 2")
    if not 0.0 < min_hz <= max_hz:
        raise ValueError("need 0 < min_hz <= max_hz")
    if not 0.0 <= tolerance < 1.0:
        raise ValueError("tolerance must be in [0, 1)")
    if len(onsets) < repeats:
        return False
    lo = 1.0 / (max_hz * (1.0 + tolerance))
    hi = 1.0 / (min_hz * (1.0 - tolerance))
    last = list(onsets)[-repeats:]
    return all(lo <= b - a <= hi for a, b in zip(last, last[1:], strict=False))


@dataclass
class _PendingJaw:
    event: BioEvent
    release_t: float


class JawClenchDetector:
    """Jaw clench from the broadband high-frequency power burst on temporal/frontal EEG.

    Clenching the jaw recruits the temporalis, and its EMG shows up on nearby scalp
    electrodes as broadband high-frequency power far above the EEG's own. The detector:

    1. Band-passes the selected channels to ``band_hz`` (default 20-100 Hz; the upper
       edge is clamped to 0.45 * fs so it never reaches Nyquist). Mains hum (50/60 Hz)
       falls inside this band; it is constant, so the adaptive baseline absorbs it.
    2. Squares and smooths (``smooth_s``) to a power envelope, takes the per-sample
       median across channels, and works in dB.
    3. Compares that to a robust running baseline (median and MAD of the last
       ``baseline_s`` seconds of per-hop dB values). The user rests quietly for
       ``warmup_s`` first; that is the calibration. The baseline is *frozen* while a
       burst is in progress (up to ``max_duration_s``, so a permanent level change is
       eventually adopted) and while the user is talking, so neither contaminates it.
    4. Opens a burst when power is ``max(on_db, on_z * scale)`` above baseline and closes
       it below ``max(off_db, off_z * scale)`` (hysteresis, so one burst is one event).
       The event fires **once**, when the burst has lasted ``min_duration_s``.
    5. Suppresses the event when ``speech_guard()`` was true at any point from
       ``speech_hangover_s`` before the burst began until it was confirmed, when the
       burst falls inside ``refractory_s`` of the last event, or when the burst onsets
       repeat at a chewing cadence (``chewing_rhythm_suppressed``).

    Talking is the fatal confound for a dictation tool, so ``speech_guard`` should be
    wired to the VAD / push-to-talk state. It is called at most once per 100 ms of
    signal, in stream order. If it raises, the detector fails closed (treats the user
    as talking). With no guard the detector cannot tell a clench from speech and the
    docstring above is the warning.

    Chewing leak: the cadence is only recognisable on the ``chew_repeats``-th burst, so
    the earlier ones have already fired. ``chew_holdoff_s > 0`` holds each event for that
    long and drops it if the cadence materialises -- at the cost of that much latency.
    The default is 0 (no hold). The honest figure for how often either mechanism helps
    must come from recordings of the actual user.

    ``confidence`` in [0, 1] averages how far the peak clears the threshold and how long
    the burst has been sustained; like the blink's, it is a ranking aid, not a
    probability. ``detail``: ``peak_db`` (above baseline), ``z_score`` (peak_db in robust
    sigmas), ``sustained_s`` (duration at confirmation), ``baseline_db``, ``scale_db``,
    ``confirmed_t``. The event time ``t`` is the burst *onset*, delay-compensated for
    the filters; ``confirmed_t`` is when the detector could first say so.

    ``min_burst_power_uv2`` is an optional absolute floor on the in-band power (µV^2 per
    channel, after the band-pass) a burst must reach, on top of the baseline-relative
    ``on_db`` / ``on_z`` test. ``JawClenchDetector.from_calibration`` sets it from the
    user's own calibrated clench. ``set_sensitivity_scale`` scales ``on_db``, ``off_db``,
    ``on_z``, ``off_z`` and that floor together.
    """

    def __init__(
        self,
        fs: float,
        *,
        channels: Sequence[str] | None = DEFAULT_JAW_CHANNELS,
        band_hz: tuple[float, float] = (20.0, 100.0),
        smooth_s: float = 0.1,
        on_db: float = 6.0,
        off_db: float = 3.0,
        on_z: float = 4.0,
        off_z: float = 2.0,
        min_duration_s: float = 0.2,
        max_duration_s: float = 3.0,
        refractory_s: float = 0.3,
        baseline_s: float = 30.0,
        warmup_s: float = 3.0,
        min_scale_db: float = 1.0,
        speech_guard: Callable[[], bool] | None = None,
        speech_hangover_s: float = 0.5,
        chew_hz: tuple[float, float] = (1.0, 2.0),
        chew_repeats: int = 3,
        chew_tolerance: float = 0.3,
        chew_holdoff_s: float = 0.0,
        min_burst_power_uv2: float = 0.0,
    ) -> None:
        if not min_burst_power_uv2 >= 0.0:
            raise ValueError(f"min_burst_power_uv2 must be >= 0, got {min_burst_power_uv2!r}")
        _check_positive(
            fs=fs, smooth_s=smooth_s, on_db=on_db, off_db=off_db, on_z=on_z, off_z=off_z,
            min_duration_s=min_duration_s, max_duration_s=max_duration_s,
            refractory_s=refractory_s, baseline_s=baseline_s, warmup_s=warmup_s,
            min_scale_db=min_scale_db,
        )
        if off_db > on_db or off_z > on_z:
            raise ValueError("off thresholds must not exceed on thresholds (hysteresis)")
        if speech_hangover_s < 0 or chew_holdoff_s < 0:
            raise ValueError("speech_hangover_s and chew_holdoff_s must be >= 0")
        if warmup_s > baseline_s:
            raise ValueError("warmup_s must be <= baseline_s")
        lo_hz = float(band_hz[0])
        hi_hz = min(float(band_hz[1]), 0.45 * float(fs))
        if not (lo_hz > 0.0 and hi_hz > 1.5 * lo_hz):
            raise ValueError(
                f"band {band_hz} leaves no usable passband at fs={fs} "
                f"(upper edge clamped to {hi_hz:.1f} Hz)"
            )
        # Validate the chewing parameters now, not at first use.
        chewing_rhythm_suppressed(
            [], min_hz=chew_hz[0], max_hz=chew_hz[1],
            repeats=chew_repeats, tolerance=chew_tolerance,
        )

        self.fs = float(fs)
        self.band_hz = (lo_hz, hi_hz)
        # The public threshold attributes are the EFFECTIVE values; the configured ones
        # are kept so set_sensitivity_scale() is never cumulative.
        self._cfg_thresholds = (float(on_db), float(off_db), float(on_z), float(off_z))
        self._cfg_min_burst_power = float(min_burst_power_uv2)
        self._sens_scale = 1.0
        self.on_db, self.off_db, self.on_z, self.off_z = self._cfg_thresholds
        self.min_burst_power_uv2 = self._cfg_min_burst_power
        self.min_duration_s = float(min_duration_s)
        self.max_duration_s = float(max_duration_s)
        self.refractory_s = float(refractory_s)
        self.min_scale_db = float(min_scale_db)
        self.speech_guard = speech_guard
        self.speech_hangover_s = float(speech_hangover_s)
        self.chew_hz = (float(chew_hz[0]), float(chew_hz[1]))
        self.chew_repeats = int(chew_repeats)
        self.chew_tolerance = float(chew_tolerance)
        self.chew_holdoff_s = float(chew_holdoff_s)

        self._selector = _ChannelSelector(
            channels, always_kinds=frozenset(), any_kinds=frozenset({SignalKind.EEG}),
        )
        ntaps = _odd(round(0.3 * self.fs))
        ma_n = _odd(round(smooth_s * self.fs))
        self._bp_taps = _bandpass_taps(self.fs, lo_hz, hi_hz, ntaps)
        self._ma_taps = np.full(ma_n, 1.0 / ma_n)
        self._delay_s = ((ntaps - 1) / 2.0 + (ma_n - 1) / 2.0) / self.fs
        self._startup_n = ntaps + ma_n
        self._hop = max(1, round(_HOP_S * self.fs))
        self._base_hops = max(1, round(baseline_s / _HOP_S))
        self._warm_hops = min(self._base_hops, max(1, round(warmup_s / _HOP_S)))
        self._min_dur_n = max(1, round(self.min_duration_s * self.fs))
        self._off_n = max(1, round(0.05 * self.fs))
        self._reset_state()

    # -- sensitivity --------------------------------------------------------------

    @property
    def sensitivity_scale(self) -> float:
        """The current threshold multiplier (1.0 = configured thresholds)."""
        return self._sens_scale

    def set_sensitivity_scale(self, scale: float) -> None:
        """Multiply the burst thresholds by ``scale`` (clamped to [1, 4]).

        ``scale > 1`` makes the detector LESS sensitive: ``on_db``, ``off_db``, ``on_z``
        and ``off_z`` are multiplied (so the hysteresis ordering ``off <= on`` is kept) and
        so is the absolute power floor (as a linear power factor). Like the blink
        detector's, the scale applies to the configured thresholds, not cumulatively; a
        governor can desensitise but never make the detector more sensitive than
        configured; it survives ``reset()``. Raises ``ValueError`` for a non-finite or
        non-numeric scale.
        """
        self._sens_scale = _clamp_scale(scale)
        on_db, off_db, on_z, off_z = self._cfg_thresholds
        k = self._sens_scale
        self.on_db, self.off_db, self.on_z, self.off_z = on_db * k, off_db * k, on_z * k, off_z * k
        self.min_burst_power_uv2 = self._cfg_min_burst_power * k

    @classmethod
    def from_calibration(
        cls,
        fs: float,
        clench_power: float | None,
        *,
        fraction: float = _CAL_CLENCH_FRACTION,
        **kw: Any,
    ) -> JawClenchDetector:
        """Build a detector whose minimum burst power follows the user's own clenches.

        ``clench_power`` is ``CalibrationProfile.clench_power``: the mean squared first
        difference (µV^2 per sample^2) inside the guided clench bursts. To compare it with
        this detector's band power it is converted with a *flat-spectrum model*: a
        first difference has power gain ``4 sin^2(pi f / fs)``, whose mean over
        ``[0, fs/2]`` is 2, so the signal variance is about ``clench_power / 2``; a flat
        spectrum puts ``(hi - lo) / (fs / 2)`` of it in the detector's band ``[lo, hi]``.
        Real EMG is not flat, so this is an order-of-magnitude estimate -- which is why
        only a ``fraction`` of it (default 0.25, about -6 dB; a design choice) is used as
        the floor ``min_burst_power_uv2``.

        The floor only ever raises the bar: the baseline-relative ``on_db`` / ``on_z`` test
        still applies, so a tiny calibration cannot make the detector hair-trigger -- at
        worst the floor has no effect. When ``clench_power`` is None, NaN, zero or
        negative the result is exactly ``JawClenchDetector(fs, **kw)``. An explicit
        ``min_burst_power_uv2`` in ``kw`` wins over the calibration.
        """
        if not 0.0 < fraction <= 1.0:
            raise ValueError(f"fraction must be in (0, 1], got {fraction!r}")
        power = _positive_or_none(clench_power)
        if power is not None and "min_burst_power_uv2" not in kw:
            lo_hz, hi_hz = kw.get("band_hz", (20.0, 100.0))
            hi_hz = min(float(hi_hz), 0.45 * float(fs))
            band_share = max(0.0, (hi_hz - float(lo_hz)) / (0.5 * float(fs)))
            kw["min_burst_power_uv2"] = fraction * 0.5 * power * band_share
        return cls(fs, **kw)

    # -- state ------------------------------------------------------------------

    def _reset_state(self) -> None:
        self._selector.reset()
        self._bp = _StreamFIR(self._bp_taps)
        self._ma = _StreamFIR(self._ma_taps)
        self._n = 0
        self._acc_sum = 0.0
        self._acc_cnt = 0
        self._hops: deque[float] = deque(maxlen=self._base_hops)
        self._base: float | None = None
        self._scale = self.min_scale_db
        # burst
        self._active = False
        self._decided = False
        self._below = 0
        self._onset_n = 0
        self._onset_ts = 0.0
        self._peak_db = 0.0
        self._onsets: deque[float] = deque(maxlen=max(8, 2 * self.chew_repeats))
        self._last_event_t: float | None = None
        self._pending: _PendingJaw | None = None
        self._speech_until = float("-inf")
        self._last_speech_poll_t: float | None = None
        self.stats: dict[str, int] = {
            "clenches": 0,
            "suppressed_speech": 0,
            "suppressed_chewing": 0,
            "suppressed_refractory": 0,
            "short_bursts": 0,
        }

    def reset(self) -> None:
        """Forget the baseline, any burst in progress and the chewing history."""
        self._reset_state()

    def chewing_rhythm_suppressed(self) -> bool:
        """Whether the most recent burst onsets form a chewing cadence right now."""
        return chewing_rhythm_suppressed(
            list(self._onsets), min_hz=self.chew_hz[0], max_hz=self.chew_hz[1],
            repeats=self.chew_repeats, tolerance=self.chew_tolerance,
        )

    # -- public ------------------------------------------------------------------

    def process(self, block: SampleBlock) -> list[BioEvent]:
        if block.fs != self.fs:
            raise ValueError(f"block.fs={block.fs} does not match detector fs={self.fs}")
        rows, lost = self._selector.select(block)
        if lost:
            log.warning("jaw: a locked channel vanished from the stream; resetting")
            self._reset_state()
            return []
        if rows is None or rows.shape[1] == 0:
            return []
        rows = np.nan_to_num(rows, nan=0.0, posinf=0.0, neginf=0.0)
        power = self._ma.apply(self._bp.apply(rows) ** 2)
        envelope = np.median(power, axis=0)
        db = 10.0 * np.log10(envelope + 1e-12)

        events: list[BioEvent] = []
        total = db.size
        i = 0
        while i < total:
            seg_len = min(total - i, self._hop - (self._n % self._hop))
            t_seg0 = block.t0 + i / self.fs
            t_seg_end = t_seg0 + seg_len / self.fs
            self._poll_speech(t_seg_end)
            seg = db[i:i + seg_len]
            if self._base is not None:
                events.extend(self._scan(seg, t_seg0))
            if self._pending is not None and t_seg_end >= self._pending.release_t:
                events.append(self._pending.event)
                self._pending = None
            self._acc_sum += float(seg.sum())
            self._acc_cnt += seg_len
            self._n += seg_len
            if self._n % self._hop == 0:
                self._end_of_hop(t_seg_end)
            i += seg_len
        return events

    # -- speech guard ------------------------------------------------------------

    def _poll_speech(self, t_now: float) -> None:
        if self.speech_guard is None:
            return
        # At most once per 100 ms of signal, however the source chops its blocks: the guard
        # is a daemon callback, and 7-sample blocks must not turn into 480 calls in 6 s.
        last = self._last_speech_poll_t
        if last is not None and 0.0 <= t_now - last < _SPEECH_POLL_S:
            return
        self._last_speech_poll_t = t_now
        try:
            speaking = bool(self.speech_guard())
        except Exception:  # fail closed: an unreadable guard means "assume talking"
            log.warning("jaw: speech_guard raised; treating as speaking", exc_info=True)
            speaking = True
        if speaking:
            self._speech_until = t_now + self.speech_hangover_s

    # -- baseline ----------------------------------------------------------------

    def _end_of_hop(self, t_now: float) -> None:
        value = self._acc_sum / max(1, self._acc_cnt)
        self._acc_sum, self._acc_cnt = 0.0, 0
        if self._n < self._startup_n:
            return  # filter start-up transient is not a baseline
        talking = self._speech_until >= t_now
        in_burst = self._active and (self._n - self._onset_n) / self.fs <= self.max_duration_s
        if talking or in_burst:
            return
        self._hops.append(value)
        if len(self._hops) < self._warm_hops:
            return
        arr = np.fromiter(self._hops, dtype=np.float64, count=len(self._hops))
        base = float(np.median(arr))
        mad = float(np.median(np.abs(arr - base)))
        self._base = base
        self._scale = max(_MAD_TO_SIGMA * mad, self.min_scale_db)

    # -- burst state machine -------------------------------------------------------

    def _scan(self, seg: FloatArray, t_seg0: float) -> list[BioEvent]:
        assert self._base is not None
        delta = seg - self._base
        on_th = max(self.on_db, self.on_z * self._scale)
        off_th = max(self.off_db, self.off_z * self._scale)
        if self.min_burst_power_uv2 > 0.0:
            # Absolute floor, in the same dB-above-baseline units as ``delta``.
            on_th = max(on_th, 10.0 * math.log10(self.min_burst_power_uv2) - self._base)
        if not self._active and float(delta.max()) < on_th:
            return []
        out: list[BioEvent] = []
        for j in range(seg.size):
            v = float(delta[j])
            gn = self._n + j
            ts = t_seg0 + j / self.fs
            if not self._active:
                if v >= on_th:
                    self._active = True
                    self._decided = False
                    self._below = 0
                    self._onset_n = gn
                    self._onset_ts = ts
                    self._peak_db = v
                    self._onsets.append(ts - self._delay_s)
                continue
            self._peak_db = max(self._peak_db, v)
            if v < off_th:
                self._below += 1
                if self._below >= self._off_n:
                    if not self._decided:
                        self.stats["short_bursts"] += 1
                    self._active = False
                continue
            self._below = 0
            if not self._decided and gn - self._onset_n + 1 >= self._min_dur_n:
                self._decided = True
                out.extend(self._confirm(ts, gn))
        return out

    def _confirm(self, t_conf: float, gn: int) -> list[BioEvent]:
        onset_t = self._onset_ts - self._delay_s
        if self._speech_until >= onset_t:
            self.stats["suppressed_speech"] += 1
            return []
        if self.chewing_rhythm_suppressed():
            self.stats["suppressed_chewing"] += 1
            self._pending = None  # earlier bursts of the same chewing run, still held
            return []
        if self._last_event_t is not None and onset_t - self._last_event_t < self.refractory_s:
            self.stats["suppressed_refractory"] += 1
            return []
        self._last_event_t = onset_t

        sustained = (gn - self._onset_n + 1) / self.fs
        z = self._peak_db / self._scale
        amp = float(np.clip(self._peak_db / (2.0 * max(self.on_db, self.on_z * self._scale)),
                            0.0, 1.0))
        dur = float(np.clip(sustained / (2.0 * self.min_duration_s), 0.0, 1.0))
        event = BioEvent(
            EventKind.JAW_CLENCH,
            onset_t,
            float(np.clip(0.5 * (amp + dur), 0.0, 1.0)),
            ",".join(self._selector.names),
            {
                "peak_db": self._peak_db,
                "z_score": z,
                "sustained_s": sustained,
                "baseline_db": self._base,
                "scale_db": self._scale,
                "confirmed_t": t_conf - self._delay_s,
            },
        )
        self.stats["clenches"] += 1
        out: list[BioEvent] = []
        if self._pending is not None:
            # Not a chewing cadence after all (checked above): the held one stands.
            out.append(self._pending.event)
            self._pending = None
        if self.chew_holdoff_s > 0.0:
            self._pending = _PendingJaw(event, t_conf + self.chew_holdoff_s)
        else:
            out.append(event)
        return out


# --------------------------------------------------------------------------- the bank


class ArtifactBank:
    """Fan one ``SampleBlock`` out to several detectors; return the merged events.

    Events come back sorted by time (stable, so ties keep detector order). The bank is
    itself a ``StreamDetector``, so banks nest. A detector that raises is logged and
    skipped for that block -- one faulty electrode channel must not silence the others --
    and counted in ``errors``.
    """

    def __init__(self, detectors: Sequence[StreamDetector]) -> None:
        self.detectors: tuple[StreamDetector, ...] = tuple(detectors)
        self.errors = 0

    def process(self, block: SampleBlock) -> list[BioEvent]:
        merged: list[BioEvent] = []
        for det in self.detectors:
            try:
                merged.extend(det.process(block))
            except Exception:
                self.errors += 1
                log.warning("artifact detector %s failed", type(det).__name__, exc_info=True)
        merged.sort(key=lambda e: e.t)
        return merged

    def reset(self) -> None:
        for det in self.detectors:
            det.reset()
        self.errors = 0
