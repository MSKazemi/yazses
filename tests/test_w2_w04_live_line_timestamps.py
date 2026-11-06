"""A live-transcript line is stamped where its words BEGAN in the recording.

Before this fix the worker stamped each line with `MeetingSession.elapsed_s()` at the
moment the decode *finished*: the utterance's end, plus the 700 ms hangover, plus the
decode time, plus any queue backlog. `live-transcript.md` exists to be the readable
record when the batch transcript cannot be trusted, and its `[MM:SS]` stamps pointed
past the speech they labelled -- by at least the utterance's own length.

The sample position is the same timeline as `audio.wav` and the batch transcript's word
timings, so the expected values below are exact, not tolerances.
"""
from __future__ import annotations

import numpy as np

from yazses.config import MeetingConfig
from yazses.meeting import store
from yazses.meeting.controller import MeetingController
from yazses.meeting.segmenter import UtteranceSegmenter

SR = 1000  # 100-sample chunks are 0.1 s each


def _silent(chunk):
    return not np.asarray(chunk).any()


def _voiced():
    return np.ones(100, dtype="float32")


def _quiet():
    return np.zeros(100, dtype="float32")


class _Engine:
    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, sample_rate=16000):
        self.calls += 1
        return f"sentence {self.calls}"


# --- the pure segmenter -------------------------------------------------------------


def _seg(**kw):
    return UtteranceSegmenter(
        _silent, sample_rate=SR, hangover_ms=300, min_utterance_ms=200, **kw
    )


def test_last_start_counts_the_dropped_leading_silence():
    seg = _seg()
    for _ in range(5):            # 0.0-0.5 s of silence, dropped from the buffer
        assert seg.push(_quiet()) is None
    for _ in range(3):            # speech starts at 0.5 s
        assert seg.push(_voiced()) is None
    emitted = [seg.push(_quiet()) for _ in range(3)]  # 0.3 s hangover closes it
    assert emitted[-1] is not None
    assert seg.last_start_s == 0.5


def test_second_utterance_is_stamped_from_its_own_start():
    seg = _seg()
    emitted = []
    script = [_voiced()] * 3 + [_quiet()] * 3 + [_quiet()] * 4 + [_voiced()] * 2 + [_quiet()] * 3
    for chunk in script:
        if seg.push(chunk) is not None:
            emitted.append(seg.last_start_s)
    # First utterance at 0.0 s; it closes after 0.6 s. Four more silent chunks are
    # leading silence for the next one, which starts at 1.0 s.
    assert emitted == [0.0, 1.0]


def test_a_hard_cut_continuation_starts_where_the_cut_fell():
    seg = _seg(max_utterance_ms=500)
    starts = []
    for _ in range(12):
        if seg.push(_voiced()) is not None:
            starts.append(seg.last_start_s)
    assert starts == [0.0, 0.5]


def test_flush_at_stop_reports_the_tail_start():
    seg = _seg()
    for _ in range(4):
        seg.push(_quiet())
    for _ in range(3):
        seg.push(_voiced())
    assert seg.flush() is not None
    assert seg.last_start_s == 0.4


# --- end to end through the controller ----------------------------------------------


def _controller(tmp_path):
    cfg = MeetingConfig(output_dir=str(tmp_path))
    d = store.new_meeting(cfg, "m1")
    return MeetingController(cfg, d, "m1", engine=_Engine(), is_silent=_silent, sample_rate=SR)


def test_live_jsonl_stamps_are_utterance_starts_not_decode_times(tmp_path):
    ctl = _controller(tmp_path)
    ctl.start()
    for _ in range(5):            # 0.5 s of silence before anyone speaks
        ctl.feed(_quiet())
    for _ in range(3):            # utterance 1: 0.5-0.8 s
        ctl.feed(_voiced())
    for _ in range(12):           # hangover (0.7 s) closes it, then more silence
        ctl.feed(_quiet())
    for _ in range(4):            # utterance 2 starts at 2.0 s
        ctl.feed(_voiced())
    for _ in range(8):
        ctl.feed(_quiet())
    ctl.stop_capture()

    recs = store.read_live_lines(ctl.dir)
    assert [r["text"] for r in recs] == ["sentence 1", "sentence 2"]
    # On the old code these were the captured duration at decode time: >= 1.5 s and
    # >= 2.7 s, i.e. after each utterance had already ENDED.
    assert [r["t"] for r in recs] == [0.5, 2.0]


def test_the_readable_copy_carries_the_same_start_stamp(tmp_path):
    ctl = _controller(tmp_path)
    ctl.start()
    for _ in range(650):          # 65 s of silence
        ctl.feed(_quiet())
    for _ in range(3):
        ctl.feed(_voiced())
    for _ in range(8):
        ctl.feed(_quiet())
    ctl.stop_capture()

    md = store.live_markdown_path(ctl.dir).read_text(encoding="utf-8")
    assert "[01:05] sentence 1" in md
