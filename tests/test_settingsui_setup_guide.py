"""The first-run setup guide inside the real settings window, headless, with no daemon."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QComboBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
)

from yazses.config import Config  # noqa: E402
from yazses.settingsui import setup_dialog  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402
from yazses.system import firstrun  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _same_default_key_everywhere(monkeypatch):
    monkeypatch.setattr(setup_dialog, "_platform_default", lambda: "right_alt")
    monkeypatch.setattr(setup_dialog, "_snap_warning", lambda: "")


class _Daemon:
    def __init__(self, **replies):
        self.replies = replies
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method, **params):
        self.calls.append((method, params))
        return self.replies.get(method)


def _now(key, fn, done):
    try:
        value = fn()
    except Exception:
        value = None
    done(value)
    return True


_OPEN: list = []


@pytest.fixture(autouse=True)
def _close_windows(qapp):
    """Destroy every window a test built, and stop its timers."""
    yield
    from PySide6.QtCore import QCoreApplication, QEvent

    while _OPEN:
        window = _OPEN.pop()
        guide = getattr(window, "_setup_dialog", None)
        if guide is not None:
            guide.timer.stop()
            guide.dialog.hide()
        window._page_timer.stop()
        window._level_timer.stop()
        window._win.hide()
        window._win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qapp.processEvents()


def _window(qapp, cfg=None, daemon=None):
    cfg = cfg or Config()
    writes: list[tuple] = []
    controller = SettingsController(lambda: cfg, lambda s, k, v, q: writes.append((s, k, v, q)),
                                    lambda modules: [])
    win = SettingsWindow(build_settings_model(cfg), controller)
    _OPEN.append(win)
    win._warn = lambda title, body: None  # type: ignore[method-assign]
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    daemon = daemon or _Daemon()
    ctx = win._page_context
    ctx.client_call = daemon
    ctx.run = _now
    ctx.daemon_running = lambda: False
    win.writes = writes  # type: ignore[attr-defined]
    win.daemon = daemon  # type: ignore[attr-defined]
    return win


def _status(**extra):
    return {"state": "idle", "ready": True, "model": "base.en", "silent_streak": 0,
            "silent_streak_threshold": 3, "hotkey": "right_alt", "vad_threshold": 0.01,
            **extra}


def _guide(win, step="welcome"):
    guide = setup_dialog.open_setup(win)
    guide.go(("welcome", "microphone", "key", "try").index(step))
    return guide


def _text(guide):
    return "\n".join(w.text() for w in guide.dialog.findChildren(QLabel))


# --- when it appears ----------------------------------------------------------------


def test_showing_the_window_does_not_open_the_guide_by_itself(qapp):
    win = _window(qapp)
    win.show()
    assert getattr(win, "_setup_dialog", None) is None


def test_the_overview_button_opens_it(qapp):
    win = _window(qapp)
    win._app_pages["overview"].setup_button.click()
    assert win._setup_dialog.is_open()
    assert win._setup_dialog.step == "welcome"


def test_only_one_guide_at_a_time(qapp):
    win = _window(qapp)
    first = setup_dialog.open_setup(win)
    assert setup_dialog.open_setup(win) is first


def test_it_can_be_reopened_after_it_is_closed(qapp):
    win = _window(qapp)
    first = _guide(win, "try")
    first.dialog.reject()
    again = setup_dialog.open_setup(win)
    assert again is not first and again.is_open() and again.step == "welcome"


def test_the_offer_opens_it_and_marks_it_seen(qapp, tmp_path):
    config = tmp_path / "config.toml"
    win = _window(qapp)
    guide = setup_dialog.offer_on_open(win, config)
    assert guide is not None and guide.is_open()
    assert firstrun.setup_marker_path(config).read_text(encoding="utf-8").strip() == "seen"


def test_a_window_opened_at_another_page_is_not_covered(qapp, tmp_path):
    config = tmp_path / "config.toml"
    win = _window(qapp)
    win._shell.select("audio")
    assert setup_dialog.offer_on_open(win, config) is None
    assert not firstrun.setup_marker_path(config).exists()
    setup_dialog.open_setup(win)        # asked for later: that counts as shown
    assert firstrun.setup_marker_path(config).exists()


# --- the frame ----------------------------------------------------------------------


def test_walking_through_every_step_writes_nothing(qapp):
    win = _window(qapp, daemon=_Daemon(status=_status()))
    guide = setup_dialog.open_setup(win)
    seen = [guide.step]
    for _ in range(3):
        guide.next_button.click()
        seen.append(guide.step)
    assert seen == ["welcome", "microphone", "key", "try"]
    assert guide.next_button.text() == "Finish"
    assert not guide.skip_button.isVisibleTo(guide.dialog)
    guide.next_button.click()
    assert not guide.is_open() and not guide.timer.isActive()
    assert not win.writes


def test_back_goes_back_and_is_hidden_on_the_first_step(qapp):
    win = _window(qapp)
    guide = setup_dialog.open_setup(win)
    assert not guide.back_button.isVisibleTo(guide.dialog)
    guide.next_button.click()
    guide.back_button.click()
    assert guide.step == "welcome"


@pytest.mark.parametrize("step", ("welcome", "microphone", "key", "try"))
def test_it_can_be_skipped_from_any_step(qapp, step):
    win = _window(qapp)
    guide = _guide(win, step)
    guide.dialog.reject()           # Esc and the close button end here, as Skip does
    assert not guide.is_open() and not guide.timer.isActive()
    assert not win.writes


def test_the_status_is_polled_only_on_the_steps_that_show_it(qapp):
    win = _window(qapp)
    guide = setup_dialog.open_setup(win)
    assert not guide.timer.isActive()
    guide.go(1)
    assert guide.timer.isActive()
    guide.go(2)
    assert not guide.timer.isActive()


# --- the microphone -----------------------------------------------------------------


def test_the_level_follows_a_hold_and_the_result_is_said(qapp):
    daemon = _Daemon(status=_status(state="recording", audio_level=0.05))
    win = _window(qapp, daemon=daemon)
    guide = _guide(win, "microphone")
    assert guide.level.value() > 0
    daemon.replies["status"] = _status()
    guide.refresh()
    assert guide.level.value() == 0
    assert "hears you" in _text(guide)


def test_without_a_daemon_it_offers_to_start_one(qapp):
    win = _window(qapp)
    started = []
    win._page_context.start_daemon = lambda: started.append(1) or (True, "")
    guide = _guide(win, "microphone")
    assert guide.mic_action.isVisibleTo(guide.dialog)
    assert not guide.recalibrate_button.isEnabled()
    guide.mic_action.click()
    assert started == [1]


def test_a_failed_start_keeps_its_reason_on_screen(qapp):
    win = _window(qapp)
    win._page_context.start_daemon = lambda: (False, "no model")
    guide = _guide(win, "microphone")
    guide.mic_action.click()
    guide.refresh()
    assert "no model" in _text(guide)
    assert guide.mic_action.isEnabled()


def test_recalibrating_calls_the_daemon_and_reports_the_new_threshold(qapp):
    daemon = _Daemon(status=_status(), recalibrate_mic={"ok": True, "started": True})
    win = _window(qapp, daemon=daemon)
    guide = _guide(win, "microphone")
    now = [0.0]
    guide.clock = lambda: now[0]
    guide.recalibrate_button.click()
    assert ("recalibrate_mic", {}) in daemon.calls
    assert "Stay quiet" in _text(guide)
    assert not guide.recalibrate_button.isEnabled()
    now[0] = 5.0
    guide.refresh()
    assert "Now speak" in _text(guide)
    now[0] = 30.0
    daemon.replies["status"] = _status(vad_threshold=0.004)
    guide.refresh()
    assert "0.004" in _text(guide)
    assert guide.recalibrate_button.isEnabled()


def test_a_refused_recalibration_shows_why(qapp):
    daemon = _Daemon(status=_status(), recalibrate_mic={"ok": False, "reason": "busy"})
    win = _window(qapp, daemon=daemon)
    guide = _guide(win, "microphone")
    guide.recalibrate_button.click()
    assert "busy" in _text(guide)
    guide.refresh()
    assert guide.recalibrate_button.isEnabled()


def test_choosing_another_microphone_closes_the_guide_on_the_audio_page(qapp):
    win = _window(qapp)
    guide = _guide(win, "microphone")
    guide.microphone_button.click()
    assert not guide.is_open()
    assert win._shell.current_key() == "audio"


# --- the key ------------------------------------------------------------------------


def test_a_new_key_is_saved_and_shown_on_the_general_page(qapp):
    win = _window(qapp)
    guide = _guide(win, "key")
    guide.key_box.setCurrentText("left_ctrl")
    assert guide.next_button.text() == "Save key and continue"
    guide.next_button.click()
    assert win.writes == [("hotkey", "key", "left_ctrl", True)]
    assert guide.step == "try"
    assert win._hotkey_box.currentText() == "left_ctrl"
    assert "general" not in win._dirty_pages()
    assert "restart" in win._hint.text()


def test_going_back_or_skipping_saves_nothing(qapp):
    win = _window(qapp)
    guide = _guide(win, "key")
    guide.key_box.setCurrentText("left_ctrl")
    guide.back_button.click()
    guide.skip_button.click()
    assert not win.writes


def test_a_refused_key_stays_on_the_step_and_says_why(qapp):
    cfg = Config()
    cfg.hotkey.command_key = "left_ctrl"
    win = _window(qapp, cfg)
    guide = _guide(win, "key")
    guide.key_box.setCurrentText("left_ctrl")
    guide.next_button.click()
    assert guide.step == "key"
    assert "command key" in _text(guide)
    assert not win.writes


# --- trying it ----------------------------------------------------------------------


def test_after_a_new_key_the_try_step_offers_a_restart(qapp):
    win = _window(qapp, daemon=_Daemon(status=_status()))
    restarted = []
    win._page_context.restart_daemon = lambda: restarted.append(1) or (True, "")
    guide = _guide(win, "key")
    guide.key_box.setCurrentText("left_ctrl")
    guide.next_button.click()
    assert guide.try_action.isVisibleTo(guide.dialog)
    assert "Left Ctrl" in _text(guide)
    guide.try_action.click()
    assert restarted == [1]


def test_no_second_restart_while_apply_is_restarting(qapp):
    win = _window(qapp)
    started = []
    win._page_context.start_daemon = lambda: started.append(1) or (True, "")
    win._restart_thread = object()
    guide = _guide(win, "try")
    guide.try_action.click()
    assert not started
    assert "already running" in _text(guide)
    win._restart_thread = None


def test_the_practice_box_counts_words_saves_nothing_and_is_emptied(qapp):
    win = _window(qapp, daemon=_Daemon(status=_status()))
    guide = _guide(win, "try")
    guide.practice.setPlainText("it types what I say")
    assert "5 words. It works." in _text(guide)
    assert not win.writes
    guide.next_button.click()
    assert guide.practice.toPlainText() == ""


def test_every_control_has_a_name(qapp):
    win = _window(qapp, daemon=_Daemon(status=_status()))
    guide = setup_dialog.open_setup(win)
    unnamed = []
    for index in range(4):
        guide.go(index)
        for kind in (QAbstractButton, QComboBox, QPlainTextEdit, QProgressBar):
            for widget in guide.dialog.findChildren(kind):
                if widget.objectName().startswith("qt_") or not widget.isVisibleTo(guide.dialog):
                    continue
                text = widget.text() if isinstance(widget, QAbstractButton) else ""
                if not (widget.accessibleName() or text):
                    unnamed.append((guide.step, kind.__name__))
    assert not unnamed
