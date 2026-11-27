"""Ways a meeting, or a file transcription, could be lost after it was captured.

Each test here pins one defect that was real: a transcript truncated by a full disk
mid-rewrite, a relabel that destroyed the only copy, a failed `meeting recover` that left
the meeting with no transcript, a recording made unreadable by half a sample, audio that
silently never reached the disk, notes written world-readable, and a `transcribe --out`
that could overwrite the recording or throw away a finished transcript.

Synthetic audio and fake engines throughout: no model, no microphone.
"""
from __future__ import annotations

import errno
import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.config import Config, MeetingConfig
from yazses.meeting import recover, store
from yazses.meeting.controller import MeetingController
from yazses.meeting.lock import LOCK_NAME
from yazses.meeting.session import MeetingSession, WavFileSink, read_wav_mono_f32
from yazses.postprocess.prosody import Word
from yazses.recimport.align import Utterance
from yazses.recimport.pipeline import TranscriptResult
from yazses.system import private_files as pf

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX modes and symlinks")


def _result(names=None) -> TranscriptResult:
    names = names or {"speaker_0": "Alice", "speaker_1": "Bob"}
    return TranscriptResult(
        text="hello there general kenobi",
        utterances=[
            Utterance("speaker_0", 0.0, 1.0, "hello there"),
            Utterance("speaker_1", 2.0, 3.0, "general kenobi"),
        ],
        assigned=[
            ("speaker_0", 0.0, 0.5, "hello"),
            ("speaker_0", 0.5, 1.0, "there"),
            ("speaker_1", 2.0, 2.5, "general"),
            ("speaker_1", 2.5, 3.0, "kenobi"),
        ],
        language="en",
        diarized=True,
        speaker_names=names,
    )


def _meeting(tmp_path: Path, meeting_id: str = "20260101-100000") -> Path:
    d = store.new_meeting(MeetingConfig(output_dir=str(tmp_path)), meeting_id)
    store.write_outputs(d, _result(), fmt="md")
    store.write_meta(d, {"id": meeting_id, "status": "done"})
    return d


def _contents(d: Path) -> dict[str, bytes]:
    # The lock file is bookkeeping a command leaves behind, not part of the meeting.
    return {
        p.name: p.read_bytes() for p in d.iterdir() if p.is_file() and p.name != LOCK_NAME
    }


def _disk_full(*_args, **_kwargs):
    raise OSError(errno.ENOSPC, "No space left on device")


class _Engine:
    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "a new decode", [
            Word("a", 0.0, 0.2, 0.9), Word("new", 0.3, 0.5, 0.9),
            Word("decode", 0.6, 0.9, 0.9),
        ]

    def transcribe(self, audio, sample_rate=16000, **_kw):
        return "a new decode"


def _tone(seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(16000 * seconds)) / 16000.0
    return (0.2 * np.sin(2 * np.pi * 220 * t)).astype("float32")


def _record(d: Path, seconds: float = 1.0) -> Path:
    sink = WavFileSink(d / "audio.wav")
    sink.write(_tone(seconds))
    sink.close()
    return d / "audio.wav"


# --- replacing a file never leaves less than there was --------------------------------


def test_a_failed_replace_leaves_the_old_file_and_no_temporary(tmp_path, monkeypatch):
    p = tmp_path / "transcript.json"
    pf.replace_private_text(p, "the only copy\n")
    monkeypatch.setattr(pf.os, "fsync", _disk_full)

    with pytest.raises(OSError):
        pf.replace_private_text(p, "a longer replacement\n")

    assert p.read_text(encoding="utf-8") == "the only copy\n"
    assert [f.name for f in tmp_path.iterdir()] == ["transcript.json"]


def test_replace_writes_the_new_content(tmp_path):
    p = tmp_path / "a.txt"
    pf.replace_private_text(p, "one\n")
    pf.replace_private_text(p, "two\n")
    assert p.read_text(encoding="utf-8") == "two\n"
    assert [f.name for f in tmp_path.iterdir()] == ["a.txt"]


