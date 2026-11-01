"""Streaming, stateful, numpy-only DSP for multichannel bio-signal blocks.

Every detector in ``yazses.biosignal`` (squeeze, blink, jaw clench) reads a signal that
has first been cleaned here. Cleaning is where most false triggers are born or prevented,
so each design choice below is tied to the failure it avoids.

Why this module exists in this shape
------------------------------------

* **Stateful, block-size independent.** Boards deliver blocks of whatever size the poll
  happened to catch (``BrainFlowSource`` polls at 50 Hz, a file replay may hand over one
  sample at a time). A filter that restarts per block produces a start-up transient at
  every block edge, which is a periodic fake "onset". Here the delay-line state is carried
  across calls, so ``process(a); process(b)`` equals ``process(concatenate(a, b))`` for any
  split. (Verified numerically by the author's scratch check, not by a committed test.)

* **Second-order sections (SOS), not one high-order polynomial.** A band-pass of 0.5 Hz
  at a 250 Hz sample rate has poles within ~0.01 of the unit circle. Expanding that into
  a single ``b``/``a`` polynomial makes the coefficients so sensitive to rounding that the
  filter can become unstable; cascading biquads keeps each section well-conditioned.
  Everything runs in float64 for the same reason.

* **Steady-state initialisation.** Bio-amplifiers present a DC offset thousands of times
  larger than the signal. A filter started from a zero state sees that offset as a huge
  step, rings for seconds, and the ring looks exactly like a burst. On the first sample of
  a stream each section is instead initialised to its *steady state for a constant input
  equal to that sample* (the same idea as ``scipy.signal.lfilter_zi``), so a constant
  input produces no transient. Call :meth:`reset` to re-arm it, e.g. after a gap.

* **Causal only.** Filtering forwards-and-backwards (``filtfilt``) would need future
  samples, so it cannot run live. The price is phase delay; detectors that need onset
  timing must account for it.

* **Non-finite guard.** A dropped packet or a driver glitch can deliver ``NaN``/``Inf``.
  One of them fed into a recursive (IIR) filter poisons its state permanently and every
  later output is ``NaN``. :class:`FiniteGuard` replaces each bad sample with the last good
  value of that channel (zero before any good sample) *before* it reaches a filter, and
  counts how many it replaced so the caller can surface a data-quality warning instead of
  silently trusting repaired data.

* **Refuse impossible designs loudly.** A band edge at or above Nyquist, or a sample rate
  too low to hold the requested band, would otherwise yield a filter that quietly does
  something else. ``ValueError`` with the numbers in the message is raised instead.

* **Denormal flush.** After the input goes silent, recursive state decays toward zero
  through subnormal floats, which many CPUs process orders of magnitude slower. States
  below 1e-30 are flushed to exactly zero each block; this is far below any microvolt
  signal and costs one comparison per section.

Design choices that are *not* from the literature
-------------------------------------------------

The pass bands are conventional ranges for each signal class, and the safety margins
(upper edge at most 0.45 * fs, a band at least one octave wide, notch Q = 30, 4th-order
edges for EMG/EEG, 2nd-order for EOG, envelope cut-off 5 Hz) are engineering choices made
for this package, not figures taken from ``docs/research/muscle-brain-control.md``. They
are constants at the top of the file so they can be revisited when real recordings exist.
The Teager-Kaiser operator is the one named in ``yazses.platform.emg.pressure``; this
module provides its block-continuous streaming equivalent and leaves ``pressure.py``
untouched.

Performance (measured, see below; added in the DSP-performance pass)
--------------------------------------------------------------------

The first implementation ran one Python-level step per sample per section (vectorised
across channels only). Measured on one development machine (numpy 2.4, single thread; the
EMG and EEG chains, 250/500/1000 Hz, 4/8/16 channels, blocks of 32/64/256 samples):
up to 4.5 % of one core in real time (1 kHz), ~38 us per sample. The same grid now peaks at
0.24 % (numpy back-end), i.e. 15x to 38x less CPU. :class:`SosFilter` has two
interchangeable back-ends over the *same* transposed direct-form II state
(``(n_sections, n_ch, 2)``), selected once at construction:

* ``numpy`` (always available, the default when scipy has not been imported). Each section
  is a linear time-invariant system, so a block of ``m <= 64`` samples is computed
  *exactly* (not by truncation) as ``y = x @ H + z @ G`` and
  ``z_new = z + z @ (A^m - I) + x @ Q`` with the impulse-response Toeplitz matrix ``H`` and
  the state-propagation tables ``G``, ``A^m - I``, ``Q`` derived once per distinct section
  (cached, read-only, ~37 kB and ~1 ms per section). Longer blocks are processed
  in chunks of 64 with the state carried between chunks, so there is no start-up transient
  anywhere. A single-sample chunk uses the plain per-sample recursion, which is
  cheaper than six small matrix products (the matrix form wins from two samples up).
* ``scipy`` (optional, lazy). ``scipy.signal.sosfilt`` with ``zi`` runs the same
  recursion in C (bit-identical to the original loop in the measurements below). It is
  imported only on an explicit ``backend="scipy"``; ``backend="auto"`` (the default) uses it
  only when the host process has already imported ``scipy.signal``, and never imports it
  just for this (importing it measured ~0.9 s and ~66 MB, for a ~2x gain over ``numpy``).

Equivalence with the original per-sample loop, measured over random block splits (sizes
0, 1, 2..300) and NaN/Inf input: the scipy back-end is bit-identical; the numpy back-end
differs by ~4e-12 for the EMG chain and ~3e-9 for the EEG chain on 600 000 samples riding on
a 900-unit offset, with no growth over time, and by up to 1e-7 in the most extreme corner
tried (0.1 Hz high-pass at 2 kHz on a +-2000-unit offset), where the filter itself has a
DC-gain denominator of ~1e-8 and so amplifies float64 coefficient rounding by ~1e8; that is
~1e-10 of the offset, far below any ADC resolution. The block form sums the same terms in a
different order, so ``process(a); process(b)`` equals ``process(concatenate(a, b))`` to
float tolerance rather than bit-for-bit, and which chunk boundaries fall where depends on
the block sizes. State, NaN repair and the first-sample steady-state start are unchanged.

Pure: numpy + stdlib only (scipy optional, lazy); no I/O, no threads.
"""

