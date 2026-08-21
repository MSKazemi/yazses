"""Filtering the settings window's rows — pure, so it runs without PySide6.

The window has ~200 rows. These tests pin the two properties that make its filter
box worth having: it finds a capability by what it *does*, not only by its name,
and it takes the same words `yazses features --on/--tier` takes.
"""

from yazses.config import Config
from yazses.settingsui.model import SettingRow, build_settings_model
from yazses.settingsui.search import (
    describe_filter,
    matches,
    parse_query,
    visible_counts,
)


def _row(**kw) -> SettingRow:
    base = dict(
        slug="demo",
        label="Demo capability",
        tier_label="optional",
        enabled=False,
        toggleable=True,
        experimental=False,
        why="Collapses stutters and repeats.",
    )
    base.update(kw)
    return SettingRow(**base)  # type: ignore[arg-type]


def test_an_empty_query_matches_everything():
    assert matches(_row(), "") is True
    assert matches(_row(), "   ") is True


def test_matching_by_visible_name():
    assert matches(_row(), "demo") is True
    assert matches(_row(), "DEMO") is True, "filtering must be case-insensitive"
    assert matches(_row(), "capab") is True, "a partial word still matches"
    assert matches(_row(), "spreadsheet") is False


def test_matching_by_toggle_name_the_cli_uses():
    assert matches(_row(slug="read-back", label="Read-Back Loop"), "read-back") is True


def test_matching_by_what_it_does_not_only_its_name():
    """The whole point: 'stutter' must find a row whose label lacks the word."""
    row = _row(label="Dysfluency-Friendly", why="Collapses stutters/repeats.")
    assert matches(row, "stutter") is True


def test_matching_by_use_case_and_example():
    row = _row(use_case="When you dictate in a noisy cafe.", example="say 'go'")
    assert matches(row, "cafe") is True
    assert matches(row, "go") is True


def test_matching_by_category_heading():
    row = _row()
    assert matches(row, "multilingual", category="Multilingual") is True
    assert matches(row, "multilingual", category="Core dictation") is False


def test_several_terms_narrow_rather_than_widen():
    row = _row(label="Meeting Mode", why="Records a whole meeting hands-free.")
    assert matches(row, "meeting hands-free") is True
    assert matches(row, "meeting spreadsheet") is False


def test_on_and_off_filters_mirror_the_cli_flags():
    on, off = _row(enabled=True), _row(enabled=False)
    assert matches(on, "on:") is True
    assert matches(off, "on:") is False
    assert matches(off, "off:") is True
    assert matches(on, "off:") is False


def test_a_state_filter_combines_with_text():
    row = _row(enabled=True, label="Meeting Mode")
    assert matches(row, "on: meeting") is True
    assert matches(row, "off: meeting") is False


def test_tier_filter_takes_the_words_yazses_features_takes():
    rec = _row(tier_label="recommended")
    exp = _row(tier_label="experimental — not advised yet")
    assert matches(rec, "tier:rec") is True
    assert matches(rec, "tier:exp") is False
    assert matches(exp, "tier:experimental") is True


def test_an_unknown_filter_token_is_treated_as_text_not_silently_dropped():
    """A typo'd filter that quietly matches everything is invisible to the user."""
    terms, enabled, tier = parse_query("tier:nonsense")
    assert terms == ("tier:nonsense",)
    assert enabled is None and tier is None
    assert matches(_row(), "tier:nonsense") is False


def test_counts_report_matching_against_the_whole_model():
    model = build_settings_model(Config())
    matching, total = visible_counts(model.groups, "")
    assert total == len(model.rows())
    assert matching == total

    narrowed, total_again = visible_counts(model.groups, "meeting")
    assert total_again == total
    assert 0 < narrowed < total


def test_the_status_line_stays_quiet_when_nothing_is_filtered():
    """An unconditional "showing 200 of 200" trains people to stop reading it."""
    assert describe_filter(200, 200, "") == ""
    assert describe_filter(200, 200, "   ") == ""


def test_the_status_line_says_when_a_query_matches_nothing():
    message = describe_filter(0, 200, "zzz")
    assert "No capability matches" in message
    assert "'zzz'" in message


def test_the_status_line_counts_a_narrowed_list():
    assert describe_filter(3, 200, "meeting") == "Showing 3 of 200 capabilities."


def test_every_shipped_capability_is_reachable_by_its_own_toggle_name():
    """A row no query can surface is a row the filter has hidden for good."""
    model = build_settings_model(Config())
    for group in model.groups:
        for row in group.rows:
            assert matches(row, row.slug, category=group.category), row.slug
