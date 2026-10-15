"""The hands-free window through the Qt accessibility API, the keyboard and a larger font (#420).

``test_settingsui_handsfree_panel.py`` checks the *properties* the shell sets. This file checks
what a person or an assistive technology actually receives, on Qt's offscreen platform (no window
is ever shown on a real desktop):

* what the accessibility layer reports for every widget -- its role, its name, and whether a
  label's own sentence reaches it (an ``accessibleName`` on a ``QLabel`` *replaces* the text in
  what a screen reader is told, so a caption like "Hands-free state" hid the state itself);
* the real focus chain Qt builds, not the list the shell hands to ``setTabOrder``;
* every control operated with the keyboard alone, and what Enter does when it is not aimed at a
  button;
* the window at a larger system font, where the three emergency buttons were once cut to
  fragments;
* that no colour is used at all, and that no pose or gaze value can reach any string.

**What this cannot see.** Qt's offscreen platform has no AT-SPI / UIA / NSAccessibility bridge, so
this asserts what Qt *offers* the bridge, not what Orca, NVDA or VoiceOver then say. It does not
render with the user's real theme or a real compositor. Those still need a person at a screen
(``design/eye-control/README.md`` keeps that as an open item).
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 (the `desktop` extra) is not installed")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QAccessible, QFont, QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QWidget,
)

from tests.test_settingsui_handsfree_panel import _hp, _inputs, _Rig  # noqa: E402
from yazses.handsfree.panel import PanelInputs, build_panel, stop_without_state  # noqa: E402
from yazses.handsfree.safety import SafetyState  # noqa: E402
from yazses.settingsui import handsfree_panel as panel_module  # noqa: E402
from yazses.settingsui.handsfree_panel import HandsFreePanel, enlarged  # noqa: E402

SRC = Path(panel_module.__file__).resolve().parent


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def font_restored(qapp):
    original = QFont(qapp.font())
    yield
    qapp.setFont(original)


def _plain(text: str) -> str:
    return text.replace("&", "")


def _shown(rig: _Rig, qapp) -> None:
    rig.panel.dialog.show()
    qapp.processEvents()


def _interactive(rig: _Rig) -> list[QWidget]:
    d = rig.panel.dialog
    return [*d.findChildren(QPushButton), *d.findChildren(QComboBox)]


def _faulted_with_everything_on() -> PanelInputs:
    return _inputs(SafetyState.FAULTED, reason="headpointer: signal is stale (900 ms old)",
                   face_on=True)


# ---------------------------------------------------------------- what the accessibility layer is told


def test_every_label_sentence_reaches_the_accessibility_layer(qapp):
    """The regression: ``setAccessibleName("Hands-free state")`` made the layer report the caption
    and drop the sentence, so a screen reader never announced Faulted / Paused / Active."""
    rig = _Rig(qapp, _faulted_with_everything_on())
    labels = [lb for lb in rig.panel.dialog.findChildren(QLabel) if lb.text().strip()]
    assert len(labels) >= 8
    for label in labels:
        iface = QAccessible.queryAccessibleInterface(label)
        assert iface is not None
        told = " ".join(
            iface.text(kind) for kind in (QAccessible.Text.Name, QAccessible.Text.Value)
        )
        assert _plain(label.text()).strip() in told, (
            f"a screen reader is told {told!r} instead of {label.text()!r}"
        )


def test_the_state_headline_is_what_a_screen_reader_is_told_first(qapp):
    rig = _Rig(qapp, _inputs(SafetyState.PAUSED, reason="paused by the user"))
    iface = QAccessible.queryAccessibleInterface(rig.panel._headline)
    assert iface is not None
    assert iface.text(QAccessible.Text.Name).startswith("Paused")


def test_every_button_and_combo_has_the_right_role_and_a_human_name(qapp):
    rig = _Rig(qapp, _faulted_with_everything_on())
    widgets = _interactive(rig)
    assert len(widgets) >= 18
    for widget in widgets:
        iface = QAccessible.queryAccessibleInterface(widget)
        assert iface is not None, widget.objectName()
        want = QAccessible.Role.ComboBox if isinstance(widget, QComboBox) else QAccessible.Role.Button
        assert iface.role() == want, widget.objectName()
        name = iface.text(QAccessible.Text.Name)
        assert name.strip(), f"{widget.objectName()} has no accessible name"
        assert "&" not in name, f"{name!r} leaks a mnemonic marker"
        assert name != widget.objectName(), f"{name!r} is an identifier, not a name"
        assert not re.fullmatch(r"[a-z]+(_[a-z]+)+", name), f"{name!r} reads like an identifier"


def _announced(widget: QWidget) -> str:
    """What a screen reader says for ``widget``: its name, preceded by whatever labels it.

    On Linux a combo box's *name* is its current choice (Qt's ``QAccessibleComboBox``), so the
    question it answers has to arrive through a "labelled by" relation (a ``QLabel`` buddy).
    """
    iface = QAccessible.queryAccessibleInterface(widget)
    assert iface is not None
    labels = [
        other.text(QAccessible.Text.Name)
        for other, _flag in iface.relations(QAccessible.RelationFlag.Label)
    ]
    return " / ".join([*labels, iface.text(QAccessible.Text.Name)])


def test_no_two_controls_are_announced_alike(qapp):
    """Five identical "Set" buttons and five combos that all read "Not mapped" were the trap:
    each must say which gesture it is for."""
    rig = _Rig(qapp, _faulted_with_everything_on())
    said = [_announced(w) for w in _interactive(rig)]
    assert len(said) == len(set(said)), sorted({n for n in said if said.count(n) > 1})


def test_each_gesture_combo_is_labelled_by_its_gesture_name(qapp):
    rig = _Rig(qapp, _inputs(face_on=True))
    for gesture, (label, combo, _setb) in rig.panel._map_widgets.items():
        iface = QAccessible.queryAccessibleInterface(combo)
        assert iface is not None
        labelled_by = [
            other.text(QAccessible.Text.Name)
            for other, _f in iface.relations(QAccessible.RelationFlag.Label)
        ]
        assert label.text() in labelled_by, f"{gesture}: a screen reader is never told which gesture"


def test_before_the_first_read_no_control_is_named_after_an_identifier(qapp):
    rig = _Rig(qapp)
    fresh = HandsFreePanel(lambda: rig.inputs, lambda spec: None, poll_ms=0, threaded=False)
    for widget in [*fresh.dialog.findChildren(QPushButton)]:
        text = _plain(widget.text())
        assert not re.fullmatch(r"[a-z]+(_[a-z]+)+", text), f"placeholder text {text!r}"
        assert text.strip()


# ---------------------------------------------------------------- the focus chain, as Qt really builds it


def _chain(rig: _Rig, qapp) -> list[QWidget]:
    """Every Tab stop, in the order Qt will visit them, starting at Pause."""
    _shown(rig, qapp)
    start = rig.button("pause")
    stops: list[QWidget] = []
    widget = start
    for _ in range(500):
        if (
            widget.focusPolicy() & Qt.FocusPolicy.TabFocus
            and widget.isEnabled()
            and widget.isVisibleTo(rig.panel.dialog)
        ):
            stops.append(widget)
        widget = widget.nextInFocusChain()
        if widget is start:
            break
    return stops


def test_the_real_focus_chain_starts_with_pause_resume_recenter_and_misses_no_control(qapp):
    rig = _Rig(qapp, _faulted_with_everything_on())
    stops = _chain(rig, qapp)
    assert stops[:3] == [rig.button("pause"), rig.button("resume"), rig.button("recenter")]
    enabled = [w for w in _interactive(rig) if w.isEnabled()]
    missing = [w.objectName() or w.accessibleName() for w in enabled if w not in stops]
    assert missing == [], f"operable by pointer, skipped by Tab: {missing}"


def test_the_only_extra_tab_stops_are_the_scroll_area_and_the_selectable_health_text(qapp):
    rig = _Rig(qapp, _faulted_with_everything_on())
    stops = _chain(rig, qapp)
    extras = [w for w in stops if not isinstance(w, (QPushButton, QComboBox))]
    assert {type(w) for w in extras} <= {QScrollArea, QLabel}
    assert rig.panel._health in extras, "the health report must be reachable to be read and copied"
    labels = [w for w in extras if isinstance(w, QLabel)]
    assert labels == [rig.panel._health]


def test_the_real_chain_follows_the_order_the_shell_declared(qapp):
    rig = _Rig(qapp, _faulted_with_everything_on())
    stops = [w for w in _chain(rig, qapp) if w in rig.panel.tab_order]
    declared = [w for w in rig.panel.tab_order if w.isEnabled() and w in stops]
    assert stops == declared


# ---------------------------------------------------------------- the keyboard alone


def test_every_enabled_button_can_be_pressed_with_space_and_with_enter(qapp):
    rig = _Rig(qapp, _faulted_with_everything_on())
    _shown(rig, qapp)
    pressed: list[str] = []
    buttons = [b for b in rig.panel.dialog.findChildren(QPushButton) if b.isEnabled()]
    # Close would end the test's own dialog; the rest are exercised for real.
    buttons = [b for b in buttons if b.objectName() != "close"]
    assert len(buttons) >= 10
    for button in buttons:
        button.clicked.connect(lambda _=False, n=button.objectName(): pressed.append(n))
    for key in (Qt.Key.Key_Space, Qt.Key.Key_Return):
        pressed.clear()
        for button in buttons:
            button.setFocus()
            QTest.keyClick(button, key)
        assert sorted(pressed) == sorted(b.objectName() for b in buttons), key


def test_a_combo_box_is_changed_with_the_arrow_keys_and_saved_with_its_set_button(qapp):
    rig = _Rig(qapp, _inputs(face_on=True))
    _shown(rig, qapp)
    combo = rig.panel._map_widgets["smile"][1]
    combo.setFocus()
    before = combo.currentIndex()
    QTest.keyClick(combo, Qt.Key.Key_Down)
    if combo.currentIndex() == before:  # it was on the last choice
        QTest.keyClick(combo, Qt.Key.Key_Up)
    assert combo.currentIndex() != before
    rig.button("map_smile").setFocus()
    QTest.keyClick(rig.button("map_smile"), Qt.Key.Key_Space)
    assert rig.performed, "the mapping was never saved by keyboard alone"


def test_the_three_emergency_buttons_have_distinct_alt_mnemonics_and_nothing_else_collides(qapp):
    rig = _Rig(qapp, _faulted_with_everything_on())
    seen: dict[str, str] = {}
    for button in rig.panel.dialog.findChildren(QPushButton):
        seq = QKeySequence.mnemonic(button.text())
        if seq.isEmpty():
            continue
        key = seq.toString()
        assert key not in seen, f"{key} is claimed by {seen[key]} and {button.objectName()}"
        seen[key] = button.objectName()
    assert seen.get("Alt+P") == "pause"
    assert seen.get("Alt+C") == "recenter"
    assert "resume" in seen.values()


def test_enter_on_text_refreshes_and_never_pauses(qapp):
    """Qt makes the first button -- Pause -- the dialog's default, so Enter on the health text
    paused hands-free input. The default is now Refresh."""
    rig = _Rig(qapp, _inputs(SafetyState.ACTIVE))
    _shown(rig, qapp)
    assert rig.button("refresh").isDefault()
    assert not rig.button("pause").isDefault()
    rig.panel._health.setFocus()
    gathers = rig.gathers
    QTest.keyClick(rig.panel._health, Qt.Key.Key_Return)
    assert rig.performed == [], "Enter on the health text performed an action"
    assert rig.gathers == gathers + 1, "Enter on the health text should have refreshed"


def test_escape_closes_the_window_without_performing_anything(qapp):
    rig = _Rig(qapp)
    _shown(rig, qapp)
    QTest.keyClick(rig.panel.dialog, Qt.Key.Key_Escape)
    assert not rig.panel.dialog.isVisible()
    assert rig.performed == []


# ---------------------------------------------------------------- before the first read


def _unread_panel():
    performed: list = []

    class Done:
        ok = True
        message = "ok"

    def perform(spec):
        performed.append(spec)
        return Done()

    panel = HandsFreePanel(lambda: None, perform, poll_ms=0, threaded=False)
    return panel, performed


def test_pause_works_before_the_daemon_has_been_read_and_makes_the_ordinary_call(qapp):
    panel, performed = _unread_panel()
    pause = panel._buttons["pause"]
    assert pause.isEnabled()

    pause.click()

    assert [s.id for s in performed] == ["pause"]
    ordinary = build_panel(_inputs(SafetyState.ACTIVE)).action("pause")
    assert performed[0].ipc == ordinary.ipc and performed[0].cli == ordinary.cli  # type: ignore[union-attr]
    assert performed[0] == stop_without_state()


def test_every_other_control_is_disabled_until_the_first_read(qapp):
    panel, performed = _unread_panel()
    for ident, button in panel._buttons.items():
        if ident in ("pause", "refresh", "close"):
            assert button.isEnabled(), ident
        else:
            assert not button.isEnabled(), f"{ident} is pressable before the state is known"
    panel._buttons["resume"].click()
    assert performed == []


def test_after_the_first_read_the_controls_the_state_allows_become_usable(qapp):
    rig = _Rig(qapp, _faulted_with_everything_on())
    assert rig.button("resume").isEnabled()
    assert rig.button("apply").isEnabled()
    assert rig.button("safety_toggle").isEnabled()


@pytest.mark.parametrize(
    ("state", "reason", "expected"),
    [
        pytest.param(SafetyState.ACTIVE, "", "pause", id="active-focuses-pause"),
        pytest.param(SafetyState.FAULTED, "headpointer: signal is stale", "resume",
                     id="faulted-focuses-recover"),
        pytest.param(SafetyState.PAUSED, "paused by the user", "resume", id="paused-focuses-resume"),
    ],
)
def test_the_first_read_puts_keyboard_focus_on_the_action_the_state_calls_for(
    qapp, state, reason, expected
):
    rig = _Rig(qapp, _inputs(state, reason=reason))
    assert rig.panel.dialog.focusWidget() is rig.button(expected)


# ---------------------------------------------------------------- a larger system font


@pytest.mark.parametrize(
    "points",
    [pytest.param(9, id="9pt"), pytest.param(14, id="14pt"), pytest.param(24, id="24pt"),
     pytest.param(32, id="32pt")],
)
def test_no_button_or_combo_is_cut_short_and_nothing_forces_sideways_scrolling(
    qapp, font_restored, points
):
    font = QFont(qapp.font())
    font.setPointSize(points)
    qapp.setFont(font)
    rig = _Rig(qapp, _faulted_with_everything_on())
    _shown(rig, qapp)
    for button in rig.panel.dialog.findChildren(QPushButton):
        need = max(button.sizeHint().width(), button.minimumSizeHint().width())
        assert button.width() >= need, (
            f"{button.objectName()} is {button.width()}px wide but needs {need}px at {points}pt: "
            f"{_plain(button.text())!r} is cut short"
        )
    for combo in rig.panel.dialog.findChildren(QComboBox):
        widest = max(combo.fontMetrics().horizontalAdvance(combo.itemText(i)) for i in range(combo.count()))
        assert combo.width() >= widest, f"{combo.accessibleName()} would elide its choices at {points}pt"
    for area in rig.panel.dialog.findChildren(QScrollArea):
        assert area.horizontalScrollBar().maximum() == 0, f"sideways scrolling at {points}pt"


def _narrowest_and_widest_families(qapp) -> list[str]:
    """The installed font families with the smallest and the largest average glyph width.

    The window's fixed-pixel parts (target sizes, margins, the combo arrow, the scroll bar) do not
    scale with the font, so a NARROW font is where a width worked out from the average glyph width
    comes up short. That is the Windows case: its default font is narrower than the Linux one the
    layout was first tuned on, and the hosted Windows run scrolled sideways by 25 px at 14 pt.
    """
    from PySide6.QtGui import QFontDatabase, QFontMetrics

    widths = {}
    for family in QFontDatabase.families():
        font = QFont(family)
        font.setPointSize(14)
        if QFontMetrics(font).averageCharWidth() > 0:
            widths[family] = QFontMetrics(font).averageCharWidth()
    if len(widths) < 2:
        return []
    return [min(widths, key=widths.get), max(widths, key=widths.get)]


@pytest.mark.parametrize("points", [pytest.param(9, id="9pt"), pytest.param(14, id="14pt"),
                                    pytest.param(24, id="24pt")])
@pytest.mark.parametrize("which", [pytest.param(0, id="narrowest-font"), pytest.param(1, id="widest-font")])
def test_no_sideways_scrolling_in_the_narrowest_and_the_widest_installed_font(
    qapp, font_restored, which, points
):
    families = _narrowest_and_widest_families(qapp)
    if not families:
        pytest.skip("fewer than two font families are installed")
    font = QFont(families[which])
    font.setPointSize(points)
    qapp.setFont(font)
    rig = _Rig(qapp, _faulted_with_everything_on())
    _shown(rig, qapp)
    for area in rig.panel.dialog.findChildren(QScrollArea):
        assert area.horizontalScrollBar().maximum() == 0, (
            f"sideways scrolling by {area.horizontalScrollBar().maximum()}px at {points}pt in {families[which]!r}"
        )


def test_the_emergency_buttons_and_headline_grow_with_the_system_font(qapp, font_restored):
    sizes = {}
    for points in (10, 20):
        font = QFont(qapp.font())
        font.setPointSize(points)
        qapp.setFont(font)
        rig = _Rig(qapp)
        sizes[points] = (
            rig.button("pause").font().pointSizeF(),
            rig.panel._headline.font().pointSizeF(),
            rig.button("pause").sizeHint().height(),
        )
    assert sizes[20][0] > sizes[10][0] and sizes[20][1] > sizes[10][1]
    assert sizes[20][0] >= 20, "the emergency buttons are smaller than the system font"
    assert sizes[20][2] >= sizes[10][2]


def test_a_pixel_sized_system_font_is_scaled_not_replaced_with_a_constant(qapp, font_restored):
    """On a desktop that scales by pixels ``pointSize()`` is -1; the old code then wrote a fixed
    13 pt, so the user's chosen text size was silently ignored on exactly the controls that matter."""
    font = QFont(qapp.font())
    font.setPixelSize(40)
    qapp.setFont(font)
    rig = _Rig(qapp)
    pause = rig.button("pause").font()
    assert pause.pixelSize() >= 40
    assert enlarged(QFont(font), 2.0).pixelSize() > 40


