"""The Windows tray greys out a Meeting Mode entry that cannot work, and says why.

Both entries used to be always clickable, on the stated grounds that a pystray menu
"is built once and cannot be re-derived per open". pystray re-evaluates a callable
``enabled``/``visible``/text whenever it rebuilds the menu, and ``update_menu()`` makes
it rebuild, so the Windows menu now follows the same `meeting_entries` the Linux tray
uses. The permanently greyed-out "Pause hotkey" placeholder is gone.

A stand-in `pystray` records the menu, so this runs where pystray is not installed.
"""

from __future__ import annotations

import sys
import types

import pytest

from yazses.platform.base import TrayModel, TrayState
from yazses.platform.windows import tray as win_tray
from yazses.tray.menu import MEETING_START_LABEL, MEETING_STOP_LABEL


class _Item:
    def __init__(self, text, action=None, enabled=True, visible=True, **_kw):
        self._text, self.action = text, action
        self._enabled, self._visible = enabled, visible

    # pystray resolves callables the same way: called with the item, when it builds.
    def _resolve(self, value):
        return value(self) if callable(value) else value

    @property
    def text(self):
        return self._resolve(self._text)

    @property
    def enabled(self):
        return self._resolve(self._enabled)

    @property
    def visible(self):
        return self._resolve(self._visible)


class _Menu:
    SEPARATOR = _Item("----")

    def __init__(self, *items):
        self.items = items


class _Icon:
    last = None

    def __init__(self, name, image, title, menu):
        self.menu, self.icon, self.title = menu, image, title
        self.menu_updates = 0
        _Icon.last = self

    def run(self, setup=None):
        pass  # the real one blocks on the message loop

    def update_menu(self):
        self.menu_updates += 1


@pytest.fixture
def tray(monkeypatch):
    fake = types.ModuleType("pystray")
    fake.Menu, fake.MenuItem, fake.Icon = _Menu, _Item, _Icon
    monkeypatch.setitem(sys.modules, "pystray", fake)
    monkeypatch.setattr(win_tray, "_make_icon", lambda colour: object())
    t = win_tray.WindowsTray()
    t.run(on_quit=lambda: None)
    # run() returned because the fake Icon.run does; put the icon back as if running.
    t._icon = _Icon.last
    return t


def _item(label):
    return next(i for i in _Icon.last.menu.items if i.text == label)


def _notice():
    first_meeting = next(
        n for n, i in enumerate(_Icon.last.menu.items) if i.text == MEETING_START_LABEL
    )
    return _Icon.last.menu.items[first_meeting - 1]


def test_the_pause_hotkey_placeholder_is_gone(tray):
    assert not any(i.text == "Pause hotkey" for i in _Icon.last.menu.items)


def test_idle_offers_start_and_greys_out_stop(tray):
    tray.set_state(TrayModel(state=TrayState.IDLE, meeting_enabled=True))
    assert _item(MEETING_START_LABEL).enabled is True
    assert _item(MEETING_STOP_LABEL).enabled is False


def test_a_running_meeting_offers_stop_only(tray):
    tray.set_state(TrayModel(state=TrayState.IDLE, meeting_enabled=True, meeting_active=True))
    assert _item(MEETING_START_LABEL).enabled is False
    assert _item(MEETING_STOP_LABEL).enabled is True


def test_meeting_mode_off_greys_out_both_and_says_why(tray):
    tray.set_state(TrayModel(state=TrayState.IDLE, meeting_enabled=False))
    assert not _item(MEETING_START_LABEL).enabled
    assert not _item(MEETING_STOP_LABEL).enabled
    note = _notice()
    assert note.visible and not note.enabled
    assert "Meeting Mode is off" in note.text


def test_the_note_is_hidden_when_there_is_nothing_to_explain(tray):
    tray.set_state(TrayModel(state=TrayState.IDLE, meeting_enabled=True))
    assert _notice().visible is False


def test_the_menu_is_rebuilt_only_when_the_entries_change(tray):
    icon = _Icon.last
    idle = TrayModel(state=TrayState.IDLE, meeting_enabled=True)
    tray.set_state(idle)
    before = icon.menu_updates
    for _ in range(20):  # the poller's steady state: four times a second
        tray.set_state(idle)
    assert icon.menu_updates == before
    tray.set_state(TrayModel(state=TrayState.IDLE, meeting_enabled=True, meeting_active=True))
    assert icon.menu_updates == before + 1


def test_a_failing_menu_rebuild_never_breaks_the_icon_update(tray):
    def boom():
        raise OSError("menu handle gone")

    _Icon.last.update_menu = boom
    tray.set_state(TrayModel(state=TrayState.IDLE, meeting_enabled=False))  # must not raise
