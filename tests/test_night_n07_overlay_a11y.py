"""The overlay's windows are named for assistive technology, and the scan says its state in words.

Every overlay window is click-through and focus-less, which is right, but they were also
anonymous: no window title, no accessible name, and the Mouth-Sound Switch strip conveyed
which item was lit only by colour. The words live in the pure ``overlay/a11y.py``; the Qt
half is checked headlessly and skipped without PySide6.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from yazses.overlay.a11y import (
    GRID_NAME,
    SCAN_NAME,
    SONAR_DESCRIPTION,
    SONAR_NAME,
    grid_description,
    scan_description,
)
from yazses.overlay.grid import GridSnapshot
from yazses.overlay.scanstrip import strip_layout

_SCREEN = (0, 0, 1920, 1080)


# -- pure -------------------------------------------------------------------------------


def test_the_scan_names_the_lit_item_its_position_and_the_whole_list():
    text = scan_description(("copy", "click", "paste", "stop"), 1)
    assert text == "Click selected, 2 of 4: Copy, Click, Paste, Stop"


def test_the_description_changes_when_the_highlight_moves():
    labels = ("copy", "click", "paste")
    seen = {scan_description(labels, i) for i in range(len(labels))}
    assert len(seen) == len(labels)


@pytest.mark.parametrize(("labels", "index"), [((), 0), (("a",), -1), (("a", "b"), 2)])
def test_no_scan_says_nothing_exactly_when_nothing_is_drawn(labels, index):
    assert scan_description(labels, index) == ""
    assert strip_layout(labels, index, _SCREEN) is None


def test_the_grid_description_counts_the_cells_and_says_how_to_use_them():
    snap = GridSnapshot(active=True, region=(0.0, 0.0, 900.0, 600.0), cols=4, rows=2)
    text = grid_description(snap)
    assert text.startswith("4 by 2 grid, cells 1 to 8.")
    assert "number" in text


def test_an_inactive_grid_has_no_description():
    assert grid_description(GridSnapshot()) == ""


def test_every_window_has_a_distinct_non_empty_name():
    names = {SONAR_NAME, GRID_NAME, SCAN_NAME}
    assert len(names) == 3
    assert all(n.startswith("YazSes ") for n in names)
    assert SONAR_DESCRIPTION


def test_the_words_module_does_not_pull_in_the_grid():
    """The sonar window imports a11y on every overlay; the grid stays behind its flag."""
    code = (
        "import sys, yazses.overlay.a11y; "
        "print('yazses.overlay.grid' in sys.modules, 'yazses.mousegrid.grid' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
        check=True, timeout=60,
    ).stdout.split()
    assert out == ["False", "False"]


# -- Qt (headless) ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_sonar_window_is_named_and_described(qapp):
    from yazses.overlay.widget import SonarWidget

    w = SonarWidget(120, "#00e5ff")
    assert w.windowTitle() == SONAR_NAME
    assert w.accessibleName() == SONAR_NAME
    assert w.accessibleDescription() == SONAR_DESCRIPTION


def test_the_grid_window_is_named_and_describes_the_open_grid(qapp):
    from yazses.overlay.grid_widget import GridWidget

    w = GridWidget("#00e5ff")
    assert w.windowTitle() == GRID_NAME
    assert w.accessibleName() == GRID_NAME
    snap = GridSnapshot(active=True, region=(0.0, 0.0, 300.0, 300.0), cols=3, rows=3)
    w.show_grid(snap)
    try:
        assert w.accessibleDescription() == grid_description(snap)
        w.show_grid(GridSnapshot())
        assert w.accessibleDescription() == ""
    finally:
        w.hide()


def test_the_scan_window_says_which_item_is_lit_and_clears_when_the_scan_ends(qapp):
    from yazses.overlay.scan_widget import ScanWidget

    w = ScanWidget("#00e5ff")
    assert w.windowTitle() == SCAN_NAME
    assert w.accessibleName() == SCAN_NAME
    labels = ("copy", "click", "paste")
    try:
        w.show_scan(labels, 0, _SCREEN)
        assert w.accessibleDescription() == scan_description(labels, 0)
        w.show_scan(labels, 2, _SCREEN)
        assert w.accessibleDescription().startswith("Paste selected, 3 of 3")
        w.show_scan((), 0, _SCREEN)
        assert w.accessibleDescription() == ""
    finally:
        w.hide()
