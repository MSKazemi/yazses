"""Pure speaker-name resolution — ADR-v2-125 (recimport/naming.py)."""
from __future__ import annotations

import numpy as np

from yazses.recimport.align import Utterance
from yazses.recimport.naming import resolve_names


def _utts(*spec):
    return [Utterance(spk, s, e, "…") for (spk, s, e) in spec]


class _FakeEmbedder:
    def __init__(self, vector):
        self._v = np.asarray(vector, dtype="float32")

    def embed(self, audio, sample_rate=16000):
        class _E:
            vector = self._v
        return _E()


def test_anonymous_labels_by_first_appearance():
    names = resolve_names(_utts(("speaker_1", 0, 1), ("speaker_0", 1, 2)))
    # first-seen is speaker_1 → "Speaker 1"
    assert names == {"speaker_1": "Speaker 1", "speaker_0": "Speaker 2"}


def test_positional_names_in_order():
    names = resolve_names(_utts(("speaker_0", 0, 1), ("speaker_1", 1, 2)),
                          names=["Alice", "Bob"])
    assert names == {"speaker_0": "Alice", "speaker_1": "Bob"}


def test_explicit_rename_wins():
    names = resolve_names(_utts(("speaker_0", 0, 1), ("speaker_1", 1, 2)),
                          names=["Alice", "Bob"], renames={"speaker_1": "Carol"})
    assert names["speaker_1"] == "Carol"


def test_voiceprint_names_matching_cluster():
    utts = _utts(("speaker_0", 0.0, 4.0))  # ≥3s
    names = resolve_names(
        utts, embedder=_FakeEmbedder([1, 0, 0]),
        audio=np.ones(16000 * 5, dtype="float32"),
        profiles={"You": np.array([1, 0, 0], dtype="float32")},
        min_speaker_seconds=3.0, name_threshold=0.5,
    )
    assert names["speaker_0"] == "You"


def test_voiceprint_rejects_below_threshold():
    utts = _utts(("speaker_0", 0.0, 4.0))
    names = resolve_names(
        utts, embedder=_FakeEmbedder([0, 1, 0]),  # orthogonal → cosine 0
        audio=np.ones(16000 * 5, dtype="float32"),
        profiles={"You": np.array([1, 0, 0], dtype="float32")},
        min_speaker_seconds=3.0, name_threshold=0.5,
    )
    assert names["speaker_0"] == "Speaker 1"  # unknown → anonymous


def test_voiceprint_skipped_for_short_cluster():
    utts = _utts(("speaker_0", 0.0, 1.5))  # < 3s → never voice-named even if it'd match
    names = resolve_names(
        utts, embedder=_FakeEmbedder([1, 0, 0]),
        audio=np.ones(16000 * 5, dtype="float32"),
        profiles={"You": np.array([1, 0, 0], dtype="float32")},
        min_speaker_seconds=3.0, name_threshold=0.5,
    )
    assert names["speaker_0"] == "Speaker 1"
