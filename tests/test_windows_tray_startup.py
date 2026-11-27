"""Windows tray: early messages are kept, and an unchanged icon is left alone.

Found by reading the code (and pystray's Win32 backend), not observed on Windows;
``pystray`` is a stand-in, so this runs on any OS. The poller starts before the icon
exists and its first ``status`` read takes the daemon's notification queue.
"""

from __future__ import annotations

import sys
import types

import pytest

from yazses.platform.base import TrayModel, TrayState
from yazses.platform.windows import tray as win_tray

# ---- Tray: early messages, unchanged icon ----------------------------------


class _Item:
    def __init__(self, *args, **kwargs):
        pass


class _Menu(_Item):
    SEPARATOR = None


class _Icon:
    """pystray's Win32 icon: a balloon changes an icon that must already be shown."""

    last: _Icon

    def __init__(self, name, image, title, menu):
        self._image, self.title, self.visible = image, title, False
        self.assigned: list[str] = []
        self.balloons: list[tuple[str, str]] = []
        self.before_setup = None
        self.fail_next_assignment = False
        _Icon.last = self

    @property
    def icon(self):
        return self._image

    @icon.setter
    def icon(self, value):
        if self.fail_next_assignment:
            self.fail_next_assignment = False
            raise OSError("Shell_NotifyIcon failed")
        self._image = value
        self.assigned.append(value)

    def notify(self, body, title):
        if not self.visible:
            raise OSError("Shell_NotifyIcon: no such icon")
        self.balloons.append((title, body))

    def update_menu(self):
        pass

    def run(self, setup=None):
        if _Icon.during_startup is not None:
            _Icon.during_startup()
        setup(self)

    during_startup = None


@pytest.fixture
def tray(monkeypatch):
    fake = types.ModuleType("pystray")
    fake.Menu, fake.MenuItem, fake.Icon = _Menu, _Item, _Icon
    monkeypatch.setitem(sys.modules, "pystray", fake)
    monkeypatch.setattr(win_tray, "_make_icon", lambda colour: colour)
    monkeypatch.setattr(win_tray, "pending_update_report", lambda launcher: None)
    monkeypatch.setattr(_Icon, "during_startup", None)
    return win_tray.WindowsTray()


def test_messages_read_before_the_icon_exists_are_shown_once_it_does(tray, monkeypatch):
    tray.notify("first", "read before run()")
    monkeypatch.setattr(
        _Icon, "during_startup", lambda: tray.notify("second", "icon built, not yet shown")
    )
    tray.run(on_quit=lambda: None)
    tray.notify("third", "icon on screen")

    assert [title for title, _ in _Icon.last.balloons] == ["first", "second", "third"]


def test_the_early_queue_is_bounded_and_keeps_the_newest(tray):
    for n in range(win_tray._EARLY_NOTICES_MAX + 3):
        tray.notify(str(n), "body")
    tray.run(on_quit=lambda: None)

    shown = [title for title, _ in _Icon.last.balloons]
    assert shown == [str(n) for n in range(3, win_tray._EARLY_NOTICES_MAX + 3)]


def test_an_unchanged_state_does_not_rewrite_the_icon(tray):
    tray.run(on_quit=lambda: None)
    icon = _Icon.last
    for _ in range(20):  # the poller's steady state
        tray.set_state(TrayModel(state=TrayState.IDLE))
    assert icon.assigned == []

    for _ in range(5):
        tray.set_state(TrayModel(state=TrayState.RECORDING))
    tray.set_state(TrayModel(state=TrayState.IDLE))
    assert len(icon.assigned) == 2


def test_the_tooltip_still_follows_a_change_that_keeps_the_colour(tray):
    tray.run(on_quit=lambda: None)
    tray.set_state(TrayModel(state=TrayState.IDLE, input_device="Yeti"))
    tray.set_state(TrayModel(state=TrayState.IDLE, input_device="Headset"))

    assert "Headset" in _Icon.last.title
    assert _Icon.last.assigned == []


def test_a_failed_icon_change_is_tried_again(tray):
    tray.run(on_quit=lambda: None)
    icon = _Icon.last
    icon.fail_next_assignment = True
    tray.set_state(TrayModel(state=TrayState.RECORDING))
    assert icon.assigned == []

    tray.set_state(TrayModel(state=TrayState.RECORDING))
    assert len(icon.assigned) == 1
