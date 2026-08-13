"""Graded squeeze: how hard, not just whether (#103).

The EMG backend today answers one question — is the muscle tense? Grip force
regresses at r≈0.97 in the literature and onset lands at 35–125 ms with classical
threshold/TKEO methods, so a squeeze can carry *which mode* as well as *when*,
which is what makes a one-muscle switch usable without a keyboard.

Semantics deliberately mirror the two mode switches that already exist — the
command key and the sotto-voce channel — so all three behave identically:

* **light squeeze → dictate** (push-to-talk)
* **hard squeeze → command mode**

Everything here is pure: envelope → level → mode. No serial port, no board, no
threads, so it tests against synthetic envelopes exactly as the issue asks.

## Why TKEO rather than a bare threshold

The Teager–Kaiser energy operator, ψ(x[n]) = x[n]² − x[n−1]·x[n+1], responds to
*amplitude × frequency* rather than amplitude alone. EMG onset is a burst of
high-frequency activity, while the artefacts that plague a raw threshold —
baseline wander, cable sway, a DC offset from a shifting electrode — are
low-frequency and large. Squaring the raw signal cannot separate those; TKEO
suppresses them by construction, which is why the onset literature uses it.

## Calibration is per person and per session, and is not guessed

Muscle amplitude varies by an order of magnitude between people, electrode
placement, and skin condition, so fixed microvolt thresholds are meaningless.
`calibrate` derives both thresholds from the user's own relaxed baseline and
maximum voluntary contraction, which is a 10-second procedure rather than a
number in a config file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class SqueezeLevel(Enum):
    """How hard the muscle is being squeezed, as a level rather than a number."""

    RELAXED = "relaxed"
    LIGHT = "light"
    HARD = "hard"


# The mode each level owns. Mirrors the command key: hold to dictate, harder to
# command — so a user who learns one has learned all three.
LEVEL_MODE = {
    SqueezeLevel.RELAXED: None,
    SqueezeLevel.LIGHT: "full_text",
    SqueezeLevel.HARD: "command",
}

# Fractions of the calibrated contraction range. Light starts well above the
# noise floor so a resting twitch cannot trigger dictation; hard sits at 60%
# because a sustained maximum contraction is tiring and nobody would hold it.
DEFAULT_LIGHT_FRACTION = 0.20
DEFAULT_HARD_FRACTION = 0.60
# A level must persist to count, so a spike on the way to a hard squeeze is not
# read as a light one. 40 ms is below the 35–125 ms onset range, so it costs
# nothing perceptible.
DEFAULT_HOLD_SAMPLES = 3


@dataclass(frozen=True)
class PressureThresholds:
    """Calibrated envelope levels for one person, one session."""

    light: float
    hard: float

    def level(self, envelope: float) -> SqueezeLevel:
        if envelope >= self.hard:
            return SqueezeLevel.HARD
        if envelope >= self.light:
            return SqueezeLevel.LIGHT
        return SqueezeLevel.RELAXED


def tkeo(signal) -> np.ndarray:
    """Teager–Kaiser energy: ψ(x[n]) = x[n]² − x[n−1]·x[n+1]. Pure.

    Endpoints are dropped rather than padded — padding invents an energy value
    that the operator cannot know, and a phantom sample at the edge is exactly
    where a spurious onset would be read.
    """
    x = np.asarray(signal, dtype="float64")
    if x.size < 3:
        return np.zeros(0, dtype="float64")
    return x[1:-1] ** 2 - x[:-2] * x[2:]


def envelope(signal, *, window: int = 32) -> float:
    """A single robust activity level for a window of raw EMG.

    The mean of the rectified TKEO output. Mean rather than peak: a single
    spike — a cable knock, an ADC glitch — should not read as a contraction.
    """
    energy = np.abs(tkeo(signal))
    if energy.size == 0:
        return 0.0
    if window and energy.size > window:
        energy = energy[-window:]
    return float(np.mean(energy))


def calibrate(
    relaxed_signal,
    max_contraction_signal,
    *,
    light_fraction: float = DEFAULT_LIGHT_FRACTION,
    hard_fraction: float = DEFAULT_HARD_FRACTION,
) -> PressureThresholds:
    """Derive thresholds from this person's own baseline and maximum. Pure.

    Both thresholds are placed inside the range *above* the resting floor, so a
    person whose baseline is noisy gets higher thresholds automatically instead
    of a stream of false activations.
    """
    floor = envelope(relaxed_signal, window=0)
    ceiling = envelope(max_contraction_signal, window=0)
    span = max(ceiling - floor, 0.0)
    if span <= 0:
        # Indistinguishable baseline and contraction: refuse to invent a range.
        # Placing thresholds anyway would produce a switch that fires at random.
        raise ValueError(
            "relaxed and maximum contraction are indistinguishable — check "
            "electrode placement and re-run calibration"
        )
    return PressureThresholds(
        light=floor + span * light_fraction,
        hard=floor + span * hard_fraction,
    )


class GradedSqueeze:
    """Turns a stream of envelope readings into stable mode transitions.

    Holds the level for `hold_samples` before reporting it, so the ramp through
    `light` on the way to a `hard` squeeze does not briefly start dictation.
    """

    def __init__(
        self,
        thresholds: PressureThresholds,
        *,
        hold_samples: int = DEFAULT_HOLD_SAMPLES,
    ) -> None:
        self._thresholds = thresholds
        self._hold = max(1, hold_samples)
        self._reported = SqueezeLevel.RELAXED
        self._pending = SqueezeLevel.RELAXED
        self._count = 0

    @property
    def level(self) -> SqueezeLevel:
        return self._reported

    @property
    def mode(self) -> str | None:
        """The activation mode this level owns, or None when relaxed."""
        return LEVEL_MODE[self._reported]

    def update(self, envelope_value: float) -> SqueezeLevel | None:
        """Feed one envelope reading. Returns the new level on a change, else None."""
        candidate = self._thresholds.level(envelope_value)
        if candidate == self._pending:
            self._count += 1
        else:
            self._pending, self._count = candidate, 1
        if candidate != self._reported and self._count >= self._hold:
            self._reported = candidate
            return candidate
        return None
