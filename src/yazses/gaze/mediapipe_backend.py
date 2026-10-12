"""MediaPipe FaceLandmarker gaze backend (opencv + mediapipe — pip-installable).

A lightweight, CPU-only, fully-offline alternative to the L2CS backend: MediaPipe's
FaceLandmarker gives 478 landmarks including the iris centres, and the iris offset
within each eye is a stable 2D signal that tracks where you look. That raw offset
is what :meth:`estimate` returns — the calibration step fits the affine map from it
to screen coordinates, so no explicit angle model is needed (look-to-PANE is coarse
by design). The camera is opened lazily and frames are processed in-RAM, never
stored or transmitted (ADR-011).
"""
from __future__ import annotations

# The iris-offset arithmetic (landmark indices, eye-width normalisation, left/right
# agreement) lives in ``yazses.perception.derive`` -- the shared camera source derives
# its gaze channel with the same functions, so there is one copy instead of two that
# drift (#396). This backend is the *own-camera* path: still used by the calibration
# CLI, by installs with ``[perception]`` off, and wherever the shared source is not
# allowed to serve gaze.


class MediapipeGazeBackend:
    """Webcam gaze estimator over MediaPipe FaceLandmarker (normalised iris offset)."""

    def __init__(self, config) -> None:
        import cv2  # optional, pip-install
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        from yazses.gaze.download import ensure_face_landmarker

        self._cv2 = cv2
        self._mp = mp
        self._camera_index = config.camera_index
        self._cap = None
        model = getattr(config, "model_path", "") or str(ensure_face_landmarker())
        opts = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=model),
            num_faces=1,
            running_mode=vision.RunningMode.IMAGE,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(opts)

    @property
    def name(self) -> str:
        return "mediapipe"

    def _ensure_camera(self):
        if self._cap is None:
            self._cap = self._cv2.VideoCapture(self._camera_index)
        return self._cap

    def estimate(self) -> tuple[float, float] | None:
        sample = self.estimate_sample()
        return None if sample is None else sample.point

    def estimate_sample(self):
        """One gaze estimate with a real per-frame confidence, or None.

        Confidence comes from left/right eye agreement: the two eyes measure the
        same gaze independently, so their disagreement is a per-frame landmark
        quality signal (blur, extreme pose, occlusion). This is what makes
        ``[gaze] confidence_min`` effective for the default backend.
        """
        from yazses.gaze.confidence import GazeSample
        from yazses.perception.derive import derive_gaze

        cap = self._ensure_camera()
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        try:
            result = self._landmarker.detect(image)
        except Exception:
            return None
        if not getattr(result, "face_landmarks", None):
            return None
        # Timestamp 0.0: a GazeSample carries none, and derive_gaze only validates it.
        signal = derive_gaze(result.face_landmarks[0], 0.0)
        if signal is None:
            return None
        return GazeSample(signal.raw_x, signal.raw_y, signal.confidence)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
