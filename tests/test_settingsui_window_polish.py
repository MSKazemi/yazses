"""The settings window's frame on the Windows 11 style: dividers, page edges, repeated copy.

Three things that read as unfinished once the window was rendered and looked at:

* **The dividers were heavy.** A ``Sunken`` ``VLine``/``HLine`` paints a dark and a light
  line side by side, which the Windows 11 style shows as one 2 px bar, between a sidebar
  and a page that otherwise use hairlines (the feature list's row dividers).
* **Captions sat right of everything above them.** A stylesheet ``margin-*`` makes Qt count
  a ``QLabel`` as framed, and a framed label gets a default text indent of half an "x".
  Every page's blurb started about 6 px right of its heading and the labels below it.
* **The Hands-free page said the same sentence twice**, one line apart.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QMainWindow, QWidget  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui import app as settings_app  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402
from yazses.settingsui.pages import PAGES  # noqa: E402
from yazses.settingsui.shell import SettingsShell, hairline  # noqa: E402
from yazses.settingsui.theme import mute_label  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _window(qapp):
    cfg = Config()
    win = settings_app.SettingsWindow(
        build_settings_model(cfg), SettingsController(lambda: cfg, lambda *a: None, lambda m: [])
    )
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    return win


def _labels(widget):
    return {label.text(): label for label in widget.findChildren(QLabel)}


# ---- dividers --------------------------------------------------------------------------


def test_a_hairline_is_one_pixel_and_not_a_drawn_frame_line(qapp):
    v, h = hairline(vertical=True), hairline(vertical=False)
    assert (v.minimumWidth(), v.maximumWidth()) == (1, 1)
    assert (h.minimumHeight(), h.maximumHeight()) == (1, 1)
    for line in (v, h):
        assert line.frameShape() == QFrame.Shape.NoFrame, "a Sunken line paints two lines"
        assert "palette(midlight)" in line.styleSheet(), "colours come from the theme"


def test_the_window_uses_hairlines_between_sidebar_page_and_footer(qapp):
    shell = _window(qapp)._shell
    assert shell.sidebar_rule.maximumWidth() == 1
    assert shell.footer_rule.maximumHeight() == 1


# ---- the empty banner strip ------------------------------------------------------------


def test_with_no_banner_the_reserved_strip_leaves_no_gap(qapp):
    margins = _window(qapp)._shell.banner_layout.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (0, 0, 0, 0)


def test_with_a_banner_the_strip_keeps_its_margins(qapp):
    """The snap banner sits in this strip; collapsing the margins around it would crowd it."""
    central, window = QWidget(), QMainWindow()  # kept alive: Qt deletes layouts with their parent
    shell = SettingsShell(central, window)
    shell.banner_layout.addWidget(QLabel("microphone permission is missing"))
    shell.finish()
    margins = shell.banner_layout.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (8, 8, 8, 0)


# ---- the left edge ---------------------------------------------------------------------


def test_mute_label_keeps_the_text_on_the_left_edge(qapp):
    label = QLabel("a caption")
    mute_label(label, "margin-bottom: 6px;")
    assert label.indent() == 0
    assert "margin-bottom: 6px" in label.styleSheet()
    assert label.styleSheet().startswith("color: #"), "still the contrast-checked muted colour"


def test_a_styled_label_without_indent_zero_is_shifted(qapp):
    """The Qt behaviour the fix is for. If this stops being true, the fix is dead weight."""
    label = QLabel("a caption")
    label.setStyleSheet("margin-bottom: 6px;")
    label.show()
    qapp.processEvents()
    assert label.frameWidth() > 0, "a stylesheet margin makes a QLabel framed"


def test_every_page_blurb_starts_at_the_left_edge(qapp):
    win = _window(qapp)
    for index, spec in enumerate(PAGES):
        blurbs = [lb for text, lb in _labels(win._shell.stack.widget(index)).items() if text == spec.blurb]
        assert blurbs, f"no blurb found on the {spec.key} page"
        assert blurbs[0].indent() == 0, f"the {spec.key} page's blurb is indented"


def test_the_general_and_hands_free_notes_start_at_the_left_edge(qapp):
    win = _window(qapp)
    general = _labels(win._shell.stack.widget(0))
    note = next(lb for text, lb in general.items() if text.startswith("Changes are staged"))
    assert note.indent() == 0
    handsfree = _labels(win._shell.stack.widget(next(i for i, s in enumerate(PAGES) if s.key == "handsfree")))
    about = next(lb for text, lb in handsfree.items() if "does not open the camera" in text)
    assert about.indent() == 0


# ---- the repeated sentence -------------------------------------------------------------


def test_the_hands_free_page_does_not_repeat_its_own_blurb(qapp):
    win = _window(qapp)
    spec = next(s for s in PAGES if s.key == "handsfree")
    page = win._shell.stack.widget(PAGES.index(spec))
    texts = list(_labels(page))
    about = next(t for t in texts if "does not open the camera" in t)
    assert "Pause, resume" not in about, "that is the blurb's sentence, one line above"
    assert about != spec.blurb
    # What a person needs before clicking is still said: the camera is not opened.
    assert "does not open the camera" in about
