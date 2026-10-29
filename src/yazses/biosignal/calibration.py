"""Per-user calibration for the bio-signal switches: measured, not guessed.

Electrode amplitude differs by roughly an order of magnitude between people, between
placements and between days (skin condition, contact pressure), so a fixed microvolt
threshold is meaningless: it either never fires or fires constantly.
``platform/emg/pressure.py`` already states the principle — thresholds are derived from the
user's *own* relaxed baseline and maximum contraction — and this module is the guided
procedure that produces those numbers, plus the artifact-detector references (blink, jaw
clench) that the other detectors in this package need.

## The procedure

A short, scripted sequence, driven by the caller feeding :class:`~yazses.biosignal.types.SampleBlock`
objects into a :class:`CalibrationSession`:

1. ``RELAX`` — sit still; records the resting level and the noise floor.
2. ``SQUEEZE_LIGHT`` — a gentle squeeze; records the *light* level.
3. ``SQUEEZE_HARD`` — a firm (comfortable, not painful) squeeze; the maximum-contraction
   reference. The graded switch places its thresholds as a fraction of the span between
   rest and this level, exactly as ``pressure.calibrate`` does.
4. ``BLINK_X3`` / ``CLENCH_X3`` (optional) — three deliberate blinks / jaw clenches, so the
   artifact detectors know what *this* person's artifact looks like.

Every phase is **validated before it is believed**. A "relax" phase that is not quiet, a
squeeze that does not clearly rise above the baseline, or a blink prompt that produced no
blinks yields a :class:`CalibrationIssue` carrying a plain-language reason, and the phase is
restarted — the session never silently produces thresholds from bad data, because a switch
calibrated on a noisy baseline fires at random (the same reason ``pressure.calibrate``
refuses an indistinguishable range).

## Design notes

* **Pure and deterministic.** No I/O, no threads, no board. Time enters through two injected
  callables (``clock`` for stall detection, ``wall_clock`` for ``created_at``); the *amount*
  of data per phase is counted in samples, so a replayed recording calibrates identically.
* **numpy + stdlib only.** No scipy: window RMS, a first difference (a crude high-pass for
  the jaw-clench feature) and a boxcar smoother are all that is needed.
* **Robust statistics.** Medians, MADs and percentiles rather than means and maxima, so one
  twitch or cable knock during the baseline does not move the result.
* **Every numeric choice below is a design choice, not a measured operating point.** The
  repository's research notes cite no per-person calibration constants; the defaults here
  (phase lengths, ratios, sigma multiples) are conditioning guards that keep the arithmetic
  well posed and the user from being handed thresholds built on nothing. They are exposed on
  :class:`CalibrationConfig` so they can be tuned once measured on people. The squeeze
  fractions 0.20 / 0.60 are *not* new: they are imported from ``pressure.py``.
* **No thought decoding.** Calibration only measures amplitude references for artifact-grade
  switches (muscle bursts, blinks, jaw clenches). Decoding thoughts stays rejected
  (ADR-v2-129, "Rejected").

## Units of the derived numbers

* ``baseline_rms``, ``noise_floor``, ``mvc_rms``, ``light_rms`` and the squeeze thresholds are
  windowed RMS in microvolts (window ``CalibrationConfig.window_s``, mean removed per window,
  power averaged over the channels of the relevant kind).
* ``blink_amplitude`` is the peak deviation, in microvolts, of the smoothed rectified signal
  from its median.
* ``clench_power`` is the mean squared first difference (microvolts squared per sample
  squared) averaged over the channels, taken inside the clench bursts.

## Privacy

A calibration profile is **biometric-adjacent**: it encodes how this person's muscles and
eyes sit under these electrodes. It is derived numbers only (never a raw trace — the session
drops its buffers the moment a phase is analysed and again on ``result()``/``abort()``), it
is written to the local data directory with mode ``0o600``, it never leaves the machine, and
it is **never logged in full**: ``repr()`` of a profile and every log line here carry
identity-free summaries (board, channel count, age), not the amplitudes.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind
from yazses.platform.emg.pressure import DEFAULT_HARD_FRACTION, DEFAULT_LIGHT_FRACTION

log = logging.getLogger(__name__)

#: Version of the on-disk profile layout. A loader meeting any other value returns ``None``.
SCHEMA_VERSION = 1

#: File name of the profile under the data directory.
PROFILE_FILENAME = "biosignal_calibration.json"

#: Profiles older than this are reported stale. Design choice: electrode placement and skin
#: condition drift between days, so a week is already generous; ``pressure.py`` calls
#: calibration "per person and per session".
DEFAULT_MAX_AGE_DAYS = 7.0

#: A profile larger than this is not ours (a real one is well under 2 KiB).
_MAX_PROFILE_BYTES = 1 << 20

#: Relative tolerance when comparing sampling rates for "same board setting".
_FS_REL_TOL = 0.01

#: A profile stamped this far in the future is untrustworthy (clock error), hence stale.
_FUTURE_TOLERANCE = timedelta(hours=1)

#: ``1.4826 * MAD`` estimates a standard deviation for normal data.
_MAD_TO_SIGMA = 1.4826

#: Numerical zero guard: a median window RMS at or below this is a flat line (electrode off
#: or a dead channel), not a quiet muscle.
_MIN_SIGNAL_RMS = 1e-3


# --------------------------------------------------------------------------- vocabulary


class CalibrationPhase(Enum):
    """Where the session is. The first five are data-collecting; the rest are terminal."""

    RELAX = "relax"
    SQUEEZE_LIGHT = "squeeze_light"
    SQUEEZE_HARD = "squeeze_hard"
    BLINK_X3 = "blink_x3"
    CLENCH_X3 = "clench_x3"
    DONE = "done"
    ABORTED = "aborted"
    FAILED = "failed"


class IssueCode(Enum):
    """Machine-readable reason a phase was rejected (the text is in ``message``)."""

    BAD_SAMPLES = "bad_samples"
    NO_SIGNAL = "no_signal"
    NOT_QUIET = "not_quiet"
    SQUEEZE_TOO_WEAK = "squeeze_too_weak"
    SQUEEZE_TOO_BRIEF = "squeeze_too_brief"
    HARD_NOT_HARDER = "hard_not_harder"
    BLINKS_NOT_FOUND = "blinks_not_found"
    TOO_MANY_BLINKS = "too_many_blinks"
    CLENCHES_NOT_FOUND = "clenches_not_found"
    TOO_MANY_CLENCHES = "too_many_clenches"
    STALLED = "stalled"


class CalibrationError(RuntimeError):
    """``result()`` was asked for before (or instead of) a successful calibration."""


@dataclass(frozen=True)
class CalibrationIssue:
    """A phase was rejected. ``message`` is written for the person, not for a log.

    ``fatal`` is True when the retry budget for the phase is spent: the session is then
    ``FAILED`` and the caller should send the user back to electrode placement.
    """

    phase: CalibrationPhase
    code: IssueCode
    message: str
    attempt: int = 1
    fatal: bool = False


@dataclass(frozen=True)
class CalibrationProgress:
    """Where the session is, for a progress bar. Both fractions are in ``[0, 1]``."""

    phase: CalibrationPhase
    phase_index: int          # 0-based position among the phases this session runs
    phase_count: int
    phase_fraction: float
    overall_fraction: float


@dataclass(frozen=True)
class CalibrationConfig:
    """Tunable guards of the procedure. All are design choices (see module docstring)."""

    # -- timing (seconds of *data*, counted in samples) --------------------------------
    relax_s: float = 5.0
    squeeze_s: float = 4.0
    blink_s: float = 10.0
    clench_s: float = 8.0
    settle_s: float = 1.0          # discarded after each prompt change (reaction time)
    window_s: float = 0.25         # RMS window
    # -- rest validity ------------------------------------------------------------------
    rest_max_ratio: float = 2.0    # p95 / median of resting window RMS above this = not quiet
    # -- squeeze validity ---------------------------------------------------------------
    squeeze_min_ratio: float = 2.0       # squeeze plateau vs baseline
    squeeze_min_snr: float = 1.5         # squeeze plateau vs noise floor
    squeeze_min_hold_s: float = 1.0      # time actually spent at the plateau
    hard_over_light_ratio: float = 1.25  # hard plateau vs light plateau
    # -- artifact prompts ---------------------------------------------------------------
    artifact_count: int = 3
    artifact_max_count: int = 6          # more than this = too much unrelated movement
    artifact_sigma: float = 6.0          # burst must clear median + this * robust sigma
    artifact_rel_peak: float = 0.25      # ... and this fraction of the largest excursion
    blink_smooth_s: float = 0.05
    blink_min_s: float = 0.04
    blink_merge_gap_s: float = 0.15
    clench_window_s: float = 0.10
    clench_min_s: float = 0.30
    clench_merge_gap_s: float = 0.20
    clench_min_ratio: float = 3.0        # clench power vs resting high-frequency power
    # -- derived thresholds -------------------------------------------------------------
    light_fraction: float = DEFAULT_LIGHT_FRACTION
    hard_fraction: float = DEFAULT_HARD_FRACTION
    offset_fraction: float = 0.5         # release level, between baseline and onset
    noise_margin: float = 1.2            # onset is never below noise_floor * this
    blink_threshold_fraction: float = 0.5
    clench_threshold_fraction: float = 0.3
    # -- retry / stall ------------------------------------------------------------------
    max_attempts: int = 3
    stall_timeout_s: float = 5.0         # wall time without a block before tick() complains


# --------------------------------------------------------------------------- the profile


def _fmt_age(created_at: str) -> str:
    return created_at or "unknown time"


@dataclass(frozen=True, repr=False)
class CalibrationProfile:
    """What one calibration run produced: derived numbers and the identity they belong to.

    Optional measurements are ``None`` when their phase did not run. ``thresholds`` holds
    ready-to-use plain floats (keys: ``light``, ``hard``, ``onset``, ``offset`` for the
    squeeze family; ``blink``; ``clench``) so a detector can be built from the profile
    without this module importing the detector modules. Keys appear only for phases that ran.

    ``repr`` is deliberately redacted — the profile is biometric-adjacent and must not end
    up in a log line or a traceback in full.
    """

    created_at: str                    # ISO 8601, UTC
    board_id: str
    channels: tuple[str, ...]
    channel_kinds: tuple[str, ...]     # SignalKind.value, parallel to ``channels``
    fs: float
    baseline_rms: float
    noise_floor: float
    mvc_rms: float | None = None
    light_rms: float | None = None
    blink_amplitude: float | None = None
    clench_power: float | None = None
    thresholds: dict[str, float] = field(default_factory=dict)
    phases: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __repr__(self) -> str:
        return (
            f"CalibrationProfile(board_id={self.board_id!r}, channels={len(self.channels)}, "
            f"fs={self.fs:g}, created_at={_fmt_age(self.created_at)!r}, <values redacted>)"
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready mapping (lists, not tuples)."""
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "board_id": self.board_id,
            "channels": list(self.channels),
            "channel_kinds": list(self.channel_kinds),
            "fs": self.fs,
            "baseline_rms": self.baseline_rms,
            "noise_floor": self.noise_floor,
            "mvc_rms": self.mvc_rms,
            "light_rms": self.light_rms,
            "blink_amplitude": self.blink_amplitude,
            "clench_power": self.clench_power,
            "thresholds": dict(self.thresholds),
            "phases": list(self.phases),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CalibrationProfile:
        """Validate and build. Raises ``ValueError`` on anything malformed or unknown."""
        version = data.get("schema_version")
        if version != SCHEMA_VERSION or isinstance(version, bool):
            raise ValueError("unsupported schema_version")
        created_at = data.get("created_at")
        board_id = data.get("board_id")
        if not isinstance(created_at, str) or not isinstance(board_id, str):
            raise ValueError("created_at / board_id must be strings")
        if _parse_time(created_at) is None:
            raise ValueError("created_at is not an ISO timestamp")
        channels = _str_tuple(data.get("channels"), "channels")
        kinds = _str_tuple(data.get("channel_kinds"), "channel_kinds")
        if len(channels) != len(kinds) or not channels:
            raise ValueError("channels / channel_kinds mismatch")
        valid_kinds = {k.value for k in SignalKind}
        if any(k not in valid_kinds for k in kinds):
            raise ValueError("unknown channel kind")
        raw_thresholds = data.get("thresholds", {})
        if not isinstance(raw_thresholds, Mapping):
            raise ValueError("thresholds must be a mapping")
        thresholds = {str(k): _positive(v, f"thresholds.{k}") for k, v in raw_thresholds.items()}
        return cls(
            created_at=created_at,
            board_id=board_id,
            channels=channels,
            channel_kinds=kinds,
            fs=_positive(data.get("fs"), "fs"),
            baseline_rms=_positive(data.get("baseline_rms"), "baseline_rms", allow_zero=True),
            noise_floor=_positive(data.get("noise_floor"), "noise_floor", allow_zero=True),
            mvc_rms=_optional_positive(data.get("mvc_rms"), "mvc_rms"),
            light_rms=_optional_positive(data.get("light_rms"), "light_rms"),
            blink_amplitude=_optional_positive(data.get("blink_amplitude"), "blink_amplitude"),
            clench_power=_optional_positive(data.get("clench_power"), "clench_power"),
            thresholds=thresholds,
            phases=_str_tuple(data.get("phases", []), "phases"),
            schema_version=SCHEMA_VERSION,
        )

    def summary(self) -> str:
        """One log-safe line: identity and age only, never an amplitude."""
        return (
            f"board={self.board_id!r} channels={len(self.channels)} fs={self.fs:g} "
            f"created_at={_fmt_age(self.created_at)} phases={','.join(self.phases) or '-'}"
        )


