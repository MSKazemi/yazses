"""Persistent word-goal store + progress rendering — ADR-v2-092."""
from __future__ import annotations

from yazses.wordgoal import store
from yazses.wordgoal.tracker import WordGoalTracker, render_progress


def test_save_load_roundtrip(tmp_path):
    p = store.wordgoal_path(tmp_path)
    assert store.load_state(p) == {"count": 0, "goal": 0}
    store.save_state(p, count=120, goal=500)
    assert store.load_state(p) == {"count": 120, "goal": 500}


def test_load_clamps_and_tolerates_garbage(tmp_path):
    p = store.wordgoal_path(tmp_path)
    p.write_text("not json", encoding="utf-8")
    assert store.load_state(p) == {"count": 0, "goal": 0}
    store.save_state(p, count=-5, goal=-9)  # clamped to 0
    assert store.load_state(p) == {"count": 0, "goal": 0}


def test_render_progress_variants():
    assert render_progress(10, 0) == "10 words so far."
    assert render_progress(120, 500) == "120 of 500 words — 380 to go."
    assert "reached your goal" in render_progress(500, 500)


def test_render_progress_matches_tracker():
    # the class now delegates to the shared pure helper
    t = WordGoalTracker(goal=100)
    t.add("one two three")
    assert t.progress() == render_progress(3, 100)
