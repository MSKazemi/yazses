"""Vocal-strain core (ADR-v2-034): edges of ``strain_level`` and ``should_suggest_break``.

The headline cases live in ``test_wakeword_voicehealth.py``; these pin the boundaries the
session history in ``voicehealth/biomarkers.py`` relies on.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from yazses.voicehealth.strain import should_suggest_break, strain_level


@dataclass
class _Cfg:
    enabled: bool = True
    threshold: float = 0.6
    min_samples: int = 3


def test_strain_components_are_clamped():
    assert strain_level(-1.0, -1.0, 100.0) == 0.0
    assert strain_level(10.0, 10.0, -100.0) == 1.0


@pytest.mark.parametrize("jitter,shimmer,hnr,expected", [
    (0.02, 0.0, 20.0, 1 / 3),   # jitter anchor alone
    (0.0, 0.10, 20.0, 1 / 3),   # shimmer anchor alone
    (0.0, 0.0, 0.0, 1 / 3),     # HNR at 0 dB alone
    (0.01, 0.05, 10.0, 0.5),    # each component at half
])
def test_strain_components_are_averaged(jitter, shimmer, hnr, expected):
    assert strain_level(jitter, shimmer, hnr) == pytest.approx(expected)


def test_strain_is_monotone_in_each_biomarker():
    assert strain_level(0.01, 0.05, 15.0) < strain_level(0.015, 0.05, 15.0)
    assert strain_level(0.01, 0.05, 15.0) < strain_level(0.01, 0.08, 15.0)
    assert strain_level(0.01, 0.05, 15.0) < strain_level(0.01, 0.05, 10.0)


def test_threshold_is_inclusive():
    assert should_suggest_break([0.6, 0.6, 0.6], _Cfg()) is True


def test_only_the_most_recent_window_counts():
    assert should_suggest_break([0.9] * 10 + [0.1, 0.1, 0.1], _Cfg()) is False
    assert should_suggest_break([0.1] * 10 + [0.9, 0.9, 0.9], _Cfg()) is True


def test_non_positive_min_samples_never_fires():
    assert should_suggest_break([0.9] * 5, _Cfg(min_samples=0)) is False
    assert should_suggest_break([0.9] * 5, _Cfg(min_samples=-1)) is False


def test_config_without_enabled_never_fires():
    class _Bare:
        threshold = 0.1
        min_samples = 1

    assert should_suggest_break([0.9], _Bare()) is False


def test_missing_threshold_and_window_use_defaults():
    class _OnlyEnabled:
        enabled = True

    assert should_suggest_break([0.9] * 19, _OnlyEnabled()) is False
    assert should_suggest_break([0.9] * 20, _OnlyEnabled()) is True
