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
    dialog = rig.panel.dialog
    dialog.resize(width, height)
    dialog.show()
    for _ in range(5):
        qapp.processEvents()
    return dialog


def test_wide_window_is_two_columns_and_narrow_is_one(qapp):
    rig = _Rig(qapp)
    _show(rig, qapp, TWO_COLUMN_MIN_PX + 200)
    assert rig.panel._columns.direction() == QBoxLayout.Direction.LeftToRight
    _show(rig, qapp, TWO_COLUMN_MIN_PX - 200)
    assert rig.panel._columns.direction() == QBoxLayout.Direction.TopToBottom
    _show(rig, qapp, TWO_COLUMN_MIN_PX + 200)
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
