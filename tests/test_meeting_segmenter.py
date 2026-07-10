"""Continuous-audio utterance segmentation (pure) — ADR-v2-127."""
from __future__ import annotations

import numpy as np

from yazses.meeting.segmenter import UtteranceSegmenter

SR = 1000  # tiny rate keeps sample maths readable


def _silent(chunk):
    return not np.asarray(chunk).any()


def _seg(**kw):
    return UtteranceSegmenter(
        _silent, sample_rate=SR, hangover_ms=300, min_utterance_ms=100,
        max_utterance_ms=1000, **kw,
    )


def _voiced(n=100):
    return np.ones(n, dtype="float32")


def _quiet(n=100):
    return np.zeros(n, dtype="float32")


def test_leading_silence_is_dropped():
    seg = _seg()
    assert seg.push(_quiet()) is None
    assert seg.push(_quiet()) is None


def test_utterance_emitted_after_hangover():
    seg = _seg()
    for _ in range(3):
        assert seg.push(_voiced()) is None      # 300 voiced samples
    assert seg.push(_quiet()) is None            # trailing 100
    assert seg.push(_quiet()) is None            # trailing 200
    utt = seg.push(_quiet())                     # trailing 300 == hangover → emit
    assert utt is not None
    assert utt.shape[0] == 600                   # 300 voiced + 300 silence


def test_hard_cut_at_max_length():
    seg = _seg()
    out = None
    for _ in range(10):                          # 10 * 100 = 1000 == max
        out = seg.push(_voiced())
    assert out is not None
    assert out.shape[0] == 1000


def test_flush_emits_pending_utterance():
    seg = _seg()
    seg.push(_voiced())
    seg.push(_voiced())                          # 200 >= min
    utt = seg.flush()
    assert utt is not None and utt.shape[0] == 200
    assert seg.flush() is None                   # nothing left


def test_flush_below_min_returns_none():
    seg = UtteranceSegmenter(_silent, sample_rate=SR, min_utterance_ms=500)
    seg.push(_voiced(100))
    assert seg.flush() is None
