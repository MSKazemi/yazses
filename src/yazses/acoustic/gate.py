"""Burst-level acoustic gate (numpy) -- the daemon-facing half of ADR-v2-039.

``scene.py`` is pure over a list of frame levels; this module cuts a hold-to-talk burst into
20 ms frames, feeds it, keeps the :class:`~yazses.acoustic.scene.SceneTracker`, and hands the
daemon the gate to use for *this* burst. The result is an in-memory override only: it is never
written to ``config.toml`` and the configured ``vad_threshold`` is never modified.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from yazses.acoustic.scene import (
    FloorEstimate,
    SceneTracker,
    classify_scene,
    effective_gate,
    floor_estimate,
)

FRAME_MS = 20


@dataclass(frozen=True)
class GateDecision:
    scene: str           # the tracker's current scene after this burst
    floor: float | None  # measured floor of this burst; None without enough audio
    base_gate: float     # the gate the user configured
    gate: float          # the gate to use for this burst; >= base_gate


def frame_levels(audio: np.ndarray, sample_rate: int) -> list[float]:
    """Mean |x| of each whole 20 ms frame -- the quantity the silence gate compares."""
    x = np.asarray(audio, dtype=np.float32).reshape(-1)
    size = max(1, int(sample_rate * FRAME_MS / 1000))
    n = x.size // size
    if n == 0:
        return []
    return np.abs(x[: n * size]).reshape(n, size).mean(axis=1).tolist()


class AcousticGate:
    """Per-daemon state: the scene tracker and the last decision, for ``yazses status``."""

    def __init__(self, min_stable: int = 3) -> None:
        self._tracker = SceneTracker(min_stable)
        self._last: GateDecision | None = None
        self._bursts = 0

    def decide(self, audio: np.ndarray, sample_rate: int, base_gate: float) -> GateDecision:
        est: FloorEstimate | None = floor_estimate(frame_levels(audio, sample_rate))
        if est is not None:
            self._tracker.observe(classify_scene(est, base_gate))
        scene = self._tracker.current
        decision = GateDecision(
            scene=scene,
            floor=None if est is None else est.floor,
            base_gate=base_gate,
            gate=effective_gate(base_gate, est, scene),
        )
        self._last = decision
        self._bursts += 1
        return decision

    def status(self) -> dict | None:
        """What ``yazses status`` shows; ``None`` until a burst has been judged."""
        d = self._last
        if d is None:
            return None
        return {
            "scene": d.scene,
            "floor": None if d.floor is None else round(d.floor, 6),
            "base_gate": round(d.base_gate, 6),
            "gate": round(d.gate, 6),
            "bursts": self._bursts,
        }