@posix_only
def test_replace_is_owner_only_and_refuses_a_symlink(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("loose", encoding="utf-8")
    os.chmod(p, 0o644)
    pf.replace_private_text(p, "tight")
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600

    target = tmp_path / "elsewhere.txt"
    target.write_text("original", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises(OSError) as info:
        pf.replace_private_text(link, "x")
    assert info.value.errno == errno.ELOOP
    assert link.is_symlink() and target.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("write", ["outputs", "meta", "relabel"])
def test_a_full_disk_during_a_rewrite_keeps_the_meeting(tmp_path, monkeypatch, write):
    d = _meeting(tmp_path)
    before = _contents(d)
    monkeypatch.setattr(pf.os, "fsync", _disk_full)

    with pytest.raises(OSError):
        if write == "outputs":
            store.write_outputs(d, _result(), fmt="md")
        elif write == "meta":
            store.write_meta(d, {"id": "other"})
        else:
            store.relabel(d, renames={"speaker_0": "Amara"})

    assert _contents(d) == before


# --- relabel ---------------------------------------------------------------------------


def test_relabel_keeps_the_previous_versions_including_hand_edits(tmp_path):
    d = _meeting(tmp_path)
    (d / "transcript.md").write_text("corrected by hand\n", encoding="utf-8")
    canonical = (d / "transcript.json").read_bytes()

    store.relabel(d, merges={"speaker_1": "speaker_0"})

    kept = d / "attempts" / "1"
    assert (kept / "transcript.json").read_bytes() == canonical
    assert (kept / "transcript.md").read_text(encoding="utf-8") == "corrected by hand\n"


def test_relabel_does_not_overwrite_when_the_copy_cannot_be_made(tmp_path, monkeypatch):
    d = _meeting(tmp_path)
    before = _contents(d)
    monkeypatch.setattr(store, "write_private_bytes", _disk_full)

    with pytest.raises(OSError):
        store.relabel(d, merges={"speaker_1": "speaker_0"})

    assert _contents(d) == before


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fmt": "docx"},
        {"merges": {"speaker_1": "speker_0"}},
        {"merges": {"SPEAKER_1": "speaker_0"}},
    ],
    ids=["bad-format", "bad-target", "bad-source"],
)
def test_a_refused_relabel_changes_nothing(tmp_path, kwargs):
    d = _meeting(tmp_path)
    before = _contents(d)

    with pytest.raises(ValueError):
        store.relabel(d, **kwargs)

    assert _contents(d) == before
    assert not (d / "attempts").exists()


@pytest.mark.parametrize("order", [("speaker_0", "speaker_1"), ("speaker_1", "speaker_0")])
def test_merging_keeps_the_surviving_speakers_name(tmp_path, order):
    d = _meeting(tmp_path)
    names = {"speaker_0": "Alice", "speaker_1": "Bob"}
    store.write_outputs(d, _result({k: names[k] for k in order}), fmt="md")

    store.relabel(d, merges={"speaker_1": "speaker_0"})

    data = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    assert data["speakers"] == {"speaker_0": "Alice"}


