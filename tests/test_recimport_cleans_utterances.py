"""A recorded meeting of room noise was stored as a transcript reading ". . .".

Found in the real meeting folder on this machine. An 11.6-second capture finalized as:

    meeting.json    {"duration_s": 11.6, "num_speakers": 0, "status": "done"}
    transcript.md   ". . ."
    transcript.json {"text": ". . .", "utterances": [{"text": ". . ."}],
                     "words": [{"text": "."}, {"text": "."}, {"text": "."}]}

`status: "done"`, listed by `yazses meeting list` like any other meeting.

## The rule existed and was applied on one path only

The daemon injects what survives `clean_text`, never what the model returned — that is why
a dictated `[BLANK_AUDIO]` is discarded instead of typed, and why `yazses verify` was
changed to run it before certifying anything. `clean_text` appeared nowhere in `recimport/`
or `meeting/`, so both file paths stored Whisper's artefacts as content.

One rule, one implementation, applied at the single point both callers share
(`recimport.pipeline.transcribe_file`, which `meeting.finalize` wraps).

## Why `silent_input` did not catch it, and could not

`transcribe_file` already computes `carries_no_signal(audio)`, and its docstring is right
about why: *"Whisper answers silence with a confident hallucination, so the empty transcript
check cannot see it."* But it measures the **peak** of the input, deliberately — an hour of
sparse interview must not be called silent. A quiet room is not digital silence, so
`silent_input` was False here.

The two checks answer different questions and both are needed: `silent_input` asks *was
anything recorded at all*, this asks *did any of it survive cleaning*.

(Separately: `silent_input` is consumed only by `yazses transcribe`. `meeting.finalize`
wraps the same pipeline and drops it, so a meeting recorded against a dead microphone gets
no warning at all. Not fixed here — it needs a `meeting.json` field and a display for it.)

## Deliberately narrow

`words` are left untouched. They are timing data feeding alignment and subtitle spans, and
an index into them is not this function's to invalidate.

A leading ellipsis is stripped from real speech ("...and then we left" → "and then we
left"), which is a small loss of trailing-in nuance in a transcript. It is the same trade
the dictation path already makes, and it is the price of one rule rather than two.
"""

from __future__ import annotations

import pytest

from yazses.recimport.align import Utterance
from yazses.recimport.pipeline import cleaned_utterance


@pytest.mark.parametrize(
    "artefact", [". . .", ".", "[BLANK_AUDIO]", "(blank)", "   ", "", " . "]
)
def test_an_artefact_utterance_is_dropped_not_emptied(artefact: str) -> None:
    """Dropped, so a caller counting utterances sees the truth."""
    assert cleaned_utterance(Utterance("S1", 0.0, 1.0, artefact)) is None


@pytest.mark.parametrize(
    "spoken,expected",
    [
        (" Hello there.", "Hello there."),
        ("Okay.", "Okay."),
        ("...and then we left", "and then we left"),
        ("Well... I think so.", "Well... I think so."),
        ("- So I said no.", "- So I said no."),
    ],
)
def test_real_speech_survives(spoken: str, expected: str) -> None:
    """The expensive direction: a cleaner that dropped speech would destroy a meeting."""
    out = cleaned_utterance(Utterance("S1", 0.0, 1.0, spoken))
    assert out is not None
    assert out.text == expected


def test_speaker_and_timings_are_preserved() -> None:
    """Cleaning is a text operation; alignment must be untouched by it."""
    out = cleaned_utterance(Utterance("SPEAKER_02", 3.25, 9.5, "  Right, so the plan is this."))
    assert out is not None
    assert (out.speaker, out.start, out.end) == ("SPEAKER_02", 3.25, 9.5)


def test_a_meeting_of_room_noise_produces_an_empty_transcript() -> None:
    """End to end through the real pipeline, with the engine and diarizer injected.

    This is the recorded case: three word-level "." spanning 11.6 s.
    """
    from yazses.recimport.pipeline import transcribe_file

    class _Word:
        def __init__(self, text, start, end):
            self.text, self.start, self.end = text, start, end

    class _Engine:
        def transcribe_words(self, audio, sample_rate, task=None):
            return ". . .", [_Word(".", 0.0, 0.54), _Word(".", 0.54, 1.06),
                             _Word(".", 10.48, 11.56)]

    class _Cfg:
        language = "en"
        diarize = False
        min_speaker_seconds = 3.0
        name_threshold = 0.5

    import numpy as np

    result = transcribe_file(
        "unused.wav", _Cfg(),
        audio=np.full(16000, 0.004, dtype=np.float32),
        sample_rate=16000,
        engine=_Engine(),
        diarizer=None,
    )
    assert result.text == "", f"stored {result.text!r} as a transcript"
    assert result.utterances == []


def test_a_real_recording_still_produces_a_transcript() -> None:
    """A pipeline that emptied everything would pass the test above."""
    from yazses.recimport.pipeline import transcribe_file

    class _Word:
        def __init__(self, text, start, end):
            self.text, self.start, self.end = text, start, end

    class _Engine:
        def transcribe_words(self, audio, sample_rate, task=None):
            return " We should ship on Friday.", [
                _Word("We", 0.0, 0.3), _Word("should", 0.3, 0.6),
                _Word("ship", 0.6, 0.9), _Word("on", 0.9, 1.1),
                _Word("Friday.", 1.1, 1.5),
            ]

    class _Cfg:
        language = "en"
        diarize = False
        min_speaker_seconds = 3.0
        name_threshold = 0.5

    import numpy as np

    result = transcribe_file(
        "unused.wav", _Cfg(),
        audio=np.full(16000, 0.05, dtype=np.float32),
        sample_rate=16000,
        engine=_Engine(),
        diarizer=None,
    )
    assert result.text == "We should ship on Friday."
    assert len(result.utterances) == 1
    assert result.utterances[0].text == "We should ship on Friday."


def test_the_rule_has_one_implementation() -> None:
    """It was applied on the dictation path only; both file paths stored raw output."""
    import inspect

    from yazses.recimport import pipeline

    assert "clean_text" in inspect.getsource(pipeline), (
        "the shared file/meeting pipeline no longer cleans — Whisper artefacts will be "
        "stored as transcript content again"
    )
