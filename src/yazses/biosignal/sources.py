"""Sample sources: where ``SampleBlock``s come from (synthetic, file replay, BrainFlow).

Every class here satisfies :class:`yazses.biosignal.types.BlockSource`, so a detector
pipeline never knows whether its samples come from a headset, a recording, or a
generator. That is the point: the *same* detector code is exercised by the synthetic
source in tests and ``doctor``, by a recorded session in the replay CLI, and by real
hardware in the daemon.

## Why a synthetic source is a first-class citizen

An artifact-grade switch (blink, jaw clench, muscle squeeze) is only trustworthy if its
false-positive rate is measured, and that needs signals whose ground truth is known.
:class:`SyntheticSource` is deterministic (same seed, same samples) and scriptable
(``schedule_squeeze`` / ``schedule_blink`` / ``schedule_clench``), and it can inject the
faults that wreck real recordings — mains hum, baseline drift, electrode pops, a lead
that goes flat — so a detector is judged on the conditions it will meet, not on a clean
sine. The amplitudes, durations and fault shapes are **design choices** (plausible
orders of magnitude for scalp / skin electrodes), not values calibrated against a
published dataset; do not quote them as physiology. ``ground_truth()`` returns what the
generator did, so a test or the replay CLI can score a detector against it.

## Failure semantics: a missing board is a logged no-op

:class:`BrainFlowBlockSource` follows ``platform/emg/brainflow_source.py``: a missing
``brainflow`` package or an unplugged/busy device is logged and leaves the source
*unavailable* (``available`` is ``False``, ``read()`` returns ``None``). It never raises
out of ``start()`` or ``read()``. A dictation daemon that dies because an optional
headset is unplugged is worse than one that simply does not have the headset. File
replay, by contrast, raises on a bad *file* (``FileNotFoundError`` / ``ValueError``)
because there the caller named the input explicitly and silence would hide the mistake.

## Recordings are sensitive

Raw EEG/EMG is biometric-adjacent: it can carry identity, fatigue, and medical signal
beyond the few events a switch needs. :class:`RecordingTap` is therefore opt-in (nothing
here records unless someone constructs one), local-only (a plain file path, no network),
and writes the file with mode ``0o600``. Treat the output like a voiceprint: do not
upload it, attach it to an issue, or commit it. Nothing in this module runs unless
constructed, so it is dormant by default.

## Recording formats

CSV (``write_csv`` / replay): optional ``# key=value`` comment lines (``fs``, ``t0``),
then a header of channel specs ``name:kind`` (``Fp1:eeg``, ``EMG1:emg``, ``EOG_V:eog``),
then one row per sample in microvolts. An external CSV may start with a time column
named ``t`` / ``time`` / ``timestamp`` (seconds), from which ``fs`` is inferred when no
``# fs=`` line is present. ``.npz`` holds ``data`` (channels x samples, µV), ``fs``,
``channels`` (an array of ``name:kind`` strings) and optionally ``t0`` — loaded with
``allow_pickle=False``.
"""

from __future__ import annotations

import io
import logging
import os
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from yazses.biosignal.boards import preset_for
from yazses.biosignal.types import (
    BioEvent,
    BlockSource,
    ChannelInfo,
    EventKind,
    SampleBlock,
    SignalKind,
)

log = logging.getLogger(__name__)

__all__ = [
    "SYNTHETIC_BOARD_ID",
    "BoardDescription",
    "BrainFlowBlockSource",
    "FileReplaySource",
    "RecordingTap",
    "SyntheticSource",
    "describe_board",
    "iter_blocks",
    "open_source",
    "write_csv",
    "write_npz",
]

# BrainFlow's own synthetic board — lets `doctor` and a curious user exercise the whole
# path with no hardware. Same value as platform/emg/brainflow_source.py (kept local so
# this module does not import the serial/EMG backend).
SYNTHETIC_BOARD_ID = -1

_DEFAULT_BLOCK_SECONDS = 0.04          # 25 blocks/s: well inside a 35-125 ms onset window
_IDLE_SLEEP_SECONDS = 0.005
_RECORDING_FILE_MODE = 0o600


# ====================================================================================
# helpers shared by the sources
# ====================================================================================


def _coerce_kind(value: SignalKind | str) -> SignalKind:
    """``"eeg"`` / ``"EEG"`` / ``SignalKind.EEG`` -> ``SignalKind.EEG``; ValueError otherwise."""
    if isinstance(value, SignalKind):
        return value
    try:
        return SignalKind(str(value).strip().lower())
    except ValueError:
        valid = ", ".join(k.value for k in SignalKind)
        raise ValueError(f"unknown signal kind {value!r} (expected one of: {valid})") from None


def _channel_spec(info: ChannelInfo) -> str:
    return f"{info.name}:{info.kind.value}"


def _parse_channel_spec(spec: str) -> ChannelInfo:
    """``"Fp1:eeg"`` -> ChannelInfo. The kind is the text after the LAST colon."""
    name, sep, kind = spec.strip().rpartition(":")
    if not sep or not name:
        raise ValueError(
            f"channel spec {spec!r} must look like 'name:kind' (for example 'Fp1:eeg')"
        )
    return ChannelInfo(name=name, kind=_coerce_kind(kind))


class _Pacer:
    """Real-time pacing: how many samples a wall clock says are due.

    ``clock`` is injectable so a test (or the replay CLI at 4x) controls time.
    """

    def __init__(self, fs: float, clock: Callable[[], float]) -> None:
        self._fs = fs
        self._clock = clock
        self._t_start: float | None = None

    def start(self) -> None:
        self._t_start = self._clock()

    def due(self, emitted: int) -> int:
        if self._t_start is None:
            self.start()
        assert self._t_start is not None
        return max(0, int((self._clock() - self._t_start) * self._fs) - emitted)


