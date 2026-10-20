"""Shared camera perception — one webcam, derived signals, several consumers (ADR-v2-145).

Gaze routing, the Head-Pointer and face-gesture switches all want the same
FaceLandmarker result. This package holds the boundary between the one source that
owns the camera and the features that consume it: immutable, timestamped, derived
values that carry no frame, no MediaPipe object and no optional dependency.

``signals`` is pure and always importable. ``source`` is the lifecycle that fills
those values — it owns the camera, the model and the capture loop, and takes both
of them from injected factories, so importing it still pulls in no camera
dependency. ``factory`` reads ``[perception]`` and returns ``None`` when there is
nothing to build, which is the shipped state.

``derive``, ``mediapipe_backend`` and ``camera`` are the MediaPipe half: the pure
arithmetic that turns one FaceLandmarker result into the three channels, the
processor that holds the one model, and the webcam behind it. Importing them still
costs no ``cv2`` and no ``mediapipe`` — both arrive inside the call that opens a
camera — so this whole package stays importable on a base install.
"""
from yazses.perception.camera import OpenCVFrameCapture, opencv_capture_factory
from yazses.perception.derive import (
    derive_face,
    derive_gaze,
    derive_head_pose,
)
from yazses.perception.factory import (
    CaptureFactory,
    ProcessorFactory,
    build_perception_source,
)
from yazses.perception.mediapipe_backend import (
    CHANNELS,
    MediapipeFaceProcessor,
    mediapipe_processor_factory,
)
from yazses.perception.signals import (
    FacePerceptionSource,
    FaceSignal,
    GazeSignal,
    HeadPoseSignal,
    PerceptionSample,
)
from yazses.perception.source import (
    FrameCapture,
    FrameProcessor,
    PerceptionLease,
    PerceptionStatus,
    SharedPerceptionSource,
    SourceState,
    Worker,
)

__all__ = [
    "CHANNELS",
    "CaptureFactory",
    "FacePerceptionSource",
    "FaceSignal",
    "FrameCapture",
    "FrameProcessor",
    "GazeSignal",
    "HeadPoseSignal",
    "MediapipeFaceProcessor",
    "OpenCVFrameCapture",
    "PerceptionLease",
    "PerceptionSample",
    "PerceptionStatus",
    "ProcessorFactory",
    "SharedPerceptionSource",
    "SourceState",
    "Worker",
    "build_perception_source",
    "derive_face",
    "derive_gaze",
    "derive_head_pose",
    "mediapipe_processor_factory",
    "opencv_capture_factory",
]
