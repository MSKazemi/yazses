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

import threading
import time

# The iris-offset arithmetic (landmark indices, eye-width normalisation, left/right
# agreement) lives in ``yazses.perception.derive`` -- the shared camera source derives
# its gaze channel with the same functions, so there is one copy instead of two that
# drift (#396). This backend is the *own-camera* path: still used by the calibration
# CLI, by installs with ``[perception]`` off, and wherever the shared source is not
# allowed to serve gaze.

#: Seconds to leave a camera that would not open alone before trying it again.
_OPEN_BACKOFF_S = 5.0


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
        self._camera_off = False
        self._camera_failure = ""
        self._camera_lock = threading.RLock()
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

    #: Earliest ``time.monotonic()`` at which a failed open may be retried.
    _open_retry_at = 0.0

    def _ensure_camera(self):
        with self._camera_lock:
            if self._camera_off:
                return None  # switched off at runtime (perception/switch.py): hold nothing
            if self._cap is None:
                if time.monotonic() < self._open_retry_at:
                    return None  # it failed a moment ago: do not retry on every frame
                self._cap = self._cv2.VideoCapture(self._camera_index)
                if not self._cap.isOpened():
                    self._camera_failure = (
                        f"camera {self._camera_index} is in use or permission was denied"
                    )
                    self._cap.release()
                    self._cap = None
                    self._open_retry_at = time.monotonic() + _OPEN_BACKOFF_S
                    return None
                self._camera_failure = ""
            return self._cap

    def _read_frame(self):
        """One frame, read under the camera lock so a pause cannot release it mid-read."""
        with self._camera_lock:
            cap = self._ensure_camera()
            if cap is None:
                return None
            ok, frame = cap.read()
        return frame if ok and frame is not None else None

    # -- camera on/off switch (perception/switch.py) ---------------------------

    def pause_camera(self) -> None:
        """Release the device and stay off it until :meth:`resume_camera`."""
        with self._camera_lock:
            self._camera_off = True
            self.close()

    def set_camera_index(self, index: int) -> None:
        """Open camera *index* at the next (re)open."""
        with self._camera_lock:
            self._camera_index = int(index)
            self._open_retry_at = 0.0

    def resume_camera(self) -> None:
        """Reopen the device now, so ``camera status`` is truthful and a failure is reported.

        A busy or denied camera is recorded in :attr:`camera_failure`, never raised.
        """
        with self._camera_lock:
            self._camera_off = False
            self._open_retry_at = 0.0  # an explicit "camera on" always tries now
            try:
                self._ensure_camera()
            except Exception as exc:  # a driver error must not reach the switch
                self._camera_failure = f"could not open camera {self._camera_index}: {exc}"[:200]
                self._cap = None
                self._open_retry_at = time.monotonic() + _OPEN_BACKOFF_S

    @property
    def camera_held(self) -> bool:
        return self._cap is not None

    @property
    def camera_failure(self) -> str:
        return self._camera_failure

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

        frame = self._read_frame()
        if frame is None:
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
