"""Spoken Table→CSV (ADR-v2-091) + Word-Count/Goal Tracker (ADR-v2-092) — pure cores."""
from __future__ import annotations

from yazses.tablecsv.entry import parse_row, row_plan, rows_to_delimited
from yazses.wordgoal.tracker import WordGoalTracker, count_words, parse_goal_command

# ---- table → csv -----------------------------------------------------------

def test_parse_row():
    assert parse_row("row: Ada, 1815, London") == ["Ada", "1815", "London"]
    assert parse_row("Ada and Grace and Alan") == ["Ada", "Grace", "Alan"]
    assert parse_row("") == []


def test_rows_to_delimited():
    text = "row: Ada, 1815 next row row: Grace, 1906"
    assert rows_to_delimited(text) == ["Ada,1815", "Grace,1906"]
    assert rows_to_delimited("entry: a; b; c", sep="\t") == ["a\tb\tc"]


def test_row_plan():
    plan = row_plan(["Ada", "1815"])
    assert plan == [("type", "Ada"), ("key", "Tab"), ("type", "1815"), ("key", "Return")]
    assert row_plan([]) == []


# ---- word count / goal -----------------------------------------------------

def test_count_words():
    assert count_words("hello there world") == 3
    assert count_words("") == 0


def test_tracker_no_goal():
    t = WordGoalTracker()
    t.add("one two three")
    t.add("four five")
    assert t.count() == 5
    assert t.progress() == "5 words so far."


def test_tracker_with_goal():
    t = WordGoalTracker(goal=10)
    t.add("a b c d")
    assert t.progress() == "4 of 10 words — 6 to go."
    t.add("e f g h i j")
    assert "reached your goal" in t.progress()


def test_tracker_reset_and_setgoal():
    t = WordGoalTracker()
    t.add("x y z")
    t.reset()
    assert t.count() == 0
    t.set_goal(-5)          # clamped to 0
    assert t.progress() == "0 words so far."


def test_parse_goal_command():
    assert parse_goal_command("goal 500 words") == 500
    assert parse_goal_command("set my goal to 300") == 300
    assert parse_goal_command("target of 1000") == 1000
    assert parse_goal_command("hello there") is None


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "tablecsv" in slugs and "wordgoal" in slugs
    assert Config().tablecsv.enabled is False and Config().wordgoal.enabled is False
