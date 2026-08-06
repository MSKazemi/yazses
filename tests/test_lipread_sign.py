"""Silent Lip-Reading (ADR-v2-053) + Sign-Language Input (ADR-v2-054) — pure gate cores."""
from __future__ import annotations

from yazses.lipread.gate import mouth_active, mouth_aspect_ratio
from yazses.sign.segment import SignSegmenter, hands_present

# ---- lip-reading -----------------------------------------------------------

def test_mouth_aspect_ratio():
    # width 100, opening 40 → 0.4
    r = mouth_aspect_ratio(top=(50, 30), bottom=(50, 70), left=(0, 50), right=(100, 50))
    assert r == 0.4


def test_mouth_aspect_ratio_degenerate_width():
    assert mouth_aspect_ratio((0, 0), (0, 10), (5, 0), (5, 0)) == 0.0


def test_mouth_active_threshold():
    assert mouth_active(0.4) is True
    assert mouth_active(0.2) is False


# ---- sign language ---------------------------------------------------------

def test_hands_present():
    assert hands_present(1) is True
    assert hands_present(0) is False


def test_segmenter_start_and_end_on_stillness():
    seg = SignSegmenter(start_threshold=0.02, pause_frames=2)
    assert seg.update(0.0, 1) is None      # hands, no motion → still waiting
    assert seg.update(0.1, 1) == "start"   # motion onset → start
    assert seg.update(0.1, 1) is None      # still signing
    assert seg.update(0.0, 1) is None      # still frame 1
    assert seg.update(0.0, 1) == "end"     # still frame 2 → end


def test_segmenter_end_when_hands_leave():
    seg = SignSegmenter(start_threshold=0.02, pause_frames=8)
    assert seg.update(0.1, 2) == "start"
    assert seg.update(0.0, 0) == "end"     # hands gone → immediate end


def test_segmenter_no_start_without_hands():
    seg = SignSegmenter()
    assert seg.update(0.5, 0) is None      # motion but no hands → nothing


def test_segmenter_motion_resumes_resets_stillness():
    seg = SignSegmenter(start_threshold=0.02, pause_frames=2)
    seg.update(0.1, 1)                      # start
    seg.update(0.0, 1)                      # still 1
    assert seg.update(0.1, 1) is None       # motion again → reset
    assert seg.update(0.0, 1) is None       # still 1 again
    assert seg.update(0.0, 1) == "end"      # still 2 → end


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "lipread" in slugs and "sign" in slugs
    assert Config().lipread.enabled is False and Config().sign.enabled is False
