"""Closing Settings with unapplied changes asks first: Apply, Discard or Cancel.

Every change in the window is staged until Apply writes it, and the sidebar marks the
pages holding one. Closing the window used to drop all of it without a word. These tests
drive the REAL window offscreen (synthetic, ``QT_QPA_PLATFORM=offscreen``), with the
modal prompt replaced by a recorder so nothing blocks; the prompt itself is built and
inspected without being shown. None of this is a physical-desktop result.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _window(qapp, answer: str = "cancel"):
    writes: list[tuple] = []
    controller = SettingsController(
        Config, lambda s, k, v, q: writes.append((s, k, v, q)), lambda modules: []
    )
    win = SettingsWindow(build_settings_model(Config()), controller)
    # No real modal dialog and no host daemon: either would hang a headless run.
    win._confirm_experimental = lambda row: True  # type: ignore[method-assign]
    win._warn = lambda title, body: None  # type: ignore[method-assign]
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    win._confirm_restart = lambda: False  # type: ignore[method-assign]
    asked: list[frozenset[str]] = []

    def _ask(pages):
        asked.append(frozenset(pages))
        return answer

    win._ask_unsaved_close = _ask  # type: ignore[method-assign]
    win.writes = writes  # type: ignore[attr-defined]
    win.asked = asked  # type: ignore[attr-defined]
    win._win.show()
    qapp.processEvents()
    return win


def _force_close(win) -> None:
    win._ask_unsaved_close = lambda pages: "discard"  # type: ignore[method-assign]
    win._win.close()


def test_closing_with_nothing_staged_does_not_ask(qapp):
    win = _window(qapp)
    assert win._win.close() is True
    assert win.asked == []


def test_cancel_keeps_the_window_and_the_staged_change(qapp):
    win = _window(qapp, "cancel")
    win._checkboxes["streaming"].setChecked(True)
    assert win._win.close() is False
    assert win._win.isVisible()
    assert win.asked == [frozenset({"features"})]
    assert len(win._pending) == 1
    assert win.writes == []
    _force_close(win)


def test_discard_closes_without_writing_anything(qapp):
    win = _window(qapp, "discard")
    win._checkboxes["streaming"].setChecked(True)
    assert win._win.close() is True
    assert len(win.asked) == 1
    assert win.writes == []


def test_apply_writes_the_staged_change_then_closes(qapp):
    win = _window(qapp, "apply")
    win._checkboxes["streaming"].setChecked(True)
    assert win._win.close() is True
    assert len(win.asked) == 1
    assert win.writes, "Apply from the close prompt must write the staged change"
    assert len(win._pending) == 0


def test_a_moved_form_control_counts_as_unapplied(qapp):
    win = _window(qapp, "cancel")
    win._vad_slider.setValue(win._vad_baseline_pos + 5)
    assert win._win.close() is False
    assert win.asked == [frozenset({"audio"})]
    _force_close(win)


def test_mid_restart_the_close_is_refused_without_the_prompt(qapp):
    win = _window(qapp, "discard")
    win._checkboxes["streaming"].setChecked(True)
    win._restart_thread = object()  # a restart in flight; nothing here runs it
    try:
        assert win._win.close() is False
        assert win.asked == [], "the restart guard comes first; no prompt over it"
        assert "Restarting" in win._hint.text()
    finally:
        win._restart_thread = None
    _force_close(win)


def test_a_hidden_window_closes_without_a_prompt(qapp):
    """Nobody can answer a dialog over a window that is not on screen."""
    win = _window(qapp, "cancel")
    win._checkboxes["streaming"].setChecked(True)
    win._win.hide()
    assert win._win.close() is True
    assert win.asked == []


def test_the_prompt_offers_apply_discard_cancel_and_defaults_to_cancel(qapp):
    win = _window(qapp)
    box = win._unsaved_close_box(frozenset({"features", "audio"}))
    try:
        buttons = box.standardButtons()
        sb = QMessageBox.StandardButton
        for wanted in (sb.Apply, sb.Discard, sb.Cancel):
            assert buttons & wanted, f"missing {wanted}"
        assert box.defaultButton() is box.button(sb.Cancel)
        assert box.escapeButton() is box.button(sb.Cancel)
        assert box.isModal()
    finally:
        box.deleteLater()
    win._win.close()
