"""Mouth-Sound Switch Access (ADR-v2-097) + Involuntary-Vocalization Excision (ADR-v2-102) — pure."""
from __future__ import annotations

from yazses.involuntary.excise import excise_nonspeech_spans, is_involuntary_vocalization
from yazses.mouthswitch.scan import ScanSelector, classify_mouth_sound

# ---- mouth-sound switch access ---------------------------------------------

def test_classify_mouth_sound():
    assert classify_mouth_sound({"duration_ms": 50, "centroid_hz": 800, "burst": True}) == "pop"
    assert classify_mouth_sound({"duration_ms": 40, "centroid_hz": 5000, "burst": True}) == "click"
    assert classify_mouth_sound({"duration_ms": 300, "centroid_hz": 6000, "zcr": 0.5}) == "sh"
    assert classify_mouth_sound({"duration_ms": 300, "centroid_hz": 800, "zcr": 0.1}) is None
    assert classify_mouth_sound({"duration_ms": 40, "burst": False}) is None


def test_scan_selector_tick_and_switch():
    s = ScanSelector(["a", "b", "c"], dwell_s=1.0)
    assert s.current() == "a"
    assert s.tick(0.0) == 0            # first tick seeds the clock
    assert s.tick(1.0) == 1            # one dwell → advance
    assert s.tick(3.0) == 0            # two more dwells → wrap 1→2→0
    assert s.on_switch("advance", now=3.0) is None
    assert s.current() == "b"
    assert s.on_switch("select") == "b"
    assert s.on_switch("noop") is None


def test_scan_selector_empty():
    s = ScanSelector([], dwell_s=1.0)
    assert s.current() is None
    assert s.tick(5.0) == 0
    assert s.on_switch("select") is None


# ---- involuntary-vocalization excision -------------------------------------

def test_is_involuntary_vocalization():
    assert is_involuntary_vocalization(
        {"duration_ms": 300, "peak_energy": 0.8, "centroid_hz": 900, "burst": True}) == "cough"
    assert is_involuntary_vocalization(
        {"duration_ms": 300, "peak_energy": 0.8, "centroid_hz": 3000, "burst": True}) == "sneeze"
    assert is_involuntary_vocalization(
        {"duration_ms": 400, "centroid_hz": 600, "voiced": False, "burst": False}) == "throat_clear"
    assert is_involuntary_vocalization(
        {"duration_ms": 300, "peak_energy": 0.9, "voiced": True, "burst": True}) is None   # voiced speech


def test_excise_nonspeech_spans():
    tokens = ["the", "cough", "cat", "sat"]
    spans = [(0.0, 0.3), (0.3, 0.8), (0.8, 1.1), (1.1, 1.4)]
    flagged = [(0.3, 0.8)]                       # the "cough" token's span
    assert excise_nonspeech_spans(tokens, spans, flagged) == ["the", "cat", "sat"]
    assert excise_nonspeech_spans(tokens, spans, []) == tokens
    assert excise_nonspeech_spans([], [], flagged) == []


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "mouthswitch" in slugs and "involuntary" in slugs
    assert Config().mouthswitch.enabled is False and Config().involuntary.enabled is False