def _str_tuple(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{name} must be a list of strings")
    return tuple(value)


def _positive(value: Any, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise ValueError(f"{name} must be a finite positive number")
    return number


def _optional_positive(value: Any, name: str) -> float | None:
    return None if value is None else _positive(value, name)


def _parse_time(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- signal helpers


def _window_rms(data: np.ndarray, win: int) -> np.ndarray:
    """Windowed RMS of ``(channels, samples)`` data, mean removed per window. Pure.

    Power is averaged over channels *before* the square root, so one disconnected channel
    lowers the level rather than dominating it.
    """
    n_win = data.shape[1] // win if win > 0 else 0
    if n_win == 0:
        return np.zeros(0, dtype="float64")
    x = data[:, : n_win * win].reshape(data.shape[0], n_win, win)
    x = x - x.mean(axis=2, keepdims=True)
    return np.sqrt((x * x).mean(axis=(0, 2)))


def _segments(mask: np.ndarray, min_len: int, merge_gap: int) -> list[tuple[int, int]]:
    """Runs of True in ``mask`` as ``(start, stop)``; gaps ≤ ``merge_gap`` are bridged, runs
    shorter than ``min_len`` dropped."""
    if mask.size == 0 or not mask.any():
        return []
    padded = np.concatenate(([0], mask.astype("int8"), [0]))
    edges = np.flatnonzero(np.diff(padded))
    runs = [(int(a), int(b)) for a, b in zip(edges[0::2], edges[1::2], strict=True)]
    merged: list[tuple[int, int]] = []
    for start, stop in runs:
        if merged and start - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], stop)
        else:
            merged.append((start, stop))
    return [(a, b) for a, b in merged if b - a >= min_len]


def _robust_sigma(values: np.ndarray) -> float:
    return float(_MAD_TO_SIGMA * np.median(np.abs(values - np.median(values))))


def _burst_threshold(trace: np.ndarray, cfg: CalibrationConfig) -> tuple[float, float]:
    """``(median, threshold)`` of a one-dimensional activity trace. Pure.

    The threshold is the larger of ``median + sigma_multiple * robust_sigma`` and a fraction
    of the largest excursion: the first rejects ordinary noise, the second stops noise
    ripples from being counted as extra events next to one dominant burst.
    """
    med = float(np.median(trace))
    sigma = _robust_sigma(trace)
    excursion = float(trace.max()) - med
    return med, med + max(cfg.artifact_sigma * sigma, cfg.artifact_rel_peak * excursion)


def _blink_trace(data: np.ndarray, fs: float, smooth_s: float) -> np.ndarray:
    """Smoothed rectified deviation from the per-channel median, averaged over channels."""
    centred = data - np.median(data, axis=1, keepdims=True)
    rectified = np.abs(centred).mean(axis=0)
    k = max(1, round(smooth_s * fs))
    if k == 1:
        return rectified
    return np.convolve(rectified, np.ones(k) / k, mode="same")


def _hf_power_trace(data: np.ndarray, win: int) -> np.ndarray:
    """Windowed mean squared first difference (a crude high-pass), averaged over channels.

    A blink or a drift is slow and barely moves the first difference; a clench is broadband
    muscle activity and moves it a lot — which is what separates the two without a filter.
    """
    if data.shape[1] < 2 or win <= 0:
        return np.zeros(0, dtype="float64")
    d = np.diff(data, axis=1)
    n_win = d.shape[1] // win
    if n_win == 0:
        return np.zeros(0, dtype="float64")
    return (d[:, : n_win * win] ** 2).reshape(d.shape[0], n_win, win).mean(axis=(0, 2))


# --------------------------------------------------------------------------- the session

_PROMPTS: dict[CalibrationPhase, str] = {
    CalibrationPhase.RELAX: "Relax completely and keep still. Let the muscle go loose.",
    CalibrationPhase.SQUEEZE_LIGHT: (
        "Squeeze gently, like a light handshake, and hold it steady until the next prompt."
    ),
    CalibrationPhase.SQUEEZE_HARD: (
        "Squeeze firmly, as hard as is comfortable (do not strain), and hold it steady."
    ),
    CalibrationPhase.BLINK_X3: (
        "Blink firmly three times, about a second apart, then keep your eyes still."
    ),
    CalibrationPhase.CLENCH_X3: (
        "Clench your jaw firmly three times, about a second each with a pause between."
    ),
}

_TERMINAL_PROMPTS: dict[CalibrationPhase, str] = {
    CalibrationPhase.DONE: "Calibration complete.",
    CalibrationPhase.ABORTED: "Calibration cancelled.",
    CalibrationPhase.FAILED: (
        "Calibration could not be completed. Check that the electrodes are placed and "
        "making good contact, then start again."
    ),
}


class CalibrationSession:
    """Guided calibration as a pure, clock-injected state machine.

    Typical use::

        session = CalibrationSession(board_id, channels, fs, include_blink=True)
        while session.phase not in TERMINAL:
            show(session.prompt(), session.progress())
            issue = session.feed(source.read())      # None when nothing to say
            if issue:
                show(issue.message)
        profile = session.result()

    Blocks must arrive in order with the sampling rate and channel names the session was
    built with; ``block.t0`` is not inspected (not every source stamps it). The session keeps
    raw samples only until a phase is analysed; nothing raw survives ``result()``/``abort()``.
    """

    def __init__(
        self,
        board_id: str,
        channels: Sequence[ChannelInfo],
        fs: float,
        *,
        include_squeeze: bool | None = None,
        include_blink: bool = False,
        include_clench: bool = False,
        config: CalibrationConfig | None = None,
        clock: Callable[[], float] | None = None,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        if fs <= 0 or not math.isfinite(fs):
            raise ValueError("fs must be a positive finite number")
        self._channels = tuple(channels)
        if not self._channels:
            raise ValueError("at least one channel is required")
        self._names = tuple(c.name for c in self._channels)
        if len(set(self._names)) != len(self._names):
            raise ValueError("channel names must be unique")
        self._board_id = board_id
        self._fs = float(fs)
        self._cfg = config or CalibrationConfig()
        if self._cfg.max_attempts < 1 or self._cfg.artifact_count < 1:
            raise ValueError("max_attempts and artifact_count must be at least 1")
        self._clock = clock or _monotonic
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))

        emg = self._indices({SignalKind.EMG})
        self._squeeze_idx = emg
        # The resting level is measured on the muscle channels when there are any; an
        # EEG-only board still gets a baseline, over whatever channels it has.
        self._rest_idx = emg or tuple(range(len(self._channels)))
        self._blink_idx = self._indices({SignalKind.EOG}) or self._indices({SignalKind.EEG})
        self._clench_idx = self._indices({SignalKind.EEG}) or emg

        squeeze = bool(emg) if include_squeeze is None else include_squeeze
        if squeeze and not emg:
            raise ValueError("squeeze calibration needs at least one EMG channel")
        if include_blink and not self._blink_idx:
            raise ValueError("blink calibration needs an EOG or EEG channel")
        if include_clench and not self._clench_idx:
            raise ValueError("clench calibration needs an EEG or EMG channel")
        self._plan: tuple[CalibrationPhase, ...] = (
            (CalibrationPhase.RELAX,)
            + ((CalibrationPhase.SQUEEZE_LIGHT, CalibrationPhase.SQUEEZE_HARD) if squeeze else ())
            + ((CalibrationPhase.BLINK_X3,) if include_blink else ())
            + ((CalibrationPhase.CLENCH_X3,) if include_clench else ())
        )

        self._step = 0
        self._state = self._plan[0]
        self._attempts = dict.fromkeys(self._plan, 0)
        self._chunks: list[np.ndarray] = []
        self._collected = 0
        self._last_feed = self._clock()
        self._last_issue: CalibrationIssue | None = None
        self._phase_issue_pending = False  # a retry notice should lead the next prompt
        # derived values, filled as phases pass
        self._rest_data: np.ndarray | None = None
        self._baseline = 0.0
        self._noise_floor = 0.0
        self._light_plateau: float | None = None
        self._mvc: float | None = None
        self._blink_amp: float | None = None
        self._clench_pow: float | None = None
        self._clench_rest: float | None = None
        self._blink_rest: tuple[float, float] | None = None  # (median, sigma) at rest
        self._profile: CalibrationProfile | None = None

    # ------------------------------------------------------------------ introspection

    @property
    def phase(self) -> CalibrationPhase:
        return self._state

    @property
    def phases(self) -> tuple[CalibrationPhase, ...]:
        """The collecting phases this session will run, in order."""
        return self._plan

    @property
    def finished(self) -> bool:
        return self._state in (
            CalibrationPhase.DONE,
            CalibrationPhase.ABORTED,
            CalibrationPhase.FAILED,
        )

    @property
    def last_issue(self) -> CalibrationIssue | None:
        """The most recent rejection, kept until the phase it concerned passes."""
        return self._last_issue

    def prompt(self) -> str:
        """The instruction to show now, led by the retry reason after a rejection."""
        if self._state in _TERMINAL_PROMPTS:
            return _TERMINAL_PROMPTS[self._state]
        text = _PROMPTS[self._state]
        if self._last_issue is not None and self._last_issue.phase is self._state:
            return f"{self._last_issue.message} {text}"
        return text

    def progress(self) -> CalibrationProgress:
        n = len(self._plan)
        if self._state is CalibrationPhase.DONE:
            return CalibrationProgress(self._state, n, n, 1.0, 1.0)
        frac = self._phase_fraction()
        return CalibrationProgress(self._state, self._step, n, frac, (self._step + frac) / n)

    # ------------------------------------------------------------------ driving

    def feed(self, block: SampleBlock | None) -> CalibrationIssue | None:
        """Consume one block. Returns an issue when a phase was rejected, else ``None``.

        ``None`` blocks (a source with nothing new) are accepted and only exercise stall
        detection. A block may straddle a phase boundary; the remainder is processed in the
        next phase. After a rejection the rest of that block is discarded — the user has just
        been told to retry.
        """
        if self.finished:
            return None
        if block is None:
            return self.tick()
        data = self._validate(block)
        if data is None:
            return self._reject(IssueCode.BAD_SAMPLES, (
                "The recording contained invalid values (NaN or infinite samples). "
                "Check the connection and try this step again."
            ))
        self._last_feed = self._clock()
        while data.shape[1] > 0 and not self.finished:
            need = self._target_samples() - self._collected
            take = min(need, data.shape[1])
            self._chunks.append(data[:, :take])
            self._collected += take
            data = data[:, take:]
            if self._collected >= self._target_samples():
                issue = self._finish_phase()
                if issue is not None:
                    return issue
        return None

    def tick(self) -> CalibrationIssue | None:
        """Stall check without data: reports (and restarts the phase) if the source has gone
        quiet for ``stall_timeout_s`` of wall time. ``feed`` calls this for ``None`` blocks."""
        if self.finished or self._clock() - self._last_feed < self._cfg.stall_timeout_s:
            return None
        self._last_feed = self._clock()
        return self._reject(IssueCode.STALLED, (
            "No signal is arriving from the device. Check that it is on and connected."
        ))

    def abort(self) -> None:
        """Cancel. Drops every buffered sample; ``result()`` will then raise."""
        if self._state is not CalibrationPhase.DONE:
            self._state = CalibrationPhase.ABORTED
        self._drop_buffers()

    def result(self) -> CalibrationProfile:
        """The finished profile. Raises :class:`CalibrationError` unless the session is DONE."""
        if self._state is not CalibrationPhase.DONE or self._profile is None:
            raise CalibrationError(
                f"calibration is not complete (phase: {self._state.value}); "
                "the user must finish or repeat the remaining steps"
            )
        return self._profile

    # ------------------------------------------------------------------ internals

    def _indices(self, kinds: set[SignalKind]) -> tuple[int, ...]:
        return tuple(i for i, c in enumerate(self._channels) if c.kind in kinds)

    def _duration_s(self, phase: CalibrationPhase) -> float:
        cfg = self._cfg
        return {
            CalibrationPhase.RELAX: cfg.relax_s,
            CalibrationPhase.SQUEEZE_LIGHT: cfg.squeeze_s,
            CalibrationPhase.SQUEEZE_HARD: cfg.squeeze_s,
            CalibrationPhase.BLINK_X3: cfg.blink_s,
            CalibrationPhase.CLENCH_X3: cfg.clench_s,
        }[phase]

    def _settle_samples(self) -> int:
        return round(self._cfg.settle_s * self._fs)

    def _target_samples(self) -> int:
        return self._settle_samples() + round(self._duration_s(self._state) * self._fs)

    def _phase_fraction(self) -> float:
        if self._state is CalibrationPhase.DONE:
            return 1.0
        if self._state not in self._attempts:
            return 0.0
        return min(1.0, self._collected / max(1, self._target_samples()))

    def _validate(self, block: SampleBlock) -> np.ndarray | None:
        """The block's samples reordered to the session's channels, or None if non-finite.

        Mismatched sampling rate or channel names are programming errors and raise.
        """
        if abs(block.fs - self._fs) > _FS_REL_TOL * self._fs:
            raise ValueError(f"block fs {block.fs} does not match session fs {self._fs}")
        names = tuple(c.name for c in block.channels)
        data = np.asarray(block.data, dtype="float64")
        if names != self._names:
            if set(names) != set(self._names) or len(set(names)) != len(names):
                raise ValueError("block channels do not match the session's channels")
            data = data[[names.index(n) for n in self._names]]
        if data.ndim != 2 or data.shape[0] != len(self._names):
            raise ValueError("block data must have shape (n_channels, n_samples)")
        if not np.isfinite(data).all():
            return None
        return data

    def _drop_buffers(self) -> None:
        self._chunks = []
        self._collected = 0
        self._rest_data = None

    def _phase_data(self) -> np.ndarray:
        """Collected samples for the current phase with the settle period removed."""
        data = np.concatenate(self._chunks, axis=1) if self._chunks else np.zeros(
            (len(self._names), 0)
        )
        return data[:, self._settle_samples():]

    def _reject(self, code: IssueCode, message: str) -> CalibrationIssue:
        phase = self._state
        self._attempts[phase] = self._attempts.get(phase, 0) + 1
        attempt = self._attempts[phase]
        fatal = attempt >= self._cfg.max_attempts
        if fatal:
            message = (
                f"{message} This step has failed {attempt} times; check the electrode "
                "placement and skin contact, then start the calibration again."
            )
        issue = CalibrationIssue(phase, code, message, attempt, fatal)
        self._last_issue = issue
        self._chunks = []
        self._collected = 0
        if fatal:
            self._state = CalibrationPhase.FAILED
            self._drop_buffers()
        return issue

    def _advance(self) -> None:
        self._chunks = []
        self._collected = 0
        self._last_issue = None
        self._step += 1
        if self._step >= len(self._plan):
            self._state = CalibrationPhase.DONE
            self._profile = self._build_profile()
            self._drop_buffers()
        else:
            self._state = self._plan[self._step]
        self._last_feed = self._clock()

    def _finish_phase(self) -> CalibrationIssue | None:
        data = self._phase_data()
        handler = {
            CalibrationPhase.RELAX: self._check_relax,
            CalibrationPhase.SQUEEZE_LIGHT: self._check_squeeze,
            CalibrationPhase.SQUEEZE_HARD: self._check_squeeze,
            CalibrationPhase.BLINK_X3: self._check_blink,
            CalibrationPhase.CLENCH_X3: self._check_clench,
        }[self._state]
        issue = handler(data)
        if issue is not None:
            return issue
        self._advance()
        return None

    # -- per-phase analysis -------------------------------------------------------------

    def _win(self) -> int:
        return max(1, round(self._cfg.window_s * self._fs))

    def _check_relax(self, data: np.ndarray) -> CalibrationIssue | None:
        rms = _window_rms(data[list(self._rest_idx)], self._win())
        if rms.size < 4 or float(np.median(rms)) <= _MIN_SIGNAL_RMS:
            return self._reject(IssueCode.NO_SIGNAL, (
                "The signal is flat, so the electrodes do not seem to be picking anything "
                "up. Check that they are attached and the board is streaming."
            ))
        med = float(np.median(rms))
        p95 = float(np.percentile(rms, 95))
        if p95 > self._cfg.rest_max_ratio * med:
            return self._reject(IssueCode.NOT_QUIET, (
                "The baseline was not quiet enough: there was movement or a sudden burst "
                "while you were meant to be resting."
            ))
        self._baseline = med
        self._noise_floor = p95
        self._rest_data = data.copy()
        self._blink_rest = None
        self._clench_rest = None
        if self._blink_idx:
            trace = _blink_trace(data[list(self._blink_idx)], self._fs, self._cfg.blink_smooth_s)
            self._blink_rest = (float(np.median(trace)), _robust_sigma(trace))
        if self._clench_idx:
            hf = _hf_power_trace(
                data[list(self._clench_idx)], max(1, round(self._cfg.clench_window_s * self._fs))
            )
            if hf.size:
                self._clench_rest = float(np.median(hf))
        return None

    def _check_squeeze(self, data: np.ndarray) -> CalibrationIssue | None:
        cfg = self._cfg
        phase = self._state
        rms = _window_rms(data[list(self._squeeze_idx)], self._win())
        if rms.size < 4:
            return self._reject(IssueCode.NO_SIGNAL, "Not enough signal was recorded.")
        peak = float(np.percentile(rms, 90))
        active = rms >= self._baseline + 0.5 * (peak - self._baseline)
        hold_s = float(active.sum()) * cfg.window_s
        plateau = float(np.median(rms[active])) if active.any() else 0.0
        too_weak = (
            plateau < cfg.squeeze_min_ratio * self._baseline
            or plateau < cfg.squeeze_min_snr * self._noise_floor
        )
        if too_weak:
            gentle = phase is CalibrationPhase.SQUEEZE_LIGHT
            return self._reject(IssueCode.SQUEEZE_TOO_WEAK, (
                "I could not see a squeeze clearly above your resting level. "
                + ("Squeeze a little more firmly (still gently), and " if gentle else
                   "Squeeze harder (comfortably), and ")
                + "check that the electrode sits over the muscle."
            ))
        if hold_s < cfg.squeeze_min_hold_s:
            return self._reject(IssueCode.SQUEEZE_TOO_BRIEF, (
                "The squeeze was too brief. Hold it steady for the whole step."
            ))
        if phase is CalibrationPhase.SQUEEZE_LIGHT:
            self._light_plateau = plateau
        else:
            light = self._light_plateau
            if light is not None and plateau < cfg.hard_over_light_ratio * light:
                return self._reject(IssueCode.HARD_NOT_HARDER, (
                    "That squeeze was not clearly harder than the gentle one. Squeeze "
                    "noticeably harder this time (the gentle one should be light)."
                ))
            self._mvc = plateau
        return None

    def _artifact_bursts(
        self, trace: np.ndarray, min_len: int, merge_gap: int
    ) -> list[tuple[int, int]]:
        if trace.size == 0:
            return []
        _, thr = _burst_threshold(trace, self._cfg)
        return _segments(trace > thr, min_len, merge_gap)

    def _check_blink(self, data: np.ndarray) -> CalibrationIssue | None:
        cfg = self._cfg
        trace = _blink_trace(data[list(self._blink_idx)], self._fs, cfg.blink_smooth_s)
        if trace.size == 0 or float(trace.max()) - float(np.median(trace)) <= _MIN_SIGNAL_RMS:
            return self._reject(IssueCode.BLINKS_NOT_FOUND, (
                "I could not see any blinks. Blink firmly, and check the electrodes near "
                "the eyes or forehead."
            ))
        med = float(np.median(trace))
        bursts = self._artifact_bursts(
            trace,
            max(1, round(cfg.blink_min_s * self._fs)),
            round(cfg.blink_merge_gap_s * self._fs),
        )
        if len(bursts) < cfg.artifact_count:
            return self._reject(IssueCode.BLINKS_NOT_FOUND, (
                f"I found {len(bursts)} blink{'s' if len(bursts) != 1 else ''} instead of "
                f"{cfg.artifact_count}. Blink firmly, with a pause between blinks."
            ))
        if len(bursts) > cfg.artifact_max_count:
            return self._reject(IssueCode.TOO_MANY_BLINKS, (
                "There was too much eye or face movement. Keep still and blink only "
                f"{cfg.artifact_count} times."
            ))
        peaks = [float(trace[a:b].max()) - med for a, b in bursts]
        self._blink_amp = float(np.median(peaks))
        return None

    def _check_clench(self, data: np.ndarray) -> CalibrationIssue | None:
        cfg = self._cfg
        win = max(1, round(cfg.clench_window_s * self._fs))
        trace = _hf_power_trace(data[list(self._clench_idx)], win)
        if trace.size == 0 or float(trace.max()) <= 0.0:
            return self._reject(IssueCode.CLENCHES_NOT_FOUND, (
                "I could not see any jaw clenches. Clench firmly and check the electrodes."
            ))
        bursts = self._artifact_bursts(
            trace,
            max(1, round(cfg.clench_min_s / cfg.clench_window_s)),
            max(0, round(cfg.clench_merge_gap_s / cfg.clench_window_s)),
        )
        if len(bursts) < cfg.artifact_count:
            return self._reject(IssueCode.CLENCHES_NOT_FOUND, (
                f"I found {len(bursts)} clench{'es' if len(bursts) != 1 else ''} instead of "
                f"{cfg.artifact_count}. Clench firmly for about a second each time, with a "
                "pause between."
            ))
        if len(bursts) > cfg.artifact_max_count:
            return self._reject(IssueCode.TOO_MANY_CLENCHES, (
                "There was too much jaw or face movement. Keep still and clench only "
                f"{cfg.artifact_count} times."
            ))
        power = float(np.median([float(trace[a:b].mean()) for a, b in bursts]))
        rest = self._clench_rest
        if rest is not None and power < cfg.clench_min_ratio * max(rest, 1e-12):
            return self._reject(IssueCode.CLENCHES_NOT_FOUND, (
                "The clenches were not clearly stronger than your resting jaw. Clench "
                "harder."
            ))
        self._clench_pow = power
        return None

    # -- result -------------------------------------------------------------------------

    def _derive_thresholds(self) -> dict[str, float]:
        cfg = self._cfg
        out: dict[str, float] = {}
        base, noise = self._baseline, self._noise_floor
        if self._mvc is not None:
            span = max(self._mvc - base, 0.0)
            light = base + span * cfg.light_fraction
            hard = base + span * cfg.hard_fraction
            # The onset is never allowed below the resting noise, whatever the fractions say.
            onset = max(light, noise * cfg.noise_margin)
            hard = max(hard, onset * 1.05)
            offset = base + (onset - base) * cfg.offset_fraction
            out.update(light=onset, hard=hard, onset=onset, offset=offset)
        if self._blink_amp is not None:
            floor = 0.0
            if self._blink_rest is not None:
                floor = cfg.artifact_sigma * self._blink_rest[1]
            out["blink"] = max(cfg.blink_threshold_fraction * self._blink_amp, floor)
        if self._clench_pow is not None:
            rest = self._clench_rest or 0.0
            out["clench"] = rest + cfg.clench_threshold_fraction * (self._clench_pow - rest)
        return {k: float(v) for k, v in out.items() if math.isfinite(v) and v > 0}

    def _build_profile(self) -> CalibrationProfile:
        stamp = self._wall_clock()
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return CalibrationProfile(
            created_at=stamp.astimezone(UTC).isoformat(timespec="seconds"),
            board_id=self._board_id,
            channels=self._names,
            channel_kinds=tuple(c.kind.value for c in self._channels),
            fs=self._fs,
            baseline_rms=self._baseline,
            noise_floor=self._noise_floor,
            mvc_rms=self._mvc,
            light_rms=self._light_plateau,
            blink_amplitude=self._blink_amp,
            clench_power=self._clench_pow,
            thresholds=self._derive_thresholds(),
            phases=tuple(p.value for p in self._plan),
        )


