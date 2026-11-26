"""pyannote.audio 4.x output shapes: exclusive diarization first, legacy still works (N2).

community-1 returns a ``DiarizeOutput`` dataclass carrying ``speaker_diarization`` (with
overlaps) and ``exclusive_speaker_diarization`` (one speaker per instant). The adapter
prefers the exclusive view, falls back to the regular one, and still reads a bare
``Annotation`` from a legacy pipeline. Everything here is a fake object: no torch, no
model, no network, so nothing needs a decoder-stack marker.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import numpy as np
import pytest

from yazses.recimport.align import assign_words_to_turns, merge_utterances
from yazses.recimport.diarizer import DiarTurn
from yazses.recimport.pyannote_backend import (
    PIPELINE_ID,
    annotation_to_turns,
    select_annotation,
    turns_from_pipeline_output,
)


class _Segment:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class _Annotation:
    def __init__(self, tracks):
        self._tracks = tracks

    def itertracks(self, yield_label=False):
        for start, end, label in self._tracks:
            yield _Segment(start, end), None, label


@dataclass
class _DiarizeOutput:
    """The shape of pyannote.audio 4.x ``DiarizeOutput`` (fields as upstream names them)."""
    speaker_diarization: object
    exclusive_speaker_diarization: object
    speaker_embeddings: object = None


# Two speakers who overlap between 1.5 s and 2.5 s.
_REGULAR = [(0.0, 2.5, "SPEAKER_00"), (1.5, 4.0, "SPEAKER_01")]
# The same diarization with the overlap resolved to one speaker per instant.
_EXCLUSIVE = [(0.0, 2.0, "SPEAKER_00"), (2.0, 4.0, "SPEAKER_01")]


def _output(exclusive=_EXCLUSIVE, regular=_REGULAR):
    return _DiarizeOutput(
        speaker_diarization=_Annotation(regular),
        exclusive_speaker_diarization=None if exclusive is None else _Annotation(exclusive),
    )


def _overlaps(turns):
    ordered = sorted(turns, key=lambda t: t.start)
    return [(a, b) for a, b in zip(ordered, ordered[1:]) if b.start < a.end]


def test_the_default_pipeline_is_still_3_1():
    """The pin moves only after a human measures (docs/benchmarks.md, N2)."""
    assert PIPELINE_ID == "pyannote/speaker-diarization-3.1"


def test_exclusive_view_is_preferred_when_present():
    annotation, kind = select_annotation(_output())
    assert kind == "exclusive"
    turns = annotation_to_turns(annotation)
    assert [(t.start, t.end) for t in turns] == [(0.0, 2.0), (2.0, 4.0)]


def test_exclusive_output_maps_to_dense_sorted_diarturns():
    turns = turns_from_pipeline_output(_output())
    assert all(isinstance(t, DiarTurn) for t in turns)
    assert [t.speaker for t in turns] == ["speaker_0", "speaker_1"]
    assert turns == sorted(turns, key=lambda t: t.start)
    assert _overlaps(turns) == []


def test_regular_view_is_used_when_exclusive_is_missing():
    annotation, kind = select_annotation(_output(exclusive=None))
    assert kind == "regular"
    turns = turns_from_pipeline_output(_output(exclusive=None))
    assert [(t.start, t.end) for t in turns] == [(0.0, 2.5), (1.5, 4.0)]


def test_a_legacy_bare_annotation_still_works():
    """pyannote 3.x, and a 4.x pipeline built with ``legacy=True``, return an Annotation."""
    annotation, kind = select_annotation(_Annotation(_REGULAR))
    assert kind == "legacy"
    turns = turns_from_pipeline_output(_Annotation(_REGULAR))
    assert [t.speaker for t in turns] == ["speaker_0", "speaker_1"]


def test_an_output_with_no_annotation_fails_by_name():
    with pytest.raises(RuntimeError, match="itertracks"):
        turns_from_pipeline_output(object())


def test_align_never_gives_one_word_to_two_speakers_on_exclusive_turns():
    """Inside the overlap the regular view makes the speaker a tie-break; the exclusive
    view makes it a fact. Every word gets exactly one speaker, and words in the overlap
    region go to whoever the exclusive view says holds the floor."""
    turns = turns_from_pipeline_output(_output())
    # Every instant is covered by at most one turn.
    for t in np.arange(0.0, 4.0, 0.01):
        active = [x for x in turns if x.start <= t < x.end]
        assert len(active) <= 1, (t, active)

    words = [(0.2, 0.6, "hello"), (1.6, 1.9, "there"), (2.1, 2.4, "hi"), (3.0, 3.5, "back")]
    assigned = assign_words_to_turns(words, turns)
    assert [a[3] for a in assigned] == ["hello", "there", "hi", "back"]
    speakers = [a[0] for a in assigned]
    assert all(isinstance(s, str) for s in speakers)
    assert speakers == ["speaker_0", "speaker_0", "speaker_1", "speaker_1"]

    utterances = merge_utterances(assigned)
    assert [(u.speaker, u.text) for u in utterances] == [
        ("speaker_0", "hello there"), ("speaker_1", "hi back")]


def test_diarize_reads_the_exclusive_view_through_the_adapter(monkeypatch):
    """End to end through ``PyannoteDiarizer`` with fake torch / pyannote modules."""

    class _Pipeline:
        def to(self, device):
            return self

        def __call__(self, payload, **kw):
            return _output()

    class _Factory:
        @staticmethod
        def from_pretrained(name, token=None):
            assert name == PIPELINE_ID
            return _Pipeline()

    class _NoGrad:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False

    torch_mod = types.ModuleType("torch")
    torch_mod.device = lambda name: name
    torch_mod.from_numpy = lambda a: a
    torch_mod.no_grad = _NoGrad
    pkg = types.ModuleType("pyannote")
    audio_mod = types.ModuleType("pyannote.audio")
    audio_mod.Pipeline = _Factory
    pkg.audio = audio_mod
    monkeypatch.setitem(sys.modules, "torch", torch_mod)
    monkeypatch.setitem(sys.modules, "pyannote", pkg)
    monkeypatch.setitem(sys.modules, "pyannote.audio", audio_mod)

    from yazses.recimport.pyannote_backend import PyannoteDiarizer

    class _Cfg:
        min_speakers = 0
        max_speakers = 0

    turns = PyannoteDiarizer(_Cfg()).diarize(np.zeros(16000, dtype="float32"))
    assert [(t.start, t.end, t.speaker) for t in turns] == [
        (0.0, 2.0, "speaker_0"), (2.0, 4.0, "speaker_1")]