def _invoke(monkeypatch, tmp_path, argv):
    cfg = Config()
    cfg = replace(cfg, meeting=replace(cfg.meeting, output_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "load_config", lambda *_a, **_k: cfg, raising=False)
    monkeypatch.setattr("yazses.config.load_config", lambda *_a, **_k: cfg, raising=False)
    return CliRunner().invoke(cli.app, argv, env={"COLUMNS": "220", "TERM": "dumb"})


def test_the_cli_refuses_a_bad_relabel_with_exit_1(monkeypatch, tmp_path):
    d = _meeting(tmp_path)
    before = _contents(d)

    result = _invoke(
        monkeypatch, tmp_path, ["meeting", "relabel", d.name, "--format", "docx"])

    assert result.exit_code == 1, result.output
    assert "Could not relabel" in result.output
    assert _contents(d) == before


# --- recovery --------------------------------------------------------------------------


def _recover_config(tmp_path):
    return MeetingConfig(output_dir=str(tmp_path), diarize=False, notes=False)


def test_a_failed_recovery_leaves_the_previous_transcript_in_place(tmp_path):
    d = _meeting(tmp_path)
    _record(d)
    before = (d / "transcript.json").read_bytes()

    class _Broken:
        def transcribe_words(self, *_a, **_k):
            raise MemoryError("synthetic")

    with pytest.raises(MemoryError):
        recover.recover_meeting(d, _recover_config(tmp_path), engine=_Broken())

    assert (d / "transcript.json").read_bytes() == before
    assert (d / "transcript.md").exists()


def test_a_recovery_that_cannot_write_puts_the_previous_outputs_back(tmp_path, monkeypatch):
    d = _meeting(tmp_path)
    _record(d)
    before = (d / "transcript.json").read_bytes()
    monkeypatch.setattr(store, "replace_private_text", _disk_full)

    with pytest.raises(OSError):
        recover.recover_meeting(d, _recover_config(tmp_path), engine=_Engine())

    assert (d / "transcript.json").read_bytes() == before
    assert (d / "transcript.md").exists()


def test_a_successful_recovery_still_archives_the_previous_outputs(tmp_path):
    d = _meeting(tmp_path)
    _record(d)
    before = (d / "transcript.json").read_bytes()

    info = recover.recover_meeting(d, _recover_config(tmp_path), engine=_Engine())

    assert (Path(info["archived_previous"]) / "transcript.json").read_bytes() == before
    assert "a new decode" in (d / "transcript.json").read_text(encoding="utf-8")


def test_an_archive_that_cannot_move_everything_raises_and_moves_nothing(
    tmp_path, monkeypatch
):
    d = _meeting(tmp_path)
    before = _contents(d)
    real = Path.replace

    def replace_but_not_the_markdown(self, target):
        if self.name == "transcript.md" and self.parent == d:
            raise PermissionError("synthetic")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", replace_but_not_the_markdown)

    with pytest.raises(OSError):
        store.archive_outputs(d)

    assert _contents(d) == before


# --- the recording ---------------------------------------------------------------------


def test_a_recording_cut_mid_sample_is_still_readable(tmp_path):
    wav = _record(tmp_path, 0.5)
    with wav.open("r+b") as fh:
        fh.truncate(wav.stat().st_size - 1)

    audio = read_wav_mono_f32(wav)

    assert audio.shape[0] == 8000 - 1


class _FullDiskSink:
    """Accepts ``good`` chunks, then fails like a full disk."""

    def __init__(self, good: int) -> None:
        self.good = good
        self.close_failed = False

    def write(self, _chunk) -> None:
        if self.good <= 0:
            _disk_full()
        self.good -= 1

    def close(self) -> None:
        pass


def test_a_failed_audio_write_is_counted_not_raised(tmp_path):
    session = MeetingSession("m", tmp_path, sink=_FullDiskSink(good=1))
    session.append_chunk(_tone(1.0))
    assert not session.write_failed

    session.append_chunk(_tone(2.0))

    assert session.write_failed
    assert session.unsaved_s() == pytest.approx(2.0)
    assert session.duration_s() == pytest.approx(3.0)


def test_a_failed_close_is_reported(tmp_path, monkeypatch):
    session = MeetingSession("m", tmp_path)
    session.append_chunk(_tone(0.1))
    real_close = session._sink._wav.close

    def failing_close():
        real_close()
        _disk_full()

    monkeypatch.setattr(session._sink._wav, "close", failing_close)

    session.stop()

    assert session.write_failed


def test_a_meeting_the_disk_could_not_hold_keeps_the_recording_and_says_so(tmp_path):
    cfg = MeetingConfig(
        output_dir=str(tmp_path), diarize=False, notes=False, live_transcript=True,
        retain_audio=False,
    )
    d = store.new_meeting(cfg, "m")
    session = MeetingSession("m", d, sink=_FullDiskSink(good=1))
    ctl = MeetingController(
        cfg, d, "m", engine=_Engine(), is_silent=lambda _c: False, session=session)
    pushed: list[int] = []
    real_push = ctl._seg.push

    def push(chunk):
        pushed.append(len(chunk))
        return real_push(chunk)

    ctl._seg.push = push
    ctl.start()
    ctl.feed(_tone(1.0))
    ctl.feed(_tone(2.0))  # the disk is full from here

    assert len(pushed) == 2, "the live transcript must keep hearing the meeting"
    assert ctl.status()["audio_write_failed"] is True
    ctl.stop_capture()
    info = ctl.finalize(_tone(1.0))

    assert info["audio_kept"] is True
    assert "could not be written" in info["audio_warning"]
    meta = store.read_meta(d)
    assert meta["audio_write_failed"] is True
    assert meta["audio_unsaved_s"] == pytest.approx(2.0)
    assert "could not be written" in (d / "summary.md").read_text(encoding="utf-8")


def test_a_healthy_meeting_carries_no_write_warning(tmp_path):
    cfg = MeetingConfig(
        output_dir=str(tmp_path), diarize=False, notes=False, live_transcript=False)
    d = store.new_meeting(cfg, "m")
    ctl = MeetingController(cfg, d, "m", engine=_Engine(), is_silent=lambda _c: False)
    ctl.start()
    ctl.feed(_tone(1.0))

    info = ctl.finalize(read_wav_mono_f32(ctl.stop_capture()))

    assert info["audio_warning"] == ""
    assert "audio_write_failed" not in store.read_meta(d)


# --- notes ------------------------------------------------------------------------------


def test_regenerated_notes_are_owner_only_and_keep_the_previous_ones(monkeypatch, tmp_path):
    d = _meeting(tmp_path)
    (d / "notes.md").write_text("edited by hand\n", encoding="utf-8")
    monkeypatch.setattr(
        "yazses.meeting.notes.notes_unavailable_reason", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "yazses.meeting.notes.generate_minutes", lambda *_a, **_k: object())
    monkeypatch.setattr(
        "yazses.meeting.notes.render_minutes_md", lambda _m: "# Minutes\n")

    old = os.umask(0o022)
    try:
        result = _invoke(monkeypatch, tmp_path, ["meeting", "notes", d.name])
    finally:
        os.umask(old)

    assert result.exit_code == 0, result.output
    assert (d / "notes.md").read_text(encoding="utf-8") == "# Minutes\n"
    kept = d / "attempts" / "1" / "notes.md"
    assert kept.read_text(encoding="utf-8") == "edited by hand\n"
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(d / "notes.md").st_mode) == 0o600


