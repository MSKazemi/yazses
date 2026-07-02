"""Acoustic scene → profile policy (pure) — ADR-v2-039.

Map a coarse scene label to a recommended capture policy and apply hysteresis so a transient
sound never thrashes the active profile. Pure and deterministic; the scene tagger lives behind
the ``acoustic`` extra.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenePolicy:
    """Recommended capture settings for an acoustic scene."""
    scene: str
    vad_threshold: float
    denoise: bool


# Conservative recommendations; noisy scenes raise the VAD gate and enable denoise.
_POLICIES = {
    "quiet": ScenePolicy("quiet", 0.010, False),
    "cafe": ScenePolicy("cafe", 0.030, True),
    "car": ScenePolicy("car", 0.035, True),
    "meeting": ScenePolicy("meeting", 0.020, True),
}


def policy_for(scene) -> ScenePolicy:
    """Return the :class:`ScenePolicy` for a scene label; unknown → ``quiet``. Pure."""
    return _POLICIES.get((scene or "").lower(), _POLICIES["quiet"])


def should_switch(new_scene, current_scene, stable_count: int, min_stable: int = 3) -> bool:
    """Switch profiles only after ``new_scene`` has been observed ``min_stable`` times in a row.

    Returns False when the new scene matches the current one (nothing to do) or the run of
    consecutive observations hasn't yet reached ``min_stable`` (hysteresis). Pure.
    """
    if new_scene == current_scene:
        return False
    return stable_count >= min_stable
