"""CLI `yazses transcribe` — ADR-v2-125. No model download (engine/diarizer faked)."""
from __future__ import annotations

import json

import numpy as np
from typer.testing import CliRunner

from yazses import cli
from yazses.config import Config
from yazses.postprocess.prosody import Word
from yazses.recimport.diarizer import DiarTurn

runner = CliRunner()
_ENV = {"COLUMNS": "220", "TERM": "dumb"}

WORDS = [
    Word("hello", 0.0, 0.4, 0.9),
    Word("there", 0.5, 0.9, 0.9),
    Word("general", 2.0, 2.6, 0.9),
]


class _FakeEngine:
    def __init__(self, *a, **k):
        pass

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "hello there general", list(WORDS)


class _FakeDiarizer:
    def diarize(self, audio, sample_rate=16000):
        return [DiarTurn(0.0, 1.2, "speaker_0"), DiarTurn(1.8, 3.0, "speaker_1")]


def _patch(monkeypatch, diarizer=None):
    monkeypatch.setattr(cli, "load_config", lambda *_a, **_k: Config(), raising=False)
    monkeypatch.setattr(
        "yazses.config.load_config", lambda *_a, **_k: Config(), raising=False)
    monkeypatch.setattr(
        "yazses.stt.faster_whisper.FasterWhisperEngine", _FakeEngine, raising=True)
    monkeypatch.setattr(
        "yazses.recimport.audio_io.load_audio",
        lambda *_a, **_k: (np.zeros(16000, dtype="float32"), 16000), raising=True)
    monkeypatch.setattr(
        "yazses.recimport.pipeline.build_diarizer",
        lambda *_a, **_k: diarizer, raising=True)


def _audio(tmp_path):
    f = tmp_path / "clip.wav"
    f.write_bytes(b"RIFF")  # exists; real decode is monkeypatched away
    return f


def test_transcribe_plain_writes_sidecar_txt(tmp_path, monkeypatch):
    _patch(monkeypatch, diarizer=None)
    f = _audio(tmp_path)
    r = runner.invoke(cli.app, ["transcribe", str(f), "--no-diarize"], env=_ENV)
    assert r.exit_code == 0, r.output
    out = f.with_suffix(".txt")
    assert out.exists()
    assert out.read_text().strip() == "hello there general"


def test_transcribe_diarized_tags_speakers(tmp_path, monkeypatch):
    _patch(monkeypatch, diarizer=_FakeDiarizer())
    f = _audio(tmp_path)
    r = runner.invoke(cli.app, ["transcribe", str(f), "--diarize"], env=_ENV)
    assert r.exit_code == 0, r.output
    text = f.with_suffix(".txt").read_text()
    assert "Speaker 1: hello there" in text
    assert "Speaker 2: general" in text


def test_transcribe_names_flag(tmp_path, monkeypatch):
    _patch(monkeypatch, diarizer=_FakeDiarizer())
    f = _audio(tmp_path)
    r = runner.invoke(
        cli.app, ["transcribe", str(f), "--diarize", "--names", "Alice,Bob"], env=_ENV)
    assert r.exit_code == 0, r.output
    text = f.with_suffix(".txt").read_text()
    assert "Alice: hello there" in text and "Bob: general" in text


def test_transcribe_json_format(tmp_path, monkeypatch):
    _patch(monkeypatch, diarizer=_FakeDiarizer())
    f = _audio(tmp_path)
    r = runner.invoke(
        cli.app, ["transcribe", str(f), "--diarize", "--format", "json"], env=_ENV)
    assert r.exit_code == 0, r.output
    payload = json.loads(f.with_suffix(".json").read_text())
    assert payload["diarized"] is True and payload["words"]


def test_transcribe_custom_out_path(tmp_path, monkeypatch):
    _patch(monkeypatch, diarizer=None)
    f = _audio(tmp_path)
    dest = tmp_path / "result.txt"
    r = runner.invoke(
        cli.app, ["transcribe", str(f), "--no-diarize", "--out", str(dest)], env=_ENV)
    assert r.exit_code == 0, r.output
    assert dest.exists()


def test_transcribe_rejects_bad_format(tmp_path, monkeypatch):
    _patch(monkeypatch, diarizer=None)
    f = _audio(tmp_path)
    r = runner.invoke(cli.app, ["transcribe", str(f), "--format", "docx"], env=_ENV)
    assert r.exit_code == 1
    assert "Unknown --format" in r.output


def test_transcribe_help_lists_flags():
    r = runner.invoke(cli.app, ["transcribe", "--help"], env=_ENV)
    assert r.exit_code == 0
    for flag in ("--diarize", "--speakers", "--names", "--format", "--rename"):
        assert flag in r.output


