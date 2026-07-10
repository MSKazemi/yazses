"""Meeting finalize pipeline (batch diarization + opt-in notes) — ADR-v2-127/128."""
from __future__ import annotations

import dataclasses
import json

import numpy as np

from yazses.config import MeetingConfig
from yazses.meeting.finalize import finalize_meeting
from yazses.postprocess.prosody import Word
from yazses.recimport.diarizer import DiarTurn

WORDS = [
    Word("hello", 0.0, 0.4, 0.9),
    Word("there", 0.5, 0.9, 0.9),
    Word("general", 2.0, 2.6, 0.9),
    Word("kenobi", 2.7, 3.1, 0.9),
]


class _FakeEngine:
    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "hello there general kenobi", list(WORDS)


class _FakeDiarizer:
    def diarize(self, audio, sample_rate=16000):
        return [DiarTurn(0.0, 1.2, "speaker_0"), DiarTurn(1.8, 3.4, "speaker_1")]


def _cfg(**kw):
    return dataclasses.replace(MeetingConfig(diarize=True), **kw)


def _audio():
    return np.zeros(16000, dtype="float32")


def test_finalize_diarizes_and_skips_notes_by_default():
    res = finalize_meeting(_audio(), _cfg(), engine=_FakeEngine(), diarizer=_FakeDiarizer())
    assert res.transcript.diarized is True
    assert {u.speaker for u in res.transcript.utterances} == {"speaker_0", "speaker_1"}
    assert res.minutes is None


def test_finalize_generates_notes_when_enabled():
    reply = json.dumps({"summary": "Shipped.", "decisions": ["ship"], "action_items": []})
    res = finalize_meeting(
        _audio(), _cfg(notes=True), engine=_FakeEngine(), diarizer=_FakeDiarizer(),
        llm=lambda p: reply,
    )
    assert res.minutes is not None
    assert res.minutes.summary == "Shipped."


def test_finalize_degrades_without_diarizer():
    res = finalize_meeting(_audio(), _cfg(diarize=False), engine=_FakeEngine(), diarizer=None)
    assert res.transcript.diarized is False
    assert res.transcript.text == "hello there general kenobi"
