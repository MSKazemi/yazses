"""Quiet / noisy room classifier and a floor-relative gate (pure) -- ADR-v2-039.

Input is a list of per-frame levels (mean |x| per frame, the same quantity the silence gate
compares), taken from the hold-to-talk burst itself. No model, no dependency, no absolute
level: every number is a ratio to the burst's own quietest frames or to the gate the user
configured.

* **floor** -- the mean of the quietest fifth of the frames: the room as heard between and
  around words.
* **noisy** -- the floor reaches at least half of the configured gate. The room alone is then
  close enough to the gate that flat noise can cross it, whatever the microphone's scale.
* **gate** -- never below the configured gate, never above ``max_raise`` times it, never above
  twice the floor, and only for a *flat* burst. A burst whose loud frames stand well over its
  floor has speech-like dynamics and keeps the configured gate: the raise exists to reject
  flat room noise, not to second-guess speech.

The consequence that matters: the effective gate is always inside ``[configured, 1.5 x
configured]``, so a microphone that reads 0.003-0.005 against a gate calibrated to it can only
ever lose a burst that is flat, at most 1.5 x its own floor, and under 1.5 x the gate.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from yazses.acoustic.profiles import MAX_FLOOR_MULTIPLE, policy_for, should_switch

#: Frames needed for any estimate (10 x 20 ms): a shorter burst has no "between words" to hear.
MIN_FRAMES = 10
#: Share of the frames, quietest first, that make up the floor.
FLOOR_FRACTION = 0.2
#: Percentile of the frame levels taken as the burst's loud end.
LOUD_PERCENTILE = 0.9
#: The room is "noisy" when its floor is at least this share of the configured gate.
NOISY_FLOOR_RATIO = 0.5
#: Loud-end / floor above which a burst has speech-like dynamics and is never gated harder.
#: Stationary noise measured in 20 ms frames stays near 1.1-1.5; speech with any pause or
#: onset is far above 2.5.
SPEECH_SPREAD = 2.5


@dataclass(frozen=True)
class FloorEstimate:
    floor: float   # mean frame level of the quietest frames
    loud: float    # LOUD_PERCENTILE frame level
    frames: int

    @property
    def spread(self) -> float:
        """Loud end over floor; infinite when the floor is exactly zero (digital silence)."""
        return math.inf if self.floor <= 0.0 else self.loud / self.floor


def floor_estimate(levels: Sequence[float]) -> FloorEstimate | None:
    """Estimate the room floor from per-frame levels, or ``None`` without enough evidence."""
    vals = [float(v) for v in levels]
    if len(vals) < MIN_FRAMES or not all(math.isfinite(v) and v >= 0.0 for v in vals):
        return None
    vals.sort()
    n = len(vals)
    k = max(1, int(n * FLOOR_FRACTION))
    floor = sum(vals[:k]) / k
    loud = vals[min(n - 1, int(n * LOUD_PERCENTILE))]
    return FloorEstimate(floor=floor, loud=loud, frames=n)


def classify_scene(estimate: FloorEstimate | None, base_gate: float) -> str:
    """``"noisy"`` when the floor is within reach of the configured gate, else ``"quiet"``.

    No estimate, or a gate that is not a positive finite number, is ``"quiet"``: the
    conservative scene, which changes nothing.
    """
    if estimate is None or not (math.isfinite(base_gate) and base_gate > 0.0):
        return "quiet"
    return "noisy" if estimate.floor >= NOISY_FLOOR_RATIO * base_gate else "quiet"


def effective_gate(base_gate: float, estimate: FloorEstimate | None, scene: str) -> float:
    """The gate to compare this burst against; always in ``[base_gate, base_gate * max_raise]``."""
    if not (math.isfinite(base_gate) and base_gate > 0.0) or estimate is None:
        return base_gate
    policy = policy_for(scene)
    if policy.floor_multiple <= 0.0 or estimate.spread >= SPEECH_SPREAD:
        return base_gate
    ceiling = min(base_gate * policy.max_raise, estimate.floor * MAX_FLOOR_MULTIPLE)
    wanted = estimate.floor * policy.floor_multiple
    return min(max(wanted, base_gate), max(ceiling, base_gate))


class SceneTracker:
    """Holds the current scene and moves it only after ``min_stable`` consecutive observations."""

    def __init__(self, min_stable: int = 3) -> None:
        self.min_stable = max(1, int(min_stable))
        self.current = "quiet"
        self._candidate: str | None = None
        self._count = 0

    def observe(self, scene: str) -> str:
        if scene == self.current:
            self._candidate, self._count = None, 0
            return self.current
        if scene == self._candidate:
            self._count += 1
        else:
            self._candidate, self._count = scene, 1
        if should_switch(scene, self.current, self._count, self.min_stable):
            self.current = scene
            self._candidate, self._count = None, 0
        return self.current