# ---- audio with no recognisable speech --------------------------------------


class _SilentEngine:
    """Transcribes to nothing — music, silence, or a language the model cannot read."""

    def __init__(self, *a, **k):
        pass

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "", []


def _patch_silent(monkeypatch):
    _patch(monkeypatch, diarizer=None)
    monkeypatch.setattr(
        "yazses.stt.faster_whisper.FasterWhisperEngine", _SilentEngine, raising=True)


def test_an_empty_transcript_says_so(tmp_path, monkeypatch):
    """"Wrote transcript.txt" over an empty file is a silent failure, on the surface
    where most people meet YazSes working for the first time.

    A file of music, of silence, or of speech in a language an `.en` model cannot
    read all produce nothing — and the command reported success, named the file, and
    went on to ask for a star.
    """
    _patch_silent(monkeypatch)
    f = _audio(tmp_path)
    r = runner.invoke(cli.app, ["transcribe", str(f), "--no-diarize"], env=_ENV)
    assert r.exit_code == 0, r.output
    assert f.with_suffix(".txt").read_text().strip() == ""
    assert "no speech was recognised" in r.output, (
        f"an empty transcript was reported as an ordinary success: {r.output!r}"
    )


def test_the_note_names_causes_the_user_can_act_on(tmp_path, monkeypatch):
    """A warning with no cause is a warning to dismiss. The English-only model is the
    one a user can neither see nor guess from an empty file."""
    _patch_silent(monkeypatch)
    r = runner.invoke(cli.app, ["transcribe", str(_audio(tmp_path)), "--no-diarize"], env=_ENV)
    for cause in ("music", "language", ".en"):
        assert cause in r.output, f"the note never mentions {cause!r}"


def test_a_normal_transcript_stays_quiet(tmp_path, monkeypatch):
    """The note must not fire on success, or it becomes noise to scroll past."""
    _patch(monkeypatch, diarizer=None)
    r = runner.invoke(cli.app, ["transcribe", str(_audio(tmp_path)), "--no-diarize"], env=_ENV)
    assert "no speech was recognised" not in r.output


def test_the_check_is_on_utterances_not_the_rendered_text(tmp_path, monkeypatch):
    """VTT with no cues is still "WEBVTT", so a check on the rendered string would
    stay silent for exactly one of the five formats — the subtle half of this fix."""
    _patch_silent(monkeypatch)
    f = _audio(tmp_path)
    r = runner.invoke(cli.app, ["transcribe", str(f), "--no-diarize", "-f", "vtt"], env=_ENV)
    assert r.exit_code == 0, r.output
    assert f.with_suffix(".vtt").read_text().strip(), "the VTT header vanished"
    assert "no speech was recognised" in r.output, (
        "the empty-transcript note was skipped for VTT, whose rendered text is never empty"
    )


# ---- --min-speakers is not honoured by the shipped diarizer -----------------


def test_min_speakers_warns_that_the_shipped_diarizer_ignores_it(tmp_path, monkeypatch):
    """`--help` calls it "Lower bound on the auto-detected speaker count", and on the
    default backend it does nothing at all.

    Only `recimport/pyannote_backend.py` reads `min_speakers`, and pyannote is one of
    the adapters this build does not ship. The sherpa diarizer reads `max_speakers`
    alone. Saying so before a long transcription beats the user inferring it from a
    speaker count that ignored their floor.
    """
    _patch(monkeypatch, diarizer=_FakeDiarizer())
    r = runner.invoke(
        cli.app,
        ["transcribe", str(_audio(tmp_path)), "--diarize", "--min-speakers", "3"],
        env=_ENV,
    )
    assert r.exit_code == 0, r.output
    assert "--min-speakers is ignored" in r.output
    assert "sherpa" in r.output, "the note does not say which backend is in use"
    assert "--speakers" in r.output, "a note with no alternative is a note to dismiss"


def test_no_warning_when_no_lower_bound_was_asked_for(tmp_path, monkeypatch):
    """It must stay silent in the ordinary case, or it is noise on every run."""
    _patch(monkeypatch, diarizer=_FakeDiarizer())
    r = runner.invoke(
        cli.app, ["transcribe", str(_audio(tmp_path)), "--diarize"], env=_ENV)
    assert "--min-speakers" not in r.output


def test_no_warning_without_diarization(tmp_path, monkeypatch):
    """Speaker bounds are meaningless without `--diarize`; warning about one there
    would be answering a question nobody asked."""
    _patch(monkeypatch, diarizer=None)
    r = runner.invoke(
        cli.app,
        ["transcribe", str(_audio(tmp_path)), "--no-diarize", "--min-speakers", "3"],
        env=_ENV,
    )
    assert "--min-speakers is ignored" not in r.output
