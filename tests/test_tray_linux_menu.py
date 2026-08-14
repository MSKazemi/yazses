"""The Linux tray's About / Help / update handlers, driven without Qt.

``LinuxTray`` imports PySide6 lazily inside ``run()``, so the handlers can be exercised on
a bare instance with the controller and the signal bridge stubbed. What is worth pinning
here is the behaviour that is invisible until it goes wrong on a user's desktop: an update
check that blocks the GUI thread freezes the whole tray, and an install offered for a
``sudo`` command silently does nothing.
"""

from __future__ import annotations

import threading

from yazses.platform.linux.tray import LinuxTray
from yazses.system.updater import UpdateStatus


class _Sig:
    def __init__(self):
        self.emitted = []

    def emit(self, obj):
        self.emitted.append((obj, threading.current_thread().name))


class _Bridge:
    def __init__(self):
        self.update_ready = _Sig()
        self.notified = _Sig()


def _tray(controller):
    tray = LinuxTray()
    tray._controller = controller
    tray._bridge = _Bridge()
    return tray


# ---- the update check must not run on the GUI thread ------------------------


def test_the_update_check_runs_off_the_gui_thread():
    """A 5 s PyPI lookup on the Qt loop freezes the icon and the menu with it.

    Proven by blocking the check: the handler must have returned while the lookup is
    still in flight, and the result must arrive from a different thread.
    """
    started = threading.Event()
    release = threading.Event()

    class _Ctrl:
        def check_updates(self):
            started.set()
            release.wait(5)
            return "STATUS"

    tray = _tray(_Ctrl())
    caller = threading.current_thread().name

    tray._on_check_updates()

    assert started.wait(5), "the check never started"
    assert tray._bridge.update_ready.emitted == [], (
        "the handler waited for the check — that is the GUI thread frozen"
    )
    release.set()
    for _ in range(50):
        if tray._bridge.update_ready.emitted:
            break
        threading.Event().wait(0.02)
    (status, thread_name), = tray._bridge.update_ready.emitted
    assert status == "STATUS"
    assert thread_name != caller


def test_the_update_check_is_a_no_op_without_a_controller():
    tray = _tray(None)
    tray._on_check_updates()
    assert tray._bridge.update_ready.emitted == []


# ---- what the result dialog offers -----------------------------------------


def _capture_dialog(tray, accept: bool = False):
    seen = {}

    def _fake(title, text, *, rich=False, accept_label=None):
        seen.update(title=title, text=text, rich=rich, accept_label=accept_label)
        # Faithful to the real dialog: True means the accept button was clicked, and
        # there is no accept button unless one was asked for.
        return accept and accept_label is not None

    tray._dialog = _fake  # type: ignore[method-assign]
    return seen


def test_an_available_update_offers_to_install_it():
    installed = []

    class _Ctrl:
        def install_update(self, status):
            installed.append(status.command)
            return 0

    tray = _tray(_Ctrl())
    seen = _capture_dialog(tray, accept=True)
    status = UpdateStatus("uv", "1.0", "2.0", True, ["uv", "tool", "upgrade", "yazses"])

    tray._show_update_result(status)

    assert seen["accept_label"] == "Install now"
    for _ in range(50):
        if tray._bridge.notified.emitted:
            break
        threading.Event().wait(0.02)
    assert installed == [["uv", "tool", "upgrade", "yazses"]]
    (message, _thread), = tray._bridge.notified.emitted
    assert "Restart" in message[1]


def test_declining_the_offer_installs_nothing():
    class _Ctrl:
        def install_update(self, status):  # pragma: no cover - must not be reached
            raise AssertionError("installed without being asked")

    tray = _tray(_Ctrl())
    _capture_dialog(tray, accept=False)
    tray._show_update_result(
        UpdateStatus("uv", "1.0", "2.0", True, ["uv", "tool", "upgrade", "yazses"])
    )
    assert tray._bridge.notified.emitted == []


def test_a_snap_update_is_shown_but_not_offered():
    """``sudo snap refresh`` has no terminal to take a password from a tray click."""
    tray = _tray(object())
    seen = _capture_dialog(tray, accept=True)
    tray._show_update_result(
        UpdateStatus("snap", "1.0", "2.0", True, ["sudo", "snap", "refresh", "yazses"])
    )
    assert seen["accept_label"] is None
    assert "in a terminal" in seen["text"]


def test_being_up_to_date_offers_no_install_button():
    tray = _tray(object())
    seen = _capture_dialog(tray, accept=True)
    tray._show_update_result(UpdateStatus("uv", "2.0", "2.0", False, None))
    assert seen["accept_label"] is None
    assert "up to date" in seen["title"]


# ---- About and Help --------------------------------------------------------


def test_about_shows_the_version_as_rich_text():
    from yazses import branding

    tray = _tray(object())
    seen = _capture_dialog(tray)
    tray._on_about()
    assert seen["rich"] is True
    assert branding.version() in seen["text"]
    assert f'<a href="{branding.SOURCE}">' in seen["text"]


def test_a_help_link_that_cannot_open_tells_the_user_the_url():
    notes = []

    class _Ctrl:
        def open_url(self, url):
            return False

    tray = _tray(_Ctrl())
    tray._notify = lambda title, body: notes.append((title, body))  # type: ignore[method-assign]

    tray._on_open_url("https://example.test/docs")

    assert notes and "https://example.test/docs" in notes[0][1]


def test_a_help_link_that_opens_says_nothing():
    notes = []

    class _Ctrl:
        def open_url(self, url):
            return True

    tray = _tray(_Ctrl())
    tray._notify = lambda title, body: notes.append((title, body))  # type: ignore[method-assign]

    tray._on_open_url("https://example.test/docs")

    assert notes == []
