"""Daemon-level Meeting Mode IPC handlers (fakes, no mic/model) — ADR-v2-127."""
from __future__ import annotations

import time

import numpy as np

from yazses.config import Config
from yazses.core import daemon as daemon_mod
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.platform.base import TrayState
from yazses.postprocess.prosody import Word


class _FakeEngine:
    def transcribe(self, audio, sample_rate=16000):
        return "live line"

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "hello world", [Word("hello", 0.0, 0.4, 0.9), Word("world", 0.5, 0.9, 0.9)]


class _FakeRecorder:
    def __init__(self, *a, **k):
        self.on_chunk = k.get("on_chunk")
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        return np.array([], dtype="float32")


def _daemon(tmp_path, *, enabled=True):
    cfg = Config()
    cfg.meeting.enabled = enabled
    cfg.meeting.output_dir = str(tmp_path)
    cfg.meeting.diarize = False        # plain transcript → fast, no extra needed
    cfg.meeting.live_transcript = False
    cfg.meeting.retain_audio = True
    d = Daemon(config=cfg, platform=get_platform())
    d._engine = _FakeEngine()
    d._state.ready = True
    d._state.state = TrayState.IDLE
    return d


def test_start_refused_when_disabled(tmp_path):
    d = _daemon(tmp_path, enabled=False)
    assert d._handle_meeting_start(None)["ok"] is False


def test_start_refused_when_loading(tmp_path):
    d = _daemon(tmp_path)
    d._state.ready = False
    assert d._handle_meeting_start(None)["ok"] is False


def test_stop_without_meeting(tmp_path):
    d = _daemon(tmp_path)
    assert d._handle_meeting_stop(None)["ok"] is False


def test_status_lists_when_idle(tmp_path):
    d = _daemon(tmp_path)
    status = d._handle_meeting_status(None)
    assert status["active"] is False
    assert status["recent"] == []


def test_full_start_feed_stop_finalize(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon_mod, "AudioRecorder", _FakeRecorder)
    d = _daemon(tmp_path)

    started = d._handle_meeting_start(None)
    assert started["ok"] is True
    assert d._state.state == TrayState.MEETING
    assert d._meeting_controller is not None

    # a second start is refused while running
    assert d._handle_meeting_start(None)["ok"] is False

    # status reports the active meeting
    assert d._handle_meeting_status(None)["active"] is True

    # feed some audio as the mic callback would
    d._meeting_controller.feed(np.ones(16000, dtype="float32"))

    stopped = d._handle_meeting_stop(None)
    assert stopped["ok"] is True and stopped["finalizing"] is True

    for _ in range(200):  # wait for the background finalize thread
        if not d._meeting_finalizing:
            break
        time.sleep(0.02)
    assert d._meeting_finalizing is False
    assert d._state.state == TrayState.IDLE

    from pathlib import Path
    mdir = Path(stopped["dir"])
    assert (mdir / "transcript.json").exists()
    assert (mdir / "meeting.json").exists()
