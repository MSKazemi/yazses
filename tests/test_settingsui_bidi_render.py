"""What Qt itself does with Persian in the settings window and the tray (FA-07, #516).

`tests/test_bidi.py` holds the string contract; this file holds the toolkit's side
of it, measured rather than assumed, on the offscreen platform:

* Qt's text engine honours FSI..PDI. Without the isolate, an LTR line (every label,
  combo-box row and tooltip in an English UI) puts the ``!`` of ``سلام!`` on the
  word's right -- its visual *start* for an RTL reader. With ``wrap_user_text`` it
  lands on the left, at the logical end. This is the defect the helper fixes, so the
  first test asserts the defect exists as well as the fix: if a Qt release ever
  resolves it unaided, the test says so instead of passing for the wrong reason.
* ``QLineEdit`` -- the Vocabulary field -- already lays its content out by the
  first strong character while its own layout direction stays left-to-right, so
  Persian text is right-aligned and English text is not, without any change to the
  window. The text it hands back, and copies, is the logical string, byte for byte.

Glyph positions are font-independent in the property asserted: a missing Arabic
font draws boxes, but the bidi reordering that places them is the same.
Visual quality (shaping, a real RTL reader's judgement, high-DPI) is NOT checked here.

Named ``test_settingsui_*`` so the GUI job's glob runs it with PySide6 installed.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont, QTextLayout, QTextOption  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from yazses.bidi import wrap_user_text  # noqa: E402

ZWNJ = "\N{ZERO WIDTH NON-JOINER}"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _glyph_x(text: str, index: int) -> float:
    """Left x of the glyph for ``text[index]`` in an LTR paragraph, as Qt lays it out."""
    layout = QTextLayout(text, QFont())
    option = QTextOption()
    option.setTextDirection(Qt.LayoutDirection.LeftToRight)
    layout.setTextOption(option)
    layout.beginLayout()
    line = layout.createLine()
    line.setLineWidth(4000)
    layout.endLayout()
    xs = [p.x() for run in layout.glyphRuns(index, 1) for p in run.positions()]
    assert xs, f"no glyph for {text[index]!r} at {index}"
    return min(xs)


def _bang_x(text: str) -> float:
    return _glyph_x(text, text.index("!"))


def _bang_is_left_of_word(text: str) -> bool:
    """The '!' is not right of the Persian word's first letter.

    ``<=``, not ``<``: windows-latest's offscreen Qt has no font that draws Persian, so
    every Persian glyph there has zero width and sits at one x, with a correctly isolated
    '!' at that same x (PR #606 measured 144.0 for all of them). A strict ``<`` read that
    as the isolate failing when Qt had placed it correctly.
    """
    return _bang_x(text) <= _glyph_x(text, text.index("س"))


def test_without_isolation_qt_puts_the_persian_punctuation_on_the_wrong_side(qapp):
    """The defect, measured: the neutral resolves with the English sentence."""
    assert not _bang_is_left_of_word("Bookmarked 'سلام!'.")


def test_with_isolation_qt_puts_it_at_the_logical_end(qapp):
    plain = "Bookmarked 'سلام!'."
    isolated = f"Bookmarked '{wrap_user_text('سلام!')}'."
    assert _bang_is_left_of_word(isolated)
    # And it moved: without the isolate the '!' sits right of the word (the defect), so
    # the isolate must pull it left. This half holds even where Persian has no font.
    assert _bang_x(isolated) < _bang_x(plain)


def test_an_english_sentence_around_the_isolate_keeps_its_order(qapp):
    """The chrome stays LTR: 'Mic:' is still left of the device name."""
    text = f"Mic: {wrap_user_text('میکروفون')}"
    assert _glyph_x(text, 0) < _glyph_x(text, text.index("م"))


@pytest.mark.parametrize(
    "content",
    ["سلام دنیا.", "من از VS Code استفاده می" + ZWNJ + "کنم.", "فایل در /home/user/project"],
)
def test_the_vocabulary_field_lays_persian_out_right_to_left(qapp, content):
    edit = QLineEdit(content)
    edit.resize(320, 30)
    edit.show()
    qapp.processEvents()
    edit.setCursorPosition(0)
    start = edit.cursorRect().center().x()
    edit.setCursorPosition(len(content))
    end = edit.cursorRect().center().x()
    assert start > end, "logical start should be on the right for RTL content"
    # The widget's own direction -- the chrome's -- is untouched.
    assert edit.layoutDirection() == Qt.LayoutDirection.LeftToRight
    edit.close()


def test_the_vocabulary_field_keeps_english_first_text_left_to_right(qapp):
    content = "VS Code و سلام"
    edit = QLineEdit(content)
    edit.resize(320, 30)
    edit.show()
    qapp.processEvents()
    edit.setCursorPosition(0)
    start = edit.cursorRect().center().x()
    edit.setCursorPosition(len(content))
    assert start < edit.cursorRect().center().x()
    edit.close()


def test_the_vocabulary_field_returns_and_copies_the_logical_string(qapp):
    content = "یزسس، Kubernetes، می" + ZWNJ + "کنم ۱۲۳"
    edit = QLineEdit(content)
    assert edit.text() == content
    edit.selectAll()
    edit.copy()
    copied = QApplication.clipboard().text()
    assert copied == content
    assert "\N{FIRST STRONG ISOLATE}" not in copied
