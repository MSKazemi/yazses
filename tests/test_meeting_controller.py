"""Live-meeting controller: capture → live transcript → finalize — ADR-v2-127."""
from __future__ import annotations

import dataclasses
import json

import numpy as np

from yazses.config import MeetingConfig
from yazses.meeting import store
from yazses.meeting.controller import MeetingController
from yazses.meeting.session import read_wav_mono_f32
from yazses.postprocess.prosody import Word
from yazses.recimport.diarizer import DiarTurn

SR = 1000


class _FakeEngine:
    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, sample_rate=16000):
        self.calls += 1
        return f"utterance {self.calls}"

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "hello there general kenobi", [
            Word("hello", 0.0, 0.4, 0.9), Word("there", 0.5, 0.9, 0.9),
            Word("general", 2.0, 2.6, 0.9), Word("kenobi", 2.7, 3.1, 0.9),
        ]


class _FakeDiarizer:
    def diarize(self, audio, sample_rate=16000):
        return [DiarTurn(0.0, 1.2, "speaker_0"), DiarTurn(1.8, 3.4, "speaker_1")]


def _silent(chunk):
    return not np.asarray(chunk).any()


def _cfg(tmp_path, **kw):
    return dataclasses.replace(
        MeetingConfig(output_dir=str(tmp_path), diarize=True), **kw
    )


def _controller(tmp_path, engine, **cfgkw):
    cfg = _cfg(tmp_path, **cfgkw)
    d = store.new_meeting(cfg, "m1")
    return MeetingController(
        cfg, d, "m1", engine=engine, is_silent=_silent, diarizer=_FakeDiarizer(),
        sample_rate=SR,
    )


def test_live_transcript_accumulates_lines(tmp_path):
    engine = _FakeEngine()
    ctl = _controller(tmp_path, engine)
    ctl.start()
    # one utterance: 300 voiced then 300 silence (hangover 700ms default = 700 samples)
    for _ in range(3):
        ctl.feed(np.ones(100, dtype="float32"))
    for _ in range(8):
        ctl.feed(np.zeros(100, dtype="float32"))
    ctl.stop_capture()
    assert engine.calls >= 1
    assert ctl.status()["line_count"] >= 1


def test_stop_capture_writes_wav(tmp_path):
    ctl = _controller(tmp_path, _FakeEngine(), live_transcript=False)
    ctl.start()
    ctl.feed(np.ones(SR, dtype="float32"))
    wav = ctl.stop_capture()
    assert wav.exists()
    audio = read_wav_mono_f32(wav)
    assert audio.shape[0] == SR


def test_finalize_writes_outputs_and_meta(tmp_path):
    ctl = _controller(tmp_path, _FakeEngine(), live_transcript=False)
    ctl.start()
    ctl.feed(np.ones(SR, dtype="float32"))
    wav = ctl.stop_capture()
    audio = read_wav_mono_f32(wav)
    info = ctl.finalize(audio)
    assert info["diarized"] is True
    assert info["num_speakers"] == 2
    d = ctl.dir
    assert (d / "transcript.json").exists()
    assert (d / "transcript.md").exists()
    meta = json.loads((d / "meeting.json").read_text())
    assert meta["status"] == "done"
    assert meta["num_speakers"] == 2
    # shows up in listings
    assert store.list_meetings(_cfg(tmp_path))[0]["id"] == "m1"


def test_finalize_names_enrolled_user_as_you(tmp_path):
    # a voiceprint that the fake embedder will match to speaker_0's centroid
    class _FakeEmbedder:
        def embed(self, audio, sample_rate=16000):
            return type("E", (), {"vector": np.array([1.0, 0.0], dtype="float32")})()

    cfg = _cfg(tmp_path, live_transcript=False, name_from_voiceprints=True,
               min_speaker_seconds=0.0, name_threshold=0.5)
    d = store.new_meeting(cfg, "m2")
    ctl = MeetingController(
        cfg, d, "m2", engine=_FakeEngine(), is_silent=_silent, diarizer=_FakeDiarizer(),
        embedder=_FakeEmbedder(), voiceprint=np.array([1.0, 0.0], dtype="float32"),
        sample_rate=SR,
    )
    ctl.start()
    ctl.feed(np.ones(4 * SR, dtype="float32"))
    audio = read_wav_mono_f32(ctl.stop_capture())
    info = ctl.finalize(audio)
    assert "You" in info["speakers"]
