"""Load-aware decode-policy selection (pure) — ADR-v2-073.

Pick a decode policy (model, beam width, speculative on/off) from a CPU-load sample. Pure and
deterministic; the psutil read, the draft model, and the speculative-decode loop live elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DecodePolicy:
    """The chosen decode policy: which ``model``, ``beam_size``, and whether to ``speculative``-decode."""
    model: str
    beam_size: int
    speculative: bool


@dataclass
class GovernorConfig:
    """Thresholds for :func:`pick_policy` (CPU percentages)."""
    base_model: str
    light_model: str = "tiny.en"
    draft_model: str = ""      # a distil draft; enables speculative decoding when idle
    high_load: float = 85.0    # at/above → light policy
    low_load: float = 40.0     # at/below (with a draft) → speculative


def pick_policy(cpu_percent: float, config: GovernorConfig) -> DecodePolicy:
    """Select a :class:`DecodePolicy` for the current CPU load. Pure."""
    if cpu_percent >= config.high_load:
        return DecodePolicy(config.light_model, beam_size=1, speculative=False)
    if cpu_percent <= config.low_load and config.draft_model:
        return DecodePolicy(config.base_model, beam_size=5, speculative=True)
    return DecodePolicy(config.base_model, beam_size=5, speculative=False)
