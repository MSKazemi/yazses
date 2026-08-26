"""A meeting of a muted microphone was written up as a finished meeting.

`recimport.pipeline.transcribe_file` has always answered *did this audio hold
anything* -- `silent_input` since ADR-v2-125, and `no_speech` since 2026-08-20 --
and `meeting.finalize` wraps that same pipeline and dropped both. So a meeting
recorded against a dead microphone, or of a room where nobody spoke, finalized as:

    meeting.json   {"status": "done", "has_notes": true, ...}
    transcript.md  the words Whisper answers noise with
    notes.md       those words, summarised into confident bullet points

`yazses transcribe` printed a note for the same recording. The meeting path printed
nothing, and it is the path where it matters more:

- it is **unattended** -- nobody is watching stderr an hour later;
- the audio is **deleted** when the post-pass returns unless `[meeting] retain_audio`,
  so the transcript becomes the only surviving evidence, and it is the false part;
- the **notes pass** turns invented words into a write-up that reads exactly like a
  real one. That is the output nobody can audit afterwards, so it is the one that is
  refused rather than merely labelled.

Half of this was recorded as a known gap in `tests/test_recimport_cleans_utterances.py`
on 2026-08-19 and left open. It is closed here.

## Deliberately not done

**`retain_audio` is not forced on for a flagged meeting.** Keeping audio the user
asked to delete is a privacy decision, not a diagnostic one (ADR-011), and it cannot
help retroactively anyway -- the flag is only known after the audio has served its
purpose. The warning says the recording held nothing instead of quietly keeping it.

**The transcript body is untouched.** `relabel` re-renders it from `transcript.json`,
which does not carry these flags, so a header written at finalize would silently
vanish on the first relabel. Metadata that survives is better than a banner that does
not.
"""

from __future__ import annotations

import json

import pytest

from yazses.meeting import store

# --- the pure verdict ---------------------------------------------------------

@pytest.mark.parametrize(
    "silent,no_speech,expected",
    [
        (False, False, store.CAPTURE_OK),
        (True, False, store.CAPTURE_NO_SIGNAL),
        (False, True, store.CAPTURE_NO_SPEECH),
        # Cannot occur -- the pipeline computes `no_speech` only when `silent_input`
        # is False -- but if it ever did, "nothing was recorded" is the more specific
        # answer and names the device, which is where the user has to go.
        (True, True, store.CAPTURE_NO_SIGNAL),
    ],
)
def test_the_verdict_reads_the_two_flags(silent, no_speech, expected):
    assert store.capture_state(silent, no_speech) == expected


def test_a_good_meeting_is_marked_ok_rather_than_left_blank():
    """Written explicitly so a meeting recorded before this field existed is
    distinguishable from one that was checked and passed."""
    assert store.capture_state(False, False) == store.CAPTURE_OK
    assert store.capture_warning({"capture": store.CAPTURE_OK}) is None


@pytest.mark.parametrize("meta", [{}, {"capture": ""}, {"capture": "something-new"}])
def test_a_meeting_with_no_verdict_is_not_accused(meta):
    """Every meeting finalized before today has no `capture` key. Warning about
    them would be a lie about recordings nobody checked."""
    assert store.capture_warning(meta) is None


def test_the_two_warnings_name_different_remedies():
    """A dead capture is a device problem; an empty room is not. One message for
    both would send someone to `yazses audio devices` over a recording of a call
    nobody spoke on."""
    dead = store.capture_warning({"capture": store.CAPTURE_NO_SIGNAL})
    quiet = store.capture_warning({"capture": store.CAPTURE_NO_SPEECH})
    assert dead and quiet and dead != quiet
    assert "audio devices" in dead, "the device remedy belongs on the device fault"
    assert "audio devices" not in quiet
    for text in (dead, quiet):
        assert "invented" in text, "the point is that the words were not heard"


# --- finalize -----------------------------------------------------------------

