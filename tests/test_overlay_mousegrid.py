"""The overlay's half of the Voice Mouse Grid (ADR-v2-030): what it draws, how it polls.

The daemon owns the grid; the overlay draws the numbered cells over the region the daemon
reports. The pure layout and parsing are tested here without Qt; the click-through window is
smoke-tested headlessly when PySide6 (the ``desktop`` extra) is installed.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

import yazses.overlay.app as overlay_app
from yazses.mousegrid.runtime import MousegridRuntime
from yazses.overlay.grid import (
    GridPoller,
    GridSnapshot,
    grid_cells,
    next_grid_interval,
    parse_grid_status,
)


def test_a_status_reply_becomes_a_snapshot():
    snap = parse_grid_status({"active": True, "region": [10, 20, 300, 150], "cols": 3, "rows": 3})
    assert snap == GridSnapshot(True, (10.0, 20.0, 300.0, 150.0), 3, 3)


@pytest.mark.parametrize("info", [
    None, "x", {}, {"active": False, "region": [0, 0, 9, 9]},
    {"active": True}, {"active": True, "region": [0, 0, 0, 9]},
    {"active": True, "region": [0, 0, "a", 9]}, {"active": True, "region": [0, 0, 9]},
    {"active": True, "region": [0, 0, float("inf"), 9]},
    {"active": "yes", "region": [0, 0, 9, 9]},
])
def test_a_malformed_reply_draws_nothing(info):
    assert parse_grid_status(info).active is False


def test_bad_dimensions_fall_back_to_three_by_three():
    snap = parse_grid_status({"active": True, "region": [0, 0, 9, 9], "cols": 0, "rows": True})
    assert (snap.cols, snap.rows) == (3, 3)


def test_the_painted_numbers_are_the_numbers_the_daemon_resolves():
    """A cell labelled N must be the cell that "N" moves the pointer to."""
    rt = MousegridRuntime(sink_factory=None, region_provider=lambda: (0, 0, 900, 600))
    rt._unavailable = ""  # draw-only: opening needs no sink
    assert rt.handle_transcript("mouse grid") == "opened"
    snap = parse_grid_status(rt.status())
    cells = grid_cells(snap)
    assert [n for n, _ in cells] == list(range(1, 10))
    assert cells[0][1] == (0.0, 0.0, 300.0, 200.0)
    assert cells[2][1] == (600.0, 0.0, 300.0, 200.0)   # 3 = top right
    assert cells[6][1] == (0.0, 400.0, 300.0, 200.0)   # 7 = bottom left
    assert grid_cells(GridSnapshot()) == []


def test_it_polls_fast_only_while_a_grid_is_open():
    open_grid = GridSnapshot(active=True, region=(0, 0, 1, 1))
    assert next_grid_interval(open_grid) < next_grid_interval(GridSnapshot())


class _Client:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[tuple[str, dict]] = []

    def call(self, method, **params):
        self.calls.append((method, params))
        if params.get("action") == "screen":
            return {"ok": True}
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_the_poller_reports_its_screen_whenever_the_daemon_has_none():
    client = _Client([
        {"active": False, "screen_reported": False},
        {"active": True, "region": [0, 0, 90, 90], "screen_reported": True},
        {"active": False, "screen_reported": False},   # the daemon restarted
    ])
    poller = GridPoller(client, (0, 0, 1920, 1080))
    assert poller.poll_once().active is False
    assert poller.poll_once().active is True
    poller.poll_once()
    screens = [p for _m, p in client.calls if p.get("action") == "screen"]
    assert screens == [{"action": "screen", "region": [0, 0, 1920, 1080]}] * 2
    assert all(m == "mousegrid" for m, _p in client.calls)


def test_an_unreachable_daemon_hides_the_grid():
    poller = GridPoller(_Client([ConnectionError("down")]))
    assert poller.poll_once() == GridSnapshot()
    assert poller.latest() == GridSnapshot()


def test_the_overlay_builds_the_grid_only_when_the_feature_is_on():
    """An overlay without `[mousegrid]` must import nothing more and send no new IPC."""
    tree = ast.parse(Path(overlay_app.__file__).read_text(encoding="utf-8"))
    run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
    guarded: list[str] = []
    for node in ast.walk(run):
        if isinstance(node, ast.If) and "mousegrid.enabled" in ast.unparse(node.test):
            guarded += [ast.unparse(n) for n in ast.walk(node) if isinstance(n, ast.ImportFrom)]
    assert any("overlay.grid_widget" in g for g in guarded)
    assert any("overlay.grid import" in g for g in guarded)
    top = [ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any("grid" in t for t in top)


# ---- the Qt window (desktop extra only) ---------------------------------------


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_grid_window_is_click_through_and_follows_the_snapshot(qapp):
    from PySide6.QtCore import Qt

    from yazses.overlay.grid_widget import GridWidget

    w = GridWidget("#00e5ff")
    assert w.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert bool(w.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
    w.show_grid(GridSnapshot(True, (10.0, 20.0, 300.0, 240.0), 3, 3))
    assert w.isVisible() and (w.width(), w.height()) == (300, 240)
    assert not w.grab().isNull()  # runs paintEvent
    w.show_grid(GridSnapshot())
    assert not w.isVisible()
