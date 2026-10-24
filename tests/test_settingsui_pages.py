"""The settings window's page and category logic, with no Qt — pure and display-free.

The sidebar, the Features page's category list and the "this page has unsaved changes"
marker all reduce to small decisions (what a label says, which categories can be picked
under a filter, which tier earns a chip). They live in :mod:`yazses.settingsui.pages` so they
are tested directly, the way ``search.py`` is, and the Qt shell only paints the answer.
"""

from __future__ import annotations

from yazses.config import Config
from yazses.settingsui import pages
from yazses.settingsui.model import build_settings_model


def _groups():
    return build_settings_model(Config()).groups


def test_pages_are_the_six_in_the_agreed_order():
    assert [p.key for p in pages.PAGES] == [
        "general", "speech", "audio", "features", "handsfree", "updates",
    ]


def test_every_page_has_a_label_a_title_and_a_one_line_blurb():
    for page in pages.PAGES:
        assert page.label and page.title and page.blurb
        assert "\n" not in page.blurb, page.key


def test_page_keys_are_unique():
    keys = [p.key for p in pages.PAGES]
    assert len(keys) == len(set(keys))


def test_a_dirty_page_label_carries_a_marker_and_a_clean_one_does_not():
    assert pages.page_label("Speech", dirty=False) == "Speech"
    assert pages.page_label("Speech", dirty=True) != "Speech"
    assert pages.page_label("Speech", dirty=True).startswith("Speech")


def test_category_entries_cover_every_group_and_count_every_row():
    groups = _groups()
    entries = pages.category_entries(groups, lambda slug: False, "")
    assert [e.category for e in entries] == [g.category for g in groups]
    assert [e.total for e in entries] == [len(g.rows) for g in groups]
    assert all(e.enabled == 0 for e in entries)
    # No query: everything matches.
    assert [e.matching for e in entries] == [e.total for e in entries]


def test_category_entries_count_what_is_enabled_through_the_callback():
    groups = _groups()
    first = groups[0]
    on = {first.rows[0].slug}
    entries = pages.category_entries(groups, lambda slug: slug in on, "")
    assert entries[0].enabled == 1
    assert sum(e.enabled for e in entries) == 1


def test_category_entries_apply_the_query_to_matching_only():
    groups = _groups()
    entries = pages.category_entries(groups, lambda slug: False, "meeting")
    by_name = {e.category: e for e in entries}
    assert by_name["Conversation & recording capture"].matching > 0
    assert by_name["Multilingual"].matching == 0
    # totals do not move with the filter
    assert [e.total for e in entries] == [len(g.rows) for g in groups]


def test_item_text_shows_enabled_over_total_until_a_filter_is_active():
    entry = pages.CategoryEntry("Core dictation", enabled=4, total=12, matching=12)
    assert pages.category_item_text(entry, filtering=False) == "Core dictation · 4/12"
    filtered = pages.CategoryEntry("Core dictation", enabled=4, total=12, matching=3)
    assert pages.category_item_text(filtered, filtering=True) == "Core dictation · 3 match"


def test_an_ampersand_in_a_category_is_shown_as_written():
    """List items are plain text, so unlike a QGroupBox title nothing needs doubling."""
    entry = pages.CategoryEntry("Commands & automation", 1, 2, 2)
    assert "Commands & automation" in pages.category_item_text(entry, filtering=False)
    assert "&&" not in pages.category_item_text(entry, filtering=False)


def test_a_category_with_no_matches_cannot_be_picked_while_filtering():
    empty = pages.CategoryEntry("Multilingual", 0, 5, 0)
    assert pages.category_selectable(empty, filtering=True) is False
    assert pages.category_selectable(empty, filtering=False) is True
    some = pages.CategoryEntry("Multilingual", 0, 5, 2)
    assert pages.category_selectable(some, filtering=True) is True


def test_a_section_is_shown_only_when_selected_and_not_emptied_by_the_filter():
    assert pages.section_visible("A", selected=None, matching=2) is True
    assert pages.section_visible("A", selected="A", matching=2) is True
    assert pages.section_visible("A", selected="B", matching=2) is False
    assert pages.section_visible("A", selected=None, matching=0) is False
    assert pages.section_visible("A", selected="A", matching=0) is False


def test_the_selection_falls_back_to_all_when_a_filter_empties_it():
    entries = (
        pages.CategoryEntry("A", 0, 3, 2),
        pages.CategoryEntry("B", 0, 3, 0),
    )
    assert pages.effective_selection("A", entries, filtering=True) == "A"
    assert pages.effective_selection("B", entries, filtering=True) is None
    assert pages.effective_selection("B", entries, filtering=False) == "B"
    assert pages.effective_selection(None, entries, filtering=True) is None
    # A category that vanished from the model (it cannot today) is treated as All.
    assert pages.effective_selection("Gone", entries, filtering=False) is None


def test_field_pages_map_every_baseline_to_a_real_page():
    keys = {p.key for p in pages.PAGES}
    assert pages.FIELD_PAGES, "an empty map would make every page look clean"
    for attr, page in pages.FIELD_PAGES.items():
        assert attr.endswith(("_baseline", "_baseline_pos")), attr
        assert page in keys, (attr, page)
    # Features is dirty from staged capabilities, never from a form field.
    assert "features" not in set(pages.FIELD_PAGES.values())


def test_dirty_page_keys_unions_staged_features_with_changed_form_fields():
    assert pages.dirty_page_keys(staged_features=0, changed_fields=()) == frozenset()
    assert pages.dirty_page_keys(staged_features=2, changed_fields=()) == {"features"}
    got = pages.dirty_page_keys(
        staged_features=0, changed_fields=("_model_baseline", "_vad_baseline_pos")
    )
    assert got == {"speech", "audio"}
    got = pages.dirty_page_keys(staged_features=1, changed_fields=("_hotkey_baseline",))
    assert got == {"general", "features"}


def test_an_unknown_changed_field_is_ignored_rather_than_raised():
    assert pages.dirty_page_keys(staged_features=0, changed_fields=("_nope_baseline",)) == frozenset()
