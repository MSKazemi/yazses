"""LoRA adapter held-out gate (ADR-v2-021) — pure should_apply_adapter."""
from __future__ import annotations

from yazses.personalize.adapter_gate import should_apply_adapter


def test_applies_when_improvement_meets_threshold():
    d = should_apply_adapter(0.20, 0.16, min_improvement=0.03)  # 20% relative win
    assert d.apply and d.improvement == (0.20 - 0.16) / 0.20


def test_rejects_when_improvement_below_threshold():
    d = should_apply_adapter(0.20, 0.199, min_improvement=0.03)
    assert not d.apply and "insufficient" in d.reason


def test_rejects_when_adapter_worse():
    d = should_apply_adapter(0.20, 0.30)
    assert not d.apply and d.improvement < 0


def test_zero_baseline_never_applies():
    d = should_apply_adapter(0.0, 0.0)
    assert not d.apply and "no baseline" in d.reason


def test_boundary_exactly_at_threshold_applies():
    # exactly 3% relative improvement with default threshold
    d = should_apply_adapter(1.0, 0.97, min_improvement=0.03)
    assert d.apply


def test_config_field_default():
    from yazses.config import Config
    assert Config().personalize.lora_min_improvement == 0.03
