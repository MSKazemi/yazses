"""The Linux tray menu says what the other trays say, and never invents "idle".

The macOS menu shows `status_lines` (the daemon's error, an engine fallback, a silent
streak) and the icon tooltip shows the "no text field focused" warning. The Linux menu
used to read only the silent streak, so a daemon in ``error`` showed a header of "error"
and no reason, and an unreachable daemon (``ctrl.status() == {}``) showed "idle" with
Start meeting enabled.

Offscreen Qt, structural assertions only: which disabled lines exist, and whether an
action is enabled. No pixels and no timing.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from yazses.platform.linux.tray import LinuxTray  # noqa: E402
from yazses.stt.factory import fallback_phrase  # noqa: E402
from yazses.tray.menu import (  # noqa: E402
    MEETING_START_LABEL,
    NO_TARGET_WARNING,
    icon_spec,
    top_warning,
)

_ENGINE = {"engine": "faster-whisper", "engine_model": "base.en", "model": "base.en"}
_FALLBACK = {"from": "parakeet", "reason": "it failed to load (RuntimeError)"}


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class _Ctl:
    def __init__(self, status: dict) -> None:
        self._status = status

    def status(self) -> dict:
        return dict(self._status)

    def list_devices(self) -> list:
        return []


def _menu(qapp, fresh: dict, latest: dict | None = None) -> QMenu:
    tray = LinuxTray()
    tray._controller = _Ctl(fresh)  # type: ignore[assignment]
    tray._latest = dict(latest or {})
    menu = QMenu()
    tray._populate_menu(menu)
    return menu


def _texts(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _disabled_texts(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator() and not a.isEnabled()]


def _action(menu: QMenu, text: str):
    (found,) = [a for a in menu.actions() if a.text() == text]
    return found


def test_an_error_state_shows_its_reason_as_a_disabled_line(qapp):
    status = {"state": "error", "last_error": "Could not load the speech model 'x'"}
    warning = top_warning(status)
    assert warning is not None
    assert warning in _disabled_texts(_menu(qapp, status))


def test_an_engine_fallback_is_shown_as_a_disabled_line(qapp):
    status = {"state": "idle", **_ENGINE, "engine_fallback": _FALLBACK}
    phrase = fallback_phrase(status)
    assert phrase is not None
    warning = top_warning(status)
    assert warning is not None and "parakeet" in warning  # cut to one line, so not whole
    assert warning in _disabled_texts(_menu(qapp, status))


def test_dictating_with_no_text_target_is_shown_as_a_disabled_line(qapp):
    status = {"state": "recording", "target_ok": False}
    assert NO_TARGET_WARNING in _disabled_texts(_menu(qapp, status))
    # The tooltip and the menu use one wording, from one rule.
    assert NO_TARGET_WARNING in icon_spec(status)[1]


def test_a_healthy_menu_carries_no_warning_lines(qapp):
    for status in (
        {"state": "idle", **_ENGINE},
        {"state": "recording", "target_ok": True},
        {"state": "recording", "target_ok": None},
        {"state": "recording", "target_ok": False, "command_mode": True},
    ):
        menu = _menu(qapp, status)
        assert not [t for t in _disabled_texts(menu) if t.startswith("⚠")], status


def test_an_unreachable_daemon_is_not_shown_as_idle(qapp):
    # What the poller leaves behind once the daemon stops answering.
    latest = {"state": "error", "last_error": "The daemon is not running."}
    menu = _menu(qapp, {}, latest)
    texts = _texts(menu)
    assert not any("idle" in t for t in texts), texts
    assert any("error" in t for t in texts)
    assert "⚠ The daemon is not running." in _disabled_texts(menu)
    assert not _action(menu, MEETING_START_LABEL).isEnabled()


def test_a_fresh_reading_wins_over_what_the_poller_remembered(qapp):
    latest = {"state": "error", "last_error": "old trouble"}
    menu = _menu(qapp, {"state": "idle", "last_error": None, **_ENGINE}, latest)
    assert any("idle" in t for t in _texts(menu))
    assert not [t for t in _disabled_texts(menu) if "old trouble" in t]
