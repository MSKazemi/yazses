"""`verify` judged the transcript, and never asked the recording.

Run for real in a quiet room with nobody speaking, 2026-08-20, this machine:

    [OK] Signal: level 0.0059 clears the gate (0.0040) — but only just (1.5x)…
    [OK] Transcription: heard "You"

    ✓ The whole chain ran: captured, heard, cleaned.

`test_verify_silence_verdict.py` explains why "You" is deliberately *not* treated as a
ghost phrase, and that decision is right: "You" is the commonest thing this model returns
for silence and also an ordinary English word somebody may have said, so no rule on the
**output** separates them, and a verify that wrongly fails sends someone to re-calibrate a
microphone that was fine.

The dilemma only exists on the output side. On the **input** side the question has an
answer, and this repo already computes it: `recimport/audio_io.holds_no_speech` runs the
Silero detector that `faster-whisper` bundles (nothing downloaded, nothing sent — ADR-011)
and was written for this exact hallucination. `yazses transcribe` asks it. `verify` did
not — so on the same room, the same minute and the same microphone, `transcribe` said
"no speech was recognised" while `verify` certified the pipeline.

Same shape as the hotkey and meeting-capture defects before it: both facts present, no
surface comparing them.

Everything here is injected, so none of it needs a microphone.
"""
from __future__ import annotations

import pathlib

import pytest

from yazses.system.verify import verify

SPEECH = pathlib.Path(__file__).resolve().parent.parent / "data/librispeech-sample/jfk.wav"


def _run(text: str = "You", *, speechless=None, level: float = 0.01):
    return verify(
        record=lambda: "AUDIO",
        level_of=lambda _a: level,
        threshold=0.001,
        transcribe=lambda _a: text,
        **({} if speechless is None else {"holds_no_speech": speechless}),
    )


def _step(result, name: str):
    return next((s for s in result.steps if s.name == name), None)


def test_a_recording_with_no_speech_in_it_is_the_broken_link():
    result = _run(speechless=lambda _a: True)
    assert not result.ok
    assert result.failure is not None and result.failure.name == "Speech"
    assert "no speech" in result.failure.detail


def test_the_transcript_is_never_asked_for_once_the_audio_has_no_speech():
    """Stopping early is this module's own rule, and here it also saves a decode.

    A transcript from speechless audio is invented by construction; printing it invites
    the user to weigh words that mean nothing.
    """
    asked = []
    verify(
        record=lambda: "AUDIO",
        level_of=lambda _a: 0.01,
        threshold=0.001,
        transcribe=lambda _a: asked.append(1) or "You",
        holds_no_speech=lambda _a: True,
    )
    assert asked == [], "the model was decoded anyway"


def test_speech_that_was_detected_changes_nothing():
    result = _run("You", speechless=lambda _a: False)
    assert result.ok
    assert _step(result, "Speech") is None, (
        "a passing run gains no new line -- the detector speaks only when it has "
        "something to report"
    )
    assert 'heard "You"' in _step(result, "Transcription").detail


def test_a_detector_that_cannot_answer_leaves_the_verdict_exactly_as_it_was():
    """`None` is 'unknown'. Inventing a verdict there is the failure this prevents."""
    result = _run("You", speechless=lambda _a: None)
    assert result.ok
    assert 'heard "You"' in _step(result, "Transcription").detail


def test_no_detector_at_all_leaves_the_verdict_exactly_as_it_was():
    """Every existing caller passes nothing, and must be unaffected."""
    result = _run("You")
    assert result.ok
    assert 'heard "You"' in _step(result, "Transcription").detail


def test_the_deliberate_you_decision_is_untouched_where_it_applies():
    """The pin in `test_verify_silence_verdict.py`, restated as the pair it now forms.

    Someone who really says "You" into a working microphone still passes; the audio is
    what tells the two cases apart, which is the whole reason this is not a text rule.
    """
    assert _run("You", speechless=lambda _a: False).ok
    assert not _run("You", speechless=lambda _a: True).ok


def test_a_level_below_the_gate_still_fails_on_the_gate():
    """Order matters: the gate names a fix the user can act on (`mic-level --set`).

    Reporting 'no speech' first would be true and useless — of course a recording below
    the silence gate holds no speech; the actionable fact is the gate.
    """
    called = []
    result = verify(
        record=lambda: "AUDIO",
        level_of=lambda _a: 0.0001,
        threshold=0.01,
        transcribe=lambda _a: "You",
        holds_no_speech=lambda _a: called.append(1) or True,
    )
    assert result.failure is not None and result.failure.name == "Signal"
    assert called == [], "the detector was run on audio already known to be too quiet"


# --- the detector itself, on real audio ----------------------------------------


@pytest.fixture(scope="module")
def detector():
    from yazses.recimport.audio_io import holds_no_speech

    return holds_no_speech


def test_real_speech_is_not_called_speechless(detector):
    """The expensive direction, on a real recording rather than a fake.

    A wrong `True` here is a `verify` that fails on a working machine — the exact cost
    `test_verify_silence_verdict.py` weighed when it chose not to judge the text.
    """
    from yazses.recimport.audio_io import load_audio

    audio, _sr = load_audio(SPEECH)
    verdict = detector(audio, 16000)
    if verdict is None:
        pytest.skip("the bundled Silero asset is unavailable here")
    assert verdict is False


def test_digital_silence_is_called_speechless(detector):
    import numpy as np

    verdict = detector(np.zeros(16000 * 3, dtype="float32"), 16000)
    if verdict is None:
        pytest.skip("the bundled Silero asset is unavailable here")
    assert verdict is True


def test_the_cli_asks_the_question_at_all():
    """The seam is optional, so a wiring that forgets it fails nothing else.

    That is precisely how this defect survived: `holds_no_speech` existed, `transcribe`
    called it, and the command people are sent to when dictation breaks did not.
    """
    import ast
    import inspect

    from yazses import cli

    tree = ast.parse(inspect.getsource(cli.verify))
    passed = {
        kw.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg
    }
    assert "holds_no_speech" in passed, (
        "`yazses verify` no longer hands the speech detector to `verify()`, so a silent "
        "room is certified again"
    )