def test_enlarged_keeps_a_floor_for_small_point_fonts_and_grows_large_ones():
    small = QFont()
    small.setPointSizeF(8.0)
    big = QFont()
    big.setPointSizeF(20.0)
    assert enlarged(small, 2.0).pointSizeF() == 13.0
    assert enlarged(big, 2.0).pointSizeF() == 22.0


# ---------------------------------------------------------------- no colour, no pose, no gaze


def test_no_colour_is_set_anywhere_in_the_shell_or_on_any_widget(qapp):
    tree = ast.parse((SRC / "handsfree_panel.py").read_text(encoding="utf-8"))
    forbidden = {"setStyleSheet", "setPalette", "setForeground", "setBackground", "QColor",
                 "QPalette", "setColor"}
    used = {
        node.attr if isinstance(node, ast.Attribute) else node.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Attribute, ast.Name))
    } & forbidden
    assert used == set(), f"the shell sets colour via {sorted(used)}"
    rig = _Rig(qapp, _faulted_with_everything_on())
    for widget in rig.panel.dialog.findChildren(QWidget):
        assert widget.styleSheet() == "", widget.objectName()
        assert widget.palette().resolveMask() == 0, f"{widget.objectName()} overrides the palette"


def _every_string(rig: _Rig) -> str:
    chunks: list[str] = []
    for widget in rig.panel.dialog.findChildren(QWidget):
        for getter in ("text", "toolTip", "accessibleName", "accessibleDescription", "title"):
            value = getattr(widget, getter, None)
            if callable(value):
                chunks.append(str(value()))
        if isinstance(widget, QComboBox):
            chunks += [widget.itemText(i) for i in range(widget.count())]
    return "\n".join(chunks)


