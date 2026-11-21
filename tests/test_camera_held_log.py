"""The camera-held log line (#922): a video-call app says "camera not available" and nothing
in YazSes's logs says why. These tests pin the wording and the three places it is emitted.

Fakes only: no camera, no OpenCV, no real device is touched.
"""
from __future__ import annotations

import logging
import sys
from types import SimpleNamespace

from yazses.config import FacegestureConfig
from yazses.facegesture.backend import FaceGestureBackend
from yazses.perception.camera import OpenCVFrameCapture, camera_held_message


class _Cap:
    def __init__(self, opened=True):
        self._opened = opened
        self.released = False

    def isOpened(self):  # noqa: N802 - cv2 spelling
        return self._opened

    def release(self):
        self.released = True


def _fake_cv2(monkeypatch, opened=True):
    cap = _Cap(opened)
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(VideoCapture=lambda index: cap))
    return cap


def test_held_message_names_the_camera_the_cause_and_the_way_out():
    text = camera_held_message(2)
    assert "camera 2" in text
    assert "video calls" in text
    assert "systemctl --user stop yazses" in text
    assert "[facegesture]" in text


def test_released_message_says_the_camera_is_free_again():
    text = camera_held_message(0, released=True)
    assert "released" in text
    assert "cannot use it" not in text


def test_perception_capture_logs_hold_once_and_release_once(monkeypatch, caplog):
    _fake_cv2(monkeypatch)
    capture = OpenCVFrameCapture(1)
    with caplog.at_level(logging.INFO, logger="yazses.perception.camera"):
        capture.open()
        capture.open()  # already open: no second device, no second line
        capture.close()
        capture.close()  # idempotent: no second line
    messages = [r.getMessage() for r in caplog.records]
    assert messages == [camera_held_message(1), camera_held_message(1, released=True)]


def test_perception_capture_logs_nothing_when_the_open_fails(monkeypatch, caplog):
    _fake_cv2(monkeypatch, opened=False)
    capture = OpenCVFrameCapture(0)
    with caplog.at_level(logging.INFO, logger="yazses.perception.camera"):
        try:
            capture.open()
        except OSError:
            pass
    assert not [r for r in caplog.records if "holding camera" in r.getMessage()]


def test_face_switch_logs_hold_when_it_opens_its_own_camera(monkeypatch, caplog):
    cap = _fake_cv2(monkeypatch)
    backend = FaceGestureBackend(FacegestureConfig(enabled=True, camera_index=3), None)
    with caplog.at_level(logging.INFO, logger="yazses.facegesture.backend"):
        opened, _ = backend._open_camera()
    assert opened is cap
    assert camera_held_message(3) in [r.getMessage() for r in caplog.records]


def test_face_switch_busy_camera_warning_says_another_application_holds_it(monkeypatch, caplog):
    cap = _fake_cv2(monkeypatch, opened=False)
    backend = FaceGestureBackend(FacegestureConfig(enabled=True), None)
    with caplog.at_level(logging.INFO, logger="yazses.facegesture.backend"):
        assert backend._open_camera() == (None, None)
    assert cap.released
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "another application holds it" in text
    assert "holding camera" not in text
