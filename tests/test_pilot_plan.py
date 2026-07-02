"""AT-SPI Voice Pilot planning (ADR-v2-007) — pure command parse + label match."""
from __future__ import annotations

from yazses.pilot.plan import (
    Element,
    PilotPlan,
    match_elements,
    parse_command,
    plan_action,
)

ELEMENTS = [
    Element("Save", role="push button"),
    Element("Save As", role="push button"),
    Element("Cancel", role="push button"),
    Element("Terminal", role="frame"),
]


# ---- parse_command ---------------------------------------------------------

def test_parse_maps_verb_and_strips_fillers():
    cmd = parse_command("click the Save button")
    assert cmd is not None
    assert cmd.action == "activate"
    assert cmd.target == "save"
    assert cmd.ordinal is None


def test_parse_focus_and_toggle_verbs():
    assert parse_command("focus the terminal").action == "focus"
    assert parse_command("toggle dark mode").action == "toggle"


def test_parse_extracts_ordinal():
    cmd = parse_command("click the third result")
    assert cmd.ordinal == 2
    assert cmd.target == "result"


def test_parse_rejects_non_command():
    assert parse_command("what time is it") is None
    assert parse_command("") is None
    assert parse_command("click the") is None  # no target after fillers


# ---- match_elements --------------------------------------------------------

def test_match_ranks_by_similarity_above_threshold():
    cands = match_elements("cancel", ELEMENTS, threshold=0.5)
    assert cands[0][0].label == "Cancel"


def test_match_empty_when_below_threshold():
    assert match_elements("nonexistent widget", ELEMENTS, threshold=0.5) == []


# ---- plan_action -----------------------------------------------------------

def test_plan_picks_best_element():
    plan = plan_action("click Cancel", ELEMENTS)
    assert isinstance(plan, PilotPlan)
    assert plan.action == "activate"
    assert plan.element.label == "Cancel"
    assert plan.ambiguous is False


def test_plan_flags_ambiguous_tie():
    # two identical labels tie the top score → ambiguous
    els = [Element("Save"), Element("Save"), Element("Quit")]
    plan = plan_action("click Save", els)
    assert plan is not None and plan.ambiguous is True


def test_plan_ordinal_disambiguates():
    els = [Element("Save"), Element("Save"), Element("Quit")]
    plan = plan_action("click the second Save", els)
    assert plan is not None and plan.ambiguous is False


def test_plan_none_when_no_match_or_not_command():
    assert plan_action("click nonexistent", ELEMENTS) is None
    assert plan_action("hello world", ELEMENTS) is None


def test_plan_ordinal_out_of_range_is_none():
    assert plan_action("click the fifth Cancel", ELEMENTS) is None


def test_score_zero_when_label_has_no_content_tokens():
    # An element whose label is all stopwords yields empty tokens → score 0.0 → filtered out.
    only_stopwords = [Element("the", role="label")]
    assert match_elements("cancel", only_stopwords, threshold=0.0) == [(only_stopwords[0], 0.0)]