class _Transcript:
    def __init__(self, *, silent_input=False, no_speech=False):
        self.text = "You"
        self.utterances = [_Utt()]
        self.assigned = []
        self.language = "en"
        self.diarized = False
        self.speaker_names = {}
        self.silent_input = silent_input
        self.no_speech = no_speech


class _Utt:
    speaker = ""
    start = 0.0
    end = 1.0
    text = "You"


class _Config:
    notes = True
    notes_model = "/nonexistent.gguf"
    output_format = "md"


def _finalize(monkeypatch, transcript, calls):
    from yazses.meeting import finalize as finalize_mod

    monkeypatch.setattr(
        "yazses.recimport.pipeline.transcribe_file",
        lambda *a, **k: transcript,
        raising=True,
    )
    monkeypatch.setattr(
        "yazses.meeting.notes.generate_minutes",
        lambda *a, **k: calls.append(1) or "MINUTES",
        raising=True,
    )
    return finalize_mod.finalize_meeting(None, _Config())


def test_no_notes_are_written_from_a_recording_that_holds_no_speech(monkeypatch):
    calls: list[int] = []
    result = _finalize(monkeypatch, _Transcript(no_speech=True), calls)
    assert calls == [], "the notes pass ran over invented words"
    assert result.minutes is None
    assert result.transcript.text == "You", "the transcript is kept -- it is the evidence"


def test_no_notes_are_written_from_a_dead_microphone(monkeypatch):
    calls: list[int] = []
    result = _finalize(monkeypatch, _Transcript(silent_input=True), calls)
    assert calls == []
    assert result.minutes is None


def test_a_real_recording_still_gets_its_notes(monkeypatch):
    """Non-vacuity, and the regression that would hurt: notes are the feature."""
    calls: list[int] = []
    result = _finalize(monkeypatch, _Transcript(), calls)
    assert calls == [1], "notes were skipped for a perfectly good meeting"
    assert result.minutes == "MINUTES"


# --- the stored metadata ------------------------------------------------------

def test_the_verdict_is_written_into_meeting_json(tmp_path):
    """Read back off disk: an in-memory dict proves nothing about what survives."""
    store.write_meta(tmp_path, {"id": "m1", "status": "done", "capture": store.CAPTURE_NO_SPEECH})
    on_disk = json.loads((tmp_path / "meeting.json").read_text(encoding="utf-8"))
    assert on_disk["capture"] == store.CAPTURE_NO_SPEECH
    assert store.capture_warning(store.read_meta(tmp_path))


def test_the_controller_records_the_verdict_it_was_given(tmp_path):
    """Drive a real controller and read `meeting.json` back off disk.

    This was an AST probe for a ``"capture"`` key in a dict literal at the
    ``write_meta`` call, on the stated grounds that "building one needs an audio
    session". It does not — a fake engine and a numpy array are enough — and the probe
    went red the first time the dict was assigned to a name before being passed, which
    is a refactor, not a regression. What it was defending is real (the field was
    computed and dropped for a year); this defends the same thing by observing it.
    """
    import dataclasses

    import numpy as np

    from yazses.config import MeetingConfig
    from yazses.meeting.controller import MeetingController
    from yazses.postprocess.prosody import Word

    class _Engine:
        def transcribe(self, audio, sample_rate=16000):
            return "live line"

        def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
            text = " ".join(f"word{'a' * i}" for i in range(600))
            words = [Word(w, i * 0.5, i * 0.5 + 0.4, 0.9) for i, w in enumerate(text.split())]
            return text, words

    cfg = dataclasses.replace(MeetingConfig(output_dir=str(tmp_path), diarize=False))
    d = store.new_meeting(cfg, "m1")
    ctl = MeetingController(
        cfg, d, "m1", engine=_Engine(),
        is_silent=lambda chunk: not np.asarray(chunk).any(), sample_rate=1000,
    )
    ctl.start()
    ctl.feed(np.ones(300, dtype="float32"))
    ctl.feed(np.zeros(900, dtype="float32"))
    ctl.stop_capture()
    ctl.finalize(np.ones(1000 * 300, dtype="float32"))

    on_disk = json.loads((d / "meeting.json").read_text(encoding="utf-8"))
    assert "capture" in on_disk, "the finalized meeting no longer records what its audio held"
    assert on_disk["capture"] == store.CAPTURE_OK


