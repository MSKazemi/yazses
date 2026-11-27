"""One owner per meeting folder, and one folder per meeting.

`meeting recover`, `relabel` and `notes` ran on a meeting the daemon was still recording
or processing (a running meeting's folder looks exactly like a crashed one), nothing kept
the daemon and the CLI from writing the same files at once, and two meetings started within
one second were given the same folder, so the second truncated the first one's recording.

Synthetic audio and fake engines throughout: no model, no microphone.
"""
from __future__ import annotations

import errno
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.config import Config, MeetingConfig
from yazses.core import daemon as daemon_mod
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request
from yazses.meeting import lock as lock_mod
from yazses.meeting import store
from yazses.meeting.lock import LOCK_NAME, MeetingBusyError, MeetingLock, is_busy
from yazses.meeting.session import WavFileSink
from yazses.platform import get_platform
from yazses.platform.base import TrayState
from yazses.postprocess.prosody import Word
from yazses.recimport.align import Utterance
from yazses.recimport.pipeline import TranscriptResult
from yazses.system.single_instance import SingleInstanceLock

MID = "20260101-100000"


def _cfg(tmp_path: Path) -> MeetingConfig:
    return MeetingConfig(output_dir=str(tmp_path))


def _folder(tmp_path: Path, meeting_id: str = MID) -> Path:
    return store.new_meeting(_cfg(tmp_path), meeting_id)


def _record(d: Path) -> None:
    sink = WavFileSink(d / "audio.wav")
    sink.write(np.zeros(1600, dtype="float32"))
    sink.close()


def _finished(tmp_path: Path) -> Path:
    d = _folder(tmp_path)
    result = TranscriptResult(
        text="hello there",
        utterances=[Utterance("speaker_0", 0.0, 1.0, "hello there")],
        assigned=[("speaker_0", 0.0, 1.0, "hello there")],
        language="en",
        diarized=True,
        speaker_names={"speaker_0": "Speaker 1"},
    )
    store.write_outputs(d, result, fmt="md")
    store.write_meta(d, {"id": MID, "status": "done"})
    return d


def _contents(d: Path) -> dict[str, bytes]:
    return {
        p.name: p.read_bytes() for p in d.iterdir() if p.is_file() and p.name != LOCK_NAME
    }


def _os_lock_is_free(d: Path) -> bool:
    """Ask the operating system, past this module's own record of what it holds."""
    probe = SingleInstanceLock(d / LOCK_NAME)
    if not probe.acquire():
        return False
    probe.release()
    return True


# --- the lock ---------------------------------------------------------------------------


def test_a_meeting_has_one_owner_at_a_time(tmp_path):
    d = _folder(tmp_path)

    with MeetingLock(d):
        assert is_busy(d)
        assert not _os_lock_is_free(d)
        with pytest.raises(MeetingBusyError) as info:
            MeetingLock(d).acquire()
        assert info.value.pid == os.getpid()

    assert not is_busy(d)
    assert (d / LOCK_NAME).exists(), "the file stays; only a held lock means anything"
    with MeetingLock(d):
        pass


def test_release_twice_is_harmless(tmp_path):
    lock = MeetingLock(_folder(tmp_path))
    lock.release()
    lock.acquire()
    lock.release()
    lock.release()


def test_one_meetings_lock_does_not_hold_another(tmp_path):
    a, b = _folder(tmp_path, "a"), _folder(tmp_path, "b")
    with MeetingLock(a), MeetingLock(b):
        pass
    with MeetingLock(a):
        assert not is_busy(b)


def test_asking_whether_a_meeting_is_busy_creates_nothing(tmp_path):
    d = _folder(tmp_path)
    assert not is_busy(d)
    assert list(d.iterdir()) == []


def test_a_missing_meeting_is_not_created_by_locking_it(tmp_path):
    with pytest.raises(FileNotFoundError):
        MeetingLock(tmp_path / "no-such-meeting").acquire()
    assert not (tmp_path / "no-such-meeting").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks")
def test_the_lock_is_not_written_through_a_symlink(tmp_path):
    d = _folder(tmp_path)
    target = tmp_path / "elsewhere"
    target.write_text("original", encoding="utf-8")
    (d / LOCK_NAME).symlink_to(target)

    with pytest.raises(OSError) as info:
        MeetingLock(d).acquire()

    assert info.value.errno == errno.ELOOP
    assert target.read_text(encoding="utf-8") == "original"


