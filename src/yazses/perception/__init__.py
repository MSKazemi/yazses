"""Shared camera perception — one webcam, derived signals, several consumers (ADR-v2-145).

Gaze routing, the Head-Pointer and face-gesture switches all want the same
FaceLandmarker result. This package holds the boundary between the one source that
owns the camera and the features that consume it: immutable, timestamped, derived
values that carry no frame, no MediaPipe object and no optional dependency.

``signals`` is pure and always importable. The camera/model lifecycle that fills
these values lives behind the existing optional extras.
"""
from yazses.perception.signals import (
    FacePerceptionSource,
    FaceSignal,
    GazeSignal,
    HeadPoseSignal,
    PerceptionSample,
)

__all__ = [
    "FacePerceptionSource",
    "FaceSignal",
    "GazeSignal",
    "HeadPoseSignal",
    "PerceptionSample",
]
