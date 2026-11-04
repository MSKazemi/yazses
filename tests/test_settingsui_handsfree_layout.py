"""The hands-free window's two-column layout (headless, Qt offscreen).

The wording and meaning of every control is the view-model's and is tested elsewhere; what is
held here is only the shell's arrangement: two columns when there is room and one when there is
not, columns tall enough for their wrapped text (they once drew over each other), empty
explanation lines taking no room, and the state's own action set in bold.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QBoxLayout  # noqa: E402

from tests.test_settingsui_handsfree_panel import _hp, _inputs, _Rig  # noqa: E402
from yazses.handsfree.safety import SafetyState  # noqa: E402
from yazses.settingsui.handsfree_panel import TWO_COLUMN_MIN_PX  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _show(rig, qapp, width: int, height: int = 800):
    dialog = rig.panel.widget
    dialog.resize(width, height)
    dialog.show()
    for _ in range(5):
        qapp.processEvents()
    return dialog


def _expected(dialog) -> QBoxLayout.Direction:
    return (
        QBoxLayout.Direction.LeftToRight
        if dialog.width() >= TWO_COLUMN_MIN_PX
        else QBoxLayout.Direction.TopToBottom
    )


def test_the_columns_follow_the_width_the_window_actually_has(qapp):
    """The rule is about the real width: a platform may refuse to shrink a window below what its
    fonts need (Windows did), so the test reads the width back instead of assuming the resize."""
    rig = _Rig(qapp)
    for width in (TWO_COLUMN_MIN_PX + 200, TWO_COLUMN_MIN_PX - 200, TWO_COLUMN_MIN_PX + 200):
        dialog = _show(rig, qapp, width)
        assert rig.panel._columns.direction() == _expected(dialog), dialog.width()
    # the wide end of the range is two columns on every platform
    assert rig.panel._columns.direction() == QBoxLayout.Direction.LeftToRight


def test_each_column_is_as_tall_as_its_wrapped_text_needs(qapp):
    """Side by side the box layout asked each label for one line, so cards were squashed on top
    of one another. Each column must be at least as tall as it needs at its actual width."""
    rig = _Rig(qapp, _inputs(SafetyState.FAULTED, reason="headpointer: signal is stale",
                             face_on=True))
    _show(rig, qapp, TWO_COLUMN_MIN_PX + 200)
    for column in (rig.panel._now_column, rig.panel._setup_column):
        need = column.layout().heightForWidth(column.width())
        assert column.height() >= need, (column.height(), need)


def test_the_tab_order_does_not_depend_on_the_window_width(qapp):
    rig = _Rig(qapp)
    before = list(rig.panel.tab_order)
    _show(rig, qapp, TWO_COLUMN_MIN_PX - 200)
    _show(rig, qapp, TWO_COLUMN_MIN_PX + 200)
    assert rig.panel.tab_order == before
    assert before[3] is rig.panel._routes and before[4] is rig.panel._health


def test_an_empty_explanation_takes_no_room_and_comes_back_with_text(qapp):
    rig = _Rig(qapp, _inputs(SafetyState.ACTIVE))
    _show(rig, qapp, TWO_COLUMN_MIN_PX + 200)
    assert rig.panel._result.isHidden()  # nothing has been pressed
    rig.panel._press("pause")
    assert not rig.panel._result.isHidden()
    assert rig.panel._result.text().startswith("Done:")


def test_the_action_the_state_calls_for_is_the_bold_one(qapp):
    paused = _Rig(qapp, _inputs(SafetyState.PAUSED, hp=_hp(active=False, state="stopped")))
    assert paused.button("resume").font().bold()
    assert not paused.button("pause").font().bold()
    running = _Rig(qapp, _inputs(SafetyState.ACTIVE))
    assert running.button("pause").font().bold()
    assert not running.button("resume").font().bold()


# ----------------------------------------------------------------- the column decision (pure)


def test_two_columns_need_the_threshold_and_room_for_both_columns():
    from yazses.settingsui.handsfree_panel import wants_two_columns

    assert wants_two_columns(TWO_COLUMN_MIN_PX, 400, 400, 24)
    assert not wants_two_columns(TWO_COLUMN_MIN_PX - 1, 400, 400, 24)
    # Wide enough by the threshold, but a large font makes the columns need more: one column.
    assert not wants_two_columns(1100, 600, 600, 24)
    assert wants_two_columns(1300, 600, 600, 24)
    # The 24 pt case that scrolled 448 px: 685 px of viewport is never two columns.
    assert not wants_two_columns(685, 560, 560, 24)
