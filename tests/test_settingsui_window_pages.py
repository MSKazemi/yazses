"""The settings window's sidebar, pages and Features list, headless.

The old window stacked every control in one column and gave the capability list whatever
height was left — about 70 px at the default size — so the largest part of the product could
not be seen. These tests hold the replacement to what it promised: one page at a time, a
Features list with real height and a category column, a mark on every page that holds
changes Apply has not written, and no loss of behaviour (staging, hiding and Apply are
covered by ``test_settingsui_window.py``, which this change leaves untouched).

Skipped when PySide6 is not installed; uses the offscreen platform.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui import pages  # noqa: E402
from yazses.settingsui.app import _FORM_FIELDS, SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _window(qapp, *, confirm=True):
    writes: list[tuple] = []
    controller = SettingsController(Config, lambda s, k, v, q: writes.append((s, k, v, q)),
                                    lambda modules: [])
    win = SettingsWindow(build_settings_model(Config()), controller)
    # No real modal dialog and no host daemon: either would hang a headless run.
    win._confirm_experimental = lambda row: confirm  # type: ignore[method-assign]
    win._confirm_reset = lambda diff, labels: True  # type: ignore[method-assign]
    win._warn = lambda title, body: None  # type: ignore[method-assign]
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    win._confirm_restart = lambda: False  # type: ignore[method-assign]
    win.writes = writes  # type: ignore[attr-defined]
    return win


def _labels(win):
    sidebar = win._shell.sidebar
    return [sidebar.item(i).text() for i in range(sidebar.count())]


def _marked(win):
    return {text.removesuffix(pages.DIRTY_MARK) for text in _labels(win)
            if text.endswith(pages.DIRTY_MARK)}


def _section(win, category):
    return next(box for box, cat, _m in win._group_widgets if cat == category)


def _select_category(win, category):
    lst = win._category_list
    for row in range(lst.count()):
        if lst.item(row).data(win._user_role()) == category:
            lst.setCurrentRow(row)
            return
    raise AssertionError(category)


# --- the frame ---------------------------------------------------------------------


def test_the_sidebar_lists_the_six_pages_in_order_and_opens_on_the_first(qapp):
    win = _window(qapp)
    assert _labels(win) == [p.label for p in pages.PAGES]
    assert win._shell.stack.count() == len(pages.PAGES)
    assert win._shell.current_key() == "general"


def test_selecting_a_sidebar_entry_shows_its_page(qapp):
    win = _window(qapp)
    for index, spec in enumerate(pages.PAGES):
        win._shell.select(spec.key)
        assert win._shell.current_key() == spec.key
        assert win._shell.stack.currentIndex() == index


def test_an_unknown_page_key_is_ignored(qapp):
    win = _window(qapp)
    win._shell.select("nope")
    assert win._shell.current_key() == "general"


def test_every_page_has_a_shortcut_and_find_jumps_to_the_features_search(qapp):
    win = _window(qapp)
    assert len(win._shell._shortcuts) == len(pages.PAGES)
    win._focus_filter()
    assert win._shell.current_key() == "features"


def test_the_features_list_gets_real_height_at_the_default_size(qapp):
    """The regression this redesign exists for: the list was squeezed into ~70 px."""
    win = _window(qapp)
    win._win.show()
    win._shell.select("features")
    qapp.processEvents()
    assert win._feature_scroll.height() >= 300, win._feature_scroll.height()
    win._win.close()


def test_the_controls_the_old_window_stacked_each_live_on_their_own_page(qapp):
    win = _window(qapp)
    stack = win._shell.stack

    def page_of(widget):
        node = widget
        while node is not None and node.parent() is not stack:
            node = node.parent()
        return pages.PAGES[stack.indexOf(node)].key

    assert page_of(win._hotkey_box) == "general"
    assert page_of(win._model_box) == "speech"
    assert page_of(win._mic_box) == "audio"
    assert page_of(win._filter_box) == "features"
    assert page_of(win._handsfree_button) == "handsfree"
    assert page_of(win._maintenance.check_button) == "updates"


def test_apply_and_restore_are_outside_the_pages_so_they_never_scroll_away(qapp):
    win = _window(qapp)
    stack = win._shell.stack
    for button in (win._apply_button, win._reset_button, win._hint):
        node = button
        while node is not None:
            assert node is not stack, "a footer control ended up inside a page"
            node = node.parent()


# --- the Features page -------------------------------------------------------------


def test_the_category_list_has_all_plus_one_entry_per_category(qapp):
    win = _window(qapp)
    model = build_settings_model(Config())
    lst = win._category_list
    assert lst.count() == 1 + len(model.groups)
    assert lst.item(0).data(win._user_role()) == ""
    assert [lst.item(i + 1).data(win._user_role()) for i in range(len(model.groups))] == [
        g.category for g in model.groups
    ]


def test_picking_a_category_shows_only_that_section_and_all_shows_every_one(qapp):
    win = _window(qapp)
    target = win._group_widgets[1][1]
    _select_category(win, target)
    shown = {cat for box, cat, _m in win._group_widgets if not box.isHidden()}
    assert shown == {target}

    _select_category(win, "")
    assert all(not box.isHidden() for box, _c, _m in win._group_widgets)


def test_a_filter_that_empties_the_chosen_category_falls_back_to_all(qapp):
    win = _window(qapp)
    _select_category(win, "Multilingual")
    win._filter_box.setText("meeting")  # nothing in Multilingual mentions a meeting

    assert win._category_list.currentRow() == 0
    shown = {cat for box, cat, _m in win._group_widgets if not box.isHidden()}
    assert "Conversation & recording capture" in shown
    assert "Multilingual" not in shown


def test_a_category_with_no_matches_leaves_the_list_while_filtering_and_returns_after(qapp):
    win = _window(qapp)
    names = {win._category_list.item(i).text(): i for i in range(win._category_list.count())}
    multilingual = next(i for text, i in names.items() if text.startswith("Multilingual"))

    win._filter_box.setText("meeting")
    assert win._category_list.item(multilingual).isHidden() is True

    win._filter_box.setText("")
    assert win._category_list.item(multilingual).isHidden() is False


def test_the_filter_and_the_category_hide_the_same_sections_without_fighting(qapp):
    """Two controls write one `setVisible`; clearing one must not resurrect what the other hid."""
    win = _window(qapp)
    _select_category(win, "Conversation & recording capture")
    win._filter_box.setText("meeting")
    win._filter_box.setText("")
    shown = {cat for box, cat, _m in win._group_widgets if not box.isHidden()}
    assert shown == {"Conversation & recording capture"}


def test_category_counts_follow_a_ticked_box_before_apply(qapp):
    win = _window(qapp)
    model = build_settings_model(Config())
    category = next(g.category for g in model.groups if any(r.slug == "streaming" for r in g.rows))
    row = next(i for i in range(win._category_list.count())
               if win._category_list.item(i).data(win._user_role()) == category)
    before = win._category_list.item(row).text()
    win._checkboxes["streaming"].setChecked(True)
    after = win._category_list.item(row).text()
    assert before != after
    on_before = int(before.rsplit(" ", 1)[1].split("/")[0])
    on_after = int(after.rsplit(" ", 1)[1].split("/")[0])
    assert on_after == on_before + 1


def test_the_search_box_explains_its_syntax_where_it_can_be_seen(qapp):
    win = _window(qapp)
    from PySide6.QtWidgets import QLabel

    page = win._shell.stack.widget(3)
    text = " ".join(label.text() for label in page.findChildren(QLabel))
    assert "tier:" in text and "on:" in text


# --- unapplied-change marks --------------------------------------------------------


def test_a_clean_window_marks_nothing(qapp):
    win = _window(qapp)
    assert _marked(win) == set()


def test_staging_a_capability_marks_features_and_unstaging_clears_it(qapp):
    win = _window(qapp)
    win._checkboxes["streaming"].setChecked(True)
    assert _marked(win) == {"Features"}
    win._checkboxes["streaming"].setChecked(False)
    assert _marked(win) == set()


def test_changing_a_form_control_marks_its_page_and_putting_it_back_clears_it(qapp):
    win = _window(qapp)
    original = win._model_box.currentText()
    other = next(win._model_box.itemText(i) for i in range(win._model_box.count())
                 if win._model_box.itemText(i) != original)
    win._model_box.setCurrentText(other)
    assert "Speech" in _marked(win)
    win._model_box.setCurrentText(original)
    assert "Speech" not in _marked(win)


def test_the_hotkey_marks_general_and_the_slider_marks_audio(qapp):
    win = _window(qapp)
    box = win._hotkey_box
    other = next(box.itemText(i) for i in range(box.count())
                 if box.itemText(i) != win._hotkey_baseline)
    box.setCurrentText(other)
    assert "General" in _marked(win)

    win._vad_slider.setValue(win._vad_baseline_pos + 5)
    assert "Audio" in _marked(win)


def test_apply_clears_the_marks_it_has_just_satisfied(qapp):
    win = _window(qapp)
    win._checkboxes["streaming"].setChecked(True)
    box = win._hotkey_box
    other = next(box.itemText(i) for i in range(box.count())
                 if box.itemText(i) != win._hotkey_baseline)
    box.setCurrentText(other)
    assert _marked(win) >= {"Features", "General"}

    win._on_apply()

    assert _marked(win) == set()


def test_a_staged_row_gets_an_accent_and_loses_it_when_unstaged(qapp):
    win = _window(qapp)
    holder = win._row_holders["streaming"]
    assert "border-left" not in holder.styleSheet()
    win._checkboxes["streaming"].setChecked(True)
    assert "border-left" in holder.styleSheet()
    win._checkboxes["streaming"].setChecked(False)
    assert "border-left" not in holder.styleSheet()


def test_restore_defaults_stages_and_marks_like_a_hand_made_change(qapp):
    win = _window(qapp)
    win._checkboxes["streaming"].setChecked(True)
    win._on_apply()
    assert _marked(win) == set()
    win._on_restore_defaults()
    assert "Features" in _marked(win)


def test_every_baseline_the_window_keeps_is_known_to_the_marker_map(qapp):
    """A hand-written set is the defect: a new control with a baseline must not go unmarked."""
    win = _window(qapp)
    baselines = {name for name in vars(win)
                 if name.endswith(("_baseline", "_baseline_pos"))}
    assert baselines, "the window keeps no baselines any more; this guard guards nothing"
    assert baselines == set(pages.FIELD_PAGES), baselines ^ set(pages.FIELD_PAGES)
    assert baselines == {baseline for baseline, _w, _r in _FORM_FIELDS}


def test_the_marker_map_and_the_apply_paths_name_the_same_widgets(qapp):
    win = _window(qapp)
    for baseline, widget_attr, _read in _FORM_FIELDS:
        assert getattr(win, widget_attr, None) is not None, (baseline, widget_attr)