def test_no_pose_gaze_or_position_value_can_reach_any_string_in_the_window(qapp):
    """Everything the shell shows comes from the model; the model reads named keys only. A
    status reply that carried raw angles, a gaze point or a pointer position must not be echoed."""
    secrets = {"yaw": 0.37731, "pitch": -0.18842, "roll": 0.0614, "gaze_x": 913.25,
               "gaze_y": 441.75, "x": 1234, "y": 567, "landmarks": [[0.5731, 0.2917]]}
    rig = _Rig(qapp, _inputs(hp=_hp(**secrets), face_on=True))
    text = _every_string(rig)
    for needle in ("0.37731", "0.18842", "0.0614", "913.25", "441.75", "1234", "0.5731", "0.2917"):
        assert needle not in text, f"{needle} reached the window"
    for word in ("yaw", "pitch", "landmark", "gaze_x"):
        assert word not in text.lower(), f"{word!r} reached the window"


def test_the_window_shows_no_numbers_that_look_like_measurements(qapp):
    """Ages in milliseconds are timing facts the gate publishes on purpose; anything with a
    decimal fraction would be a sensor reading."""
    rig = _Rig(qapp, _inputs(SafetyState.FAULTED, reason="headpointer: signal is stale (900 ms old)",
                             hp=_hp(sample_age_s=0.9)))
    assert not re.findall(r"\d+\.\d+", _every_string(rig))
