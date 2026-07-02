"""Screen-Grounded Dictation (ADR-v2-051) + Head-Pointer (ADR-v2-052) — pure cores."""
from __future__ import annotations

from yazses.headpointer.pointer import DwellClicker, PointerCalib, pose_to_cursor
from yazses.screengrounded.harvest import extract_terms, harvest_terms


# ---- screen-grounded -------------------------------------------------------

def test_extract_terms_kinds():
    got = extract_terms("meet Aoife about useAuthContext and HTTP in my_var today")
    assert "Aoife" in got            # proper noun
    assert "useAuthContext" in got   # camelCase
    assert "HTTP" in got             # acronym
    assert "my_var" in got           # snake_case
    assert "today" not in got and "and" not in got  # ordinary words dropped


def test_harvest_terms_dedup_and_cap():
    got = harvest_terms(["Kubernetes Kubernetes", "kubernetes", "Docker"], max_terms=32)
    assert got == ["Kubernetes", "Docker"]   # case-insensitive dedup, first spelling wins


def test_harvest_terms_respects_cap():
    got = harvest_terms(["Alpha Bravo Charlie Delta"], max_terms=2)
    assert len(got) == 2


def test_harvest_empty():
    assert harvest_terms([]) == []
    assert extract_terms("") == []


def test_single_char_tokens_dropped():
    # "I", "a" are too short to prime — length guard
    assert extract_terms("I saw a X") == []


# ---- head-pointer ----------------------------------------------------------

def test_pose_to_cursor_deadzone():
    # tiny angles inside the deadzone → no motion
    assert pose_to_cursor(0.01, 0.01) == (0.0, 0.0)


def test_pose_to_cursor_scales():
    dx, dy = pose_to_cursor(0.1, -0.1, PointerCalib(x_gain=100, y_gain=200, deadzone=0.02))
    assert dx == 10.0 and dy == -20.0


def test_dwell_clicker_fires_after_hold():
    c = DwellClicker(radius=5.0, hold_frames=3)
    assert c.update(100, 100) is False    # frame 1 (anchor)
    assert c.update(101, 100) is False    # frame 2 (within radius)
    assert c.update(102, 101) is True     # frame 3 → click
    # re-arms after firing
    assert c.update(102, 101) is False


def test_dwell_clicker_resets_on_move_away():
    c = DwellClicker(radius=5.0, hold_frames=3)
    c.update(100, 100)
    c.update(101, 100)
    assert c.update(200, 200) is False    # jumped away → anchor resets
    assert c.update(201, 200) is False
    assert c.update(202, 201) is True     # dwell at the new spot


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "screengrounded" in slugs and "headpointer" in slugs
    assert Config().screengrounded.enabled is False and Config().headpointer.enabled is False
