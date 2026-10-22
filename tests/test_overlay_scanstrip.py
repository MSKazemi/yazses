"""The overlay's half of the Mouth-Sound Switch (ADR-v2-097): what it draws, how it polls.

The daemon owns the scan and reports it in the ``mouthswitch`` block of the ``status`` reply
the overlay already polls -- no IPC method of its own. The parsing and layout are pure and
tested here without Qt; the click-through window is smoke-tested headlessly when PySide6
(the ``desktop`` extra) is installed.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

import yazses.overlay.app as overlay_app
from yazses.overlay.poller import StatusSnapshot, next_interval, parse_status
from yazses.overlay.scanstrip import CELL_W, GAP, TOP_MARGIN, strip_layout

ITEMS = ["enter", "undo", "scroll up", "scroll down", "click"]


def _status(**block) -> dict:
    return {"state": "idle", "mouthswitch": block}


def test_a_running_scan_becomes_items_and_a_lit_index():
    snap = parse_status(_status(scanning=True, index=2, items=ITEMS))
    assert snap.scan_items == tuple(ITEMS) and snap.scan_index == 2
    assert snap.scanning is True


@pytest.mark.parametrize("info", [
    {"state": "idle"},
    {"state": "idle", "mouthswitch": None},
    _status(scanning=False, index=-1, items=ITEMS),
    _status(scanning="yes", index=1, items=ITEMS),
    _status(scanning=True, index=5, items=ITEMS),
    _status(scanning=True, index=-1, items=ITEMS),
    _status(scanning=True, index=True, items=ITEMS),
    _status(scanning=True, index=1.0, items=ITEMS),
    _status(scanning=True, index=0, items="enter"),
    _status(scanning=True, index=0, items=["enter", 3]),
])
def test_anything_else_lights_nothing(info):
    snap = parse_status(info)
    assert (snap.scan_items, snap.scan_index, snap.scanning) == ((), -1, False)


def test_the_default_snapshot_has_no_scan():
    assert StatusSnapshot().scanning is False


def test_it_polls_fast_while_a_scan_runs_and_the_old_call_shape_is_unchanged():
    slow = next_interval("idle")
    assert next_interval("idle", 0.0, False, True) < slow
    assert next_interval("idle", 0.0, False, False) == slow


def test_the_strip_is_centred_at_the_top_and_marks_only_the_lit_cell():
    layout = strip_layout(tuple(ITEMS), 1, (0, 0, 1920, 1080))
    assert layout is not None
    x, y, w, h = layout.window
    assert y == TOP_MARGIN
    assert w == 5 * CELL_W + 6 * GAP
    assert x == (1920 - w) // 2
    assert [lit for _label, _rect, lit in layout.cells] == [False, True, False, False, False]
    assert [label for label, _rect, _lit in layout.cells] == ITEMS


def test_the_strip_follows_a_screen_that_is_not_at_the_origin():
    layout = strip_layout(("enter",), 0, (-1280, 200, 1280, 1024))
    assert layout is not None
    x, y, _w, _h = layout.window
    assert -1280 <= x < 0 and y == 200 + TOP_MARGIN


def test_a_narrow_screen_shrinks_the_cells_instead_of_running_off_the_edge():
    layout = strip_layout(tuple(ITEMS), 0, (0, 0, 600, 800))
    assert layout is not None
    assert layout.window[2] <= 600
    assert all(rect[2] < CELL_W for _label, rect, _lit in layout.cells)


@pytest.mark.parametrize("labels,index", [((), 0), (("a",), 1), (("a",), -1)])
def test_nothing_to_draw_is_none(labels, index):
    assert strip_layout(labels, index, (0, 0, 800, 600)) is None


def test_the_overlay_builds_the_strip_only_when_the_feature_is_on():
    """An overlay without `[mouthswitch]` must import nothing more."""
    tree = ast.parse(Path(overlay_app.__file__).read_text(encoding="utf-8"))
    run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
    guarded: list[str] = []
    for node in ast.walk(run):
        if isinstance(node, ast.If) and "mouthswitch.enabled" in ast.unparse(node.test):
            guarded += [ast.unparse(n) for n in ast.walk(node) if isinstance(n, ast.ImportFrom)]
    assert any("overlay.scan_widget" in g for g in guarded)
    top = [ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any("scan" in t for t in top)


def test_the_daemon_payload_parses_into_what_the_overlay_draws():
    """The block the runner reports is the block the overlay reads: one shape, two ends."""
    from tests.test_mouthswitch_wiring import _started, pop_at

    runner, _sink, _made, _ran, d = _started()
    d.advance(0.3, pop_at(0.1))
    d.advance(1.2)
    snap = parse_status({"state": "idle", "mouthswitch": runner.view()})
    assert snap.scan_items == tuple(ITEMS) and snap.scan_index == 1


# ---- the Qt window (desktop extra only) ---------------------------------------


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_strip_window_is_click_through_and_follows_the_scan(qapp):
    from PySide6.QtCore import Qt

    from yazses.overlay.scan_widget import ScanWidget

    w = ScanWidget("#00e5ff")
    assert w.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert bool(w.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
    w.show_scan(tuple(ITEMS), 3, (0, 0, 1920, 1080))
    assert w.isVisible() and w.width() == 5 * CELL_W + 6 * GAP
    assert not w.grab().isNull()  # runs paintEvent
    w.show_scan((), -1, (0, 0, 1920, 1080))
    assert not w.isVisible()
