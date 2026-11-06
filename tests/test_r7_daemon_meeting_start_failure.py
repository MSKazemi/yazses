"""A meeting whose microphone fails to open must not leave the meeting half-started.

``_handle_meeting_start`` starts the ``MeetingController`` (which opens ``audio.wav``
and, with the default ``live_transcript = true``, spawns a ``meeting-live`` worker
blocked on its queue) *before* it starts the recorder. When ``recorder.start()``
raises -- no input device, a device that vanished, PortAudio refusing the stream --
the handler reported the failure but never stopped the controller: the WAV file
handle stayed open and the worker thread waited on its queue for the life of the
daemon. Every retry from the tray leaked another pair.

Synthetic, Linux-only evidence: fake engine, fake recorder, no microphone or model.
"""
from __future__ import annotations

import threading

from yazses.config import Config
from yazses.core import daemon as daemon_mod
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request
from yazses.meeting import controller as controller_mod
from yazses.platform import get_platform
from yazses.platform.base import TrayState


class _FakeEngine:
    def transcribe(self, audio, sample_rate=16000):
        return ""


class _RecorderThatCannotOpen:
    def __init__(self, *a, **k):
        pass

    def start(self):
        raise RuntimeError("Error opening InputStream: Invalid device")

    def stop(self):  # pragma: no cover - never started
        return None


def _daemon(tmp_path) -> Daemon:
    cfg = Config()
    cfg.meeting.enabled = True
    cfg.meeting.output_dir = str(tmp_path)
    cfg.meeting.diarize = False
    cfg.meeting.live_transcript = True  # the default: a live worker thread is spawned
    d = Daemon(config=cfg, platform=get_platform())
    d._engine = _FakeEngine()
    d._state.ready = True
    d._state.state = TrayState.IDLE
    d._report_failure = lambda *a, **k: None  # no desktop notification from a test
    return d


def test_failed_recorder_start_releases_the_started_controller(tmp_path, monkeypatch):
    created: list = []

    class _Recording(controller_mod.MeetingController):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            created.append(self)

    monkeypatch.setattr(controller_mod, "MeetingController", _Recording)
    monkeypatch.setattr(daemon_mod, "AudioRecorder", _RecorderThatCannotOpen)
    d = _daemon(tmp_path)

    resp = d._handle_meeting_start(Request(method="meeting_start", params={}, id=1))

    assert resp["ok"] is False
    assert "could not start meeting" in resp["reason"]
    assert d._meeting_controller is None
    assert d._state.state == TrayState.IDLE
    assert len(created) == 1
    ctrl = created[0]
    worker: threading.Thread | None = ctrl._worker
    if worker is not None:
        worker.join(timeout=5.0)
        assert not worker.is_alive(), "the meeting-live worker outlived a failed start"
    assert ctrl._session._closed, "audio.wav was left open after a failed start"
    assert ctrl._session._sink._fh.closed


def test_a_retry_after_a_failed_start_does_not_accumulate_workers(tmp_path, monkeypatch):
    created: list = []

    class _Recording(controller_mod.MeetingController):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            created.append(self)

    monkeypatch.setattr(controller_mod, "MeetingController", _Recording)
    monkeypatch.setattr(daemon_mod, "AudioRecorder", _RecorderThatCannotOpen)
    d = _daemon(tmp_path)

    for attempt in range(2):
        # A fresh output folder per attempt, so two starts within one second (same
        # meeting id) never collide on the folder name.
        d._config.meeting.output_dir = str(tmp_path / f"attempt{attempt}")
        assert d._handle_meeting_start(
            Request(method="meeting_start", params={}, id=1)
        )["ok"] is False

    for ctrl in created:
        if ctrl._worker is not None:
            ctrl._worker.join(timeout=5.0)
    alive = [c for c in created if c._worker is not None and c._worker.is_alive()]
    assert alive == []
