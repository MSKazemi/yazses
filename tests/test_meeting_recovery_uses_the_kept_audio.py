"""A crashed meeting keeps its whole recording, and nothing offered it back.

`core/daemon.py` deletes `audio.wav` only *after* the batch post-pass succeeds, and its
failure branch logs, in as many words, that the recording "has been KEPT ... so it can be
retried". Two things were missing from the other end of that promise.

**Nothing said the file was there.** `list_meetings` flagged a meeting `recoverable` only
when a `live.jsonl` existed -- the rolling, low-quality transcript the segmenter happens
to produce during capture. A crash before the first utterance was decoded, or
`[meeting] live_transcript = false`, leaves no such file, so `yazses meeting list` printed
the meeting as if it had finished: `? speaker(s)`, no warning, and the entire recording
sitting unmentioned in the same folder. Measured on a real machine while auditing.

**Nothing performed the retry.** There was no `meeting recover`. The audio was reachable
only by finding the WAV by hand and running `yazses transcribe` on it, which produces
sidecars next to the file rather than a meeting.

Both are closed here. The one hazard worth naming: recovery must not go through
`MeetingController`, because `MeetingSession.__init__` opens `audio.wav` with
`wave.open(..., "wb")` -- recovering a meeting through the controller would truncate the
recording it is recovering, on its first line. `recover.py` reads the file and writes the
same outputs `MeetingController.finalize` does, and never deletes it: on a retry the file
is the only copy, and a second failure must leave the user no worse off than the first.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import pathlib

import pytest

from yazses.meeting import recover, store

SPEECH = pathlib.Path(__file__).resolve().parent.parent / "data/librispeech-sample/jfk.wav"


@functools.lru_cache(maxsize=1)
def _speech():
    from yazses.recimport.audio_io import load_audio

    audio, _sr = load_audio(SPEECH)
    return audio


class _Cfg:
    """Duck-typed MeetingConfig: notes off, diarization off, nothing heavy."""

    notes = False
    diarize = False
    output_format = "md"
    model = "tiny.en"
    language = "en"
    name_from_voiceprints = False

    def __init__(self, root=None):
        self.output_dir = str(root) if root is not None else ""


class _Engine:
    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        from yazses.postprocess.prosody import Word

        return "and so my fellow americans", [
            Word("and", 0.0, 0.3, 0.9), Word("so", 0.4, 0.6, 0.9),
        ]


def _recording(d, audio=None):
    """Write a real 16-bit PCM WAV the way the daemon does, via the shipped sink."""
    from yazses.meeting.session import WavFileSink

    d.mkdir(parents=True, exist_ok=True)
    sink = WavFileSink(d / "audio.wav")
    sink.write(_speech() if audio is None else audio)
    sink.close()
    return d


# --- what the listing can see -------------------------------------------------

def test_a_meeting_with_only_a_recording_is_flagged(tmp_path):
    """The case that printed as a finished meeting: audio, no live transcript."""
    d = _recording(tmp_path / "20260820-100000")
    listed = store.list_meetings(_Cfg(tmp_path))
    assert listed[0].get("recoverable") is True
    assert listed[0].get("audio_path") == str(d / "audio.wav")


def test_a_header_with_no_frames_is_not_called_a_recording(tmp_path):
    """`WavFileSink` writes the 44-byte header at session start, before any audio.

    Flagging that as recoverable would send a user to run a post-pass over nothing --
    a promise the file cannot keep.
    """
    d = tmp_path / "20260820-100000"
    d.mkdir(parents=True)
    from yazses.meeting.session import WavFileSink

    WavFileSink(d / "audio.wav").close()
    assert (d / "audio.wav").stat().st_size <= 44, "premise: an empty sink is header-only"
    listed = store.list_meetings(_Cfg(tmp_path))
    assert not listed[0].get("recoverable")
    assert "audio_path" not in listed[0]


def test_a_finished_meeting_that_retained_its_audio_is_not_flagged(tmp_path):
    """`[meeting] retain_audio` leaves the same file behind on a *successful* meeting."""
    d = _recording(tmp_path / "20260820-100000")
    store.write_meta(d, {"id": "20260820-100000", "status": "done"})
    listed = store.list_meetings(_Cfg(tmp_path))
    assert not listed[0].get("recoverable")


def test_the_live_transcript_alone_still_counts(tmp_path):
    """The pre-existing behaviour this widened must not have been replaced."""
    d = tmp_path / "20260820-100000"
    d.mkdir(parents=True)
    store.append_live_line(d, "we were discussing the budget")
    listed = store.list_meetings(_Cfg(tmp_path))
    assert listed[0].get("recoverable") is True
    assert "audio_path" not in listed[0]


# --- what it says -------------------------------------------------------------

def test_the_recording_is_offered_before_the_live_transcript():
    """Both artefacts, ordered by which is worth reaching for."""
    meta = {"recoverable": True, "id": "m1", "audio_path": "/x/audio.wav", "dir": "/x"}
    lines = store.recovery_advice(meta, 4)
    assert "yazses meeting recover m1" in lines[0]
    assert "live" in lines[1] and "4 line(s)" in lines[1]


def test_a_live_only_meeting_keeps_the_message_it_had():
    lines = store.recovery_advice({"recoverable": True, "id": "m1", "dir": "/x"}, 4)
    assert len(lines) == 1
    assert "did not finish" in lines[0] and "/x/live.jsonl" in lines[0]
    assert "recover" not in lines[0], "there is no recording to recover"


def test_a_finished_meeting_is_told_nothing():
    assert store.recovery_advice({"id": "m1", "dir": "/x"}, 4) == []


def test_every_line_is_indented_under_its_meeting():
    lines = store.recovery_advice(
        {"recoverable": True, "id": "m1", "audio_path": "/x/audio.wav", "dir": "/x"}, 2)
    assert lines and all(line.startswith("    ") for line in lines)


# --- the refusals -------------------------------------------------------------

def test_a_finished_meeting_is_not_re_transcribed_over(tmp_path):
    """The completed transcript is the expensive artefact; a rerun would replace it."""
    d = _recording(tmp_path / "m")
    reason = recover.recovery_refusal(d, {"id": "m", "status": "done"})
    assert reason and "already finished" in reason


def test_a_meeting_with_no_recording_is_refused_with_the_reason(tmp_path):
    d = tmp_path / "m"
    d.mkdir()
    reason = recover.recovery_refusal(d, {"id": "m"})
    assert reason and "audio.wav" in reason


def test_a_missing_directory_is_refused(tmp_path):
    reason = recover.recovery_refusal(tmp_path / "nope", {})
    assert reason and "No meeting directory" in reason


def test_a_recoverable_meeting_is_not_refused(tmp_path):
    d = _recording(tmp_path / "m")
    assert recover.recovery_refusal(d, {"id": "m"}) is None


# --- the recovery itself ------------------------------------------------------
def test_the_listing_and_the_refusal_agree_on_what_a_recording_is(tmp_path):
    """One predicate, not two. The refusal used to carry its own literal 44, so a
    drift in either would offer a recovery the command then declines."""
    from yazses.meeting.session import WavFileSink

    empty = tmp_path / "empty"
    empty.mkdir()
    WavFileSink(empty / "audio.wav").close()
    real = _recording(tmp_path / "real")

    for d, offered in ((empty, False), (real, True)):
        listed = [m for m in store.list_meetings(_Cfg(tmp_path)) if m["dir"] == str(d)][0]
        refused = recover.recovery_refusal(d, {}) is not None
        assert bool(listed.get("audio_path")) is offered
        assert refused is not offered, f"{d.name}: listed={listed.get('audio_path')} refused={refused}"



def test_recovering_writes_the_same_outputs_a_finished_meeting_has(tmp_path):
    d = _recording(tmp_path / "20260820-100000")
    info = recover.recover_meeting(d, _Cfg(tmp_path), engine=_Engine())

    assert (d / "transcript.json").exists() and (d / "transcript.md").exists()
    meta = json.loads((d / "meeting.json").read_text(encoding="utf-8"))
    assert meta["status"] == "done"
    assert meta["recovered"] is True, "a reader deserves to know the duration came from the WAV"
    assert meta["id"] == "20260820-100000"
    assert meta["duration_s"] == pytest.approx(11.0, abs=0.5)
    assert meta["capture"] == store.CAPTURE_OK
    assert info["recovered"] is True and info["files"]


def test_the_recording_is_not_truncated_by_recovering_it(tmp_path):
    """The hazard: `MeetingSession.__init__` opens this same path with `wb`."""
    d = _recording(tmp_path / "m")
    before = hashlib.sha256((d / "audio.wav").read_bytes()).hexdigest()
    recover.recover_meeting(d, _Cfg(tmp_path), engine=_Engine())
    assert (d / "audio.wav").exists(), "the retry deleted the only copy"
    after = hashlib.sha256((d / "audio.wav").read_bytes()).hexdigest()
    assert after == before, "the recording was rewritten by the code recovering it"


def test_recovery_never_opens_the_recording_for_writing():
    """Source guard for the same hazard, because the behavioural test above can only
    catch it once someone has already shipped it. Any of these constructors would
    truncate `audio.wav`."""
    src = pathlib.Path("src/yazses/meeting/recover.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "MeetingSession" not in called, "recovery through a session truncates the WAV"
    assert "WavFileSink" not in called, "the sink opens audio.wav for writing"
    assert "MeetingController" not in called, "the controller builds a session"


def test_a_recovered_meeting_leaves_the_listing_clean(tmp_path):
    d = _recording(tmp_path / "20260820-100000")
    assert store.list_meetings(_Cfg(tmp_path))[0].get("recoverable") is True
    recover.recover_meeting(d, _Cfg(tmp_path), engine=_Engine())
    listed = store.list_meetings(_Cfg(tmp_path))
    assert not listed[0].get("recoverable"), "still offering to recover a recovered meeting"
    assert store.recovery_advice(listed[0], 0) == []


def test_a_recovered_recording_that_held_no_speech_is_still_labelled(tmp_path):
    """The T48 verdict must survive the recovery path, which writes its own meta."""
    import numpy as np

    rng = np.random.default_rng(7)
    hiss = rng.normal(0, 0.0008, 16000 * 4).astype("float32")
    d = _recording(tmp_path / "m", audio=hiss)
    info = recover.recover_meeting(d, _Cfg(tmp_path), engine=_Engine())
    assert info["capture"] == store.CAPTURE_NO_SPEECH
    assert json.loads((d / "meeting.json").read_text(encoding="utf-8"))["capture"] == store.CAPTURE_NO_SPEECH
    assert store.capture_warning(info)


# --- the command --------------------------------------------------------------

def _invoke(monkeypatch, tmp_path, argv):
    from typer.testing import CliRunner

    from yazses import cli
    from yazses.config import Config

    cfg = Config()
    cfg.meeting.output_dir = str(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda *_a, **_k: cfg, raising=False)
    monkeypatch.setattr("yazses.config.load_config", lambda *_a, **_k: cfg, raising=False)
    monkeypatch.setattr(
        "yazses.recimport.pipeline._build_engine", lambda *_a, **_k: _Engine(), raising=True)
    return CliRunner().invoke(cli.app, argv, env={"COLUMNS": "220", "TERM": "dumb"})


def test_the_listing_names_the_command_that_gets_the_meeting_back(monkeypatch, tmp_path):
    _recording(tmp_path / "20260820-100000")
    result = _invoke(monkeypatch, tmp_path, ["meeting", "list"])
    assert result.exit_code == 0, result.output
    assert "yazses meeting recover 20260820-100000" in result.output


def test_an_unfinished_meeting_is_not_described_as_a_speaker_count(monkeypatch, tmp_path):
    """`? speaker(s)` reads as "we counted and could not tell"."""
    _recording(tmp_path / "20260820-100000")
    result = _invoke(monkeypatch, tmp_path, ["meeting", "list"])
    assert "speaker(s)" not in result.output.split("\n")[0], result.output
    assert "unfinished" in result.output


def test_the_command_recovers_the_meeting(monkeypatch, tmp_path):
    d = _recording(tmp_path / "20260820-100000")
    result = _invoke(monkeypatch, tmp_path, ["meeting", "recover", "20260820-100000"])
    assert result.exit_code == 0, result.output
    assert (d / "transcript.md").exists()
    assert json.loads((d / "meeting.json").read_text(encoding="utf-8"))["status"] == "done"


def test_the_command_refuses_a_meeting_with_nothing_to_recover(monkeypatch, tmp_path):
    (tmp_path / "20260820-100000").mkdir(parents=True)
    result = _invoke(monkeypatch, tmp_path, ["meeting", "recover", "20260820-100000"])
    assert result.exit_code == 1
    assert "audio.wav" in result.output
