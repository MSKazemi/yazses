"""The window against the daemon's own handlers, over a real IPC socket.

The other page tests hand the window a reply written for the test, which proves what a
page does with it and nothing about whether the daemon sends it. Here the window's own
client, its background threads, the IPC server, the daemon's ``status`` and ``meeting_*``
handlers and the meeting store are all real. Only the microphone and the speech model are
stand-ins, so nothing is recorded and nothing is downloaded.

The server and the client are this platform's own: a Unix socket, or a named pipe on
Windows. Skipped only without PySide6 -- the GUI CI job fails on any skip.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import yazses.platform  # noqa: E402
from yazses.config import Config  # noqa: E402
from yazses.core import daemon as daemon_mod  # noqa: E402
from yazses.core.daemon import Daemon  # noqa: E402
from yazses.platform.base import TrayState  # noqa: E402
from yazses.postprocess.prosody import Word  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402


class _Engine:
    def transcribe(self, audio, sample_rate=16000):
        return "live line"

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "hello world", [Word("hello", 0.0, 0.4, 0.9), Word("world", 0.5, 0.9, 0.9)]


class _Microphone:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def stop(self):
        return np.array([], dtype="float32")


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _wait(qapp, condition, seconds=30.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def live(qapp, tmp_path, monkeypatch):
    cfg = Config()
    cfg.meeting.enabled = True
    cfg.meeting.output_dir = str(tmp_path / "meetings")
    cfg.meeting.diarize = False
    cfg.meeting.live_transcript = False
    real = yazses.platform.get_platform()

    monkeypatch.setattr(daemon_mod, "AudioRecorder", _Microphone)
    daemon = Daemon(config=cfg, platform=real)
    daemon._engine = _Engine()
    daemon._state.ready = True
    daemon._state.state = TrayState.IDLE
    daemon._announce_meeting_result = lambda info: None  # no desktop notification

    # A short directory: a Unix socket path is limited to about 108 bytes. The file name
    # repeats its unique part, because a Windows pipe is named from the stem alone.
    runtime = Path(tempfile.mkdtemp(prefix="yz-ui-"))
    socket_path = runtime / f"{runtime.name}.sock"
    server = real.ipc_server_factory(socket_path)
    for method, handler in (
        ("status", daemon._handle_status),
        ("meeting_start", daemon._handle_meeting_start),
        ("meeting_stop", daemon._handle_meeting_stop),
        ("meeting_status", daemon._handle_meeting_status),
    ):
        server.register(method, handler)
    server.serve_in_thread()

    # The window's own client code, pointed at this socket and no other.
    here = SimpleNamespace(
        paths=SimpleNamespace(ipc_socket=socket_path, data_dir=tmp_path),
        ipc_client_factory=real.ipc_client_factory,
        lifecycle=SimpleNamespace(is_running=lambda: True),
    )
    monkeypatch.setattr(yazses.platform, "get_platform", lambda: here)

    controller = SettingsController(lambda: cfg, lambda *a: None, lambda modules: [])
    win = SettingsWindow(build_settings_model(cfg), controller)
    win._win.show()
    try:
        yield SimpleNamespace(win=win, daemon=daemon)
    finally:
        win._page_timer.stop()
        win._level_timer.stop()
        _wait(qapp, lambda: not win._background._busy, 10)
        win._win.hide()
        server.shutdown()
        shutil.rmtree(runtime, ignore_errors=True)


def test_the_overview_reads_a_real_status_reply(qapp, live):
    page = live.win._app_pages["overview"]
    assert _wait(qapp, lambda: page._title.text() == "Ready to dictate"), page._title.text()
    assert "Speech model: base.en" in page._check_text.text()
    assert not page.action_button.isVisibleTo(page.widget)


def test_a_meeting_is_started_stopped_and_read_through_the_window(qapp, live):
    live.win._shell.select("meetings")
    page = live.win._app_pages["meetings"]
    assert _wait(qapp, page.record_button.isEnabled), page._state.text()

    page.record_button.click()
    assert _wait(qapp, lambda: page.record_button.text() == "Stop meeting"), \
        page._message.text()
    assert live.daemon._state.state == TrayState.MEETING

    live.daemon._meeting_controller.feed(np.ones(16000, dtype="float32"))
    assert _wait(qapp, page.record_button.isEnabled)
    page.record_button.click()
    assert _wait(
        qapp, lambda: page.list.count() == 1 and page._rows[0].finished
    ), (page._state.text(), page._message.text())

    page.list.setCurrentRow(0)
    assert "hello world" in page.transcript.toPlainText()
    # The daemon's own id, shown as a date and time rather than raw digits.
    assert page._rows[0].title[4] == "-" and ":" in page._rows[0].title
    assert page.export_button.isVisibleTo(page.widget)