# --- the commands -------------------------------------------------------------
#
# `meeting stop` returns before the post-pass runs, so it can never carry this
# verdict. The listing is the first surface that can, and it is what a user checks
# when the transcript looks wrong.

def _cfg(tmp_path):
    from yazses.config import Config

    cfg = Config()
    cfg.meeting.output_dir = str(tmp_path)
    return cfg


def _stored(tmp_path, capture, *, meeting_id="20260820-090000"):
    d = tmp_path / meeting_id
    d.mkdir(parents=True)
    meta = {"id": meeting_id, "status": "done", "num_speakers": 0, "has_notes": False}
    if capture is not None:
        meta["capture"] = capture
    store.write_meta(d, meta)
    (d / "transcript.json").write_text(
        json.dumps({"text": "You", "utterances": [{"speaker": "", "start": 0.0,
                                                   "end": 1.0, "text": "You"}],
                    "words": [], "language": "en", "diarized": False,
                    "speaker_names": {}}),
        encoding="utf-8",
    )
    return d


def _invoke(monkeypatch, tmp_path, argv):
    from typer.testing import CliRunner

    from yazses import cli

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda *_a, **_k: cfg, raising=False)
    monkeypatch.setattr("yazses.config.load_config", lambda *_a, **_k: cfg, raising=False)
    return CliRunner().invoke(cli.app, argv, env={"COLUMNS": "220", "TERM": "dumb"})


def test_the_listing_says_the_recording_held_nothing(monkeypatch, tmp_path):
    _stored(tmp_path, store.CAPTURE_NO_SPEECH)
    result = _invoke(monkeypatch, tmp_path, ["meeting", "list"])
    assert result.exit_code == 0, result.output
    assert "invented" in result.output
    assert "audio devices" not in result.output, "wrong remedy for an empty room"


def test_the_listing_says_nothing_about_a_good_meeting(monkeypatch, tmp_path):
    _stored(tmp_path, store.CAPTURE_OK)
    result = _invoke(monkeypatch, tmp_path, ["meeting", "list"])
    assert result.exit_code == 0, result.output
    assert "invented" not in result.output


def test_the_listing_says_nothing_about_a_meeting_from_before_the_field_existed(
    monkeypatch, tmp_path
):
    _stored(tmp_path, None)
    result = _invoke(monkeypatch, tmp_path, ["meeting", "list"])
    assert result.exit_code == 0, result.output
    assert "invented" not in result.output


def test_regenerating_notes_by_hand_is_refused_for_an_invented_transcript(
    monkeypatch, tmp_path
):
    """`finalize` skips the notes pass for these; this is the same rule on the path
    that writes them afterwards, which would otherwise walk straight around it."""
    _stored(tmp_path, store.CAPTURE_NO_SPEECH)
    result = _invoke(monkeypatch, tmp_path, ["meeting", "notes", "20260820-090000"])
    assert result.exit_code == 1
    assert "Refusing to write minutes" in result.output
    assert not (tmp_path / "20260820-090000" / "notes.md").exists()


def test_the_refusal_can_be_overridden(monkeypatch, tmp_path):
    """A speech detector can be wrong about a very quiet talker, and the transcript
    is right there to judge. --force must get past the capture check -- it stops at
    the *next* precondition (notes are off by default), not at this one."""
    _stored(tmp_path, store.CAPTURE_NO_SPEECH)
    result = _invoke(monkeypatch, tmp_path, ["meeting", "notes", "20260820-090000", "--force"])
    assert "Refusing to write minutes" not in result.output


def test_notes_are_not_refused_for_an_ordinary_meeting(monkeypatch, tmp_path):
    _stored(tmp_path, store.CAPTURE_OK)
    result = _invoke(monkeypatch, tmp_path, ["meeting", "notes", "20260820-090000"])
    assert "Refusing to write minutes" not in result.output
