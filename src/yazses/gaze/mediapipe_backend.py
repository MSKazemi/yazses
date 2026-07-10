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

# MediaPipe iris (478-landmark) indices: iris centre + the two eye corners used to
# normalise the offset (so it is scale/distance-invariant).
_LEFT = (468, 33, 133)    # iris, outer corner, inner corner
_RIGHT = (473, 362, 263)


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

    @staticmethod
    def _offset(lm, iris: int, c1: int, c2: int) -> tuple[float, float]:
        """Iris centre offset from the eye midpoint, normalised by eye width."""
        cx = (lm[c1].x + lm[c2].x) / 2.0
        cy = (lm[c1].y + lm[c2].y) / 2.0
        width = abs(lm[c2].x - lm[c1].x) or 1e-6
        return (lm[iris].x - cx) / width, (lm[iris].y - cy) / width

    def estimate(self) -> tuple[float, float] | None:
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
        lm = result.face_landmarks[0]
        try:
            lx, ly = self._offset(lm, *_LEFT)
            rx, ry = self._offset(lm, *_RIGHT)
        except (IndexError, AttributeError):
            return None
        return ((lx + rx) / 2.0, (ly + ry) / 2.0)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
