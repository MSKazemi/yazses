"""LoRA adapter held-out gate (pure) — ADR-v2-021.

Decide whether a corpus-trained LoRA adapter (atypical/accented-speech personalization)
should be applied, based on its held-out WER vs the un-adapted baseline. Pure and
deterministic; the training + adapter load are heavy/deferred and live elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdapterDecision:
    """Whether to apply the adapter, the relative WER improvement, and a reason."""
    apply: bool
    improvement: float
    reason: str


def should_apply_adapter(
    baseline_wer: float,
    adapter_wer: float,
    min_improvement: float = 0.03,
) -> AdapterDecision:
    """Apply a LoRA adapter only if it beats the baseline on held-out WER.

    ``improvement`` is the *relative* WER reduction ``(baseline - adapter) / baseline``.
    The adapter is applied only when that improvement is at least ``min_improvement``.
    Guards: a non-positive baseline (no measurable error to improve) never applies. WERs
    must come from a **held-out** slice for this to be meaningful (caller's responsibility).
    Pure.
    """
    if baseline_wer <= 0:
        return AdapterDecision(False, 0.0, "no baseline error to improve on")
    improvement = (baseline_wer - adapter_wer) / baseline_wer
    if improvement >= min_improvement:
        return AdapterDecision(True, improvement, f"held-out WER improved {improvement:.1%}")
    return AdapterDecision(
        False, improvement, f"insufficient improvement ({improvement:.1%} < {min_improvement:.1%})"
    )