from __future__ import annotations

import importlib
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from functools import lru_cache
from typing import Any, NamedTuple, Protocol

import numpy as np

from yazses.biosignal.types import SampleBlock

__all__ = [
    "Biquad",
    "EnvelopeFollower",
    "FilterChain",
    "FiniteGuard",
    "RunningMeanDetrender",
    "SosFilter",
    "Stage",
    "Tkeo",
    "bipolar",
    "build_eeg_chain",
    "build_emg_chain",
    "build_eog_chain",
    "common_average_reference",
    "design_butterworth_bandpass",
    "design_butterworth_lowpass",
    "design_highpass",
    "design_lowpass",
    "design_notch",
    "detrend_running_mean",
    "rectify_envelope",
    "tkeo",
]

# ---------------------------------------------------------------------------
# Constants (design choices, see module docstring)
# ---------------------------------------------------------------------------

# A band edge may not exceed this fraction of fs. Butterworth low-passes are warped hard
# near Nyquist, so an edge at 0.5*fs would have almost no roll-off before aliasing.
_NYQUIST_FRACTION = 0.45
# A usable pass band must span at least this ratio (one octave): narrower than that is a
# resonator, not a band, and almost always means fs was configured wrongly.
_MIN_BAND_RATIO = 2.0
# Notch quality factor: -3 dB width = f0 / Q (1.7 Hz at 50 Hz). Wide enough to follow the
# small drift of the mains frequency, narrow enough to leave neighbouring EMG energy alone.
_DEFAULT_NOTCH_Q = 30.0
# Recursive states smaller than this are flushed to zero (denormal protection).
_FLUSH_EPS = 1e-30
# Samples per exact block-matrix step in the numpy back-end. Memory per distinct section is
# ~ (64*64 + 64*2*2 + ...) * 8 bytes (~34 kB); larger chunks cost O(chunk) more flops per
# sample, smaller ones pay more Python overhead per sample.
_BLOCK_CHUNK = 64
# Chunks of at most this many samples use the per-sample recursion instead of the matrices
# (measured: the matrix form already wins at 2 samples, 33 vs 52 us/sample on the EMG chain).
_LOOP_MAX = 1
_BACKENDS = ("auto", "numpy", "scipy")

EMG_BAND_HZ = (20.0, 450.0)
EEG_BAND_HZ = (0.5, 40.0)
EOG_BAND_HZ = (0.1, 20.0)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _check_fs(fs: float) -> float:
    fs = float(fs)
    if not math.isfinite(fs) or fs <= 0.0:
        raise ValueError(f"sampling rate must be a positive finite number, got {fs!r}")
    return fs


def _check_freq(name: str, freq_hz: float, fs: float) -> float:
    f = float(freq_hz)
    if not math.isfinite(f) or not 0.0 < f < fs / 2.0:
        raise ValueError(
            f"{name} must satisfy 0 < {name} < fs/2 (Nyquist); got {name}={f!r} Hz "
            f"with fs={fs!r} Hz (Nyquist = {fs / 2.0!r} Hz)"
        )
    return f


def _check_order(order: int) -> int:
    if isinstance(order, bool) or not isinstance(order, int) or order < 1:
        raise ValueError(f"filter order must be an integer >= 1, got {order!r}")
    return order


def _as_2d(x: np.ndarray) -> tuple[np.ndarray, bool]:
    """Return ``(float64 array of shape (n_ch, n), was_1d)``. Never aliases a write target."""
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim == 1:
        return arr[np.newaxis, :], True
    if arr.ndim != 2:
        raise ValueError(f"expected data of shape (n_channels, n_samples), got ndim={arr.ndim}")
    return arr, False


# ---------------------------------------------------------------------------
# Biquad + filter design
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Biquad:
    """One second-order section, normalised so a0 = 1.

    ``y[n] = b0 x[n] + b1 x[n-1] + b2 x[n-2] - a1 y[n-1] - a2 y[n-2]``. A first-order
    section is simply a biquad with ``b2 = a2 = 0``.
    """

    b0: float
    b1: float
    b2: float
    a1: float
    a2: float

    def is_stable(self) -> bool:
        """True when both poles are strictly inside the unit circle (Jury criterion)."""
        return abs(self.a2) < 1.0 and abs(self.a1) < 1.0 + self.a2

    def dc_gain(self) -> float:
        """Gain at 0 Hz; ``nan`` for a section with a pole exactly at z = 1."""
        den = 1.0 + self.a1 + self.a2
        if abs(den) < 1e-12:
            return float("nan")
        return (self.b0 + self.b1 + self.b2) / den

    def response(self, freq_hz: np.ndarray | Sequence[float], fs: float) -> np.ndarray:
        """Complex frequency response at ``freq_hz`` (Hz) for sample rate ``fs``."""
        w = 2.0 * np.pi * np.asarray(freq_hz, dtype=np.float64) / float(fs)
        z1 = np.exp(-1j * w)
        z2 = z1 * z1
        num = self.b0 + self.b1 * z1 + self.b2 * z2
        den = 1.0 + self.a1 * z1 + self.a2 * z2
        return np.asarray(num / den)


