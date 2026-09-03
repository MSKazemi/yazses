"""Daemon-level Meeting Mode IPC handlers (fakes, no mic/model) — ADR-v2-127."""
from __future__ import annotations

import time

import numpy as np

from yazses.config import Config
from yazses.core import daemon as daemon_mod
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request
from yazses.platform import get_platform
from yazses.platform.base import TrayState
from yazses.postprocess.prosody import Word


def _wait_for_finalize(d, timeout=60.0, interval=0.02):
    """Wait for the background finalize thread to clear ``_meeting_finalizing``.

    The flag *is* the postcondition, so the polling shape was right; the budget was
    not. This was ``range(200)`` at 0.02s -- four seconds for a post-pass that
    transcribes, optionally diarizes, renders and then deletes the recording. Four
    seconds is comfortable on an idle runner and not comfortable on a loaded one, so
    the tests failed as a function of what else the machine was doing.

    The timeout is a ceiling on failure, never a cost on success: a healthy finalize
    returns on the first interval. Returns whether it finished, so a caller can say
    "the finalize never completed" instead of asserting on the state it left behind
    and reporting the symptom.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not d._meeting_finalizing:
            return True
        time.sleep(interval)
    return not d._meeting_finalizing


def _start(daemon, **params):
    """Call the `meeting_start` handler the way the IPC server does.

    These tests used to pass `None`, which worked only while the handler ignored its
    request entirely. It now reads an optional `speakers`, and a stub that skips the
    parameter object cannot exercise the parameter contract at all.
    """
    return daemon._handle_meeting_start(
        Request(method="meeting_start", params=params, id=1)
    )


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
    assert _start(d)["ok"] is False


def test_start_refused_when_loading(tmp_path):
    d = _daemon(tmp_path)
    d._state.ready = False
    assert _start(d)["ok"] is False


def test_stop_without_meeting(tmp_path):
    d = _daemon(tmp_path)
    assert d._handle_meeting_stop(None)["ok"] is False


def test_status_lists_when_idle(tmp_path):
    d = _daemon(tmp_path)
    status = d._handle_meeting_status(None)
    assert status["active"] is False
    assert status["recent"] == []


def test_status_publishes_whether_the_feature_is_enabled(tmp_path):
    """The fact that decides what every other key in the payload means.

    It was already on the general `status` payload for the tray, and missing from the
    handler whose whole job is Meeting Mode -- so `yazses meeting status` could not say
    the feature was off, and printed a speaker-label complaint instead.
    """
    d = _daemon(tmp_path)
    d._config.meeting.enabled = False
    assert d._handle_meeting_status(None)["enabled"] is False
    d._config.meeting.enabled = True
    assert d._handle_meeting_status(None)["enabled"] is True


def test_diarization_status_reports_missing_models(tmp_path):
    from yazses.config import MeetingConfig
    from yazses.recimport.factory import diarization_status

    cfg = MeetingConfig(diarize=True, model_dir=str(tmp_path / "absent"))
    status = diarization_status(cfg)
    assert status["requested"] is True
    assert status["models_present"] is False
    assert status["ready"] is False


def test_start_warns_when_diarization_models_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon_mod, "AudioRecorder", _FakeRecorder)
    d = _daemon(tmp_path)
    d._config.meeting.diarize = True                       # ask for speaker labels
    d._config.meeting.model_dir = str(tmp_path / "absent")  # but no models on disk
    started = _start(d)
    assert started["ok"] is True
    assert "warning" in started and "not be attributed" in started["warning"]
    # status also surfaces the unavailability when idle
    d._handle_meeting_stop(None)
    assert _wait_for_finalize(d), "the background finalize never completed"
    idle = d._handle_meeting_status(None)
    assert idle["diarization"]["ready"] is False


def test_full_start_feed_stop_finalize(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon_mod, "AudioRecorder", _FakeRecorder)
    d = _daemon(tmp_path)

    started = _start(d)
    assert started["ok"] is True
    assert d._state.state == TrayState.MEETING
    assert d._meeting_controller is not None

    # a second start is refused while running
    assert _start(d)["ok"] is False

    # status reports the active meeting
    assert d._handle_meeting_status(None)["active"] is True

    # feed some audio as the mic callback would
    d._meeting_controller.feed(np.ones(16000, dtype="float32"))

    stopped = d._handle_meeting_stop(None)
    assert stopped["ok"] is True and stopped["finalizing"] is True

    assert _wait_for_finalize(d), "the background finalize never completed"
    assert d._meeting_finalizing is False
    assert d._state.state == TrayState.IDLE

    from pathlib import Path
    mdir = Path(stopped["dir"])
    assert (mdir / "transcript.json").exists()
    assert (mdir / "meeting.json").exists()


# ---- D4: the recording must outlive a failed finalize --------------------
#
# `retain_audio` defaults to False, so on the DEFAULT path the WAV used to be
# unlinked the moment it had been read into memory — before the post-pass that
# consumes it. Every failure after that point was unrecoverable: the file was
# gone and the only copy lived in a `daemon=True` thread that a shutdown kills
# without running `finally`. `stop` had already returned `ok: True`.


def _started_meeting(tmp_path, monkeypatch, *, retain=False):
    monkeypatch.setattr(daemon_mod, "AudioRecorder", _FakeRecorder)
    d = _daemon(tmp_path)
    d._config.meeting.retain_audio = retain
    assert _start(d)["ok"] is True
    d._meeting_controller.feed(np.ones(16000, dtype="float32"))
    return d


def _capture_wav_path(controller, monkeypatch):
    """`stop_capture()` returns the recording path; remember it so the test can
    check the file after the daemon has finished with it."""
    seen: list = []
    original = controller.stop_capture

    def _spy():
        path = original()
        seen.append(path)
        return path

    monkeypatch.setattr(controller, "stop_capture", _spy)
    return seen


def test_recording_is_kept_when_finalize_fails(tmp_path, monkeypatch):
    """The regression: a failed post-pass must leave the audio on disk.

    Without the fix this test fails — the WAV is already unlinked by the time
    finalize raises, and the meeting is gone with no way to retry.
    """
    d = _started_meeting(tmp_path, monkeypatch, retain=False)
    controller = d._meeting_controller
    seen = _capture_wav_path(controller, monkeypatch)

    def _boom(audio):
        raise RuntimeError("diarization exploded")

    monkeypatch.setattr(controller, "finalize", _boom)

    stopped = d._handle_meeting_stop(None)
    assert stopped["ok"] is True
    _wait_for_finalize(d)

    wav_path = seen[0]
    assert wav_path.exists(), (
        "finalize failed and the recording was deleted anyway — the meeting is "
        "unrecoverable"
    )


def test_recording_is_deleted_after_a_successful_finalize(tmp_path, monkeypatch):
    """The fix must not turn `retain_audio = False` into a leak.

    Deleting later must still mean deleting: the whole point of the default is
    that a meeting recording does not linger on disk once it has been consumed.
    """
    d = _started_meeting(tmp_path, monkeypatch, retain=False)
    seen = _capture_wav_path(d._meeting_controller, monkeypatch)

    assert d._handle_meeting_stop(None)["ok"] is True
    _wait_for_finalize(d)

    assert not seen[0].exists(), "retain_audio is False, so a consumed recording must go"


def test_retain_audio_keeps_the_recording_after_success(tmp_path, monkeypatch):
    d = _started_meeting(tmp_path, monkeypatch, retain=True)
    seen = _capture_wav_path(d._meeting_controller, monkeypatch)

    assert d._handle_meeting_stop(None)["ok"] is True
    _wait_for_finalize(d)

    assert seen[0].exists(), "retain_audio is True — the recording must survive"
