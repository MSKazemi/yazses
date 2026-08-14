"""Pipeline + render + factory dormancy — ADR-v2-125 (recimport)."""
from __future__ import annotations

import dataclasses
import json

import numpy as np

from yazses.config import RecimportConfig
from yazses.postprocess.prosody import Word
from yazses.recimport.diarizer import DiarTurn
from yazses.recimport.factory import build_diarizer
from yazses.recimport.pipeline import transcribe_file
from yazses.recimport.render import render_transcript

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
    return dataclasses.replace(RecimportConfig(), **kw)


def _run(diarize):
    cfg = _cfg(diarize=diarize)
    diarizer = _FakeDiarizer() if diarize else None
    return transcribe_file(
        "x.wav", cfg, engine=_FakeEngine(), diarizer=diarizer,
        audio=np.zeros(16000, dtype="float32"),
    )


def test_plain_transcript_when_not_diarized():
    result = _run(diarize=False)
    assert result.diarized is False
    assert render_transcript(result, "txt").strip() == "hello there general kenobi"


def test_diarized_txt_has_speaker_labels():
    result = _run(diarize=True)
    assert result.diarized is True
    txt = render_transcript(result, "txt")
    assert txt == "Speaker 1: hello there\nSpeaker 2: general kenobi\n"


def test_diarized_markdown():
    result = _run(diarize=True)
    md = render_transcript(result, "md")
    assert "**Speaker 1:** hello there" in md
    assert "**Speaker 2:** general kenobi" in md


def test_json_is_lossless_with_per_word_speaker():
    result = _run(diarize=True)
    payload = json.loads(render_transcript(result, "json"))
    assert payload["diarized"] is True
    assert payload["words"][0] == {"start": 0.0, "end": 0.4, "text": "hello", "speaker": "speaker_0"}
    assert {u["name"] for u in payload["utterances"]} == {"Speaker 1", "Speaker 2"}


def test_srt_has_timestamps():
    result = _run(diarize=True)
    srt = render_transcript(result, "srt")
    assert "-->" in srt and "00:00:00,000" in srt


def test_names_flow_through_pipeline():
    cfg = _cfg(diarize=True)
    result = transcribe_file(
        "x.wav", cfg, engine=_FakeEngine(), diarizer=_FakeDiarizer(),
        audio=np.zeros(16000, dtype="float32"), names=["Alice", "Bob"],
    )
    assert render_transcript(result, "txt") == "Alice: hello there\nBob: general kenobi\n"


def test_factory_returns_none_when_diarize_off():
    assert build_diarizer(_cfg(diarize=False)) is None


def test_factory_returns_none_when_backend_none():
    assert build_diarizer(_cfg(diarize=True, backend="none")) is None


def test_factory_returns_none_when_extra_missing(monkeypatch):
    """A missing extra degrades to None rather than crashing.

    The import is forced to fail rather than assumed to fail. This used to rely
    on sherpa-onnx being absent from the environment, which made it a test of
    the machine: installing the `diarization` extra — which
    `yazses features enable meeting` does — turned it red with nothing wrong in
    the code.
    """
    import sys

    monkeypatch.setitem(sys.modules, "sherpa_onnx", None)
    for name in [m for m in sys.modules if m.startswith("yazses.recimport.diarizer")]:
        monkeypatch.delitem(sys.modules, name, raising=False)

    assert build_diarizer(_cfg(diarize=True, backend="sherpa")) is None


def test_factory_returns_none_for_unknown_backend():
    assert build_diarizer(_cfg(diarize=True, backend="bogus")) is None


def test_render_rejects_unknown_format():
    import pytest

    result = _run(diarize=False)
    with pytest.raises(ValueError):
        render_transcript(result, "docx")


def test_non_diarized_md_is_plain_text():
    result = _run(diarize=False)
    assert render_transcript(result, "md").strip() == "hello there general kenobi"


def test_empty_transcript_renders_empty():
    class _Silent:
        def transcribe_words(self, *a, **k):
            return "", []

    result = transcribe_file(
        "x.wav", _cfg(diarize=False), engine=_Silent(),
        audio=np.zeros(16000, dtype="float32"),
    )
    assert render_transcript(result, "txt") == ""
    assert result.utterances == []
