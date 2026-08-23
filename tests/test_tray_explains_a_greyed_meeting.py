"""The tray must be able to say *why* Meeting Mode is greyed out.

``MeetingEntry`` documents its own contract: ``reason`` is never None on a disabled
entry, because "a greyed-out entry with no explanation is worse than no entry at all".
The Linux tray honoured it by calling ``QAction.setToolTip`` -- and a ``QMenu`` renders
action tooltips only when ``toolTipsVisible`` is set, which nothing set. So the reason
was computed, attached, and never shown, in the state that is the *default* one
(Meeting Mode is off until you enable it).

Two halves are tested here because two things had to be true for a user to see it:
the tooltip has to be switched on, and -- for the desktops that render the tray menu
themselves rather than as a Qt widget -- the reason has to exist as a visible menu line.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from yazses.tray.menu import (  # noqa: E402
    MEETING_START_LABEL,
    MEETING_STOP_LABEL,
    MeetingEntry,
    meeting_entries,
    meeting_notice,
)

OFF = {"state": "idle", "meeting_enabled": False, "ready": True}
FINALIZING = {"state": "idle", "meeting_enabled": True, "meeting_finalizing": True, "ready": True}
LOADING = {"state": "idle", "meeting_enabled": True, "ready": False}
RUNNING = {"state": "meeting", "meeting_enabled": True, "meeting_active": True, "ready": True}
READY = {"state": "idle", "meeting_enabled": True, "ready": True}


# ---- the pure notice -----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        (OFF, "Meeting Mode is off"),
        (FINALIZING, "Still finishing the last meeting"),
        (LOADING, "still starting up"),
    ],
)
def test_a_wholly_greyed_meeting_menu_says_why(status, fragment):
    notice = meeting_notice(meeting_entries(status))
    assert notice is not None
    assert fragment in notice


def test_the_default_install_is_the_case_this_exists_for():
    """Meeting Mode is off by default, so this is what most users actually see."""
    entries = meeting_entries(OFF)
    assert [e.enabled for e in entries] == [False, False]
    notice = meeting_notice(entries)
    assert notice is not None
    # The notice must carry the reason itself, not a generic "unavailable".
    assert notice.endswith(entries[0].reason or "")


def test_no_notice_when_an_action_is_actually_available():
    """A banner over a working menu is noise."""
    assert meeting_notice(meeting_entries(READY)) is None
    assert meeting_notice(meeting_entries(RUNNING)) is None


def test_no_notice_while_any_action_still_works_even_if_the_reasons_agree():
    """Isolates the *enabled* guard.

    Every status `meeting_entries` can produce that leaves one action working also
    gives the two entries different reasons, so the shared-reason check alone made
    the whole function look correct -- removing the enabled guard broke no test.
    A banner saying why the menu is unusable, over a menu with a working button, is
    the failure this guards, so it is asserted directly rather than via a status.
    """
    same = "Meeting Mode is off."
    entries = [
        MeetingEntry(MEETING_START_LABEL, "meeting_start", True, same),
        MeetingEntry(MEETING_STOP_LABEL, "meeting_stop", False, same),
    ]
    assert meeting_notice(entries) is None


def test_no_notice_when_the_two_entries_are_greyed_for_different_reasons():
    """Then the greying is self-explanatory and one banner would misdescribe one of them."""
    entries = [
        MeetingEntry(MEETING_START_LABEL, "meeting_start", False, "YazSes is busy."),
        MeetingEntry(MEETING_STOP_LABEL, "meeting_stop", False, "No meeting is running."),
    ]
    assert meeting_notice(entries) is None


def test_a_disabled_entry_with_no_reason_produces_no_notice():
    """Rather than a line that says nothing. Guards the contract's own edge."""
    entries = [
        MeetingEntry(MEETING_START_LABEL, "meeting_start", False, None),
        MeetingEntry(MEETING_STOP_LABEL, "meeting_stop", False, None),
    ]
    assert meeting_notice(entries) is None


def test_notice_never_raises_on_a_short_or_empty_list():
    assert meeting_notice([]) is None
    assert meeting_notice([MeetingEntry(MEETING_START_LABEL, "meeting_start", False, "x")]) is None


# ---- the Qt menu the user actually clicks ---------------------------------------


class _FakeController:
    def __init__(self, status: dict) -> None:
        self._status = status

    def status(self) -> dict:
        return dict(self._status)

    def list_devices(self):
        return []


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def _menu(status: dict):
    """Build the real Linux tray menu offscreen.

    Bind the result to a name before touching its actions. A ``QAction`` does not keep
    its ``QMenu`` alive, so ``_menu(...).actions()`` frees the menu the moment the
    expression ends and every action with it -- shiboken then raises "Internal C++
    object already deleted" from what looks like a perfectly ordinary read.
    """
    from PySide6.QtWidgets import QMenu

    from yazses.platform.linux.tray import LinuxTray

    tray = LinuxTray()
    tray._controller = _FakeController(status)
    menu = QMenu()
    tray._populate_menu(menu)
    return menu


def _labels(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_the_menu_switches_action_tooltips_on(qapp):
    """Without this the reason attached below is attached to nothing a user can see."""
    menu = _menu(OFF)
    assert menu.toolTipsVisible() is True


def test_the_reason_is_readable_without_hovering(qapp):
    """A desktop that renders the tray menu itself never shows a Qt tooltip."""
    menu = _menu(OFF)
    labels = _labels(menu)
    assert any("Meeting Mode is off" in text for text in labels), labels


def test_the_greyed_entries_still_carry_their_reason_as_a_tooltip(qapp):
    menu = _menu(OFF)
    acts = {a.text(): a for a in menu.actions()}
    for label in (MEETING_START_LABEL, MEETING_STOP_LABEL):
        assert acts[label].isEnabled() is False
        assert acts[label].toolTip()


def test_a_working_meeting_menu_gets_no_banner(qapp):
    menu = _menu(READY)
    labels = _labels(menu)
    assert MEETING_START_LABEL in labels
    assert not any(text.startswith("ⓘ") for text in labels), labels
