"""Meeting recording session lifecycle — ADR-v2-127."""
from __future__ import annotations

import wave

import numpy as np

from yazses.meeting.session import MeetingSession, WavFileSink


class _FakeSink:
    def __init__(self):
        self.chunks = []
        self.closed = False

    def write(self, chunk):
        self.chunks.append(np.asarray(chunk))

    def close(self):
        self.closed = True


def _clock_seq(values):
    it = iter(values)
    return lambda: next(it)


def test_append_streams_to_sink_and_tracks_duration(tmp_path):
    sink = _FakeSink()
    s = MeetingSession("m1", tmp_path, sample_rate=16000, sink=sink)
    s.append_chunk(np.ones(16000, dtype="float32"))
    s.append_chunk(np.ones(8000, dtype="float32"))
    assert len(sink.chunks) == 2
    assert abs(s.duration_s() - 1.5) < 1e-6


def test_stop_is_idempotent_and_closes_sink(tmp_path):
    sink = _FakeSink()
    s = MeetingSession("m1", tmp_path, sink=sink, started_at=100.0,
                       clock=_clock_seq([130.0]))
    path = s.stop()
    assert sink.closed is True
    assert s.ended_at == 130.0
    assert abs(s.elapsed_s() - 30.0) < 1e-6
    assert s.stop() == path                      # idempotent, no second clock read


def test_append_after_stop_is_noop(tmp_path):
    sink = _FakeSink()
    s = MeetingSession("m1", tmp_path, sink=sink)
    s.stop()
    s.append_chunk(np.ones(100, dtype="float32"))
    assert sink.chunks == []


def test_live_lines_collect_nonblank(tmp_path):
    s = MeetingSession("m1", tmp_path, sink=_FakeSink())
    s.add_live_line("  hello  ")
    s.add_live_line("")
    s.add_live_line("world")
    assert s.live_lines == ["hello", "world"]


def test_wav_sink_writes_readable_pcm(tmp_path):
    path = tmp_path / "audio.wav"
    sink = WavFileSink(path, sample_rate=16000)
    sink.write(np.zeros(16000, dtype="float32"))
    sink.close()
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000
        assert w.getnframes() == 16000