def iter_blocks(
    source: BlockSource,
    *,
    idle_sleep: float = _IDLE_SLEEP_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[SampleBlock]:
    """Drive any source to completion: start it, yield its blocks, stop it.

    Finite sources end on ``EOFError``; a live source is read until the caller stops
    iterating. ``None`` ("nothing new yet") backs off briefly instead of spinning.
    """
    source.start()
    try:
        while True:
            try:
                block = source.read()
            except EOFError:
                return
            if block is None:
                sleep(idle_sleep)
                continue
            yield block
    finally:
        source.stop()


# ====================================================================================
# 1. SyntheticSource
# ====================================================================================


@dataclass(frozen=True)
class _ChanSpec:
    """One synthetic channel and how strongly each scripted event shows up on it."""

    name: str
    kind: SignalKind
    squeeze: float = 0.0
    blink: float = 0.0
    clench: float = 0.0


# kind -> (default fs, default noise floor in µV rms, channels). Design choices: EMG is
# sampled faster because its energy sits higher; EEG/EOG at a typical consumer-board rate.
_E = SignalKind.EMG
_G = SignalKind.EEG
_O = SignalKind.EOG
_PRESETS: dict[str, tuple[float, float, tuple[_ChanSpec, ...]]] = {
    "emg": (1000.0, 6.0, (
        _ChanSpec("EMG1", _E, squeeze=1.0, clench=1.0),
        _ChanSpec("EMG2", _E, squeeze=0.8, clench=0.5),
    )),
    "eeg": (250.0, 4.0, (
        _ChanSpec("Fp1", _G, blink=1.0, clench=0.5),
        _ChanSpec("Fp2", _G, blink=1.0, clench=0.5),
        _ChanSpec("C3", _G, blink=0.15, clench=0.25),
        _ChanSpec("C4", _G, blink=0.15, clench=0.25),
    )),
    "eog": (250.0, 3.0, (
        _ChanSpec("EOG_V", _O, blink=1.0, clench=0.1),
        _ChanSpec("EOG_H", _O, blink=0.2, clench=0.1),
    )),
    "mixed": (500.0, 5.0, (
        _ChanSpec("Fp1", _G, blink=1.0, clench=0.5),
        _ChanSpec("Fp2", _G, blink=1.0, clench=0.5),
        _ChanSpec("EMG1", _E, squeeze=1.0, clench=1.0),
        _ChanSpec("EMG2", _E, squeeze=0.8, clench=0.5),
    )),
}

_BLINK_WIDTH_S = 0.30        # a blink artifact as one smooth ~300 ms bump (design choice)
_EDGE_RAMP_S = 0.02          # raised-cosine on/off ramp of a burst, so it has no click
_ALPHA_HZ = 10.0
_ALPHA_UV = 8.0              # background EEG rhythm, only on EEG-kind channels
_POP_TAU_S = 0.15            # electrode-pop decay time constant (design choice)
# Two scheduled blinks whose peaks are closer than this are a DOUBLE_BLINK in
# `ground_truth(pairs=True)`. Design choice, matched to the pipeline's double-blink window.
_DOUBLE_BLINK_GAP_S = 0.6
_MOTION_HZ = (2.0, 3.5, 6.0, 9.0)  # low-frequency components of a movement artifact (design choice)
_DC_STEP_RAMP_S = 0.005      # a DC step is a 5 ms raised-cosine edge, so it has no click


@dataclass
class _Event:
    kind: str                # squeeze | blink | clench | motion | dcstep | dropout | pop
    t: float                 # onset, seconds on the source clock
    dur: float = 0.0
    amp: float = 0.0
    ch: int = 0              # only used by dropout / pop
    phases: tuple[float, ...] = ()   # only used by motion (seed-derived, shared by all channels)


def _smooth(x: np.ndarray) -> np.ndarray:
    """0 -> 1 raised-cosine step for x already clipped to [0, 1]."""
    return 0.5 - 0.5 * np.cos(np.pi * x)


def _window(t: np.ndarray, start: float, dur: float) -> np.ndarray:
    """Burst envelope in [0, 1]: smooth ramp up at ``start``, smooth ramp down at ``start+dur``."""
    up = np.clip((t - start) / _EDGE_RAMP_S, 0.0, 1.0)
    down = np.clip((start + dur - t) / _EDGE_RAMP_S, 0.0, 1.0)
    return _smooth(up) * _smooth(down)


class SyntheticSource:
    """Deterministic, scriptable EMG/EEG/EOG generator (a :class:`BlockSource`).

    ``kind`` selects the montage: ``"emg"`` (two muscle channels), ``"eeg"`` (Fp1 Fp2 C3
    C4), ``"eog"`` (vertical + horizontal), or ``"mixed"`` (two frontal EEG + two EMG, so
    all three event types can be driven at once). Same constructor arguments and the same
    ``block_samples`` give bit-identical output; the *signal* is independent of the block
    size except for the random noise draws.

    Scripted events are absolute times on the source clock (``t0 = samples emitted / fs``).
    Scheduling something that is already in the past is a no-op for samples already
    emitted — history is not rewritten.

    ``realtime=False`` (default) hands out a block on every ``read()`` (as fast as the
    caller asks); ``realtime=True`` paces blocks to the wall clock and returns ``None``
    when none is due. ``duration`` makes the source finite (``EOFError`` after it).
    ``read()`` before ``start()`` starts the source implicitly.

    ``dropout_rate`` / ``pop_rate`` are random faults per second (off by default): a
    *dropout* flat-lines one channel for 50-300 ms (a lead losing contact), a *pop* is a
    large step on one channel that decays over ~150 ms (an electrode shifting). The same
    faults can be placed exactly with ``schedule_dropout`` / ``schedule_pop``.

    ``schedule_motion_artifact`` and ``schedule_dc_step`` add the two *common-mode*
    disturbances that robustness checks need: a burst and a baseline jump that hit every
    channel identically (a cable tug, a head movement, a re-referenced amplifier). They
    are artifacts, not events, so ``ground_truth`` never reports them. Everything is
    deterministic in ``seed``.
    """

    def __init__(
        self,
        kind: str = "mixed",
        *,
        fs: float | None = None,
        seed: int = 0,
        block_samples: int | None = None,
        duration: float | None = None,
        noise_uv: float | None = None,
        mains_hz: float = 50.0,
        mains_uv: float = 10.0,
        drift_uv: float = 20.0,
        dropout_rate: float = 0.0,
        pop_rate: float = 0.0,
        realtime: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        key = kind.strip().lower()
        if key not in _PRESETS:
            raise ValueError(f"unknown synthetic kind {kind!r} (expected one of: "
                             f"{', '.join(sorted(_PRESETS))})")
        preset_fs, preset_noise, spec = _PRESETS[key]
        if seed < 0:
            raise ValueError("seed must be >= 0")
        self.fs: float = float(fs if fs is not None else preset_fs)
        if self.fs <= 0:
            raise ValueError("fs must be > 0")
        if duration is not None and duration < 0:
            raise ValueError("duration must be >= 0")
        if min(dropout_rate, pop_rate, mains_uv, drift_uv) < 0:
            raise ValueError("rates and amplitudes must be >= 0")
        self.kind = key
        self.channels: tuple[ChannelInfo, ...] = tuple(ChannelInfo(c.name, c.kind) for c in spec)
        self._spec = spec
        self._seed = int(seed)
        self._noise_uv = float(noise_uv if noise_uv is not None else preset_noise)
        self._mains_hz = float(mains_hz)
        self._mains_uv = float(mains_uv)
        self._drift_uv = float(drift_uv)
        self._block = int(block_samples) if block_samples else max(
            1, round(self.fs * _DEFAULT_BLOCK_SECONDS))
        if self._block <= 0:
            raise ValueError("block_samples must be > 0")
        self._total = None if duration is None else int(round(duration * self.fs))
        self._realtime = bool(realtime)
        self._pacer = _Pacer(self.fs, clock)

        n_ch = len(spec)
        init = np.random.default_rng([self._seed, 99])
        self._alpha_phase = init.uniform(0.0, 2 * np.pi, n_ch)
        self._mains_phase = init.uniform(0.0, 2 * np.pi, n_ch)
        self._drift_f1 = init.uniform(0.05, 0.15, n_ch)
        self._drift_f2 = init.uniform(0.20, 0.40, n_ch)
        self._drift_p1 = init.uniform(0.0, 2 * np.pi, n_ch)
        self._drift_p2 = init.uniform(0.0, 2 * np.pi, n_ch)
        self._alpha_amp = np.array([_ALPHA_UV if c.kind is SignalKind.EEG else 0.0 for c in spec])
        self._sq = np.array([c.squeeze for c in spec])
        self._bl = np.array([c.blink for c in spec])
        self._cl = np.array([c.clench for c in spec])

        self._events: list[_Event] = []     # scripted bursts (the ground truth)
        self._faults: list[_Event] = []     # dropouts and pops (scheduled + random)
        self._rates = {"dropout": float(dropout_rate), "pop": float(pop_rate)}
        self._fault_rng = {
            "dropout": np.random.default_rng([self._seed, 1]),
            "pop": np.random.default_rng([self._seed, 2]),
        }
        self._horizon = {"dropout": 0.0, "pop": 0.0}

        self._emitted = 0
        self._base = 0
        self._block_no = 0
        self._started = False
        self._stopped = False

    # ---- scripting -------------------------------------------------------

    def schedule_squeeze(self, t: float, dur: float, amp: float = 200.0) -> SyntheticSource:
        """A muscle squeeze from ``t`` for ``dur`` s; ``amp`` is the burst's rms in µV."""
        self._check_burst(t, dur, amp)
        self._events.append(_Event("squeeze", float(t), float(dur), float(amp)))
        return self

    def schedule_blink(self, t: float, amp: float = 150.0) -> SyntheticSource:
        """One blink artifact starting at ``t``; ``amp`` is its peak in µV on a frontal channel."""
        self._check_burst(t, _BLINK_WIDTH_S, amp)
        self._events.append(_Event("blink", float(t), _BLINK_WIDTH_S, float(amp)))
        return self

    def schedule_clench(self, t: float, dur: float, amp: float = 80.0) -> SyntheticSource:
        """A jaw clench (broadband muscle burst) from ``t`` for ``dur`` s; ``amp`` is rms µV."""
        self._check_burst(t, dur, amp)
        self._events.append(_Event("clench", float(t), float(dur), float(amp)))
        return self

    def schedule_motion_artifact(self, t: float, dur: float, amp: float = 300.0) -> SyntheticSource:
        """A common-mode movement burst from ``t`` for ``dur`` s on ALL channels at once.

        The same slow, wandering waveform (a few sinusoids between 2 and 9 Hz with
        seed-derived phases, shaped by the burst envelope) is added to every channel, so a
        detector that wants a channel-specific signal should reject it. ``amp`` is the
        burst's rms in µV. A design-choice waveform, not a recording of real movement.
        """
        self._check_burst(t, dur, amp)
        rng = np.random.default_rng([self._seed, 3, len(self._events)])
        phases = tuple(float(p) for p in rng.uniform(0.0, 2 * np.pi, len(_MOTION_HZ)))
        self._events.append(_Event("motion", float(t), float(dur), float(amp), phases=phases))
        return self

    def schedule_dc_step(self, t: float, amp: float) -> SyntheticSource:
        """A permanent baseline jump of ``amp`` µV (signed) on ALL channels from ``t``.

        Models an amplifier re-reference or a contact that settles at a new offset; unlike
        :meth:`schedule_pop` it never decays. The edge is a 5 ms raised cosine.
        """
        self._check_burst(t, 0.0, amp, allow_zero_dur=True)
        self._events.append(_Event("dcstep", float(t), 0.0, float(amp)))
        return self

    def schedule_dropout(
        self, t: float, dur: float, channel: str | int = 0,
    ) -> SyntheticSource:
        """Flat-line one channel (by name or index) from ``t`` for ``dur`` s."""
        self._check_burst(t, dur, 0.0)
        self._faults.append(_Event("dropout", float(t), float(dur), 0.0, self._channel_index(channel)))
        return self

    def schedule_pop(
        self, t: float, amp: float = 1000.0, channel: str | int = 0,
    ) -> SyntheticSource:
        """An electrode pop: a step of ``amp`` µV (signed) at ``t`` decaying over ~150 ms."""
        self._check_burst(t, 0.0, amp, allow_zero_dur=True)
        self._faults.append(_Event("pop", float(t), 0.0, float(amp), self._channel_index(channel)))
        return self

    def ground_truth(self, *, pairs: bool = False) -> list[BioEvent]:
        """What the generator was told to do, as the events a perfect detector would report.

        Squeezes give ``SQUEEZE_ON`` at onset and ``SQUEEZE_OFF`` at the end; a blink is
        reported at its peak (mid-bump); a clench at its onset. Dropouts, pops, motion
        artifacts and DC steps are faults, not events, so none appears here.

        By default a ``DOUBLE_BLINK`` is not listed: it is the detector's job to infer it
        from two ``BLINK`` truths. With ``pairs=True`` the list also holds a
        ``DOUBLE_BLINK``, stamped at the second blink's peak, for every two consecutive
        scheduled blinks whose peaks are closer than 0.6 s (the underlying ``BLINK``
        truths stay in the list). In a run of three close blinks, each later blink
        pairs with the one before it. Use it to score a double-blink switch.
        """
        truth: list[BioEvent] = []
        for ev in self._events:
            detail = {"synthetic": True, "amp": ev.amp}
            if ev.kind == "squeeze":
                truth.append(BioEvent(EventKind.SQUEEZE_ON, ev.t, detail=dict(detail)))
                truth.append(BioEvent(EventKind.SQUEEZE_OFF, ev.t + ev.dur, detail=dict(detail)))
            elif ev.kind == "blink":
                truth.append(BioEvent(EventKind.BLINK, ev.t + ev.dur / 2, detail=dict(detail)))
            elif ev.kind == "clench":
                truth.append(BioEvent(EventKind.JAW_CLENCH, ev.t, detail=dict(detail)))
        if pairs:
            peaks = sorted((e for e in self._events if e.kind == "blink"), key=lambda e: e.t)
            for first, second in zip(peaks, peaks[1:]):
                gap = second.t - first.t
                if gap < _DOUBLE_BLINK_GAP_S:
                    truth.append(BioEvent(
                        EventKind.DOUBLE_BLINK, second.t + second.dur / 2,
                        detail={"synthetic": True, "amp": second.amp, "gap_s": gap}))
        return sorted(truth, key=lambda e: e.t)

    # ---- BlockSource -----------------------------------------------------

    def start(self) -> None:
        self._started = True
        self._stopped = False
        # Pacing resumes from "now"; samples already emitted are not owed again.
        self._pacer.start()
        self._base = self._emitted

    def read(self) -> SampleBlock | None:
        if self._stopped:
            return None
        if not self._started:
            self.start()
        if self._total is not None and self._emitted >= self._total:
            raise EOFError("synthetic source finished")
        n = self._block if self._total is None else min(self._block, self._total - self._emitted)
        if self._realtime and self._pacer.due(self._emitted - self._base) < n:
            return None
        data = self._render(self._emitted, n)
        block = SampleBlock(data=data, fs=self.fs, channels=self.channels,
                            t0=self._emitted / self.fs)
        self._emitted += n
        self._block_no += 1
        return block

    def stop(self) -> None:
        self._stopped = True

    # ---- internals -------------------------------------------------------

    def _check_burst(self, t: float, dur: float, amp: float, *, allow_zero_dur: bool = False) -> None:
        if t < 0:
            raise ValueError("t must be >= 0")
        if dur < 0 or (dur == 0 and not allow_zero_dur):
            raise ValueError("dur must be > 0")
        if not np.isfinite(amp):
            raise ValueError("amp must be finite")

    def _channel_index(self, channel: str | int) -> int:
        if isinstance(channel, int):
            if not 0 <= channel < len(self.channels):
                raise ValueError(f"channel index {channel} out of range")
            return channel
        for i, info in enumerate(self.channels):
            if info.name == channel:
                return i
        raise ValueError(f"no channel named {channel!r} (have: "
                         f"{', '.join(c.name for c in self.channels)})")

    def _extend_faults(self, t_end: float) -> None:
        """Pre-draw random faults up to ``t_end`` (sequential per type, so block-size independent)."""
        n_ch = len(self.channels)
        for kind, rate in self._rates.items():
            if rate <= 0:
                continue
            rng = self._fault_rng[kind]
            while self._horizon[kind] < t_end:
                self._horizon[kind] += float(rng.exponential(1.0 / rate))
                ch = int(rng.integers(0, n_ch))
                if kind == "dropout":
                    self._faults.append(_Event("dropout", self._horizon[kind],
                                               float(rng.uniform(0.05, 0.30)), 0.0, ch))
                else:
                    sign = 1.0 if rng.random() < 0.5 else -1.0
                    self._faults.append(_Event("pop", self._horizon[kind], 0.0,
                                               sign * float(rng.uniform(600.0, 1500.0)), ch))

    def _render(self, first: int, n: int) -> np.ndarray:
        t = (first + np.arange(n)) / self.fs
        t_lo, t_hi = float(t[0]), float(t[-1])
        n_ch = len(self.channels)
        rng = np.random.default_rng([self._seed, 0, self._block_no])

        x = rng.standard_normal((n_ch, n)) * self._noise_uv
        # unit-variance, high-passed noise: the carrier of every muscle burst
        hf = np.diff(rng.standard_normal((n_ch, n + 1)), axis=1) / np.sqrt(2.0)

        if self._alpha_amp.any():
            x += self._alpha_amp[:, None] * np.sin(
                2 * np.pi * _ALPHA_HZ * t[None, :] + self._alpha_phase[:, None])
        if self._mains_uv > 0 and self._mains_hz > 0:
            x += self._mains_uv * np.sin(
                2 * np.pi * self._mains_hz * t[None, :] + self._mains_phase[:, None])
        if self._drift_uv > 0:
            drift = (np.sin(2 * np.pi * self._drift_f1[:, None] * t[None, :] + self._drift_p1[:, None])
                     + 0.5 * np.sin(2 * np.pi * self._drift_f2[:, None] * t[None, :]
                                    + self._drift_p2[:, None])) / 1.5
            x += self._drift_uv * drift

        for ev in self._events:
            if ev.t > t_hi:
                continue
            if ev.kind == "dcstep":
                # permanent: still present long after its edge
                x += ev.amp * _smooth(np.clip((t - ev.t) / _DC_STEP_RAMP_S, 0.0, 1.0))[None, :]
                continue
            if ev.t + ev.dur + _EDGE_RAMP_S < t_lo:
                continue
            if ev.kind == "motion":
                wave = sum(np.sin(2 * np.pi * f * (t - ev.t) + ph)
                           for f, ph in zip(_MOTION_HZ, ev.phases))
                # n unit sinusoids have rms sqrt(n/2); normalise so `amp` is the burst rms
                x += ev.amp / np.sqrt(len(_MOTION_HZ) / 2.0) * (wave * _window(t, ev.t, ev.dur))[None, :]
            elif ev.kind == "squeeze":
                x += (self._sq * ev.amp)[:, None] * _window(t, ev.t, ev.dur)[None, :] * hf
            elif ev.kind == "clench":
                x += (self._cl * ev.amp)[:, None] * _window(t, ev.t, ev.dur)[None, :] * hf
            elif ev.kind == "blink":
                u = (t - ev.t) / ev.dur
                bump = np.where((u >= 0.0) & (u <= 1.0), 0.5 - 0.5 * np.cos(2 * np.pi * u), 0.0)
                x += (self._bl * ev.amp)[:, None] * bump[None, :]

        self._extend_faults(t_hi + 1.0)
        self._faults = [f for f in self._faults if f.kind == "pop" and f.t + 10 * _POP_TAU_S >= t_lo
                        or f.kind == "dropout" and f.t + f.dur >= t_lo]
        for f in self._faults:
            if f.kind == "pop" and f.t <= t_hi:
                after = t >= f.t
                x[f.ch] += np.where(after, f.amp * np.exp(-(t - f.t) / _POP_TAU_S), 0.0)
            elif f.kind == "dropout" and f.t <= t_hi:
                x[f.ch, (t >= f.t) & (t < f.t + f.dur)] = 0.0
        return x


# ====================================================================================
# 2. File replay, recording
# ====================================================================================


@dataclass(frozen=True)
class _Recording:
    data: np.ndarray            # (channels, samples) in µV
    fs: float
    channels: tuple[ChannelInfo, ...]
    t0: float


def _finite(data: np.ndarray, source: str) -> np.ndarray:
    if not np.all(np.isfinite(data)):
        log.warning("%s: non-finite samples replaced with 0 (treated as a dropout)", source)
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    return data


def _load_csv(path: Path, fs_override: float | None) -> _Recording:
    meta: dict[str, str] = {}
    header: str | None = None
    with path.open("r", encoding="utf-8", newline="") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                key, sep, value = stripped.lstrip("#").strip().partition("=")
                if sep:
                    meta[key.strip().lower()] = value.strip()
                continue
            header = stripped
            break
        rest = fh.read()
    if header is None:
        raise ValueError(f"{path}: no header line (expected e.g. 'Fp1:eeg,Fp2:eeg')")
    names = [c.strip() for c in header.split(",")]
    time_col = names[0].lower() in ("t", "time", "timestamp")
    specs = names[1:] if time_col else names
    channels = tuple(_parse_channel_spec(s) for s in specs)
    if not channels:
        raise ValueError(f"{path}: header names no channels")
    n_cols = len(names)
    if rest.strip():
        rows = np.loadtxt(io.StringIO(rest), delimiter=",", ndmin=2, dtype=np.float64)
    else:
        rows = np.zeros((0, n_cols))
    if rows.shape[1] != n_cols:
        raise ValueError(f"{path}: header has {n_cols} columns but rows have {rows.shape[1]}")
    times = rows[:, 0] if time_col else None
    data = _finite(rows[:, 1:].T if time_col else rows.T, str(path))

    fs = fs_override
    if fs is None and "fs" in meta:
        fs = float(meta["fs"])
    if fs is None and times is not None and times.size > 1:
        step = float(np.median(np.diff(times)))
        fs = 1.0 / step if step > 0 else None
    if fs is None or fs <= 0:
        raise ValueError(f"{path}: sampling rate unknown — add a '# fs=250' line, a time "
                         f"column, or pass fs=")
    t0 = float(meta["t0"]) if "t0" in meta else (float(times[0]) if times is not None and times.size else 0.0)
    return _Recording(np.ascontiguousarray(data), float(fs), channels, t0)


def _load_npz(path: Path, fs_override: float | None) -> _Recording:
    with np.load(path, allow_pickle=False) as z:
        if "data" not in z or "channels" not in z:
            raise ValueError(f"{path}: .npz needs 'data' and 'channels' arrays")
        data = np.asarray(z["data"], dtype=np.float64)
        channels = tuple(_parse_channel_spec(str(s)) for s in z["channels"])
        fs = fs_override if fs_override is not None else (float(z["fs"]) if "fs" in z else None)
        t0 = float(z["t0"]) if "t0" in z else 0.0
    if data.ndim != 2 or data.shape[0] != len(channels):
        raise ValueError(f"{path}: 'data' must be (channels, samples) matching the "
                         f"{len(channels)} channel names")
    if fs is None or fs <= 0:
        raise ValueError(f"{path}: sampling rate unknown — store 'fs' or pass fs=")
    return _Recording(np.ascontiguousarray(_finite(data, str(path))), float(fs), channels, t0)


class FileReplaySource:
    """Replay a recorded CSV, ``.npz``, EDF/EDF+/BDF or XDF session as a :class:`BlockSource`.

    ``realtime=False`` (default) delivers every block immediately — the way to score a
    detector over a long recording in seconds. ``realtime=True`` paces to the wall clock
    (``read()`` returns ``None`` until a block is due), which is what a live demo wants.
    ``EOFError`` is raised once the last sample has been delivered; ``start()`` rewinds,
    so one object can be replayed. The file is read in the constructor: a missing or
    malformed file raises ``FileNotFoundError`` / ``ValueError`` there, because the
    caller named it explicitly.

    ``.edf``/``.bdf`` go through the pure reader in :mod:`yazses.biosignal.edf` and
    ``.xdf`` through :mod:`yazses.biosignal.xdf` (the optional ``xdf`` extra). For those,
    ``fs`` *selects* a sample-rate group rather than overriding the rate, and the file's
    annotations or marker stream become :meth:`ground_truth` -- so ``evaluate`` can score
    a detector against a labelled recording from another tool.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        fs: float | None = None,
        block_samples: int | None = None,
        realtime: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        p = Path(path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"recording not found: {p}")
        suffix = p.suffix.lower()
        self._truth: tuple[BioEvent, ...] = ()
        if suffix in (".edf", ".bdf"):
            from yazses.biosignal.edf import load_edf
            edf = load_edf(p, fs=fs)
            rec = _Recording(edf.data, edf.fs, edf.channels, edf.t0)
            self._truth = tuple(edf.events)
        elif suffix == ".xdf":
            from yazses.biosignal.xdf import load_xdf
            xdf = load_xdf(p)
            rec = _Recording(xdf.data, xdf.fs, xdf.channels, xdf.t0)
            self._truth = tuple(xdf.events)
        elif suffix == ".npz":
            rec = _load_npz(p, fs)
        else:
            rec = _load_csv(p, fs)
        self.path = p
        self.fs: float = rec.fs
        self.channels: tuple[ChannelInfo, ...] = rec.channels
        self._data = rec.data
        self._t0 = rec.t0
        self._block = int(block_samples) if block_samples else max(
            1, round(self.fs * _DEFAULT_BLOCK_SECONDS))
        if self._block <= 0:
            raise ValueError("block_samples must be > 0")
        self._realtime = bool(realtime)
        self._pacer = _Pacer(self.fs, clock)
        self._pos = 0

    @property
    def n_samples(self) -> int:
        return int(self._data.shape[1])

    @property
    def duration(self) -> float:
        return self.n_samples / self.fs

    def ground_truth(self) -> list[BioEvent]:
        """Labelled events carried by the file (EDF+ annotations, XDF markers), else ``[]``."""
        return list(self._truth)

    def start(self) -> None:
        self._pos = 0
        self._pacer.start()

    def read(self) -> SampleBlock | None:
        if self._pos >= self.n_samples:
            raise EOFError(f"end of recording {self.path.name}")
        n = min(self._block, self.n_samples - self._pos)
        if self._realtime and self._pacer.due(self._pos) < n:
            return None
        chunk = self._data[:, self._pos:self._pos + n].copy()
        block = SampleBlock(data=chunk, fs=self.fs, channels=self.channels,
                            t0=self._t0 + self._pos / self.fs)
        self._pos += n
        return block

    def stop(self) -> None:
        return None


def _open_private(path: Path, *, text: bool) -> Any:
    """Open ``path`` for writing, created with mode 0o600 (owner only), truncating."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _RECORDING_FILE_MODE)
    try:
        os.chmod(path, _RECORDING_FILE_MODE)    # also fixes a pre-existing, looser file
    except OSError:                              # pragma: no cover - e.g. Windows ACLs
        log.debug("could not chmod %s", path, exc_info=True)
    return os.fdopen(fd, "w", encoding="utf-8", newline="") if text else os.fdopen(fd, "wb")


def _check_name(info: ChannelInfo) -> None:
    if any(ch in info.name for ch in ",\r\n") or not info.name.strip():
        raise ValueError(f"channel name {info.name!r} cannot be written to CSV")


class _CsvWriter:
    """Incremental recorder for the CSV format described in the module docstring."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path).expanduser()
        self._fh: Any = None
        self._channels: tuple[ChannelInfo, ...] = ()
        self._fs = 0.0
        self._next_t = 0.0
        self._warned_gap = False
        self.samples = 0

    def write(self, block: SampleBlock) -> None:
        if self._fh is None:
            self._open(block)
        elif block.channels != self._channels or block.fs != self._fs:
            raise ValueError("channels or sampling rate changed mid-recording")
        elif abs(block.t0 - self._next_t) > 1.5 / self._fs and not self._warned_gap:
            self._warned_gap = True
            log.warning("recording %s is not contiguous (gap before t=%.3f s); a replay "
                        "will close the gap", self._path, block.t0)
        np.savetxt(self._fh, block.data.T, delimiter=",", fmt="%.4f")
        self._next_t = block.t0 + block.n_samples / self._fs
        self.samples += block.n_samples

    def _open(self, block: SampleBlock) -> None:
        for info in block.channels:
            _check_name(info)
        self._channels, self._fs = block.channels, float(block.fs)
        fh = _open_private(self._path, text=True)
        fh.write("# yazses-biosignal recording v1 (local file; sensitive biometric-adjacent "
                 "data — do not share)\n")
        fh.write(f"# fs={self._fs!r}\n# t0={float(block.t0)!r}\n")
        fh.write(",".join(_channel_spec(c) for c in block.channels) + "\n")
        self._fh = fh

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None


def write_csv(path: str | os.PathLike[str], blocks: Iterable[SampleBlock]) -> int:
    """Write blocks to a CSV recording (mode 0o600); returns the number of samples written.

    All blocks must share channels and ``fs``; ``t0`` of the first block is stored, and
    gaps between blocks are not (a replay is contiguous). Raises ``ValueError`` if
    ``blocks`` is empty, since a recording without a header cannot be replayed.
    """
    writer = _CsvWriter(path)
    try:
        for block in blocks:
            writer.write(block)
    finally:
        writer.close()
    if writer.samples == 0:
        raise ValueError("no blocks to write")
    return writer.samples


def write_npz(path: str | os.PathLike[str], blocks: Iterable[SampleBlock]) -> int:
    """Write blocks to a compressed ``.npz`` recording (mode 0o600); returns samples written.

    Buffers every block in memory — prefer CSV for hours-long sessions.
    """
    chunks: list[np.ndarray] = []
    first: SampleBlock | None = None
    for block in blocks:
        if first is None:
            first = block
        elif block.channels != first.channels or block.fs != first.fs:
            raise ValueError("channels or sampling rate changed mid-recording")
        chunks.append(block.data)
    if first is None:
        raise ValueError("no blocks to write")
    data = np.concatenate(chunks, axis=1)
    fh = _open_private(Path(path).expanduser(), text=False)
    try:
        np.savez_compressed(
            fh, data=data, fs=np.float64(first.fs), t0=np.float64(first.t0),
            channels=np.array([_channel_spec(c) for c in first.channels]),
        )
    finally:
        fh.close()
    return int(data.shape[1])


class RecordingTap:
    """Wrap any source and write every block it yields to a local file (opt-in).

    Transparent to the consumer: ``read()`` returns exactly what the inner source
    returned. A write failure is logged once and recording stops; it never interrupts the
    stream. ``.npz``, ``.edf`` and ``.bdf`` paths are buffered in memory and written at
    ``stop()`` (or at end of stream) -- EDF+/BDF+ open in EDFbrowser, MNE and the vendor
    tools; anything else is streamed to CSV as it arrives. The file is created with mode
    ``0o600`` — it is raw biometric-adjacent signal, so keep it local and private.
    """

    def __init__(self, source: BlockSource, path: str | os.PathLike[str]) -> None:
        self._inner = source
        self._path = Path(path).expanduser()
        self._npz = self._path.suffix.lower() in (".npz", ".edf", ".bdf")
        self._writer: _CsvWriter | None = None
        self._buffer: list[SampleBlock] = []
        self._failed = False
        self._warned = False
        self.fs: float = source.fs
        self.channels: tuple[ChannelInfo, ...] = source.channels

    def start(self) -> None:
        self._inner.start()
        self.fs, self.channels = self._inner.fs, self._inner.channels

    def read(self) -> SampleBlock | None:
        try:
            block = self._inner.read()
        except EOFError:
            self._finish()
            raise
        if block is not None:
            self.fs, self.channels = block.fs, block.channels
            self._record(block)
        return block

    def stop(self) -> None:
        try:
            self._inner.stop()
        finally:
            self._finish()

    def _record(self, block: SampleBlock) -> None:
        if self._failed:
            return
        if not self._warned:
            self._warned = True
            log.warning("Recording raw biosignal samples to %s — sensitive "
                        "biometric-adjacent data; keep it local.", self._path)
        try:
            if self._npz:
                self._buffer.append(block)
            else:
                if self._writer is None:
                    self._writer = _CsvWriter(self._path)
                self._writer.write(block)
        except Exception:
            self._failed = True
            log.warning("Recording to %s failed; the stream continues without it.",
                        self._path, exc_info=True)

    def _finish(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        if self._buffer:
            buffered, self._buffer = self._buffer, []
            try:
                if self._path.suffix.lower() in (".edf", ".bdf"):
                    from yazses.biosignal.edf import write_edf
                    write_edf(self._path, buffered)
                else:
                    write_npz(self._path, buffered)
            except Exception:
                log.warning("Writing %s failed.", self._path, exc_info=True)


# ====================================================================================
# 3. BrainFlow
# ====================================================================================

# A board timestamp that disagrees with the running sample clock by less than this is
# treated as jitter (USB batching) and snapped; more is a real gap and resynchronises.
# Design choice (50 ms: a handful of samples at 250 Hz).
_TS_TOLERANCE_S = 0.05


@dataclass(frozen=True)
class _BoardLayout:
    fs: float
    rows: tuple[int, ...]                  # board row per channel, same order as channels
    channels: tuple[ChannelInfo, ...]
    timestamp_row: int | None


@dataclass(frozen=True)
class BoardDescription:
    """What ``doctor`` prints about a BrainFlow board id (no hardware needed)."""

    board_id: int
    available: bool                        # brainflow importable and the id known
    name: str = ""
    fs: float = 0.0
    channels: tuple[ChannelInfo, ...] = ()
    rows: tuple[int, ...] = ()
    timestamp_row: int | None = None
    note: str = ""                         # why unavailable, or the install hint
    kind_hint: str = ""                    # recommended signal kind(s): see `_kind_hint`

    def format(self) -> str:
        """Human-readable multi-line summary for ``yazses doctor``."""
        if not self.available:
            return f"BrainFlow board {self.board_id}: unavailable — {self.note}"
        chans = ", ".join(f"{_channel_spec(c)}@row{r}" for c, r in zip(self.channels, self.rows))
        return "\n".join([
            f"BrainFlow board {self.board_id}: {self.name or 'unnamed'}",
            f"  sampling rate: {self.fs:g} Hz",
            *([f"  signal kinds: {self.kind_hint}"] if self.kind_hint else []),
            f"  channels: {chans or 'none'}",
            f"  timestamp row: {self.timestamp_row if self.timestamp_row is not None else 'n/a'}",
        ])


def _kind_hint(
    board_id: int, channels: tuple[ChannelInfo, ...], *, overridden: bool,
) -> str:
    """The board's recommended ``kind_hint`` (``"emg"``, ``"eeg"``, ``"emg+eeg"``, ``"mixed"``).

    The board table's advice (:mod:`yazses.biosignal.boards`) when the board is listed and
    the caller has not re-labelled its channels; otherwise read off the channels that will
    actually be streamed (one kind -> that kind, several -> ``"mixed"``). ``""`` when
    there is neither. This is what lets ``doctor`` tell a mixed board (BrainFlow's
    synthetic board -1) from a pure EEG headset.
    """
    if not overridden:
        preset = preset_for(board_id)
        if preset is not None:
            return preset.kind_hint
    kinds = {c.kind for c in channels}
    if not kinds:
        return ""
    return next(iter(kinds)).value if len(kinds) == 1 else "mixed"


def _import_shim() -> Any | None:
    """The ``BoardShim`` class, or None when brainflow is not installed (hint logged)."""
    try:
        from brainflow.board_shim import BoardShim
    except ModuleNotFoundError:
        from yazses.system.remedy import install_hint

        log.info("BrainFlow not installed — biosignal board source disabled. %s",
                 install_hint("emg-band"))
        return None
    return BoardShim


def _rows(shim: Any, method: str, board_id: int) -> list[int]:
    """A static ``BoardShim.get_*_channels`` list, or [] when the board has none / lacks it."""
    try:
        return [int(r) for r in getattr(shim, method)(board_id)]
    except Exception:
        log.debug("BoardShim.%s(%s) unavailable", method, board_id, exc_info=True)
        return []


def _resolve_layout(
    shim: Any, board_id: int,
    channel_kinds: Mapping[str, SignalKind | str] | None,
) -> _BoardLayout:
    """Map a board's rows to ChannelInfo. ``shim`` is BoardShim or any instance (statics work)."""
    fs = float(shim.get_sampling_rate(board_id))
    eeg = _rows(shim, "get_eeg_channels", board_id)
    emg = _rows(shim, "get_emg_channels", board_id)
    eog = _rows(shim, "get_eog_channels", board_id)
    try:
        eeg_names = [str(n) for n in shim.get_eeg_names(board_id)]
    except Exception:
        eeg_names = []
    if len(eeg_names) != len(eeg):
        eeg_names = []                       # not aligned with the rows: do not guess

    entries: list[tuple[int, str, SignalKind]] = []
    seen: set[int] = set()
    # A row a board lists as both EEG and EMG (generic ExG pins) is treated as EEG: the
    # named scalp montage wins. `channel_kinds` is the override.
    for i, row in enumerate(eeg):
        entries.append((row, eeg_names[i] if eeg_names else f"EEG{i + 1}", SignalKind.EEG))
        seen.add(row)
    for i, row in enumerate(r for r in emg if r not in seen):
        entries.append((row, f"EMG{i + 1}", SignalKind.EMG))
        seen.add(row)
    for i, row in enumerate(r for r in eog if r not in seen):
        entries.append((row, f"EOG{i + 1}", SignalKind.EOG))
        seen.add(row)

    if channel_kinds:
        wanted = {name: _coerce_kind(kind) for name, kind in channel_kinds.items()}
        unknown = sorted(set(wanted) - {name for _, name, _ in entries})
        if unknown:
            log.warning("channel_kinds names unknown channel(s) %s for board %s (have: %s)",
                        unknown, board_id, ", ".join(n for _, n, _ in entries))
        entries = [(row, name, wanted[name]) for row, name, _ in entries if name in wanted]

    try:
        ts_row: int | None = int(shim.get_timestamp_channel(board_id))
    except Exception:
        ts_row = None
    return _BoardLayout(
        fs=fs,
        rows=tuple(r for r, _, _ in entries),
        channels=tuple(ChannelInfo(n, k) for _, n, k in entries),
        timestamp_row=ts_row,
    )


def describe_board(
    board_id: int,
    *,
    channel_kinds: Mapping[str, SignalKind | str] | None = None,
) -> BoardDescription:
    """Describe a BrainFlow board without opening it, for ``yazses doctor``.

    Never raises: a missing brainflow package or an unknown board id comes back as
    ``available=False`` with the reason (and the install hint) in ``note``. ``kind_hint``
    is the board's recommended signal kind(s) from the board table (also filled when the
    board is unavailable), or read off the streamed channels for an unlisted board or a
    ``channel_kinds`` override.
    """
    shim = _import_shim()
    if shim is None:
        from yazses.system.remedy import install_hint

        return BoardDescription(int(board_id), False,
                                note=install_hint("emg-band") or "brainflow is not importable",
                                kind_hint=_kind_hint(int(board_id), (), overridden=bool(channel_kinds)))
    try:
        layout = _resolve_layout(shim, int(board_id), channel_kinds)
    except Exception as exc:
        return BoardDescription(int(board_id), False, note=f"unknown board or no description ({exc})",
                                kind_hint=_kind_hint(int(board_id), (), overridden=bool(channel_kinds)))
    name = ""
    try:
        name = str(shim.get_device_name(int(board_id)))
    except Exception:
        try:
            name = str(shim.get_board_descr(int(board_id)).get("name", ""))
        except Exception:
            log.debug("no device name for board %s", board_id, exc_info=True)
    return BoardDescription(
        int(board_id), True, name, layout.fs, layout.channels, layout.rows,
        layout.timestamp_row,
        kind_hint=_kind_hint(int(board_id), layout.channels, overridden=bool(channel_kinds)))


class BrainFlowBlockSource:
    """A BrainFlow board as a :class:`BlockSource` (OpenBCI, Muse, ... or the synthetic board).

    ``channel_kinds`` maps channel *names* (as :func:`describe_board` shows them) to a
    ``SignalKind`` (or its string): when given, only those channels are streamed and
    their kind is overridden — how a Cyton's ExG pins become ``EMG`` for a forearm band.
    Without it, rows are classified from the board's own EEG / EMG / EOG channel lists.
    ``uv_scale`` multiplies the raw rows into microvolts; BrainFlow reports ExG rows in
    µV, so the default is 1.0 and the knob exists for a board that does not.
    ``board_factory`` is injected by tests (a fake board); production passes ``None``.

    ``kind_hint`` is the board's recommended signal kind(s) (see :func:`describe_board`):
    known from the board table before ``start()`` (``""`` for an unlisted board with a
    ``channel_kinds`` override) and refined from the real channels after it, so the doctor
    can treat a ``"mixed"`` board such as the synthetic board -1 differently.

    ``fs`` and ``channels`` are only known once the board is open: they are ``0.0`` and
    ``()`` until ``start()`` succeeds. Check ``available`` after ``start()``; when it is
    ``False`` the reason is in ``last_error`` and ``read()`` returns ``None`` forever (a
    logged no-op, never a crash). ``t0`` follows the board timestamp channel, snapping
    small jitter to a continuous clock and resynchronising across real gaps
    (``gap_samples`` estimates what was lost); it never goes backwards.
    """

    def __init__(
        self,
        board_id: int,
        serial_port: str = "",
        *,
        channel_kinds: Mapping[str, SignalKind | str] | None = None,
        board_factory: Callable[[], Any] | None = None,
        uv_scale: float = 1.0,
    ) -> None:
        from yazses.biosignal.boards import is_known_brainflow_board

        if not is_known_brainflow_board(int(board_id)):
            raise ValueError(
                f"BrainFlow board id {int(board_id)} is not one YazSes opens. "
                "`yazses biosignal boards` lists the ones it does. Boards that stream over a "
                "network are refused, because nothing may leave this machine; any other board "
                "needs an entry in biosignal/boards.py first.")
        self._board_id = int(board_id)
        self._serial_port = serial_port
        self._channel_kinds = dict(channel_kinds) if channel_kinds else None
        self._board_factory = board_factory
        self._uv_scale = float(uv_scale)
        self._board: Any = None
        self._layout: _BoardLayout | None = None
        self._origin: float | None = None        # first board timestamp, subtracted from all
        self._expected_t: float | None = None
        self.fs: float = 0.0
        self.channels: tuple[ChannelInfo, ...] = ()
        self.kind_hint: str = "" if channel_kinds else _kind_hint(
            self._board_id, (), overridden=False)
        self.available = False
        self.last_error = ""
        self.gap_samples = 0

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._board is not None:
            return
        self.available = False
        self.last_error = ""
        board = self._open()
        if board is None:
            return
        try:
            layout = _resolve_layout(board, self._board_id, self._channel_kinds)
            if not layout.rows:
                raise RuntimeError("the board exposes no usable channels")
            board.start_stream()
        except Exception as exc:
            self._fail(f"BrainFlow board {self._board_id} could not start ({exc})", board)
            return
        self._board, self._layout = board, layout
        self.fs, self.channels = layout.fs, layout.channels
        self.kind_hint = _kind_hint(
            self._board_id, layout.channels, overridden=self._channel_kinds is not None)
        self._origin = self._expected_t = None
        self.gap_samples = 0
        self.available = True
        log.info("BrainFlow block source streaming (board %s, %d channel(s) at %g Hz).",
                 self._board_id, len(layout.rows), layout.fs)

    def read(self) -> SampleBlock | None:
        """Everything the board has buffered since the last call, or None if nothing."""
        if not self.available or self._board is None or self._layout is None:
            return None
        try:
            raw = np.asarray(self._board.get_board_data())
        except Exception as exc:
            self._fail(f"BrainFlow board {self._board_id} stopped streaming ({exc})", self._board)
            return None
        block = self._convert(raw, advance=True)
        return block

    def peek(self, n_samples: int = 250) -> SampleBlock | None:
        """The latest ``n_samples`` WITHOUT draining the buffer (for ``doctor`` quality checks)."""
        if not self.available or self._board is None or self._layout is None:
            return None
        try:
            raw = np.asarray(self._board.get_current_board_data(int(n_samples)))
        except Exception:
            log.debug("BrainFlow peek failed", exc_info=True)
            return None
        return self._convert(raw, advance=False)

    def stop(self) -> None:
        board, self._board = self._board, None
        self.available = False
        if board is not None:
            self._close(board)

    # ---- internals -------------------------------------------------------

    def _open(self) -> Any | None:
        """Create the board and prepare its session, or None with the reason recorded."""
        board = None
        try:
            if self._board_factory is not None:
                board = self._board_factory()
            else:
                try:
                    from brainflow.board_shim import BoardShim, BrainFlowInputParams
                except ModuleNotFoundError:
                    from yazses.system.remedy import install_hint

                    self.last_error = "brainflow is not installed"
                    log.info("BrainFlow not installed — biosignal board source disabled. %s",
                             install_hint("emg-band"))
                    return None
                params = BrainFlowInputParams()
                if self._serial_port:
                    params.serial_port = self._serial_port
                board = BoardShim(self._board_id, params)
            board.prepare_session()
            return board
        except Exception as exc:
            # An unplugged or busy device is the common case, not worth taking the daemon down.
            self._fail(f"BrainFlow board {self._board_id} unavailable ({exc}); "
                       "continuing without it.", board)
            return None

    def _fail(self, message: str, board: Any | None) -> None:
        self.last_error = message
        self.available = False
        log.warning("%s", message)
        if board is not None:
            self._close(board)
        if board is self._board:
            self._board = None

    @staticmethod
    def _close(board: Any) -> None:
        for step in ("stop_stream", "release_session"):
            try:
                getattr(board, step)()
            except Exception:  # pragma: no cover - teardown is best effort
                log.debug("BrainFlow %s failed", step, exc_info=True)

    def _convert(self, raw: np.ndarray, *, advance: bool) -> SampleBlock | None:
        layout = self._layout
        assert layout is not None
        if raw.ndim != 2 or raw.shape[1] == 0:
            return None
        if max(layout.rows) >= raw.shape[0]:
            self._fail(f"BrainFlow board {self._board_id} returned {raw.shape[0]} rows; "
                       f"expected at least {max(layout.rows) + 1}", self._board)
            return None
        data = raw[list(layout.rows), :].astype(np.float64) * self._uv_scale
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
        n = int(data.shape[1])
        t0 = self._block_t0(raw, n, layout, advance)
        return SampleBlock(data=data, fs=layout.fs, channels=layout.channels, t0=t0)

    def _block_t0(self, raw: np.ndarray, n: int, layout: _BoardLayout, advance: bool) -> float:
        board_t0: float | None = None
        ts_row = layout.timestamp_row
        if ts_row is not None and 0 <= ts_row < raw.shape[0]:
            first = float(raw[ts_row, 0])
            if np.isfinite(first) and first > 0.0:
                if self._origin is None and advance:
                    self._origin = first
                if self._origin is not None:
                    board_t0 = first - self._origin
        expected = self._expected_t
        if expected is None:
            t0 = board_t0 if board_t0 is not None else 0.0
        elif board_t0 is None:
            t0 = expected
        else:
            gap = board_t0 - expected
            if abs(gap) <= _TS_TOLERANCE_S:
                t0 = expected                      # jitter: keep the continuous clock
            elif gap > 0:
                t0 = board_t0                      # a real hole: resynchronise
                if advance:
                    lost = int(round(gap * layout.fs))
                    self.gap_samples += lost
                    log.warning("BrainFlow board %s: ~%d sample(s) (%.3f s) missing before "
                                "t=%.3f s", self._board_id, lost, gap, t0)
            else:
                t0 = expected                      # the board clock stepped back: never rewind
        if advance:
            self._expected_t = t0 + n / layout.fs
        return t0


# ====================================================================================
# 4. factory
# ====================================================================================

_SPEC_HELP = ("expected 'synthetic', 'synthetic:<emg|eeg|eog|mixed>', 'file:<path>', "
              "'brainflow:<board_id>[:<serial_port>]', 'lsl:<name>' / 'lsl:type=<type>', "
              "'thinkgear:<port>', 'bitalino:<port>[:<options>]' or 'myo:<address>'")


def open_source(spec: str, **kw: Any) -> BlockSource:
    """Build a source from a one-line spec; extra keyword arguments go to its constructor.

    * ``synthetic`` / ``synthetic:emg`` / ``:eeg`` / ``:eog`` / ``:mixed`` — :class:`SyntheticSource`
      (bare ``synthetic`` is the ``mixed`` montage).
    * ``file:<path>`` — :class:`FileReplaySource` (everything after the first colon is the
      path, so ``file:C:\\rec.csv`` works).
    * ``brainflow:<board_id>[:<serial_port>]`` — :class:`BrainFlowBlockSource`
      (``brainflow:-1`` is BrainFlow's synthetic board).
    * ``lsl:<name>`` / ``lsl:type=<type>`` / ``lsl:source_id=<id>`` — a Lab Streaming Layer
      stream published on *this* machine (:mod:`yazses.biosignal.lsl_source`).
    * ``thinkgear:<port>[:<options>]`` — a NeuroSky ThinkGear headset
      (:mod:`yazses.biosignal.thinkgear`).
    * ``bitalino:<port>[:<options>]`` — a PLUX BITalino (r)evolution board
      (:mod:`yazses.biosignal.bitalino`).
    * ``myo:<address>`` — a Myo armband's raw EMG over Bluetooth LE
      (:mod:`yazses.biosignal.myo`).

    The device modules are imported only when their scheme is asked for, and each keeps
    its optional dependency (pylsl, pyserial, bleak) lazy inside it.

    Raises ``ValueError`` for an unknown or malformed spec. The returned source is not
    started.
    """
    text = spec.strip()
    scheme, _, rest = text.partition(":")
    scheme = scheme.strip().lower()
    if scheme == "synthetic":
        return SyntheticSource(rest.strip().lower() or "mixed", **kw)
    if scheme == "file":
        if not rest.strip():
            raise ValueError(f"file spec {spec!r} has no path ({_SPEC_HELP})")
        return FileReplaySource(rest.strip(), **kw)
    if scheme == "brainflow":
        board, _, port = rest.partition(":")
        try:
            board_id = int(board.strip())
        except ValueError:
            raise ValueError(f"brainflow spec {spec!r} needs an integer board id "
                             f"({_SPEC_HELP})") from None
        return BrainFlowBlockSource(board_id, port.strip(), **kw)
    if scheme == "lsl":
        from yazses.biosignal.lsl_source import open_lsl_source
        return open_lsl_source(text, **kw)
    if scheme == "thinkgear":
        from yazses.biosignal.thinkgear import thinkgear_from_spec
        return thinkgear_from_spec(rest, **kw)
    if scheme == "bitalino":
        from yazses.biosignal.bitalino import bitalino_from_spec
        return bitalino_from_spec(rest, **kw)
    if scheme == "myo":
        from yazses.biosignal.myo import source_from_spec
        return source_from_spec(text, **kw)   # full text: a MAC address contains colons
    raise ValueError(f"unknown source spec {spec!r}; {_SPEC_HELP}")

