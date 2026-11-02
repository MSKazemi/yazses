"""Keyboard access in the settings window: a visible focus ring, a reachable Apply, and labels
that are not clipped at a large font.

Each of these was reproduced before it was fixed. Headless and offscreen: the focus ring is
checked on the rendered pixels, against the WCAG 2.1 contrast formula in ``theme.py``, in a
light and a dark palette.

Skipped when PySide6 is not installed.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPalette  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402
from yazses.settingsui.pages import PAGES  # noqa: E402
from yazses.settingsui.theme import contrast_ratio  # noqa: E402

#: WCAG 2.1 non-text contrast minimum for a focus indicator (SC 1.4.11).
NON_TEXT_MIN = 3.0


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _window(qapp):
    controller = SettingsController(Config, lambda *a: None, lambda modules: [])
    win = SettingsWindow(build_settings_model(Config()), controller)
    # No modal dialog, no host daemon, and no level poll: any of them would block or touch
    # the machine running the test.
    win._confirm_experimental = lambda row: True  # type: ignore[method-assign]
    win._confirm_reset = lambda diff, labels: True  # type: ignore[method-assign]
    win._warn = lambda title, body: None  # type: ignore[method-assign]
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    win._confirm_restart = lambda: False  # type: ignore[method-assign]
    win._level_timer.stop()
    return win


def _rgb(color: QColor) -> tuple[int, int, int]:
    return color.red(), color.green(), color.blue()


def _palette(*, dark: bool) -> QPalette:
    palette = QPalette()
    if dark:
        values = {
            QPalette.ColorRole.Window: "#353535",
            QPalette.ColorRole.WindowText: "#ffffff",
            QPalette.ColorRole.Base: "#232323",
            QPalette.ColorRole.Text: "#ffffff",
            QPalette.ColorRole.Button: "#353535",
            QPalette.ColorRole.ButtonText: "#ffffff",
            QPalette.ColorRole.Highlight: "#2a82da",
            QPalette.ColorRole.HighlightedText: "#ffffff",
        }
    else:
        values = {
            QPalette.ColorRole.Window: "#efefef",
            QPalette.ColorRole.WindowText: "#000000",
            QPalette.ColorRole.Base: "#ffffff",
            QPalette.ColorRole.Text: "#000000",
            QPalette.ColorRole.Button: "#efefef",
            QPalette.ColorRole.ButtonText: "#000000",
            QPalette.ColorRole.Highlight: "#308cc6",
            QPalette.ColorRole.HighlightedText: "#ffffff",
        }
    for role, hex_value in values.items():
        palette.setColor(role, QColor(hex_value))
    return palette


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
@pytest.mark.parametrize("list_name", ["sidebar", "categories"])
def test_the_focused_row_has_a_two_pixel_ring_that_is_visible_on_the_window_and_the_row(
    qapp, dark, list_name
):
    """The focused row needs an indicator of its own, not only its selection fill.

    The sidebar and the category list used ``outline: 0``, which removes Qt's focus rect.
    Selection follows the arrow keys in both lists, so the only cue left was the fill, which
    says which page is open and is not a focus indicator. The ring must differ from the fill
    and contrast at least 3:1 with the window it sits on and with the fill it sits on.
    """
    original = qapp.palette()
    qapp.setPalette(_palette(dark=dark))
    try:
        win = _window(qapp)
        win._win.resize(900, 640)
        win._win.show()
        qapp.processEvents()
        widget = win._shell.sidebar if list_name == "sidebar" else win._category_list
        row = 2 if list_name == "sidebar" else 3
        if list_name == "categories":
            win._shell.select("features")  # the category list lives on the Features page
            qapp.processEvents()
        widget.setCurrentRow(row)
        widget.setFocus()
        qapp.processEvents()
        assert widget.hasFocus()

        # Grab the whole window so the margin around the row is the window's own colour,
        # not the transparent background a widget grab would leave.
        image = win._win.grab().toImage()
        rect = widget.visualItemRect(widget.item(row))
        top_left = widget.mapTo(win._win, rect.topLeft())
        x = top_left.x() + rect.width() // 2
        y = top_left.y()

        window_bg = _rgb(QColor(image.pixelColor(x, y - 3)))
        # The outer edge of whatever is painted in the row: the ring if there is one, else
        # the fill. The row's margin varies by list, so find the edge instead of assuming it.
        edge = next(
            yy for yy in range(y - 3, y + rect.height())
            if _rgb(QColor(image.pixelColor(x, yy))) != window_bg
        )
        ring = _rgb(QColor(image.pixelColor(x, edge)))
        fill = _rgb(QColor(image.pixelColor(x, edge + 6)))

        assert ring != fill, "the focused row has no ring of its own"
        assert contrast_ratio(ring, window_bg) >= NON_TEXT_MIN
        assert contrast_ratio(ring, fill) >= NON_TEXT_MIN
        win._win.close()
    finally:
        qapp.setPalette(original)


def _apply_clicks(win) -> list[int]:
    clicks: list[int] = []
    win._apply_button.clicked.connect(lambda: clicks.append(1))
    return clicks


@pytest.mark.parametrize("enter_key", [Qt.Key.Key_Return, Qt.Key.Key_Enter],
                         ids=["main-return", "keypad-enter"])
def test_ctrl_return_applies_from_the_sidebar(qapp, enter_key):
    win = _window(qapp)
    win._win.show()
    qapp.processEvents()
    clicks = _apply_clicks(win)
    win._shell.sidebar.setFocus()
    qapp.processEvents()
    QTest.keyClick(win._shell.sidebar, enter_key, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()
    assert clicks == [1]
    win._win.close()


def test_plain_return_in_the_search_box_does_not_apply(qapp):
    win = _window(qapp)
    win._win.show()
    qapp.processEvents()
    clicks = _apply_clicks(win)
    win._shell.select("features")
    win._filter_box.setFocus()
    qapp.processEvents()
    QTest.keyClick(win._filter_box, Qt.Key.Key_Return)
    qapp.processEvents()
    assert clicks == []
    win._win.close()


def test_the_apply_tooltip_states_the_shortcut_it_answers_to(qapp):
    win = _window(qapp)
    assert "Ctrl+Return" in win._apply_button.toolTip()
    win._win.close()


@pytest.mark.parametrize("scale", [1.0, 2.0], ids=["1x", "2x"])
def test_no_label_or_button_is_narrower_than_its_text_on_any_page(qapp, scale):
    """At a large font, every label's text must fit its widget (no clipped words).

    Built at the window's minimum size, which is where a squeeze shows. Wrapping labels are
    held to the widest single word: they may take more lines, never a cut word.
    """
    original_font = QFont(qapp.font())
    scaled = QFont(original_font)
    scaled.setPointSizeF(original_font.pointSizeF() * scale)
    qapp.setFont(scaled)
    try:
        win = _window(qapp)
        win._win.resize(760, 520)
        win._win.show()
        qapp.processEvents()
        problems = []
        for spec in PAGES:
            win._shell.select(spec.key)
            qapp.processEvents()
            widgets = win._win.findChildren(QLabel) + win._win.findChildren(QPushButton)
            for widget in widgets:
                text = widget.text()
                if not text or not widget.isVisible():
                    continue
                metrics = widget.fontMetrics()
                if isinstance(widget, QLabel):
                    available = widget.contentsRect().width()
                    if widget.wordWrap():
                        needed = max(metrics.horizontalAdvance(word) for word in text.split())
                    else:
                        needed = metrics.horizontalAdvance(text)
                else:
                    # A button needs its own size hint (text, padding, and the mnemonic
                    # handled as Qt draws it). The bare text width is kept as a floor.
                    available = widget.width()
                    needed = max(
                        widget.sizeHint().width(),
                        metrics.horizontalAdvance(text.replace("&", "")),
                    )
                if needed > available:
                    problems.append(f"{spec.key}: {text[:40]!r} needs {needed}px, has {available}px")
        win._win.close()
        assert problems == []
    finally:
        qapp.setFont(original_font)
