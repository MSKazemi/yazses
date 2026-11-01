"""Shared contract for the biosignal package. Pure: numpy + stdlib only.

Every other module in ``yazses.biosignal`` codes against these names so that they can be
written independently and composed later. Do not add behaviour here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

import numpy as np


class SignalKind(Enum):
    """What a channel physically measures. Decides which detector may read it."""

    EMG = "emg"      # muscle electricity (forearm, jaw, face)
    EEG = "eeg"      # scalp electricity; frontal channels carry blink/jaw artifacts
    EOG = "eog"      # eye electricity (electrodes around the eyes)


class EventKind(Enum):
    """The few things an artifact-grade detector may report."""

    SQUEEZE_ON = "squeeze_on"
    SQUEEZE_OFF = "squeeze_off"
    BLINK = "blink"
    DOUBLE_BLINK = "double_blink"
    JAW_CLENCH = "jaw_clench"


@dataclass(frozen=True)
class ChannelInfo:
    """One row of a sample block."""

    name: str
    kind: SignalKind


@dataclass(frozen=True)
class SampleBlock:
    """A contiguous chunk of multichannel samples.

    ``data`` has shape ``(n_channels, n_samples)``, in microvolts. ``t0`` is the time of
    the first sample in seconds on the source's own monotonic clock, ``fs`` the sampling
    rate in Hz.
    """

    data: np.ndarray
    fs: float
    channels: tuple[ChannelInfo, ...]
    t0: float = 0.0

    @property
    def n_samples(self) -> int:
        return int(self.data.shape[-1])

    @property
    def duration(self) -> float:
        return self.n_samples / self.fs if self.fs else 0.0


@dataclass(frozen=True)
class BioEvent:
    """One detection. ``t`` is the event time (seconds, source clock); ``confidence`` in [0, 1]."""

    kind: EventKind
    t: float
    confidence: float = 1.0
    channel: str = ""
    detail: dict = field(default_factory=dict)


@runtime_checkable
class BlockSource(Protocol):
    """Anything that produces SampleBlocks: a board, a file replay, a synthetic generator."""

    fs: float
    channels: tuple[ChannelInfo, ...]

    def start(self) -> None: ...
    def read(self) -> SampleBlock | None:
        """Next block, or None if nothing new yet. Raises EOFError when a finite source ends."""
        ...
    def stop(self) -> None: ...


@runtime_checkable
class StreamDetector(Protocol):
    """A streaming detector: feed blocks in order, get zero or more events back."""

    def process(self, block: SampleBlock) -> Sequence[BioEvent]: ...
    def reset(self) -> None: ...