def _monotonic() -> float:
    import time

    return time.monotonic()


# --------------------------------------------------------------------------- persistence


def default_profile_path(data_dir: Path | str | None = None) -> Path:
    """Where the profile lives: ``<data_dir>/biosignal_calibration.json``.

    ``data_dir`` defaults to the platform data directory (``get_paths().data_dir``, the same
    helper the learning store and tray use). Resolving it is lazy so importing this module
    stays cheap and testable with an explicit directory. Pure apart from that lookup.
    """
    if data_dir is None:
        from yazses.platform.factory import get_paths

        data_dir = get_paths().data_dir
    return Path(data_dir) / PROFILE_FILENAME


def save_profile(profile: CalibrationProfile, path: Path | str) -> None:
    """Write ``profile`` atomically with owner-only permissions (``0o600``).

    Writes a temporary file in the destination directory, flushes it to disk and renames it
    over the target, so a crash leaves either the old profile or the new one, never half of
    either. Raises ``OSError`` on failure (the caller is saving a calibration the user just
    spent a minute on and must be told). The profile is never logged; only the path is.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".biosignal-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(profile.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    log.debug("saved biosignal calibration profile to %s", target)


def load_profile(path: Path | str) -> CalibrationProfile | None:
    """Read a profile, or ``None`` if there is none or it cannot be trusted. Never raises.

    A missing file is the normal first-run case (debug log). A corrupt file, an unknown
    ``schema_version`` or implausible values log a warning that names the path and the
    reason but not the contents, and return ``None`` so the caller simply recalibrates.
    """
    target = Path(path)
    try:
        if not target.is_file():
            log.debug("no biosignal calibration profile at %s", target)
            return None
        if target.stat().st_size > _MAX_PROFILE_BYTES:
            log.warning("ignoring oversized biosignal calibration file %s", target)
            return None
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("top level is not an object")
        return CalibrationProfile.from_dict(raw)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        # json.JSONDecodeError and UnicodeDecodeError are ValueError subclasses. str(exc)
        # for from_dict names a field, never a value.
        reason = exc.__class__.__name__ if isinstance(exc, json.JSONDecodeError) else str(exc)
        log.warning("ignoring unusable biosignal calibration file %s: %s", target, reason)
        return None


# --------------------------------------------------------------------------- reuse checks


def profile_is_stale(
    profile: CalibrationProfile,
    now: datetime,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
) -> bool:
    """True when the profile is too old (or its timestamp cannot be trusted) to reuse. Pure.

    ``now`` is passed in so the check is deterministic; a naive ``datetime`` is taken as UTC.
    An unparsable ``created_at`` or one stamped in the future (beyond a small clock-skew
    allowance) counts as stale — recalibrating costs a minute, a wrong threshold costs
    phantom activations.
    """
    created = _parse_time(profile.created_at)
    if created is None:
        return True
    current = now if now.tzinfo else now.replace(tzinfo=UTC)
    age = current - created
    if age < -_FUTURE_TOLERANCE:
        return True
    return age > timedelta(days=max_age_days)


def profile_matches(
    profile: CalibrationProfile,
    board_id: str,
    channels: Sequence[str | ChannelInfo],
    fs: float,
) -> bool:
    """True when the profile was made for this board, these channels and this sampling rate.

    Channel order is ignored (it is a naming question, not a placement one); names, the
    board id and ``fs`` (within 1 %) must agree. A profile for a different band, headset or
    montage must not be silently reused — amplitudes do not transfer between placements.
    """
    names = tuple(c.name if isinstance(c, ChannelInfo) else str(c) for c in channels)
    if profile.board_id != board_id:
        return False
    if sorted(profile.channels) != sorted(names):
        return False
    if fs <= 0 or not math.isfinite(fs):
        return False
    return abs(profile.fs - fs) <= _FS_REL_TOL * profile.fs


#: Phases at which a session has stopped (handy for ``while session.phase not in TERMINAL``).
TERMINAL: frozenset[CalibrationPhase] = frozenset(
    {CalibrationPhase.DONE, CalibrationPhase.ABORTED, CalibrationPhase.FAILED}
)

__all__ = [
    "DEFAULT_MAX_AGE_DAYS",
    "PROFILE_FILENAME",
    "SCHEMA_VERSION",
    "TERMINAL",
    "CalibrationConfig",
    "CalibrationError",
    "CalibrationIssue",
    "CalibrationPhase",
    "CalibrationProfile",
    "CalibrationProgress",
    "CalibrationSession",
    "IssueCode",
    "default_profile_path",
    "load_profile",
    "profile_is_stale",
    "profile_matches",
    "save_profile",
]
