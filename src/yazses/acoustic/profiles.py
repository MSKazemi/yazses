"""Acoustic scene -> profile policy (pure) -- ADR-v2-039, amended 2026-10-15 (proposed).

Two scenes, ``quiet`` and ``noisy``, and a policy that is *relative*: a multiple of the room
floor measured from the burst itself, clamped to a multiple of the gate the user configured.
There is deliberately no absolute VAD threshold here. The earlier table (0.010 .. 0.035) sat
6-10x above the real level of a laptop's microphone (mean |x| of 0.003-0.005 at full gain), so
applying it would have gated away all speech; a number that fits one machine fits no other.

Pure and deterministic; hysteresis (:func:`should_switch`) keeps a transient sound from
thrashing the active scene.
"""
from __future__ import annotations

from dataclasses import dataclass

SCENES = ("quiet", "noisy")


@dataclass(frozen=True)
class ScenePolicy:
    """How a scene may move the silence gate -- always relative, never an absolute level."""
    scene: str
    #: Wanted gate as a multiple of the measured room floor (0 = leave the gate alone).
    floor_multiple: float
    #: The gate may rise at most this multiple of the gate the user configured.
    max_raise: float


_POLICIES = {
    "quiet": ScenePolicy("quiet", 0.0, 1.0),
    "noisy": ScenePolicy("noisy", 1.5, 1.5),
}

#: The gate never exceeds this multiple of the measured floor, whatever else is asked.
MAX_FLOOR_MULTIPLE = 2.0


def policy_for(scene) -> ScenePolicy:
    """Return the :class:`ScenePolicy` for a scene label; unknown -> ``quiet``. Pure."""
    return _POLICIES.get((scene or "").lower(), _POLICIES["quiet"])


def should_switch(new_scene, current_scene, stable_count: int, min_stable: int = 3) -> bool:
    """Switch profiles only after ``new_scene`` has been observed ``min_stable`` times in a row.

    Returns False when the new scene matches the current one (nothing to do) or the run of
    consecutive observations hasn't yet reached ``min_stable`` (hysteresis). Pure.
    """
    if new_scene == current_scene:
        return False
    return stable_count >= min_stable
