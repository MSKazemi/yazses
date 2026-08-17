"""Tests for the end-to-end pipeline proof.

Each case is a way dictation fails while `yazses doctor` still reports everything green —
which is exactly why this check exists.
"""
from __future__ import annotations

import pytest

from yazses.system.verify import verify


def _ok(**over):
    kw = dict(
        record=lambda: "audio",
        level_of=lambda a: 0.01,
        threshold=0.004,
        transcribe=lambda a: "hello world",
    )
    kw.update(over)
    return kw


def test_a_healthy_pipeline_passes_every_step():
    result = verify(**_ok())

    assert result.ok
    assert result.failure is None
    assert [s.name for s in result.steps] == ["Capture", "Signal", "Transcription", "Injection"]


def test_injection_runs_and_receives_the_transcript():
    typed: list[str] = []

    result = verify(**_ok(), inject=typed.append)

    assert result.ok
    assert typed == ["hello world"]


def test_a_dead_microphone_is_named_as_the_broken_link():
    result = verify(**_ok(level_of=lambda a: 0.0))

    assert not result.ok
    assert result.failure is not None
    assert result.failure.name == "Signal"
    assert "muted, dead" in result.failure.detail


def test_a_gate_above_the_voice_is_reported_with_the_fix():
    """The exact failure that started all of this: speech below the threshold."""
    result = verify(**_ok(level_of=lambda a: 0.0023, threshold=0.0024))

    assert not result.ok
    assert result.failure.name == "Signal"
    assert "mic-level --set" in result.failure.detail
    assert "0.0023" in result.failure.detail


def test_an_empty_transcript_blames_the_model_not_the_microphone():
    """Audio cleared the gate, so the mic is fine — say so, or the user retunes it forever."""
    result = verify(**_ok(transcribe=lambda a: "   "))

    assert not result.ok
    assert result.failure.name == "Transcription"
    assert "model" in result.failure.detail


def test_a_capture_failure_stops_before_blaming_anything_downstream():
    def boom():
        raise OSError("no such device")

    result = verify(**_ok(record=boom))

    assert not result.ok
    assert [s.name for s in result.steps] == ["Capture"], "must not cascade"
    assert "no such device" in result.failure.detail


def test_an_injection_failure_is_distinguished_from_a_transcription_one():
    def boom(text):
        raise RuntimeError("xdotool not found")

    result = verify(**_ok(), inject=boom)

    assert not result.ok
    assert result.failure.name == "Injection"
    assert any(s.name == "Transcription" and s.ok for s in result.steps)


def test_a_model_crash_is_reported_rather_than_raised():
    def boom(audio):
        raise ValueError("model file corrupt")

    result = verify(**_ok(transcribe=boom))

    assert not result.ok
    assert result.failure.name == "Transcription"
    assert "model file corrupt" in result.failure.detail


@pytest.mark.parametrize("level", [0.0041, 0.5, 1.0])
def test_any_level_at_or_above_the_gate_passes(level):
    assert verify(**_ok(level_of=lambda a: level)).ok


def test_skipping_injection_is_recorded_honestly():
    result = verify(**_ok(), inject=None)

    injection = [s for s in result.steps if s.name == "Injection"][0]
    assert injection.ok and "skipped" in injection.detail


def test_the_transcription_line_shows_what_was_heard():
    """A word count cannot be checked against what you said; the words can.

    Run on a real machine in a quiet room with nobody speaking, `yazses verify`
    printed:

        [OK] Signal: level 0.0013 clears the gate (0.0005)
        [OK] Transcription: produced 1 word(s)
        ✓ Dictation works end to end on this machine.

    The one word was Whisper's silence hallucination. Ambient noise cleared the
    gate, the model answered near-silence with a confident word, and the command
    whose entire job is to prove the chain honestly certified it — which is the
    real failure mode for a muted or wrong microphone in a room with any noise in
    it, not for a user who simply said nothing.

    Deciding whether a word is invented is not reliable. Showing it is: the person
    running this is the one who knows what they said, so put the evidence in front
    of them rather than a number that cannot contradict anything.
    """
    result = verify(**_ok(transcribe=lambda a: "You"))
    line = next(s for s in result.steps if s.name == "Transcription")
    assert line.ok
    assert "You" in line.detail, (
        f"the transcript is the evidence and it is not shown: {line.detail!r}"
    )


def test_a_long_transcript_is_shortened_but_still_shown():
    """The detail is one line in a report; a paragraph of dictation must not own it."""
    words = " ".join(f"word{i}" for i in range(40))
    result = verify(**_ok(transcribe=lambda a: words))
    line = next(s for s in result.steps if s.name == "Transcription")
    assert line.ok
    assert "word0" in line.detail, "the beginning of what was heard must survive"
    assert len(line.detail) < 120, f"the line is unbounded: {len(line.detail)} chars"
    assert "40" in line.detail, "the full length must still be reported"
