"""DIAGNOSTIC ONLY — draft PR, never merged.

Why does windows-latest put the '!' right of the Persian word even with FSI/PDI in
place (run 39566671404), while Linux puts it left? Two hypotheses:

1. Windows Qt resolves the isolate differently (a real platform difference).
2. The glyph-run measurement in test_settingsui_bidi_render.py does not survive Windows
   font fallback (the Persian glyphs come from a different font run).

This test always fails so CI prints what it measured, per character, by two independent
methods (QTextLine.cursorToX and glyph-run positions), for four markings of the same
text: none, FSI…PDI, RLI…PDI and RLE…PDF.
"""
from __future__ import annotations

import sys

import pytest

pytest.importorskip("PySide6")

from PySide6 import __version__ as pyside_version  # noqa: E402
from PySide6.QtCore import Qt, qVersion  # noqa: E402
from PySide6.QtGui import QFont, QFontInfo, QTextLayout, QTextOption  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

WORD = "سلام!"
CASES = {
    "none": f"Bookmarked '{WORD}'.",
    "FSI": f"Bookmarked '⁨{WORD}⁩'.",
    "RLI": f"Bookmarked '⁧{WORD}⁩'.",
    "RLE": f"Bookmarked '‫{WORD}‬'.",
}


def _measure(text: str) -> list[str]:
    layout = QTextLayout(text, QFont())
    option = QTextOption()
    option.setTextDirection(Qt.LayoutDirection.LeftToRight)
    layout.setTextOption(option)
    layout.beginLayout()
    line = layout.createLine()
    line.setLineWidth(4000)
    layout.endLayout()
    rows = []
    for i, ch in enumerate(text):
        x = line.cursorToX(i)  # PySide6 returns (x, cursor_pos)
        cursor_x = x[0] if isinstance(x, tuple) else x
        runs = layout.glyphRuns(i, 1)
        # No rawFont(): on windows-latest QGlyphRun.rawFont() is an access violation
        # (PR #606, first run), which killed the job before anything printed.
        glyph = [round(p.x(), 1) for r in runs for p in r.positions()]
        rows.append(f"  [{i:2}] U+{ord(ch):04X} cursorToX={cursor_x:7.1f} glyphs={glyph}")
    return rows


def test_windows_bidi_diagnostic():
    QApplication.instance() or QApplication([])
    out = [
        f"platform={sys.platform} Qt={qVersion()} PySide6={pyside_version}",
        f"default font={QFontInfo(QFont()).family()!r}",
    ]
    for name, text in CASES.items():
        out.append(f"--- {name}: {text!r}")
        out.extend(_measure(text))
    pytest.fail("\n".join(out), pytrace=False)
