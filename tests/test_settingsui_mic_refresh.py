"""Settings > Audio: a "Refresh" control re-lists microphones plugged in after the window opened.

Synthetic and offscreen: ``list_input_devices`` is patched to return different lists on
successive calls. No PortAudio, no real hotplug, no hardware is involved.

Skipped when PySide6 is not installed.
"""

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _dev(name):
    return SimpleNamespace(name=name)


class _Enumerator:
    """Stands in for list_input_devices; each call pops the next scripted result."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return result


def _window(qapp, monkeypatch, enumerator, *, pinned=""):
    monkeypatch.setattr("yazses.audio.devices.list_input_devices", enumerator)
    monkeypatch.setattr("yazses.audio.devices.current_default_input_name", lambda: "Built-in")
    cfg = Config()
    cfg.audio.device = pinned
    controller = SettingsController(Config, lambda *a: None, lambda modules: [])
    win = SettingsWindow(build_settings_model(cfg), controller)
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    win._level_timer.stop()
    return win


def _values(win):
    box = win._mic_box
    return [box.itemData(i) for i in range(box.count())]


def _refresh_button(win):
    return next(
        b for b in win._win.findChildren(QPushButton) if b.accessibleName() == "Refresh microphones"
    )


def test_refresh_lists_a_microphone_plugged_in_after_opening(qapp, monkeypatch):
    enum = _Enumerator([_dev("Built-in")], [_dev("Built-in"), _dev("USB Mic")])
    win = _window(qapp, monkeypatch, enum)
    assert "USB Mic" not in _values(win)
    _refresh_button(win).click()
    assert "USB Mic" in _values(win)
    assert enum.calls == 2


def test_refresh_keeps_selection_and_does_not_dirty_the_page(qapp, monkeypatch):
    enum = _Enumerator([_dev("Built-in"), _dev("USB Mic")], [_dev("USB Mic"), _dev("Built-in")])
    win = _window(qapp, monkeypatch, enum, pinned="USB Mic")
    assert win._mic_box.currentData() == "USB Mic"
    _refresh_button(win).click()
    assert win._mic_box.currentData() == "USB Mic"
    assert win._mic_box.currentData() == win._mic_baseline  # nothing staged


def test_refresh_keeps_a_staged_choice_selected(qapp, monkeypatch):
    enum = _Enumerator([_dev("Built-in"), _dev("USB Mic")], [_dev("Built-in"), _dev("USB Mic")])
    win = _window(qapp, monkeypatch, enum)
    win._mic_box.setCurrentIndex(_values(win).index("USB Mic"))
    _refresh_button(win).click()
    assert win._mic_box.currentData() == "USB Mic"
    assert win._mic_baseline == ""  # still unsaved: refresh never changes the pin


def test_a_pinned_device_that_is_now_absent_stays_visible_and_selected(qapp, monkeypatch):
    enum = _Enumerator([_dev("Built-in"), _dev("USB Mic")], [_dev("Built-in")])
    win = _window(qapp, monkeypatch, enum, pinned="USB Mic")
    _refresh_button(win).click()
    assert win._mic_box.currentData() == "USB Mic"
    assert "not connected" in win._mic_box.currentText()


def test_an_exception_while_enumerating_leaves_the_list_unchanged(qapp, monkeypatch):
    enum = _Enumerator([_dev("Built-in"), _dev("USB Mic")], OSError("no sound card"))
    win = _window(qapp, monkeypatch, enum)
    before = _values(win)
    _refresh_button(win).click()
    assert _values(win) == before
    assert "previous list is kept" in win._hint.text()


def test_an_empty_result_is_a_failed_refresh_not_a_wipe(qapp, monkeypatch):
    # The real list_input_devices returns [] when PortAudio's query fails; it never raises.
    enum = _Enumerator([_dev("Built-in"), _dev("USB Mic")], [])
    win = _window(qapp, monkeypatch, enum, pinned="USB Mic")
    before_values = _values(win)
    before_labels = [win._mic_box.itemText(i) for i in range(win._mic_box.count())]
    assert win._mic_box.currentData() == "USB Mic"
    _refresh_button(win).click()
    assert _values(win) == before_values
    assert [win._mic_box.itemText(i) for i in range(win._mic_box.count())] == before_labels
    assert win._mic_box.currentData() == "USB Mic"
    assert "previous list is kept" in win._hint.text()


def test_a_later_good_refresh_clears_the_failure_hint(qapp, monkeypatch):
    enum = _Enumerator([_dev("Built-in")], [], [_dev("Built-in"), _dev("USB Mic")])
    win = _window(qapp, monkeypatch, enum)
    _refresh_button(win).click()
    assert win._hint.text()
    _refresh_button(win).click()
    assert win._hint.text() == ""
    assert "USB Mic" in _values(win)


def test_a_changed_non_empty_list_replaces_the_old_one(qapp, monkeypatch):
    enum = _Enumerator([_dev("Built-in"), _dev("Old Mic")], [_dev("Built-in"), _dev("New Mic")])
    win = _window(qapp, monkeypatch, enum)
    _refresh_button(win).click()
    values = _values(win)
    assert "New Mic" in values
    assert "Old Mic" not in values


def test_the_star_follows_the_saved_pin_not_the_staged_choice(qapp, monkeypatch):
    enum = _Enumerator([_dev("Built-in"), _dev("USB Mic"), _dev("Other")])
    win = _window(qapp, monkeypatch, enum, pinned="USB Mic")
    win._mic_box.setCurrentIndex(_values(win).index("Other"))  # staged, unsaved
    _refresh_button(win).click()
    box = win._mic_box
    assert box.currentData() == "Other"
    assert win._mic_baseline == "USB Mic"
    text = {box.itemData(i): box.itemText(i) for i in range(box.count())}
    assert "\u2605" in text["USB Mic"]
    assert "\u2605" not in text["Other"]


def test_a_staged_choice_whose_device_vanished_stays_selected(qapp, monkeypatch):
    enum = _Enumerator([_dev("Built-in"), _dev("USB Mic")], [_dev("Built-in")])
    win = _window(qapp, monkeypatch, enum)
    win._mic_box.setCurrentIndex(_values(win).index("USB Mic"))
    _refresh_button(win).click()
    assert win._mic_box.currentData() == "USB Mic"
    assert "not connected" in win._mic_box.currentText()
    assert win._mic_baseline == ""