# --- yazses transcribe ------------------------------------------------------------------


def _must_not_load(*_a, **_k):
    raise AssertionError("refused paths must not load a model")


@pytest.mark.parametrize("where", ["input", "missing-folder", "folder"])
def test_transcribe_refuses_a_bad_destination_before_loading_a_model(
    monkeypatch, tmp_path, where
):
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"the only recording")
    out = {"input": clip, "missing-folder": tmp_path / "no" / "x.txt", "folder": tmp_path}
    monkeypatch.setattr("yazses.recimport.pipeline._build_engine", _must_not_load)

    result = _invoke(
        monkeypatch, tmp_path, ["transcribe", str(clip), "--out", str(out[where])])

    assert result.exit_code == 2, result.output
    assert clip.read_bytes() == b"the only recording"


def test_a_transcript_that_cannot_be_written_is_printed_instead(monkeypatch, tmp_path):
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"x")
    dest = tmp_path / "out.txt"
    monkeypatch.setattr(
        "yazses.recimport.pipeline._build_engine", lambda *_a, **_k: _Engine())
    monkeypatch.setattr(
        "yazses.recimport.pipeline.transcribe_file",
        lambda *_a, **_k: TranscriptResult(
            text="an hour of decoding", utterances=[], assigned=[], language="en",
            diarized=False, speaker_names={},
        ),
    )
    real = Path.write_text

    def write_text(self, *a, **k):
        if self == dest:
            _disk_full()
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", write_text)

    result = _invoke(
        monkeypatch, tmp_path,
        ["transcribe", str(clip), "--no-diarize", "--out", str(dest)])

    assert result.exit_code == 1, result.output
    assert "an hour of decoding" in result.output
