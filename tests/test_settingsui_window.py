"""Headless test for the settings window's Qt shell.

Skipped when PySide6 isn't installed; uses the offscreen platform so it runs in
CI without a display. Covers the shell's own behaviour — staging a checkbox,
reverting a declined experimental confirmation, and (the part that used to fail
silently) what the window shows and does when a write does not land.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class _Recorder:
    def __init__(self, fail_on=None):
        self.writes: list[tuple] = []
        self._fail_on = fail_on

    def load(self):
        return Config()

    def write(self, section, key, value, quote):
        if self._fail_on == (section, key):
            raise OSError("Read-only file system")
        self.writes.append((section, key, value, quote))

    def probe(self, modules):
        return []


def _window(qapp, rec, *, confirm=True):
    controller = SettingsController(rec.load, rec.write, rec.probe)
    win = SettingsWindow(build_settings_model(Config()), controller)
    # Never open a real modal dialog in a test: either would block forever.
    warned: list[tuple[str, str]] = []
    win._confirm_experimental = lambda row: confirm  # type: ignore[method-assign]
    win._warn = lambda title, body: warned.append((title, body))  # type: ignore[method-assign]
    win.warned = warned  # type: ignore[attr-defined]
    return win


def test_window_builds_a_checkbox_for_every_feature_row(qapp):
    model = build_settings_model(Config())
    win = _window(qapp, _Recorder())
    assert len(win._checkboxes) == sum(len(g.rows) for g in model.groups)


def test_core_and_unwired_rows_are_shown_but_not_clickable(qapp):
    win = _window(qapp, _Recorder())
    assert win._checkboxes["dictation"].isEnabled() is False  # core
    assert win._checkboxes["reask"].isEnabled() is False  # designed, not wired
    assert win._checkboxes["streaming"].isEnabled() is True


def test_checking_a_box_stages_it_and_unchecking_unstages(qapp):
    win = _window(qapp, _Recorder())
    win._checkboxes["streaming"].setChecked(True)
    assert win._pending.items() == [("streaming", True)]
    win._checkboxes["streaming"].setChecked(False)
    assert win._pending.items() == []
    assert win._hint.text() == ""


def test_declining_an_experimental_confirmation_reverts_and_stages_nothing(qapp):
    win = _window(qapp, _Recorder(), confirm=False)
    win._checkboxes["cocktail"].setChecked(True)
    assert win._checkboxes["cocktail"].isChecked() is False
    assert win._pending.items() == []


def test_accepting_an_experimental_confirmation_stages_it(qapp):
    win = _window(qapp, _Recorder(), confirm=True)
    win._checkboxes["cocktail"].setChecked(True)
    assert win._checkboxes["cocktail"].isChecked() is True
    assert win._pending.items() == [("cocktail", True)]
    assert win._pending.is_confirmed("cocktail") is True


def test_apply_writes_the_staged_change_and_hints_at_the_restart(qapp):
    rec = _Recorder()
    win = _window(qapp, rec)
    win._checkboxes["streaming"].setChecked(True)
    win._on_apply()
    assert rec.writes == [("streaming", "enabled", "true", False)]
    assert "yazses restart" in win._hint.text()
    assert win.warned == []


def test_apply_with_nothing_staged_says_so(qapp):
    rec = _Recorder()
    win = _window(qapp, rec)
    win._on_apply()
    assert rec.writes == []
    assert win._hint.text() == "Nothing to apply."


def test_a_failed_write_is_surfaced_and_the_checkbox_is_not_left_lying(qapp):
    """The window used to report a failed Apply as a success and drop the change."""
    rec = _Recorder(fail_on=("streaming", "enabled"))
    win = _window(qapp, rec)
    win._checkboxes["streaming"].setChecked(True)

    win._on_apply()

    assert rec.writes == []
    assert "failed" in win._hint.text()
    assert "Applied" not in win._hint.text()
    assert win.warned and "Read-only file system" in win.warned[0][1]
    # Still staged, so Apply can be retried once the cause is fixed.
    assert win._pending.items() == [("streaming", True)]
    assert win._checkboxes["streaming"].isChecked() is True


def test_a_partly_failed_apply_reports_both_halves(qapp):
    rec = _Recorder(fail_on=("streaming", "enabled"))
    win = _window(qapp, rec)
    win._checkboxes["streaming"].setChecked(True)
    win._checkboxes["commands"].setChecked(False)

    win._on_apply()

    assert rec.writes == [("commands", "enabled", "false", False)]
    assert "Applied 1 change(s)" in win._hint.text()
    assert "1 change(s) failed" in win._hint.text()
    assert win._checkboxes["commands"].isChecked() is False
