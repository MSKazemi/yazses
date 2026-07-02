"""Voice-biometric admission gate (ADR-v2-018) — pure admit()."""
from __future__ import annotations

from dataclasses import dataclass

from yazses.voiceguard.gate import admit


@dataclass
class _Cfg:
    enabled: bool = True
    match_threshold: float = 0.5
    spoof_threshold: float = 0.5
    fail_open: bool = True


def test_disabled_always_admits():
    d = admit(0.0, 1.0, _Cfg(enabled=False))
    assert d.admit and d.reason == "disabled"


def test_match_and_clean_admits():
    d = admit(0.8, 0.1, _Cfg())
    assert d.admit and d.reason == "admitted"


def test_speaker_mismatch_rejected():
    d = admit(0.3, 0.1, _Cfg())
    assert not d.admit and "mismatch" in d.reason


def test_spoof_rejected():
    d = admit(0.9, 0.9, _Cfg())
    assert not d.admit and "spoof" in d.reason


def test_none_scores_fail_open_admits():
    d = admit(None, None, _Cfg(fail_open=True))
    assert d.admit and d.reason == "admitted"


def test_none_similarity_fail_closed_rejects():
    d = admit(None, 0.1, _Cfg(fail_open=False))
    assert not d.admit and "no speaker score" in d.reason


def test_none_spoof_fail_closed_rejects():
    d = admit(0.9, None, _Cfg(fail_open=False))
    assert not d.admit and "no spoof score" in d.reason


def test_boundary_similarity_at_threshold_admits():
    # similarity == threshold is NOT a mismatch (strict <)
    d = admit(0.5, 0.5, _Cfg())
    assert d.admit


def test_feature_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    assert "voiceguard" in [f.slug for f in feature_status(Config())]
    assert Config().voiceguard.enabled is False
