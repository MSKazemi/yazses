"""A minutes failure must never cost the meeting transcript.

The two halves of `finalize_meeting` are not equally valuable. The transcript is an hour
of audio decoded and diarized, and by default the recording is **deleted** once finalize
succeeds — so it is expensive and, after that, irreplaceable. The minutes are an opt-in
extra produced by a local LLM that may be missing, out of memory, or simply wrong.

The ordering made the cheap half able to destroy the expensive one:

    result  = transcribe_file(...)        # the transcript exists here
    minutes = generate_minutes(...)       # ...a raise here...
    return MeetingResult(...)             # ...means this never returns, and the caller
                                          #    only writes the transcript once it has a
                                          #    result

Nothing escaped `generate_minutes` in practice — every window is guarded, the reduce is
guarded, and `_build_llm` returns `None` on anything at all. That is exactly why this is
worth pinning at the boundary instead: the invariant is a property of *this* function's
contract, not of a distant module's internals, and it should not silently depend on them
staying careful.

Verified while auditing, and worth recording: the daemon already keeps the recording when
finalize raises ("the recording has been KEPT … it is not deleted until finalize
succeeds"), so this was a lost *attempt* rather than a lost meeting. This makes it not
even that.
"""

from __future__ import annotations

import pytest

from yazses.meeting.finalize import finalize_meeting


class _Cfg:
    """Minimal duck-typed MeetingConfig with notes on and diarization off."""

    notes = True
    diarize = False
    notes_window_turns = 40
    model = "tiny.en"
    language = "en"
    name_from_voiceprints = False


class _Engine:
    """A stand-in STT engine: enough for `transcribe_file` to produce a transcript."""

    def transcribe_words(self, audio, sample_rate, **kw):
        from types import SimpleNamespace

        # (text, words) -- in that order. Getting it backwards put the word list in
        # `TranscriptResult.text`, which is how I learned it.
        return "hello", [SimpleNamespace(start=0.0, end=1.0, text="hello")]

    def transcribe(self, audio, sample_rate=16000, **kw):
        return "hello"


def _audio():
    import numpy as np

    return np.zeros(16000, dtype="float32")


def test_the_transcript_survives_a_notes_explosion(monkeypatch) -> None:
    """The guard this file exists for: `generate_minutes` itself raising.

    Patched at the source rather than fed a broken LLM, because a broken LLM does NOT
    reach the boundary -- `generate_minutes` catches it per window. That is what makes
    this worth pinning: the transcript's safety currently rests on another module's
    internal care, and this asserts the boundary holds on its own.
    """
    import yazses.meeting.notes as notes_mod

    def _boom(*a, **kw):
        raise RuntimeError("the notes model ran out of memory")

    monkeypatch.setattr(notes_mod, "generate_minutes", _boom)

    result = finalize_meeting(
        _audio(), _Cfg(), engine=_Engine(), llm=lambda p: "{}", sample_rate=16000
    )
    assert result.transcript is not None, "a notes failure took the transcript with it"
    assert result.transcript.text == "hello"
    assert result.minutes is None


def test_a_broken_llm_never_even_reaches_the_boundary() -> None:
    """Recorded because it is why the guard looks unnecessary until it is not.

    `generate_minutes` guards each window and the reduce, and `_build_llm` returns None
    on anything, so an exploding LLM yields empty minutes rather than an exception.
    """

    def _exploding_llm(prompt: str) -> str:
        raise RuntimeError("the notes model ran out of memory")

    result = finalize_meeting(
        _audio(), _Cfg(), engine=_Engine(), llm=_exploding_llm, sample_rate=16000
    )
    assert result.transcript.text == "hello"
    assert result.minutes is None


def test_the_failure_leaves_no_half_built_minutes() -> None:
    """Better nothing than a partial set presented as the meeting's decisions."""

    def _exploding_llm(prompt: str) -> str:
        raise RuntimeError("boom")

    result = finalize_meeting(
        _audio(), _Cfg(), engine=_Engine(), llm=_exploding_llm, sample_rate=16000
    )
    assert result.minutes is None


def test_working_notes_are_still_produced() -> None:
    """A guard that swallowed everything would pass both tests above."""

    def _good_llm(prompt: str) -> str:
        return '{"summary": "we agreed to ship", "decisions": ["ship on Friday"]}'

    result = finalize_meeting(
        _audio(), _Cfg(), engine=_Engine(), llm=_good_llm, sample_rate=16000
    )
    assert result.minutes is not None
    assert result.minutes.summary == "we agreed to ship"
    assert result.minutes.decisions == ["ship on Friday"]


def test_notes_off_means_no_minutes_and_no_llm_call() -> None:
    class _Off(_Cfg):
        notes = False

    called = []

    def _llm(prompt: str) -> str:
        called.append(prompt)
        return "{}"

    result = finalize_meeting(
        _audio(), _Off(), engine=_Engine(), llm=_llm, sample_rate=16000
    )
    assert result.minutes is None
    assert not called, "the notes path ran while [meeting] notes was off"
    assert result.transcript is not None


def test_a_transcription_failure_is_still_fatal() -> None:
    """Only the *optional* half is guarded.

    If the transcript itself cannot be produced there is nothing to keep, and swallowing
    that would hand the caller an empty result to write out as a finished meeting.
    """

    class _BrokenEngine:
        def transcribe_words(self, *a, **kw):
            raise RuntimeError("model failed to load")

        def transcribe(self, *a, **kw):
            raise RuntimeError("model failed to load")

    with pytest.raises(Exception):
        finalize_meeting(_audio(), _Cfg(), engine=_BrokenEngine(), sample_rate=16000)