def _rbj(kind: str, freq_hz: float, fs: float, q: float) -> Biquad:
    """RBJ audio-EQ-cookbook biquad (bilinear transform with the corner pre-warped,
    so the corner/notch lands exactly on ``freq_hz`` rather than being squeezed by warping).
    """
    w0 = 2.0 * math.pi * freq_hz / fs
    cos_w0 = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * q)
    if kind == "lp":
        b0, b1, b2 = (1.0 - cos_w0) / 2.0, 1.0 - cos_w0, (1.0 - cos_w0) / 2.0
    elif kind == "hp":
        b0, b1, b2 = (1.0 + cos_w0) / 2.0, -(1.0 + cos_w0), (1.0 + cos_w0) / 2.0
    elif kind == "notch":
        b0, b1, b2 = 1.0, -2.0 * cos_w0, 1.0
    else:  # pragma: no cover - internal
        raise ValueError(kind)
    a0 = 1.0 + alpha
    return Biquad(b0 / a0, b1 / a0, b2 / a0, (-2.0 * cos_w0) / a0, (1.0 - alpha) / a0)


def _first_order(kind: str, freq_hz: float, fs: float) -> Biquad:
    """Bilinear-transform first-order low/high-pass (used for odd Butterworth orders)."""
    k = math.tan(math.pi * freq_hz / fs)
    norm = 1.0 + k
    a1 = (k - 1.0) / norm
    if kind == "lp":
        return Biquad(k / norm, k / norm, 0.0, a1, 0.0)
    return Biquad(1.0 / norm, -1.0 / norm, 0.0, a1, 0.0)