def test_a_filesystem_without_locks_does_not_stop_meetings(tmp_path, monkeypatch):
    class _NoLocks(SingleInstanceLock):
        def acquire(self) -> bool:
            self.error = OSError(errno.ENOLCK, "No locks available")
            return False

    monkeypatch.setattr(lock_mod, "SingleInstanceLock", _NoLocks)
    d = _folder(tmp_path)
    (d / LOCK_NAME).write_text("", encoding="utf-8")

    assert not is_busy(d)
    with MeetingLock(d):
        pass


_HOLDER = (
    "import os, sys\n"
    "from yazses.meeting.lock import MeetingLock\n"
    "lock = MeetingLock(sys.argv[1])\n"
    "lock.acquire()\n"
    "print(os.getpid(), flush=True)\n"
    "sys.stdin.readline()\n"
    "os._exit(1)\n"  # dies holding it: no release, no cleanup
)


def test_another_processes_lock_is_seen_and_does_not_outlive_a_crash(tmp_path):
    d = _folder(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(d)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        assert proc.stdin is not None and proc.stdout is not None
        holder = int(proc.stdout.readline())
        assert is_busy(d)
        with pytest.raises(MeetingBusyError) as info:
            MeetingLock(d).acquire()
        assert info.value.pid == holder

        proc.stdin.write("die\n")
        proc.stdin.flush()
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:  # pragma: no cover - only when an assertion failed
            proc.kill()
            proc.wait(timeout=30)

    assert not is_busy(d)
    with MeetingLock(d):
        pass


# --- one folder per meeting --------------------------------------------------------------


def test_two_meetings_in_the_same_second_get_their_own_folders(tmp_path):
    now = time.mktime((2026, 1, 1, 10, 0, 0, 0, 0, -1))

    first_id, first = store.reserve_meeting(_cfg(tmp_path), now)
    (first / "audio.wav").write_bytes(b"the first recording")
    second_id, second = store.reserve_meeting(_cfg(tmp_path), now)

    assert (first_id, second_id) == ("20260101-100000", "20260101-100001")
    assert first != second and second.is_dir()
    assert (first / "audio.wav").read_bytes() == b"the first recording"
    assert list(second.iterdir()) == []


def test_a_reserved_id_keeps_the_timestamp_format_and_creates_the_root(tmp_path):
    meeting_id, d = store.reserve_meeting(_cfg(tmp_path / "not" / "yet"))
    assert re.fullmatch(r"\d{8}-\d{6}", meeting_id)
    time.strptime(meeting_id, "%Y%m%d-%H%M%S")
    assert d.name == meeting_id and d.is_dir()


def test_a_file_with_the_ids_name_is_stepped_over(tmp_path):
    now = time.mktime((2026, 1, 1, 10, 0, 0, 0, 0, -1))
    (tmp_path / "20260101-100000").write_text("not a meeting", encoding="utf-8")

    meeting_id, _d = store.reserve_meeting(_cfg(tmp_path), now)

    assert meeting_id == "20260101-100001"


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_a_reserved_folder_is_owner_only(tmp_path):
    old = os.umask(0o022)
    try:
        _id, d = store.reserve_meeting(_cfg(tmp_path))
    finally:
        os.umask(old)
    assert d.stat().st_mode & 0o077 == 0


# --- the listing --------------------------------------------------------------------------


def test_a_meeting_in_progress_is_not_offered_for_recovery(tmp_path):
    d = _folder(tmp_path)
    _record(d)

    with MeetingLock(d):
        listed = store.list_meetings(_cfg(tmp_path))[0]
        assert listed["busy"] is True
        assert "recoverable" not in listed
        assert store.recovery_advice(listed, 0) == []
        assert "in progress" in cli._meeting_row(listed)

    # The same folder with nobody holding it is what a crash leaves behind.
    listed = store.list_meetings(_cfg(tmp_path))[0]
    assert "busy" not in listed and listed["recoverable"] is True


def test_busy_is_never_written_into_the_meeting(tmp_path):
    d = _finished(tmp_path)
    store.ensure_quality(d, {**store.read_meta(d), "busy": True})
    assert "busy" not in store.read_meta(d)


# --- the commands --------------------------------------------------------------------------


def _invoke(monkeypatch, tmp_path, argv):
    cfg = Config()
    cfg = replace(cfg, meeting=replace(cfg.meeting, output_dir=str(tmp_path)))
    monkeypatch.setattr("yazses.config.load_config", lambda *_a, **_k: cfg, raising=False)
    return CliRunner().invoke(cli.app, argv, env={"COLUMNS": "220", "TERM": "dumb"})


def _must_not_run(*_a, **_k):
    raise AssertionError("a refused command must not do the work")


@pytest.mark.parametrize(
    "argv",
    [
        ["recover", MID],
        ["recover", MID, "--force"],
        ["relabel", MID, "--rename", "speaker_0=Alice"],
        ["notes", MID],
        ["notes", MID, "--force"],
    ],
    ids=["recover", "recover-force", "relabel", "notes", "notes-force"],
)
def test_a_command_refuses_a_meeting_somebody_holds(monkeypatch, tmp_path, argv):
    d = _finished(tmp_path)
    _record(d)
    before = _contents(d)
    monkeypatch.setattr("yazses.meeting.recover.recover_meeting", _must_not_run)
    monkeypatch.setattr(store, "relabel", _must_not_run)
    monkeypatch.setattr("yazses.meeting.notes.generate_minutes", _must_not_run)

    with MeetingLock(d):
        result = _invoke(monkeypatch, tmp_path, ["meeting", *argv])

    assert result.exit_code == 1, result.output
    assert "is in use" in result.output
    assert "yazses meeting status" in result.output
    assert "yazses meeting stop" in result.output
    assert _contents(d) == before


@pytest.mark.parametrize("command", ["recover", "relabel", "notes"])
def test_a_recording_meeting_is_reported_as_in_use_not_as_incomplete(
    monkeypatch, tmp_path, command
):
    """While recording there is audio and nothing else: no transcript, no metadata."""
    d = _folder(tmp_path)
    _record(d)
    monkeypatch.setattr("yazses.meeting.recover.recover_meeting", _must_not_run)

    with MeetingLock(d):
        result = _invoke(monkeypatch, tmp_path, ["meeting", command, MID])

    assert result.exit_code == 1, result.output
    assert "is in use" in result.output
    assert "No transcript" not in result.output


def test_a_command_releases_the_meeting_when_it_is_done(monkeypatch, tmp_path):
    d = _finished(tmp_path)

    result = _invoke(
        monkeypatch, tmp_path, ["meeting", "relabel", MID, "--rename", "speaker_0=Alice"])

    assert result.exit_code == 0, result.output
    assert _os_lock_is_free(d)


def test_a_refused_command_releases_the_meeting(monkeypatch, tmp_path):
    d = _finished(tmp_path)

    result = _invoke(monkeypatch, tmp_path, ["meeting", "recover", MID])

    assert result.exit_code == 1, result.output
    assert "already finished" in result.output
    assert _os_lock_is_free(d)


@pytest.mark.parametrize("command", ["recover", "relabel", "notes"])
def test_an_unknown_meeting_is_not_created(monkeypatch, tmp_path, command):
    result = _invoke(monkeypatch, tmp_path, ["meeting", command, "20990101-000000"])

    assert result.exit_code == 1, result.output
    assert not (tmp_path / "20990101-000000").exists()


def test_summary_of_a_recording_meeting_writes_nothing(monkeypatch, tmp_path):
    d = _folder(tmp_path)
    _record(d)
    store.append_live_line(d, "something said", 1.0)
    before = _contents(d)

    with MeetingLock(d):
        result = _invoke(monkeypatch, tmp_path, ["meeting", "summary", MID])

    assert result.exit_code == 1, result.output
    assert "is in use" in result.output
    assert _contents(d) == before


def test_summary_of_a_finished_meeting_in_use_is_shown_but_not_written(
    monkeypatch, tmp_path
):
    d = _finished(tmp_path)
    before = _contents(d)

    with MeetingLock(d):
        result = _invoke(monkeypatch, tmp_path, ["meeting", "summary", MID])

    assert result.exit_code == 0, result.output
    assert f"Meeting {MID}" in result.output
    assert "writing nothing" in result.output
    assert _contents(d) == before


# --- the daemon ----------------------------------------------------------------------------


class _Engine:
    def transcribe(self, audio, sample_rate=16000):
        return "live line"

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "hello world", [Word("hello", 0.0, 0.4, 0.9), Word("world", 0.5, 0.9, 0.9)]


class _Recorder:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass

    def stop(self):
        return np.array([], dtype="float32")


class _RecorderThatCannotOpen(_Recorder):
    def start(self):
        raise RuntimeError("Error opening InputStream: Invalid device")


def _daemon(tmp_path, monkeypatch, recorder=_Recorder) -> Daemon:
    monkeypatch.setattr(daemon_mod, "AudioRecorder", recorder)
    cfg = Config()
    cfg.meeting.enabled = True
    cfg.meeting.output_dir = str(tmp_path / "meetings")
    cfg.meeting.diarize = False
    cfg.meeting.live_transcript = False
    d = Daemon(config=cfg, platform=get_platform())
    d._engine = _Engine()
    d._state.ready = True
    d._state.state = TrayState.IDLE
    d._report_failure = lambda *a, **k: None  # no desktop notifications from a test
    d._announce_meeting_result = lambda *a, **k: None
    d._notify_meeting_failure = lambda *a, **k: None
    return d


def _start(d: Daemon) -> dict:
    return d._handle_meeting_start(Request(method="meeting_start", params={}, id=1))


def _wait_for_finalize(d: Daemon, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while d._meeting_finalizing and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not d._meeting_finalizing, "the background finalize never completed"


@pytest.mark.parametrize("outcome", ["succeeds", "fails"])
def test_the_daemon_holds_a_meeting_until_its_post_pass_ends(
    tmp_path, monkeypatch, outcome
):
    d = _daemon(tmp_path, monkeypatch)
    started = _start(d)
    assert started["ok"] is True
    mdir = Path(str(started["dir"]))
    assert not _os_lock_is_free(mdir), "not held while recording"

    controller = d._meeting_controller
    assert controller is not None
    controller.feed(np.ones(16000, dtype="float32"))
    gate = threading.Event()
    real = controller.finalize

    def _gated(audio):
        gate.wait(30)
        if outcome == "fails":
            raise RuntimeError("synthetic")
        return real(audio)

    monkeypatch.setattr(controller, "finalize", _gated)
    try:
        assert d._handle_meeting_stop(None)["ok"] is True
        assert not _os_lock_is_free(mdir), "not held while finalizing"
        assert store.list_meetings(d._config.meeting)[0]["busy"] is True
    finally:
        gate.set()

    _wait_for_finalize(d)
    assert _os_lock_is_free(mdir)


def test_a_meeting_that_cannot_be_stopped_cleanly_is_released(tmp_path, monkeypatch):
    d = _daemon(tmp_path, monkeypatch)
    mdir = Path(str(_start(d)["dir"]))
    controller = d._meeting_controller
    assert controller is not None
    real = controller.stop_capture

    def _stops_then_fails():
        real()
        raise OSError("synthetic")

    monkeypatch.setattr(controller, "stop_capture", _stops_then_fails)

    assert d._handle_meeting_stop(None)["ok"] is False
    assert _os_lock_is_free(mdir)


def test_a_meeting_that_fails_to_start_is_released(tmp_path, monkeypatch):
    d = _daemon(tmp_path, monkeypatch, recorder=_RecorderThatCannotOpen)

    assert _start(d)["ok"] is False

    (mdir,) = (tmp_path / "meetings").iterdir()
    assert _os_lock_is_free(mdir)
    assert d._meeting_lock is None


def test_back_to_back_meetings_do_not_share_a_folder(tmp_path, monkeypatch):
    d = _daemon(tmp_path, monkeypatch)
    d._config.meeting.retain_audio = True
    ids = []
    for _ in range(2):
        started = _start(d)
        assert started["ok"] is True
        ids.append(started["meeting_id"])
        assert d._handle_meeting_stop(None)["ok"] is True
        _wait_for_finalize(d)

    assert ids[0] != ids[1]
    assert sorted(p.name for p in (tmp_path / "meetings").iterdir()) == sorted(ids)
