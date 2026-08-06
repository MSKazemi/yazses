"""Recording Import (ADR-v2-083) + Crowd-Proof Dictation (ADR-v2-084) — pure cores."""
from __future__ import annotations

import numpy as np

from yazses.crowdproof.frames import apply_target_mask, frame_signal, overlap_add
from yazses.recimport.subtitles import (
    format_timestamp,
    merge_word_timestamps,
    write_srt,
    write_vtt,
)

# ---- recording import ------------------------------------------------------

def test_format_timestamp():
    assert format_timestamp(3661.5, "srt") == "01:01:01,500"
    assert format_timestamp(3661.5, "vtt") == "01:01:01.500"
    assert format_timestamp(-1) == "00:00:00,000"
    assert format_timestamp(0.9999, "srt") == "00:00:01,000"   # ms rounding carries


def test_merge_word_timestamps_gap_and_length():
    words = [("hello", 0.0, 0.4), ("world", 0.5, 0.9), ("again", 3.0, 3.4)]
    segs = merge_word_timestamps(words, max_gap=0.8)
    assert segs == [(0.0, 0.9, "hello world"), (3.0, 3.4, "again")]


def test_write_srt_and_vtt():
    segs = [(0.0, 1.0, "hi there"), (1.0, 2.0, "bye")]
    srt = write_srt(segs)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,000\nhi there\n\n2\n")
    vtt = write_vtt(segs)
    assert vtt.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhi there")
    assert write_srt([]) == ""


# ---- crowd-proof framing ---------------------------------------------------

def test_frame_signal():
    frames = frame_signal([1, 2, 3, 4, 5], frame_len=2, hop=2)
    assert frames.shape == (2, 2)
    assert list(frames[0]) == [1.0, 2.0]
    assert frame_signal([1], 4, 2).shape == (0, 4)   # too short


def test_apply_target_mask():
    frames = np.array([[1.0, 1.0], [1.0, 1.0], [1.0, 1.0]])
    scores = [0.9, 0.1, 0.6]
    masked = apply_target_mask(frames, scores, threshold=0.5)
    assert list(masked[0]) == [1.0, 1.0]   # kept
    assert list(masked[1]) == [0.0, 0.0]   # attenuated (floor 0)
    assert list(masked[2]) == [1.0, 1.0]   # kept
    assert apply_target_mask(np.empty((0, 2)), [], 0.5).size == 0


def test_overlap_add_reconstructs_length():
    sig = np.sin(np.linspace(0, 6.28, 64))
    frames = frame_signal(sig, frame_len=16, hop=8)
    recon = overlap_add(frames, hop=8)
    assert len(recon) == (frames.shape[0] - 1) * 8 + 16
    assert overlap_add(np.empty((0, 4)), hop=2).size == 0


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "recimport" in slugs and "crowdproof" in slugs
    assert Config().recimport.enabled is False and Config().crowdproof.enabled is False