def _butterworth(kind: str, freq_hz: float, fs: float, order: int) -> list[Biquad]:
    """Butterworth low/high-pass of ``order`` as cascaded sections.

    Section k of an order-n Butterworth has Q_k = 1 / (2 sin((2k+1) pi / (2n))); an odd
    order adds one first-order section. Cascading them (rather than one polynomial) is the
    conditioning argument in the module docstring.
    """
    sections: list[Biquad] = []
    for k in range(order // 2):
        q = 1.0 / (2.0 * math.sin((2 * k + 1) * math.pi / (2.0 * order)))
        sections.append(_rbj(kind, freq_hz, fs, q))
    if order % 2:
        sections.append(_first_order(kind, freq_hz, fs))
    return sections


def design_lowpass(cutoff_hz: float, fs: float, order: int = 2) -> list[Biquad]:
    """Butterworth low-pass as second-order sections. ``0 < cutoff_hz < fs/2``."""
    fs = _check_fs(fs)
    return _butterworth("lp", _check_freq("cutoff_hz", cutoff_hz, fs), fs, _check_order(order))


def design_highpass(cutoff_hz: float, fs: float, order: int = 2) -> list[Biquad]:
    """Butterworth high-pass as second-order sections. ``0 < cutoff_hz < fs/2``."""
    fs = _check_fs(fs)
    return _butterworth("hp", _check_freq("cutoff_hz", cutoff_hz, fs), fs, _check_order(order))


# Alias with the longer name for symmetry with ``design_butterworth_bandpass``.
design_butterworth_lowpass = design_lowpass


def design_butterworth_bandpass(
    low_hz: float, high_hz: float, fs: float, order: int = 4
) -> list[Biquad]:
    """Band-pass as a high-pass at ``low_hz`` cascaded with a low-pass at ``high_hz``.

    ``order`` is applied to *each* edge (so the roll-off per edge is 6*order dB/octave
    and the cascade has ``2*order`` poles, the same count ``scipy.signal.butter(order,
    ..., 'band')`` uses). Requires ``0 < low_hz < high_hz < fs/2``; anything else raises
    ``ValueError`` naming the offending numbers.
    """
    fs = _check_fs(fs)
    order = _check_order(order)
    low = float(low_hz)
    high = float(high_hz)
    if not (math.isfinite(low) and math.isfinite(high) and 0.0 < low < high < fs / 2.0):
        raise ValueError(
            f"band-pass edges must satisfy 0 < low_hz < high_hz < fs/2; got low_hz={low_hz!r}, "
            f"high_hz={high_hz!r} with fs={fs!r} Hz (Nyquist = {fs / 2.0!r} Hz). "
            "The sampling rate is too low for this band."
        )
    return _butterworth("hp", low, fs, order) + _butterworth("lp", high, fs, order)


def design_notch(freq_hz: float, fs: float, q: float = _DEFAULT_NOTCH_Q) -> list[Biquad]:
    """Second-order notch at ``freq_hz`` with quality factor ``q`` (-3 dB width = f/q).

    Single-frequency notch for mains hum. ``0 < freq_hz < fs/2`` and ``q > 0`` are enforced.
    """
    fs = _check_fs(fs)
    f = _check_freq("freq_hz", freq_hz, fs)
    q = float(q)
    if not math.isfinite(q) or q <= 0.0:
        raise ValueError(f"notch q must be a positive finite number, got {q!r}")
    return [_rbj("notch", f, fs, q)]


# ---------------------------------------------------------------------------
# Non-finite guard
# ---------------------------------------------------------------------------


class FiniteGuard:
    """Replace NaN/Inf by the previous good value of the same channel.

    State: the last good value per channel (0.0 before any). ``n_replaced`` counts every
    replaced sample since construction or :meth:`reset_counts`; ``reset`` clears only the
    carried value. Returns the input array itself (no copy) when nothing needed repair.
    """

    def __init__(self) -> None:
        self._last: np.ndarray | None = None
        self.n_replaced: int = 0

    def reset(self) -> None:
        self._last = None

    def reset_counts(self) -> None:
        self.n_replaced = 0

    def apply(self, x: np.ndarray) -> np.ndarray:
        """``x`` is ``(n_ch, n)`` float64; returns an array of the same shape."""
        n_ch, n = x.shape
        if self._last is None or self._last.shape[0] != n_ch:
            self._last = np.zeros(n_ch, dtype=np.float64)
        if n == 0:
            return x
        finite = np.isfinite(x)
        if finite.all():
            self._last = x[:, -1].copy()
            return x
        self.n_replaced += int((~finite).sum())
        # Forward-fill: index of the most recent finite sample, column 0 = carried value.
        ext = np.concatenate([self._last[:, np.newaxis], x], axis=1)
        ok = np.concatenate([np.ones((n_ch, 1), dtype=bool), finite], axis=1)
        idx = np.where(ok, np.arange(n + 1)[np.newaxis, :], 0)
        np.maximum.accumulate(idx, axis=1, out=idx)
        filled = np.take_along_axis(ext, idx, axis=1)[:, 1:]
        self._last = filled[:, -1].copy()
        return np.ascontiguousarray(filled)


# ---------------------------------------------------------------------------
# SOS filter
# ---------------------------------------------------------------------------


class _BlockTables(NamedTuple):
    """Exact block-form tables for one biquad over chunks of up to ``chunk`` samples.

    With state ``z = (z1, z2)`` and ``A = [[-a1, 1], [-a2, 0]]``, ``B = (b1 - a1*b0,
    b2 - a2*b0)``: ``y[n] = b0 x[n] + z1[n]`` and ``z[n+1] = A z[n] + B x[n]``. Unrolling
    over ``m`` samples gives the products documented in the module docstring.
    """

    ht: np.ndarray  # (chunk, chunk): ht[k, n] = impulse response h[n - k] (0 for n < k)
    g: np.ndarray  # (2, chunk): zero-input response, y_zi[n] = z1*g[0, n] + z2*g[1, n]
    dapt: np.ndarray  # (chunk + 1, 2, 2): (A**m - I).T, so z_new = z + z @ dapt[m] + ...
    pr: np.ndarray  # (chunk, 2): pr[chunk - m + k] = A**(m-1-k) @ B (rows reversed in time)


@lru_cache(maxsize=64)
def _block_tables(sec: Biquad, chunk: int) -> _BlockTables:
    """Build (and cache, shared between filters of equal design) the tables of ``sec``.

    The powers of ``A`` are accumulated in 60-digit decimal arithmetic and rounded to
    float64 once at the end. A section with poles at ~0.9999 (0.1 Hz at 2 kHz) makes the
    block form cancel terms of ~1e3 against each other; tables built in plain float64
    carried ~64 roundings each and were measured ~200x less accurate than the per-sample
    recursion on a 1800-unit offset, rounded once they are not. The state map is stored as
    ``A**m - I`` (rounded from the exact value) and added to ``z``: rounding ``A**m`` itself
    would shift its slowest eigenvalue by ~1e-16 *every chunk*, a systematic error that a
    pole at 0.9999 integrates ~140-fold.
    """
    with localcontext() as ctx:
        ctx.prec = 60
        d = Decimal
        a11, a12, a21, a22 = -d(sec.a1), d(1), -d(sec.a2), d(0)
        b0 = d(sec.b0)
        bv1 = d(sec.b1) - d(sec.a1) * b0
        bv2 = d(sec.b2) - d(sec.a2) * b0
        apow = np.empty((chunk + 1, 2, 2))  # A**j, for the zero-input response
        dpow = np.empty((chunk + 1, 2, 2))  # A**j - I, rounded once from the exact value
        p = np.empty((chunk, 2))  # P[j] = A**j @ B
        m11, m12, m21, m22 = d(1), d(0), d(0), d(1)  # A**0
        for j in range(chunk + 1):
            apow[j] = ((float(m11), float(m12)), (float(m21), float(m22)))
            dpow[j] = ((float(m11 - 1), float(m12)), (float(m21), float(m22 - 1)))
            if j < chunk:
                p[j] = (float(m11 * bv1 + m12 * bv2), float(m21 * bv1 + m22 * bv2))
            m11, m12, m21, m22 = (
                a11 * m11 + a12 * m21,
                a11 * m12 + a12 * m22,
                a21 * m11 + a22 * m21,
                a21 * m12 + a22 * m22,
            )
    h = np.empty(chunk)
    h[0] = sec.b0
    h[1:] = p[: chunk - 1, 0]  # h[j] = C A**(j-1) B with C = (1, 0)
    lag = np.arange(chunk)[np.newaxis, :] - np.arange(chunk)[:, np.newaxis]
    ht = np.where(lag >= 0, h[np.maximum(lag, 0)], 0.0)
    tables = _BlockTables(
        ht=np.ascontiguousarray(ht),
        g=np.ascontiguousarray(apow[:chunk, 0, :].T),
        dapt=np.ascontiguousarray(dpow.transpose(0, 2, 1)),
        pr=np.ascontiguousarray(p[::-1]),
    )
    for arr in tables:
        arr.setflags(write=False)
    return tables


@lru_cache(maxsize=1)
def _load_scipy_sosfilt() -> Callable[..., Any] | None:
    """``scipy.signal.sosfilt`` if scipy imports, else ``None`` (decided once per process)."""
    try:
        fn = getattr(importlib.import_module("scipy.signal"), "sosfilt", None)
    except ImportError:
        return None
    return fn  # type: ignore[no-any-return]


class SosFilter:
    """Cascade of biquads, vectorised across channels, state carried between calls.

    Direct form II transposed: two state variables per section per channel, the form with
    the best round-off behaviour for the low-corner high-passes used on bio-signals.
    The channel count is fixed by the first call; a different count later raises
    ``ValueError`` (a re-ordered or re-sized board is a configuration error, not something
    to silently re-initialise).

    ``backend`` picks the arithmetic engine once, at construction: ``"numpy"`` (exact
    block-matrix form, see the module docstring), ``"scipy"`` (``scipy.signal.sosfilt``;
    imports scipy, ``ImportError`` if it is missing) or ``"auto"``: scipy *only if*
    ``scipy.signal`` is already imported by the host process, otherwise numpy. ``"auto"``
    never imports scipy itself, because that costs ~0.9 s and ~66 MB (measured) to save
    ~0.1 % of a core. The state layout is identical, so the choice never changes behaviour
    beyond float rounding.
    """

    def __init__(
        self, sections: Sequence[Biquad], *, settle: bool = True, backend: str = "auto"
    ) -> None:
        if not sections:
            raise ValueError("SosFilter needs at least one section")
        for i, s in enumerate(sections):
            if not s.is_stable():
                raise ValueError(f"section {i} is unstable: {s!r}")
        if backend not in _BACKENDS:
            raise ValueError(f"backend must be one of {_BACKENDS}, got {backend!r}")
        self.sections: tuple[Biquad, ...] = tuple(sections)
        self.settle = settle
        self._coef = np.array([[s.b0, s.b1, s.b2, s.a1, s.a2] for s in self.sections])
        self._rows: tuple[tuple[float, float, float, float, float], ...] = tuple(
            (s.b0, s.b1, s.b2, s.a1, s.a2) for s in self.sections
        )
        self._guard = FiniteGuard()
        self._zi: np.ndarray | None = None  # (n_sections, n_ch, 2): z1, z2 per section/channel
        self._sosfilt: Callable[..., Any] | None = None
        if backend == "scipy" or (backend == "auto" and "scipy.signal" in sys.modules):
            self._sosfilt = _load_scipy_sosfilt()
            if self._sosfilt is None and backend == "scipy":
                raise ImportError("SosFilter(backend='scipy') needs scipy, which is not installed")
        self._sos: np.ndarray | None = None
        self._tables: tuple[_BlockTables, ...] = ()
        if self._sosfilt is not None:
            self._sos = np.array(
                [[s.b0, s.b1, s.b2, 1.0, s.a1, s.a2] for s in self.sections]
            )
        else:
            self._tables = tuple(_block_tables(s, _BLOCK_CHUNK) for s in self.sections)

    @property
    def backend(self) -> str:
        """The engine actually in use: ``"numpy"`` or ``"scipy"``."""
        return "scipy" if self._sosfilt is not None else "numpy"

    @property
    def n_nonfinite(self) -> int:
        """Count of NaN/Inf samples replaced at this filter's input."""
        return self._guard.n_replaced

    def reset_counts(self) -> None:
        self._guard.reset_counts()

    def reset(self) -> None:
        """Forget all signal state; the next sample re-initialises to steady state."""
        self._zi = None
        self._guard.reset()

    def magnitude_response(self, freq_hz: np.ndarray | Sequence[float], fs: float) -> np.ndarray:
        """|H(f)| of the whole cascade, for design checks and documentation plots."""
        h = np.ones(len(np.atleast_1d(freq_hz)), dtype=np.complex128)
        for s in self.sections:
            h = h * s.response(freq_hz, fs)
        return np.abs(h)

    def _init_state(self, x0: np.ndarray) -> None:
        n_sec = len(self.sections)
        n_ch = x0.shape[0]
        zi = np.zeros((n_sec, n_ch, 2))
        if self.settle:
            level = x0.copy()
            for i, s in enumerate(self.sections):
                g = s.dc_gain()
                if math.isnan(g):
                    break
                z2 = (s.b2 - s.a2 * g) * level
                zi[i, :, 1] = z2
                zi[i, :, 0] = (s.b1 - s.a1 * g) * level + z2
                level = g * level
        self._zi = zi

    def process(self, x: np.ndarray) -> np.ndarray:
        """Filter ``x`` of shape ``(n_ch, n)`` (or 1-D, one channel); returns a new float64 array."""
        arr, was_1d = _as_2d(x)
        n_ch, n = arr.shape
        clean = self._guard.apply(arr)
        if n == 0:
            return np.empty((n_ch, 0)).reshape(-1) if was_1d else np.empty((n_ch, 0))
        if self._zi is None:
            self._init_state(clean[:, 0])
        assert self._zi is not None
        if self._zi.shape[1] != n_ch:
            raise ValueError(
                f"channel count changed from {self._zi.shape[1]} to {n_ch}; "
                "reset() the filter or build a new one"
            )
        if self._sosfilt is not None:
            result, zf = self._sosfilt(self._sos, clean, axis=-1, zi=self._zi)
            self._zi = np.ascontiguousarray(zf, dtype=np.float64)
            result = np.ascontiguousarray(result, dtype=np.float64)
        else:
            result = self._process_numpy(clean)
        # Denormal flush: tiny recursive states become exactly zero (see module docstring).
        np.putmask(self._zi, np.abs(self._zi) < _FLUSH_EPS, 0.0)
        return result[0] if was_1d else result

    def _process_numpy(self, x: np.ndarray) -> np.ndarray:
        """Cascade over ``x`` (n_ch, n) in chunks; updates ``self._zi`` in place."""
        assert self._zi is not None
        n = x.shape[1]
        chunk = _BLOCK_CHUNK
        cur = x
        for i, tab in enumerate(self._tables):
            z = self._zi[i]  # (n_ch, 2) view into the state
            out = np.empty_like(cur)
            for s in range(0, n, chunk):
                m = min(chunk, n - s)
                xs = cur[:, s : s + m]
                if m <= _LOOP_MAX:
                    self._loop_section(self._rows[i], xs, z, out[:, s : s + m])
                    continue
                ys = xs @ tab.ht[:m, :m]
                ys += z @ tab.g[:, :m]
                z_new = z @ tab.dapt[m]
                z_new += xs @ tab.pr[chunk - m :]
                z_new += z
                out[:, s : s + m] = ys
                z[...] = z_new
            cur = out
        return cur

    @staticmethod
    def _loop_section(
        coef: tuple[float, float, float, float, float],
        xs: np.ndarray,
        z: np.ndarray,
        out: np.ndarray,
    ) -> None:
        """Plain per-sample transposed DF-II step for a few samples (cheaper than matrices)."""
        b0, b1, b2, a1, a2 = coef
        z1 = z[:, 0].copy()
        z2 = z[:, 1].copy()
        for k in range(xs.shape[1]):
            xk = xs[:, k]
            yk = b0 * xk + z1
            z1 = b1 * xk - a1 * yk + z2
            z2 = b2 * xk - a2 * yk
            out[:, k] = yk
        z[:, 0] = z1
        z[:, 1] = z2


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------


class Stage(Protocol):
    """Anything a :class:`FilterChain` can run: stateful ``process``/``reset``."""

    def process(self, x: np.ndarray) -> np.ndarray: ...
    def reset(self) -> None: ...


class FilterChain:
    """Stages applied in order; a single finite-guard at the input protects all of them.

    ``fs`` (optional) is the rate the chain was designed for. :meth:`process_block` refuses
    a block at a different rate: a 250 Hz filter on 500 Hz data silently moves every corner.
    """

    def __init__(self, stages: Sequence[Stage], fs: float | None = None) -> None:
        self.stages: tuple[Stage, ...] = tuple(stages)
        self.fs: float | None = None if fs is None else _check_fs(fs)
        self._guard = FiniteGuard()

    @property
    def n_nonfinite(self) -> int:
        """Total NaN/Inf samples repaired at the chain input since construction/clear."""
        return self._guard.n_replaced

    def reset_counts(self) -> None:
        self._guard.reset_counts()

    def reset(self) -> None:
        self._guard.reset()
        for st in self.stages:
            st.reset()

    def process(self, x: np.ndarray) -> np.ndarray:
        arr, was_1d = _as_2d(x)
        cur = self._guard.apply(arr)
        for st in self.stages:
            cur = st.process(cur)
        return cur[0] if was_1d and cur.ndim == 2 else cur

    def process_block(self, block: SampleBlock) -> SampleBlock:
        """Filter a :class:`SampleBlock`; returns a new block with the same metadata."""
        if self.fs is not None and not math.isclose(block.fs, self.fs, rel_tol=1e-6):
            raise ValueError(
                f"block sampling rate {block.fs!r} Hz differs from the rate this chain was "
                f"designed for ({self.fs!r} Hz); build a new chain for the new rate"
            )
        out = self.process(block.data)
        return SampleBlock(data=out, fs=block.fs, channels=block.channels, t0=block.t0)


def _capped_high(target_hz: float, low_hz: float, fs: float, what: str) -> float:
    """Upper band edge = min(target, 0.45*fs); error if the result is not a real band."""
    fs = _check_fs(fs)
    high = min(target_hz, _NYQUIST_FRACTION * fs)
    if high < _MIN_BAND_RATIO * low_hz:
        raise ValueError(
            f"fs={fs!r} Hz is too low for the {what} band {low_hz}-{target_hz} Hz: the usable "
            f"upper edge (min(target, {_NYQUIST_FRACTION} * fs) = {high} Hz) is less than one "
            f"octave above the lower edge ({low_hz} Hz). Use a sampling rate of at least "
            f"{_MIN_BAND_RATIO * low_hz / _NYQUIST_FRACTION:.1f} Hz."
        )
    return high


def _mains_sections(
    mains_hz: float | None, fs: float, harmonics: int, q: float
) -> list[Biquad]:
    if mains_hz is None:
        return []
    f = float(mains_hz)
    if not math.isfinite(f) or f <= 0.0:
        raise ValueError(f"mains_hz must be a positive number (50 or 60) or None, got {mains_hz!r}")
    if f >= fs / 2.0:
        raise ValueError(
            f"mains_hz={mains_hz!r} Hz is at or above Nyquist for fs={fs!r} Hz, so the notch "
            "cannot be built (mains would alias into the band). Raise the sampling rate or "
            "pass mains_hz=None to skip the notch deliberately."
        )
    if harmonics < 1:
        raise ValueError(f"mains_harmonics must be >= 1, got {harmonics!r}")
    out = design_notch(f, fs, q)
    for k in range(2, harmonics + 1):
        if k * f < _NYQUIST_FRACTION * fs:
            out += design_notch(k * f, fs, q)
    return out


def build_emg_chain(
    fs: float,
    mains_hz: float | None = 50.0,
    *,
    order: int = 4,
    mains_harmonics: int = 1,
    notch_q: float = _DEFAULT_NOTCH_Q,
) -> FilterChain:
    """EMG chain: 20-450 Hz band-pass (upper edge limited to < 0.45*fs) + mains notch.

    The 20 Hz high-pass removes motion artefact and electrode drift (the low-frequency,
    large-amplitude interferers TKEO is also meant to ignore); the upper edge is capped so
    a 250 Hz board gets 20-112.5 Hz instead of an impossible 450 Hz edge. The band-pass
    runs before the notch so the large DC offset is gone before it reaches the high-Q notch.
    ``mains_hz=None`` skips the notch; ``mains_harmonics=2`` also notches 2*mains where it
    is below 0.45*fs (fs > 222 Hz for 50 Hz mains, > 267 Hz for 60 Hz); otherwise it is skipped.
    """
    fs = _check_fs(fs)
    low, target = EMG_BAND_HZ
    high = _capped_high(target, low, fs, "EMG")
    sections = design_butterworth_bandpass(low, high, fs, order)
    sections += _mains_sections(mains_hz, fs, mains_harmonics, notch_q)
    return FilterChain([SosFilter(sections)], fs=fs)


def build_eeg_chain(
    fs: float,
    mains_hz: float | None = 50.0,
    *,
    order: int = 4,
    mains_harmonics: int = 1,
    notch_q: float = _DEFAULT_NOTCH_Q,
) -> FilterChain:
    """EEG chain: 0.5-40 Hz band-pass (upper edge limited to < 0.45*fs) + mains notch.

    The notch is kept even though 50/60 Hz lies above the 40 Hz edge: the Butterworth
    skirt at the mains frequency is only a few dB down, and consumer headbands pick up
    mains strongly through high-impedance dry electrodes.
    """
    fs = _check_fs(fs)
    low, target = EEG_BAND_HZ
    high = _capped_high(target, low, fs, "EEG")
    sections = design_butterworth_bandpass(low, high, fs, order)
    sections += _mains_sections(mains_hz, fs, mains_harmonics, notch_q)
    return FilterChain([SosFilter(sections)], fs=fs)


def build_eog_chain(fs: float, *, order: int = 2) -> FilterChain:
    """EOG chain: 0.1-20 Hz band-pass (upper edge limited to < 0.45*fs), no notch.

    Blinks and saccades are slow (energy below ~20 Hz), so mains is already far outside
    the band. The default is 2nd order per edge: a steeper 0.1 Hz high-pass rings for
    tens of seconds, and that ringing looks like a slow eye movement.
    """
    fs = _check_fs(fs)
    low, target = EOG_BAND_HZ
    high = _capped_high(target, low, fs, "EOG")
    return FilterChain([SosFilter(design_butterworth_bandpass(low, high, fs, order))], fs=fs)


# ---------------------------------------------------------------------------
# Referencing and detrending
# ---------------------------------------------------------------------------


def common_average_reference(
    x: np.ndarray, channels: Sequence[int] | None = None
) -> np.ndarray:
    """Subtract the across-channel mean from every channel (CAR). Stateless; new array.

    ``channels`` restricts which rows form the average (default: all). A channel with a
    large artefact (a blink on the frontal electrode, a loose lead) leaks into every other
    channel through the mean; exclude it from ``channels`` to keep the reference clean.
    Needs at least two channels in the reference: with one, CAR would return all zeros,
    which is a configuration error rather than a signal, so ``ValueError`` is raised.
    """
    if np.ndim(x) != 2:
        raise ValueError("common_average_reference needs 2-D data (n_channels, n_samples)")
    arr, _ = _as_2d(x)
    ref_idx = list(range(arr.shape[0])) if channels is None else list(channels)
    if len(ref_idx) < 2:
        raise ValueError("common_average_reference needs at least two reference channels")
    ref = arr[ref_idx].mean(axis=0, keepdims=True)
    return np.asarray(arr - ref)


def bipolar(x: np.ndarray, a: int, b: int) -> np.ndarray:
    """Differential channel ``x[a] - x[b]`` as a ``(1, n)`` array (stays 2-D so it chains).

    A bipolar pair cancels interference common to both electrodes (mains, distant muscle)
    without the leakage CAR has, which is why it suits a two-electrode forearm squeeze.
    """
    if np.ndim(x) != 2:
        raise ValueError("bipolar needs 2-D data (n_channels, n_samples)")
    arr = np.asarray(x, dtype=np.float64)
    if a == b:
        raise ValueError("bipolar needs two different channels")
    return np.asarray(arr[a] - arr[b])[np.newaxis, :]


class RunningMeanDetrender:
    """Streaming DC/slow-drift removal: ``x - EMA(x)`` with time constant ``window_s``.

    An exponential running mean (a one-pole low-pass) is used instead of a boxcar so that
    state is two numbers per channel rather than a ring buffer of ``window_s * fs``
    samples, and block boundaries cannot matter. It starts at the first sample's value, so
    the first output is 0 instead of a large step.
    """

    def __init__(self, fs: float, window_s: float = 1.0) -> None:
        fs = _check_fs(fs)
        window_s = float(window_s)
        if not math.isfinite(window_s) or window_s * fs < 1.0:
            raise ValueError(
                f"window_s must be at least one sample ({1.0 / fs!r} s), got {window_s!r}"
            )
        alpha = 1.0 - math.exp(-1.0 / (fs * window_s))
        self._mean = SosFilter([Biquad(alpha, 0.0, 0.0, -(1.0 - alpha), 0.0)])

    @property
    def n_nonfinite(self) -> int:
        return self._mean.n_nonfinite

    def reset(self) -> None:
        self._mean.reset()

    def process(self, x: np.ndarray) -> np.ndarray:
        arr, was_1d = _as_2d(x)
        mean = self._mean.process(arr)
        # The mean was computed from the guard-repaired input; a bad sample is replaced
        # by the mean itself so it outputs 0 rather than NaN.
        clean = np.where(np.isfinite(arr), arr, mean)
        out = clean - mean
        return out[0] if was_1d else out


def detrend_running_mean(x: np.ndarray, fs: float, window_s: float = 1.0) -> np.ndarray:
    """One-shot :class:`RunningMeanDetrender` over a complete array (fresh state each call).

    For a live stream, hold a :class:`RunningMeanDetrender` instead so state survives
    between blocks.
    """
    return RunningMeanDetrender(fs, window_s).process(x)


# ---------------------------------------------------------------------------
# Envelope and TKEO
# ---------------------------------------------------------------------------


class EnvelopeFollower:
    """Streaming rectify + low-pass envelope: ``lowpass(|x|)``, clipped at zero.

    The low-pass is a Butterworth of ``order`` (default 2) at ``cutoff_hz`` (default 5 Hz,
    a design choice: slow enough to bridge the gaps between EMG zero-crossings, fast enough
    to track a squeeze that lasts a few hundred milliseconds). It starts at ``|x[0]|``, so
    there is no ramp-up from zero that a threshold would read as an onset. A Butterworth
    can undershoot slightly below zero after a burst; the result is clipped at 0 because an
    envelope of magnitude cannot be negative and negative values break log/ratio logic.
    """

    def __init__(self, fs: float, cutoff_hz: float = 5.0, order: int = 2) -> None:
        fs = _check_fs(fs)
        self._lp = SosFilter(design_lowpass(cutoff_hz, fs, order))

    @property
    def n_nonfinite(self) -> int:
        return self._lp.n_nonfinite

    def reset(self) -> None:
        self._lp.reset()

    def process(self, x: np.ndarray) -> np.ndarray:
        arr, was_1d = _as_2d(x)
        # |NaN| is NaN, which SosFilter's input guard repairs (and counts).
        out = self._lp.process(np.abs(arr))
        np.maximum(out, 0.0, out=out)
        return out[0] if was_1d else out


def rectify_envelope(
    x: np.ndarray, fs: float, cutoff_hz: float = 5.0, *, order: int = 2
) -> np.ndarray:
    """One-shot envelope of a complete array (fresh state). Live code uses
    :class:`EnvelopeFollower` so the low-pass state carries across blocks.
    """
    return EnvelopeFollower(fs, cutoff_hz, order).process(x)


def tkeo(
    x: np.ndarray, carry: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Block-continuous Teager-Kaiser energy operator.

    ``psi[n] = x[n]**2 - x[n-1] * x[n+1]`` needs both neighbours, so the newest sample of a
    block cannot be scored until the next block arrives. This function therefore runs one
    sample behind: it takes ``x`` of shape ``(n_ch, n)`` plus the ``carry`` returned by the
    previous call (the last two input samples, shape ``(n_ch, 2)``) and returns
    ``(psi, new_carry)`` where ``psi`` also has shape ``(n_ch, n)`` and ``psi[:, k]`` scores
    the sample that is one position earlier in the stream than ``x[:, k]``. Concatenating
    the outputs of consecutive calls equals the one-shot operator over the whole stream
    (shifted by one sample), whatever the block sizes. With ``carry=None`` the carry is
    ``x[:, 0]`` twice, so the very first output is exactly 0 (a placeholder, not a
    measurement). Input must be finite; use :class:`Tkeo` for the guarded stateful form.
    """
    arr, _ = _as_2d(x)
    n_ch, n = arr.shape
    if carry is not None and np.shape(carry) == (n_ch, 0):
        carry = None  # "no stream yet": an empty first block handed back a placeholder
    if carry is None:
        if n == 0:
            # Nothing to anchor the stream start on yet. An empty carry says "still at the
            # start", so the next call still uses x[:, 0] twice rather than invented zeros.
            return np.empty((n_ch, 0)), np.empty((n_ch, 0))
        c = np.repeat(arr[:, :1], 2, axis=1)
    else:
        c = np.asarray(carry, dtype=np.float64)
        if c.shape != (n_ch, 2):
            raise ValueError(f"carry must have shape ({n_ch}, 2), got {c.shape}")
    if n == 0:
        return np.empty((n_ch, 0)), c
    ext = np.concatenate([c, arr], axis=1)  # (n_ch, n + 2)
    psi = ext[:, 1:-1] ** 2 - ext[:, :-2] * ext[:, 2:]
    return psi, ext[:, -2:].copy()


class Tkeo:
    """Stateful, NaN-guarded wrapper around :func:`tkeo`.

    ``nonnegative=True`` clips the output at 0: TKEO of noise is occasionally negative,
    and detectors that compare against a threshold usually want an energy-like quantity.
    """

    def __init__(self, *, nonnegative: bool = False) -> None:
        self.nonnegative = nonnegative
        self._carry: np.ndarray | None = None
        self._guard = FiniteGuard()

    @property
    def n_nonfinite(self) -> int:
        return self._guard.n_replaced

    def reset(self) -> None:
        self._carry = None
        self._guard.reset()

    def process(self, x: np.ndarray) -> np.ndarray:
        arr, was_1d = _as_2d(x)
        clean = self._guard.apply(arr)
        if clean.shape[1] == 0:
            return np.empty(0) if was_1d else np.empty((clean.shape[0], 0))
        if self._carry is not None and self._carry.shape[0] != clean.shape[0]:
            raise ValueError(
                f"channel count changed from {self._carry.shape[0]} to {clean.shape[0]}; "
                "reset() the operator"
            )
        psi, self._carry = tkeo(clean, self._carry)
        if self.nonnegative:
            np.maximum(psi, 0.0, out=psi)
        return psi[0] if was_1d else psi
