"""The frame half of covered-camera detection (#923): pure, on synthetic frames only.

Every picture here is generated: there is no recording and no image file. The scenes that
must *not* read as covered (a dim room with a lit face, a plain wall, a face-less frame)
matter more than the one that must: a false "covered" pauses a hands-free input.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from yazses.perception.camera import probe_camera_cover
from yazses.perception.cover import (
    COVER_AFTER_S,
    MAX_GAP_S,
    PROBE_BLANK,
    PROBE_CLEAR,
    PROBE_DELAY_S,
    PROBE_MAX_DELAY_S,
    PROBE_UNKNOWN,
    CoverDetector,
    FrameStats,
    ProbeJudge,
    frame_stats,
    is_blank,
    is_clear,
    probe_delay,
)

BLANK = FrameStats(3.0, 1.0)
CLEAR = FrameStats(90.0, 40.0)


def _frame(level: float, noise: float = 0.0, *, gray: bool = False) -> np.ndarray:
    shape = (120, 160) if gray else (120, 160, 3)
    rng = np.random.default_rng(923)
    values = level + noise * rng.standard_normal(shape[:2])
    plane = np.clip(values, 0, 255).astype(np.uint8)
    return plane if gray else np.repeat(plane[:, :, None], 3, axis=2)


@pytest.mark.parametrize("gray", [False, True])
def test_a_covered_sensor_is_blank_even_with_sensor_noise(gray):
    stats = frame_stats(_frame(6, noise=2, gray=gray))
    assert stats is not None and is_blank(stats) and not is_clear(stats)


def test_a_dim_room_with_a_lit_face_is_not_covered():
    frame = _frame(6, noise=2)
    frame[30:90, 50:110] = 55  # a face lit by the screen
    stats = frame_stats(frame)
    assert stats is not None and not is_blank(stats) and is_clear(stats)


def test_a_dim_but_noisy_room_is_not_covered():
    stats = frame_stats(_frame(14, noise=10))
    assert stats is not None and not is_blank(stats)


@pytest.mark.parametrize("level", [40, 128, 250])
def test_an_even_bright_picture_is_not_covered(level):
    stats = frame_stats(_frame(level))  # a plain wall, or no face in view
    assert stats is not None and not is_blank(stats) and is_clear(stats)


def test_the_band_between_the_thresholds_is_neither():
    between = FrameStats(20.0, 6.0)
    assert not is_blank(between) and not is_clear(between)


def test_luminance_weights_the_bgr_channels():
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    frame[:, :, 1] = 100  # green
    stats = frame_stats(frame)
    assert stats is not None and stats.mean == pytest.approx(58.7, abs=0.1)


@pytest.mark.parametrize(
    "frame",
    [None, "frame", [[0, 0]], np.zeros((4, 4), dtype=np.float32), np.zeros((0, 0), np.uint8),
     np.zeros((4,), np.uint8)],
)
def test_anything_that_is_not_an_8_bit_picture_gives_no_verdict(frame):
    assert frame_stats(frame) is None


def _run(detector, stats, start, seconds, step=0.25):
    verdicts = []
    for i in range(int(seconds / step) + 1):
        verdicts.append(detector.observe(stats, start + i * step))
    return verdicts


def test_blank_frames_must_last_the_whole_window():
    detector = CoverDetector()
    verdicts = _run(detector, BLANK, 100.0, COVER_AFTER_S)
    assert verdicts[-1] is True
    assert not any(verdicts[:-1])


def test_one_picture_restarts_the_run():
    detector = CoverDetector()
    assert not any(_run(detector, BLANK, 0.0, COVER_AFTER_S - 0.5))
    detector.observe(CLEAR, COVER_AFTER_S)
    assert not any(_run(detector, BLANK, COVER_AFTER_S + 0.25, COVER_AFTER_S - 0.5))


def test_a_gap_is_not_evidence():
    detector = CoverDetector()
    # Two sparse readings far apart (gaze on its own camera reads once per hold).
    for i in range(20):
        assert detector.observe(BLANK, i * (MAX_GAP_S + 1.0)) is False


def test_too_few_frames_do_not_cover():
    detector = CoverDetector(min_frames=5, max_gap_s=10.0)
    assert detector.observe(BLANK, 0.0) is False
    assert detector.observe(BLANK, 9.0) is False


def test_probe_needs_consecutive_clear_frames():
    judge = ProbeJudge(clear_frames=3)
    for stats in (BLANK, CLEAR, CLEAR, BLANK, CLEAR, CLEAR):
        assert judge.feed(stats) is False
    assert judge.verdict == PROBE_BLANK
    assert judge.feed(CLEAR) is True
    assert judge.verdict == PROBE_CLEAR


def test_probe_with_no_frame_is_unknown():
    judge = ProbeJudge()
    judge.feed(None)
    assert judge.verdict == PROBE_UNKNOWN


def test_probe_delay_doubles_and_is_capped():
    assert probe_delay(0) == PROBE_DELAY_S
    assert probe_delay(1) == 2 * PROBE_DELAY_S
    assert probe_delay(50) == PROBE_MAX_DELAY_S
    assert probe_delay(10**9) == PROBE_MAX_DELAY_S


# ---------------------------------------------------------------- the probe's camera


class _Cap:
    def __init__(self, frames, opened=True, boom=False):
        self._frames = list(frames)
        self._opened = opened
        self._boom = boom
        self.reads = 0
        self.released = 0

    def isOpened(self):  # noqa: N802 - cv2 spelling
        return self._opened

    def read(self):
        self.reads += 1
        if self._boom:
            raise RuntimeError("device gone")
        if not self._frames:
            return False, None
        frame = self._frames.pop(0) if len(self._frames) > 1 else self._frames[0]
        return True, frame

    def release(self):
        self.released += 1


def _probe(monkeypatch, cap, **kwargs):
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(VideoCapture=lambda index: cap))
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    return probe_camera_cover(0, clock=lambda: now[0], sleep=sleep, **kwargs)


def test_probe_stops_as_soon_as_there_is_a_picture(monkeypatch):
    cap = _Cap([_frame(2), _frame(2), _frame(120, noise=30)])
    assert _probe(monkeypatch, cap) == PROBE_CLEAR
    assert cap.reads == 5 and cap.released == 1


def test_probe_of_a_covered_camera_is_bounded_and_releases(monkeypatch):
    cap = _Cap([_frame(2)])
    assert _probe(monkeypatch, cap, window_s=1.0) == PROBE_BLANK
    assert cap.reads <= 12 and cap.released == 1


def test_probe_of_a_busy_camera_is_unknown(monkeypatch):
    cap = _Cap([], opened=False)
    assert _probe(monkeypatch, cap) == PROBE_UNKNOWN
    assert cap.reads == 0 and cap.released == 1


def test_probe_never_raises(monkeypatch):
    cap = _Cap([], boom=True)
    assert _probe(monkeypatch, cap) == PROBE_UNKNOWN
    assert cap.released == 1


def test_a_cancelled_probe_reads_nothing_and_releases(monkeypatch):
    cap = _Cap([_frame(120, noise=30)])
    assert _probe(monkeypatch, cap, cancelled=lambda: True) == PROBE_UNKNOWN
    assert cap.reads == 0 and cap.released == 1


def test_probe_without_opencv_is_unknown(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", None)  # makes `import cv2` raise
    assert probe_camera_cover(0) == PROBE_UNKNOWN
