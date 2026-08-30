"""Four seconds of faint room hiss was transcribed as the word "You", silently.

Found by running the shipped command against a file with nothing in it
(2026-08-20): `yazses transcribe silence.wav` wrote `silence.txt` containing `You`
and printed no warning at all. The word was never spoken -- it is what Whisper
answers non-speech audio with.

## Why the guard that exists could not catch it

`transcribe_file` already measures `carries_no_signal(audio)`, and that check is
right about its own job: it tests the **peak**, so an hour of sparse interview is
not mistaken for silence. The floor is `1e-4`. The hiss that produced "You" peaked
at `0.0036` -- thirty-six times the floor, and utterly ordinary for a real room.

A peak test answers *"was anything recorded at all"*. Nothing about amplitude
answers *"is any of it speech"*, which is the question the hallucination turns on:
a quiet talker and a noisy empty room occupy the same range.

## A detector, not a filter

`vad_filter=True` on the decode would also stop it, and it re-segments the audio.
Measured on six LibriSpeech `test-clean` clips: identical text on four, changed on
two, one of them for the worse -- *"There were the only persons on the road"* became
*"that were the only persons on the road"*. Paying for a warning with the accuracy of
every real transcription is the wrong trade, so the VAD runs beside the decode and
changes nothing but what is printed.

Silero ships inside `faster-whisper` as a 1.2 MB ONNX asset, so this downloads
nothing and sends nothing (ADR-011).

## Known and deliberately not fixed here

`meeting.finalize` wraps the same pipeline and drops `silent_input`; it now drops
`no_speech` too. A meeting recorded against a muted microphone, or of a room where
nobody spoke, still gets no warning -- that needs a `meeting.json` field and a
display for it. Recorded rather than quietly extended, the same way
`tests/test_recimport_cleans_utterances.py` recorded it.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pytest

from tests.decoder_stack import needs_faster_whisper
from yazses.config import RecimportConfig
from yazses.recimport.audio_io import SIGNAL_FLOOR, carries_no_signal, holds_no_speech
from yazses.recimport.pipeline import transcribe_file

SPEECH = pathlib.Path(__file__).resolve().parent.parent / "data/librispeech-sample/jfk.wav"


def _hiss(seconds: float = 4.0, sigma: float = 0.0008) -> np.ndarray:
    """A quiet room: no speech, and far above the digital-silence floor."""
    rng = np.random.default_rng(7)
    return rng.normal(0, sigma, int(16000 * seconds)).astype(np.float32)


class _FakeEngine:
    """Answers every input with the word the real model answered silence with."""

    def __init__(self, text: str = "You") -> None:
        self.text = text

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return self.text, []


# --- the detector ------------------------------------------------------------

def test_the_hiss_that_produced_a_word_is_far_above_the_peak_floor():
    """Non-vacuity for everything below: the old guard genuinely cannot see this."""
    audio = _hiss()
    peak = float(np.abs(audio).max())
    assert peak > SIGNAL_FLOOR * 10, f"peak {peak} is not meaningfully above {SIGNAL_FLOOR}"
    assert carries_no_signal(audio) is False, "the peak test would have caught it after all"


@needs_faster_whisper
def test_a_quiet_room_holds_no_speech():
    assert holds_no_speech(_hiss()) is True


@needs_faster_whisper
def test_a_pure_tone_holds_no_speech():
    t = np.arange(16000 * 4) / 16000
    assert holds_no_speech((np.sin(2 * np.pi * 440 * t) * 0.2).astype(np.float32)) is True


@needs_faster_whisper
@pytest.mark.skipif(not SPEECH.exists(), reason="the committed speech sample is missing")
def test_real_speech_holds_speech():
    """The half that matters most: a warning on a good transcript is worse than none."""
    from faster_whisper import decode_audio

    assert holds_no_speech(decode_audio(str(SPEECH))) is False


@needs_faster_whisper
@pytest.mark.skipif(not SPEECH.exists(), reason="the committed speech sample is missing")
def test_speech_buried_between_two_stretches_of_hiss_still_holds_speech():
    from faster_whisper import decode_audio

    audio = np.concatenate([_hiss(), decode_audio(str(SPEECH)), _hiss()])
    assert holds_no_speech(audio) is False


@pytest.mark.parametrize("empty", [None, np.zeros(0, dtype=np.float32)])
def test_nothing_at_all_holds_no_speech(empty):
    assert holds_no_speech(empty) is True


def test_a_sample_rate_the_detector_cannot_judge_declines_to_answer():
    """None, not True: Silero is a 16 kHz model, and a guess here writes a warning
    onto a transcript that may be perfectly good."""
    assert holds_no_speech(_hiss(), sample_rate=44100) is None


def test_a_detector_that_cannot_run_declines_to_answer(monkeypatch):
    """An install without the VAD asset keeps today's behaviour rather than
    inventing a verdict in either direction."""
    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "faster_whisper.vad":
            raise ImportError("no vad here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    assert holds_no_speech(_hiss()) is None


# --- the pipeline ------------------------------------------------------------

@needs_faster_whisper
def test_the_pipeline_flags_a_transcript_produced_from_room_noise():
    result = transcribe_file(
        "unused.wav", RecimportConfig(), engine=_FakeEngine(), audio=_hiss()
    )
    assert result.text == "You", "the fake engine's output should reach the result"
    assert result.no_speech is True
    assert result.silent_input is False, "there is signal here; only the speech is missing"


def test_digital_silence_is_still_reported_as_no_signal_and_not_as_no_speech():
    """The two notes name different remedies -- a muted device, versus a file that
    holds no speech. Sending someone to `yazses audio devices` over a recording of
    a song is the failure this separation exists to avoid."""
    result = transcribe_file(
        "unused.wav",
        RecimportConfig(),
        engine=_FakeEngine(),
        audio=np.zeros(16000 * 2, dtype=np.float32),
    )
    assert result.silent_input is True
    assert result.no_speech is False


@needs_faster_whisper
@pytest.mark.skipif(not SPEECH.exists(), reason="the committed speech sample is missing")
def test_a_real_recording_is_flagged_neither_way():
    from faster_whisper import decode_audio

    result = transcribe_file(
        "unused.wav",
        RecimportConfig(),
        engine=_FakeEngine("And so my fellow Americans"),
        audio=decode_audio(str(SPEECH)),
    )
    assert result.silent_input is False
    assert result.no_speech is False


# --- the command --------------------------------------------------------------
#
# Driven through the real CLI: the flag is only worth anything if the note reaches
# the person reading the transcript, and the three notes must stay exclusive.

_NO_SPEECH_NOTE = "a speech detector found no speech"
_NO_SIGNAL_NOTE = "the audio carries no signal"
_EMPTY_NOTE = "no speech was recognised"


def _run(tmp_path, monkeypatch, audio, text="You"):
    from typer.testing import CliRunner

    from yazses import cli
    from yazses.config import Config

    monkeypatch.setattr(cli, "load_config", lambda *_a, **_k: Config(), raising=False)
    monkeypatch.setattr("yazses.config.load_config", lambda *_a, **_k: Config(), raising=False)
    monkeypatch.setattr(
        "yazses.recimport.audio_io.load_audio", lambda *_a, **_k: (audio, 16000), raising=True
    )
    monkeypatch.setattr(
        "yazses.recimport.pipeline.build_diarizer", lambda *_a, **_k: None, raising=True
    )
    # Patch where the CLI *constructs* the engine, not only the pipeline helper:
    # `transcribe` builds one itself and injects it, so patching `_build_engine`
    # alone silently loaded the real base.en model -- which decoded the hiss to
    # "You" for real and made this helper 18 s slower and a fake in name only.
    monkeypatch.setattr(
        "yazses.stt.faster_whisper.FasterWhisperEngine",
        lambda *a, **k: _FakeEngine(text),
        raising=True,
    )
    monkeypatch.setattr(
        "yazses.recimport.pipeline._build_engine",
        lambda _config: _FakeEngine(text),
        raising=True,
    )
    src = tmp_path / "clip.wav"
    src.write_bytes(b"RIFF....WAVEfmt ")  # never decoded; load_audio is faked
    out = tmp_path / "clip.txt"
    result = CliRunner().invoke(
        cli.app, ["transcribe", str(src), "-o", str(out)], env={"COLUMNS": "220", "TERM": "dumb"}
    )
    assert result.exit_code == 0, result.output
    return result.output, out


@needs_faster_whisper
def test_the_command_warns_that_the_words_were_invented(tmp_path, monkeypatch):
    output, out = _run(tmp_path, monkeypatch, _hiss())
    assert out.read_text(encoding="utf-8").strip() == "You", "the transcript is still written, not suppressed"
    assert _NO_SPEECH_NOTE in output
    assert _NO_SIGNAL_NOTE not in output, "a quiet room is not a dead microphone"


@needs_faster_whisper
def test_the_command_still_names_a_dead_microphone_as_a_dead_microphone(tmp_path, monkeypatch):
    output, _ = _run(tmp_path, monkeypatch, np.zeros(16000 * 2, dtype=np.float32))
    assert _NO_SIGNAL_NOTE in output
    assert _NO_SPEECH_NOTE not in output


@needs_faster_whisper
@pytest.mark.skipif(not SPEECH.exists(), reason="the committed speech sample is missing")
def test_a_real_recording_earns_no_note_at_all(tmp_path, monkeypatch):
    """The regression that would matter most: crying wolf over a good transcript."""
    from faster_whisper import decode_audio

    output, _ = _run(
        tmp_path, monkeypatch, decode_audio(str(SPEECH)), text="And so my fellow Americans"
    )
    for note in (_NO_SPEECH_NOTE, _NO_SIGNAL_NOTE, _EMPTY_NOTE):
        assert note not in output, f"unwanted note on a good transcript: {note}"


@needs_faster_whisper
def test_an_empty_transcript_keeps_its_own_note_and_gets_no_second_one(tmp_path, monkeypatch):
    """Three notes, one cause each, and the empty-output note must come first --
    it describes the file the user is holding rather than how it came to be that
    way, and a file with nothing in it needs no theory of why.

    (Only *this* ordering is load-bearing. Swapping the other two changes no output,
    because `no_speech` is computed as False whenever `silent_input` is True -- a
    mutation that reorders them stays green, correctly.)"""
    output, _ = _run(tmp_path, monkeypatch, _hiss(), text="")
    assert _EMPTY_NOTE in output
    assert _NO_SPEECH_NOTE not in output
    assert _NO_SIGNAL_NOTE not in output


def test_an_invented_transcript_is_not_a_moment_to_ask_for_a_star(tmp_path, monkeypatch):
    """`_maybe_point_at_project` already refused after an empty transcript and after
    a dead microphone. A confident fabrication is the worst of the three."""
    import ast
    import pathlib as _pathlib

    source = (_pathlib.Path(__file__).resolve().parent.parent / "src/yazses/cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_maybe_point_at_project"
    ]
    assert calls, "_maybe_point_at_project is gone -- update this guard"
    guarded = [
        c for c in calls
        if any(
            isinstance(n, ast.Attribute) and n.attr == "no_speech" for kw in c.keywords
            for n in ast.walk(kw.value)
        )
    ]
    assert guarded, "the transcribe nudge no longer excludes an invented transcript"
