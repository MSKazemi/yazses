"""The app pages inside the real settings window, headless, with no daemon.

Everything that would reach outside the process (IPC, subprocesses, dialogs, the file
manager) is replaced, so these hold what each page *does* with a reply.
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui import pages  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


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


#: Windows built by the current test, destroyed when it ends.
_OPEN: list = []
#: Every Qt window this file has built, kept to check that the destroyed ones are gone.
_BUILT: list = []


@pytest.fixture(autouse=True)
def _close_windows(qapp):
    """Destroy every window a test built.

    A window left alive keeps its polling timers, and a later theme change repaints all of
    them, so each test ran slower than the one before: the GUI job passed its time limit.
    """
    yield
    from PySide6.QtCore import QCoreApplication, QEvent

    while _OPEN:
        window = _OPEN.pop()
        window._page_timer.stop()
        window._level_timer.stop()
        window._win.hide()
        window._win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qapp.processEvents()


def _window(qapp, cfg=None, daemon=None, *, confirm=True):
    cfg = cfg or Config()
    writes: list[tuple] = []
    controller = SettingsController(lambda: cfg, lambda s, k, v, q: writes.append((s, k, v, q)),
                                    lambda modules: [])
    win = SettingsWindow(build_settings_model(cfg), controller)
    _OPEN.append(win)
    _BUILT.append(win._win)
    win._confirm_experimental = lambda row: confirm  # type: ignore[method-assign]
    win._confirm_reset = lambda diff, labels: True  # type: ignore[method-assign]
    win._warn = lambda title, body: None  # type: ignore[method-assign]
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    win._confirm_restart = lambda: False  # type: ignore[method-assign]
    daemon = daemon or _Daemon()
    ctx = win._page_context
    ctx.client_call = daemon
    ctx.run = _now
    ctx.daemon_running = lambda: False
    win.writes = writes  # type: ignore[attr-defined]
    win.daemon = daemon  # type: ignore[attr-defined]
    return win


def _text(widget):
    parts = [w.text() for w in widget.findChildren(QLabel)]
    parts += [w.text() for w in widget.findChildren(QPushButton)]
    return "\n".join(parts)


def _status(**extra):
    return {"state": "idle", "ready": True, "model": "base.en", "silent_streak": 0,
            "silent_streak_threshold": 3, "hotkey": "right_alt", **extra}


# --- the frame ----------------------------------------------------------------------


def test_the_window_opens_on_the_overview(qapp):
    win = _window(qapp)
    assert win._shell.current_key() == "overview"


def test_every_page_in_the_list_builds_without_a_daemon(qapp):
    win = _window(qapp)
    for spec in pages.PAGES:
        win._shell.select(spec.key)
        win._refresh_current_page()
    assert win._shell.stack.count() == len(pages.PAGES)


# --- overview -----------------------------------------------------------------------


def test_the_overview_says_when_yazses_is_not_running_and_offers_to_start(qapp):
    win = _window(qapp)
    started = []
    win._page_context.start_daemon = lambda: started.append(1) or (True, "")
    page = win._app_pages["overview"]
    page.refresh()
    assert "not running" in _text(page.widget)
    assert page.action_button.isVisibleTo(page.widget)
    page.action_button.click()
    assert started == [1]


def test_a_failed_start_shows_why(qapp):
    win = _window(qapp)
    win._page_context.start_daemon = lambda: (False, "port already taken")
    page = win._app_pages["overview"]
    page.refresh()
    page.action_button.click()
    assert "port already taken" in _text(page.widget)


def test_recalibrate_calls_the_daemon(qapp):
    daemon = _Daemon(status=_status(silent_streak=4), recalibrate_mic={"ok": True})
    win = _window(qapp, daemon=daemon)
    page = win._app_pages["overview"]
    page.refresh()
    page.action_button.click()
    assert ("recalibrate_mic", {}) in daemon.calls


def test_a_ready_daemon_hides_the_action(qapp):
    win = _window(qapp, daemon=_Daemon(status=_status()))
    page = win._app_pages["overview"]
    page.refresh()
    assert "Ready to dictate" in _text(page.widget)
    assert not page.action_button.isVisibleTo(page.widget)


# --- switch cards -------------------------------------------------------------------


def _button(win, page, slug):
    return win._switches.buttons(slug, within=win._app_pages[page].widget)[0]


def test_a_card_switch_stages_the_same_change_as_the_features_box(qapp):
    win = _window(qapp)
    button = _button(win, "dictation", "voice-punctuation")
    button.click()
    assert win._checkboxes["voice-punctuation"].isChecked()
    assert ("voice-punctuation", True) in win._pending.items()
    assert button.text() == "On"


def test_the_features_box_moves_the_card(qapp):
    win = _window(qapp)
    button = _button(win, "dictation", "voice-punctuation")
    win._checkboxes["voice-punctuation"].setChecked(True)
    assert button.isChecked()


def test_declining_an_experimental_switch_leaves_the_card_off(qapp):
    win = _window(qapp, confirm=False)
    slug = next(s for s, r in win._rows.items()
                if r.experimental and r.toggleable and win._switches.buttons(s))
    button = win._switches.buttons(slug)[0]
    button.click()
    assert not button.isChecked()
    assert not len(win._pending)


def test_restore_defaults_resets_the_cards(qapp):
    win = _window(qapp)
    button = _button(win, "dictation", "voice-punctuation")
    button.click()
    win._on_restore_defaults()
    assert not button.isChecked()


def test_the_accessibility_page_has_a_card_for_each_capability_in_its_category(qapp):
    win = _window(qapp)
    group = next(g for g in win._model.groups if g.category.startswith("Accessibility"))
    page = win._app_pages["accessibility"].widget
    for row in group.rows:
        assert win._switches.buttons(row.slug, within=page), row.slug


# --- dictation ----------------------------------------------------------------------


def test_the_practice_box_counts_words_and_is_never_written_anywhere(qapp):
    win = _window(qapp)
    page = win._app_pages["dictation"]
    page.practice.setPlainText("one two three")
    assert "3 words" in _text(page.widget)
    assert not win.writes


def test_the_level_bar_follows_the_daemon_only_while_recording(qapp):
    daemon = _Daemon(status=_status(state="recording", audio_level=0.02, vad_threshold=0.01))
    win = _window(qapp, daemon=daemon)
    page = win._app_pages["dictation"]
    page.refresh()
    assert page.level.value() > 0
    daemon.replies["status"] = _status(audio_level=0.0)
    page.refresh()
    assert page.level.value() == 0


# --- meetings -----------------------------------------------------------------------


def _meeting_dir(root):
    folder = root / "20261126-100000"
    folder.mkdir(parents=True)
    (folder / "meeting.json").write_text(
        json.dumps({"id": folder.name, "status": "done", "duration_s": 60}), encoding="utf-8")
    utterance = {"speaker": "speaker_0", "start": 0.0, "end": 1.0, "text": "Hello all."}
    (folder / "transcript.json").write_text(json.dumps({
        "text": "Hello all.", "language": "en", "diarized": True,
        "utterances": [utterance], "words": [utterance],
        "speakers": {"speaker_0": "Speaker 1"}}), encoding="utf-8")
    return folder


def _meeting_config(tmp_path, *, enabled=True):
    cfg = Config()
    cfg.meeting.enabled = enabled
    cfg.meeting.output_dir = str(tmp_path / "meetings")
    return cfg


def test_stored_meetings_are_listed_and_open_their_transcript(qapp, tmp_path):
    _meeting_dir(tmp_path / "meetings")
    win = _window(qapp, _meeting_config(tmp_path))
    page = win._app_pages["meetings"]
    page.refresh()
    assert page.list.count() == 1
    page.list.setCurrentRow(0)
    assert "Hello all." in page.transcript.toPlainText()


def test_renaming_a_speaker_updates_the_transcript(qapp, tmp_path):
    _meeting_dir(tmp_path / "meetings")
    win = _window(qapp, _meeting_config(tmp_path))
    page = win._app_pages["meetings"]
    page.refresh()
    page.list.setCurrentRow(0)
    page.name_fields["speaker_0"].setText("Alice")
    page.rename_button.click()
    assert "Alice" in page.transcript.toPlainText()


def test_start_sends_the_speaker_count_and_shows_a_refusal_verbatim(qapp, tmp_path):
    daemon = _Daemon(meeting_start={"ok": False, "reason": "no microphone"},
                     meeting_status={"ok": True, "enabled": True, "active": False})
    win = _window(qapp, _meeting_config(tmp_path), daemon)
    page = win._app_pages["meetings"]
    page.refresh()
    page.people.setValue(3)
    page.record_button.click()
    assert ("meeting_start", {"speakers": 3, "wait_s": 60.0}) in daemon.calls
    assert "no microphone" in _text(page.widget)


def test_a_running_meeting_offers_only_stop_and_shows_the_draft(qapp, tmp_path):
    daemon = _Daemon(meeting_status={"ok": True, "enabled": True, "active": True,
                                     "elapsed_s": 61, "live_lines": ["draft line"]},
                     meeting_stop={"ok": True})
    win = _window(qapp, _meeting_config(tmp_path), daemon)
    page = win._app_pages["meetings"]
    page.refresh()
    assert page.record_button.text() == "Stop meeting"
    assert "00:01:01" in _text(page.widget)
    assert "draft line" in page.transcript.toPlainText()
    page.record_button.click()
    assert any(call[0] == "meeting_stop" for call in daemon.calls)


def test_meeting_mode_off_offers_to_turn_it_on_instead_of_recording(qapp, tmp_path):
    win = _window(qapp, _meeting_config(tmp_path, enabled=False))
    page = win._app_pages["meetings"]
    page.refresh()
    assert not page.record_button.isEnabled()
    assert win._switches.buttons("meeting", within=page.widget)


# --- file transcription -------------------------------------------------------------


class _Process:
    def __init__(self):
        self.started: list[list[str]] = []
        self.killed = False
        self.done = None

    def start(self, argv, done):
        self.started.append(argv)
        self.done = done

    def kill(self):
        self.killed = True


def _files(qapp, tmp_path):
    win = _window(qapp)
    page = win._app_pages["files"]
    page.process_factory = _Process
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"x")
    page.choose(source)
    return win, page, source


def test_transcribe_runs_the_command_and_shows_the_result(qapp, tmp_path):
    _win, page, source = _files(qapp, tmp_path)
    page.run_button.click()
    process = page.process
    assert str(source) in process.started[0]
    source.with_suffix(".txt").write_text("the words", encoding="utf-8")
    process.done(0, "")
    assert "the words" in page.result.toPlainText()
    assert page.history.count() == 1
    assert page.process is None


def test_the_session_list_appears_only_once_it_has_something(qapp, tmp_path):
    _win, page, source = _files(qapp, tmp_path)
    assert not page.history.isVisibleTo(page.widget)
    page.run_button.click()
    source.with_suffix(".txt").write_text("words", encoding="utf-8")
    page.process.done(0, "")
    assert page.history.isVisibleTo(page.widget)


def test_a_failure_shows_what_the_command_said(qapp, tmp_path):
    _win, page, _source = _files(qapp, tmp_path)
    page.run_button.click()
    page.process.done(1, "Unknown --model 'x'.")
    assert "Unknown --model" in page.result.toPlainText()
    assert page.history.count() == 0


def test_an_existing_output_is_not_overwritten_without_asking(qapp, tmp_path):
    _win, page, source = _files(qapp, tmp_path)
    source.with_suffix(".txt").write_text("old", encoding="utf-8")
    page.confirm_overwrite = lambda path: False
    page.run_button.click()
    assert page.process is None


def test_cancel_ends_the_process_and_ignores_its_late_result(qapp, tmp_path):
    _win, page, _source = _files(qapp, tmp_path)
    page.run_button.click()
    process = page.process
    page.cancel_button.click()
    process.done(1, "killed")
    assert process.killed and page.process is None
    assert "Cancelled" in page.result.toPlainText()


def test_nothing_runs_before_a_file_is_chosen(qapp):
    win = _window(qapp)
    assert not win._app_pages["files"].run_button.isEnabled()


def test_closing_during_a_job_asks_first_and_ends_it_on_yes(qapp, tmp_path):
    win, page, _source = _files(qapp, tmp_path)
    page.run_button.click()
    process = page.process
    page.confirm_abandon = lambda: False
    assert not win._close_allowed()
    page.confirm_abandon = lambda: True
    assert win._close_allowed()
    assert process.killed


# --- voice commands, privacy, theme -------------------------------------------------


def test_searching_commands_narrows_the_list(qapp):
    win = _window(qapp)
    page = win._app_pages["commands"]
    total = page.visible_count()
    page.search.setText("undo")
    assert 0 < page.visible_count() < total


def test_the_general_page_lists_what_can_leave_the_computer(qapp):
    win = _window(qapp)
    win._shell.select("general")
    text = _text(win._shell.stack.currentWidget())
    assert "AI cleanup" in text and "Remote dictation" in text


def test_choosing_a_theme_marks_general_and_apply_saves_it(qapp):
    win = _window(qapp)
    original = qapp.palette()
    try:
        win._theme_box.setCurrentIndex(win._theme_box.findData("violet-light"))
        assert "general" in win._dirty_pages()
        win._on_apply()
        assert ("window", "theme", "violet-light", True) in win.writes
        assert "general" not in win._dirty_pages()
    finally:
        qapp.setPalette(original)
        win._win.setStyleSheet("")


def test_a_theme_alone_does_not_ask_for_a_restart(qapp):
    win = _window(qapp)
    asked = []
    win._offer_restart = lambda summary="": asked.append(summary)  # type: ignore[method-assign]
    original = qapp.palette()
    try:
        win._theme_box.setCurrentIndex(win._theme_box.findData("system"))
        win._on_apply()
        assert not asked
    finally:
        qapp.setPalette(original)
        win._win.setStyleSheet("")


def test_the_violet_theme_paints_the_window_and_system_removes_it(qapp):
    from yazses.settingsui.theme_qt import apply_theme

    win = _window(qapp)
    original = qapp.palette()
    try:
        apply_theme(qapp, win._win, "violet-dark")
        assert qapp.palette().window().color().name() == "#0f0d1a"
        assert win._win.styleSheet()
        apply_theme(qapp, win._win, "system")
        assert win._win.styleSheet() == ""
        assert qapp.palette().window().color() == original.window().color()
    finally:
        qapp.setPalette(original)


# --- a slow daemon is not an absent one ---------------------------------------------


def test_a_daemon_that_is_slow_to_answer_is_not_offered_a_start(qapp):
    win = _window(qapp)
    win._page_context.daemon_running = lambda: True
    page = win._app_pages["overview"]
    page.refresh()
    assert "busy" in _text(page.widget)
    assert not page.action_button.isVisibleTo(page.widget)


def test_start_never_restarts_a_running_daemon_and_never_adds_a_login_item(qapp):
    win = _window(qapp)
    ran = []
    win._run_cli = lambda *args: ran.append(args) or (True, "")  # type: ignore[method-assign]
    win._daemon_running = lambda: True  # type: ignore[method-assign]
    assert win._start_daemon() == (True, "")
    assert not ran
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._start_daemon()
    assert ran == [("start", "--no-autostart")]


@pytest.mark.parametrize("key", ("start", "restart"))
def test_the_window_stays_open_while_a_start_or_restart_from_a_page_runs(qapp, key):
    win = _window(qapp)
    win._background.running = lambda name: name == key  # type: ignore[method-assign]
    assert not win._close_allowed()
    assert win._hint.text()


def test_stopping_a_slow_meeting_says_it_is_still_being_written(qapp, tmp_path):
    daemon = _Daemon(meeting_status={"ok": True, "enabled": True, "active": True})
    win = _window(qapp, _meeting_config(tmp_path), daemon)
    win._page_context.daemon_running = lambda: True
    page = win._app_pages["meetings"]
    page.refresh()
    page.record_button.click()      # meeting_stop gets no reply in time
    assert "still working" in _text(page.widget)
    assert ("meeting_stop", {"wait_s": 60.0}) in daemon.calls


def test_a_missed_poll_does_not_end_the_meeting_on_screen(qapp, tmp_path):
    daemon = _Daemon(meeting_status={"ok": True, "enabled": True, "active": True,
                                     "live_lines": ["draft line"]})
    win = _window(qapp, _meeting_config(tmp_path), daemon)
    win._page_context.daemon_running = lambda: True
    page = win._app_pages["meetings"]
    page.refresh()
    del daemon.replies["meeting_status"]
    page.refresh()
    assert page.record_button.text() == "Stop meeting"
    assert "draft line" in page.transcript.toPlainText()
    assert "busy" in _text(page.widget)


def test_a_meeting_that_finishes_while_selected_shows_its_transcript(qapp, tmp_path):
    folder = _meeting_dir(tmp_path / "meetings")
    finished = (folder / "transcript.json").read_text(encoding="utf-8")
    (folder / "transcript.json").unlink()
    (folder / "meeting.json").write_text(
        json.dumps({"id": folder.name, "status": "processing"}), encoding="utf-8")
    win = _window(qapp, _meeting_config(tmp_path))
    page = win._app_pages["meetings"]
    page.refresh()
    page.list.setCurrentRow(0)
    assert "No finished transcript" in page.transcript.toPlainText()

    (folder / "transcript.json").write_text(finished, encoding="utf-8")
    (folder / "meeting.json").write_text(
        json.dumps({"id": folder.name, "status": "done"}), encoding="utf-8")
    page.refresh()
    assert "Hello all." in page.transcript.toPlainText()
    assert page.export_button.isVisibleTo(page.widget)


# --- what the transcription command says --------------------------------------------


def test_a_note_from_a_successful_run_is_shown(qapp, tmp_path):
    _win, page, source = _files(qapp, tmp_path)
    page.run_button.click()
    source.with_suffix(".txt").write_text("plain words", encoding="utf-8")
    page.process.done(0, "Transcribing…\nNote: diarization was unavailable; wrote a plain transcript.\n")
    assert "diarization was unavailable" in page.note.text()
    assert page.note.isVisibleTo(page.widget)


def test_speaker_labels_are_not_offered_without_their_libraries(qapp):
    win = _window(qapp)
    page = win._app_pages["files"]
    page.extra_installed = lambda: False
    page.refresh()
    assert not page.speakers.isEnabled() and not page.speakers.isChecked()
    assert "extra" in page.speakers.text()
    assert win._switches.buttons("recimport", within=page.widget)
    page.extra_installed = lambda: True
    page.refresh()
    assert page.speakers.isEnabled()


# --- nothing is clipped -------------------------------------------------------------


def _clipped(page):
    """Labels shorter than their text, poking out of their parent, or under a sibling."""
    bad = []
    for lb in page.findChildren(QLabel):
        if not (lb.text() and lb.isVisibleTo(page)):
            continue
        parent, box = lb.parentWidget(), lb.geometry()
        short = lb.wordWrap() and lb.height() + 1 < lb.heightForWidth(lb.width())
        outside = not parent.rect().contains(box)
        covered = any(
            other is not lb and other.parentWidget() is parent and other.isVisibleTo(page)
            and other.geometry().intersects(box)
            for other in parent.findChildren(QWidget)
        )
        if short or outside or covered:
            bad.append((lb.text()[:40], short, outside, covered))
    return bad


@pytest.mark.parametrize(
    "key", ("overview", "dictation", "meetings", "files", "commands", "accessibility", "general")
)
@pytest.mark.parametrize("size", ((760, 520), (1060, 760)))
def test_wrapped_text_is_never_cut_off(qapp, tmp_path, key, size):
    _meeting_dir(tmp_path / "meetings")
    from yazses.settingsui.theme_qt import apply_theme

    win = _window(qapp, _meeting_config(tmp_path, enabled=False),
                  _Daemon(status=_status()))
    original = qapp.palette()
    # The theme's padding changes every size, so it is measured as users see it.
    apply_theme(qapp, win._win, "violet-dark")
    files_page = win._app_pages["files"]
    files_page.extra_installed = lambda: False
    files_page.refresh()
    win._win.resize(*size)
    win._win.show()
    try:
        win._shell.select(key)
        win._refresh_current_page()
        for _ in range(4):
            qapp.processEvents()
        # Text that arrives after the page is laid out, as a command's warning does.
        files_page._show_note("Note: " + "a long explanation of what went wrong. " * 8)
        for _ in range(8):
            qapp.processEvents()
        assert not _clipped(win._shell.stack.currentWidget())
    finally:
        win._win.hide()
        apply_theme(qapp, None, "system")
        qapp.setPalette(original)


# --- the first moment the window is on screen ---------------------------------------


def test_the_automatic_key_is_named_before_the_daemon_has_answered(qapp):
    from yazses.platform import get_platform
    from yazses.settingsui.overview import key_label

    expected = key_label(get_platform().default_hotkey)
    win = _window(qapp)      # a fresh config: `[hotkey] key = "auto"`
    for key in ("overview", "dictation"):
        text = _text(win._app_pages[key].widget)
        assert expected in text and "Auto" not in text.split("\n"), key


def test_showing_the_window_asks_for_the_status_at_once(qapp):
    daemon = _Daemon(status=_status())
    win = _window(qapp, daemon=daemon)
    try:
        win.show()
        assert any(method == "status" for method, _ in daemon.calls)
    finally:
        win._win.hide()


def test_the_system_check_is_hidden_until_there_is_something_to_check(qapp):
    win = _window(qapp)
    page = win._app_pages["overview"]
    assert not page._checks.isVisibleTo(page.widget)


# --- what a screen reader is told ---------------------------------------------------


@pytest.mark.parametrize(
    "key", ("overview", "dictation", "meetings", "files", "commands", "accessibility", "general")
)
def test_every_control_on_an_app_page_has_a_name(qapp, tmp_path, key):
    """A control with neither text nor an accessible name is announced as just its type."""
    from PySide6.QtWidgets import (
        QAbstractButton,
        QComboBox,
        QLineEdit,
        QListWidget,
        QPlainTextEdit,
        QProgressBar,
        QSlider,
        QSpinBox,
    )

    _meeting_dir(tmp_path / "meetings")
    win = _window(qapp, _meeting_config(tmp_path), _Daemon(status=_status()))
    win._shell.select(key)
    win._refresh_current_page()
    if key == "meetings":
        win._app_pages["meetings"].list.setCurrentRow(0)
    page = win._shell.stack.currentWidget()
    kinds = (QAbstractButton, QComboBox, QLineEdit, QListWidget, QPlainTextEdit,
             QProgressBar, QSlider, QSpinBox)
    unnamed = []
    for kind in kinds:
        for widget in page.findChildren(kind):
            if widget.objectName().startswith("qt_") or not widget.isVisibleTo(page):
                continue  # Qt's own parts, and anything hidden: neither is announced
            if isinstance(widget.parentWidget(), (QSpinBox, QComboBox, QLineEdit)):
                continue
            text = widget.text() if isinstance(widget, QAbstractButton) else ""
            if not (widget.accessibleName() or text):
                unnamed.append((kind.__name__, widget.objectName()))
    assert not unnamed


# --- large fonts and wider fonts ----------------------------------------------------
#
# Windows' fonts are wider than a Linux runner's, so these hold the causes rather than
# pixel widths: they fail the same way on every machine.


@pytest.mark.parametrize("key", ("files", "meetings"))
def test_no_drop_down_on_an_app_page_follows_its_longest_entry(qapp, key):
    from PySide6.QtWidgets import QComboBox

    win = _window(qapp)
    boxes = win._app_pages[key].widget.findChildren(QComboBox)
    assert boxes
    compact = QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    assert [b.accessibleName() for b in boxes if b.sizeAdjustPolicy() != compact] == []


def test_a_capability_card_gives_its_text_the_full_width(qapp):
    """The switch sits under the text: beside it, a large font left too little room."""
    win = _window(qapp)
    win._win.resize(760, 520)
    win._win.show()
    win._shell.select("accessibility")
    for _ in range(4):
        qapp.processEvents()
    page = win._app_pages["accessibility"].widget
    buttons = [b for slug in win._rows for b in win._switches.buttons(slug, within=page)]
    assert buttons
    for button in buttons:
        texts = button.parentWidget().findChildren(QLabel)
        lowest = max(lb.mapTo(button.parentWidget(), lb.rect().bottomLeft()).y() for lb in texts)
        assert button.geometry().top() >= lowest, button.accessibleName()


def test_the_wider_sidebar_does_not_narrow_the_pages(qapp):
    """The narrowest window leaves a page as much room as the 168 px sidebar did."""
    from yazses.settingsui.shell import SIDEBAR_WIDTH

    win = _window(qapp)
    assert win._win.minimumWidth() - SIDEBAR_WIDTH >= 760 - 168


# Keep this last.


def test_no_window_outlives_its_test(qapp):
    """Last in the file on purpose: every window built above has been destroyed.

    Only this file's windows: other test files share the process under ``-n``.
    """
    import shiboken6

    earlier = list(_BUILT)
    win = _window(qapp)
    assert not [w for w in earlier if shiboken6.isValid(w)]
    assert shiboken6.isValid(win._win)
