"""L2CS-Net gaze backend (l2cs + opencv — manual-install, see pyproject note).

Estimates gaze ``(yaw, pitch)`` from one webcam frame using the pretrained L2CS-Net
pipeline. Imported only when ``[gaze] enabled`` and the deps are installed; the
factory falls back to None otherwise, so look-to-pane stays dormant without them.
The camera is opened lazily and a frame is read only when ``estimate`` is called —
frames are processed in-RAM and never stored or transmitted (ADR-011).
"""
from __future__ import annotations

import threading
import time

#: Seconds to leave a camera that would not open alone before trying it again.
_OPEN_BACKOFF_S = 5.0


class L2csGazeBackend:
    """Webcam gaze estimator over L2CS-Net."""

    def __init__(self, config) -> None:
        import cv2  # optional, manual-install
        import torch
        from l2cs import Pipeline

        self._cv2 = cv2
        self._camera_index = config.camera_index
        self._confidence_min = getattr(config, "confidence_min", 0.5)
        self._cap = None
        self._camera_off = False
        self._camera_failure = ""
        self._camera_lock = threading.RLock()
        self._pipeline = Pipeline(
            weights=None,            # l2cs resolves its bundled pretrained ResNet
            arch="ResNet50",
            device=torch.device("cpu"),
        )

    @property
    def name(self) -> str:
        return "l2cs"

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
        frame = self._read_frame()
        if frame is None:
            return None
        try:
            results = self._pipeline.step(frame)
        except Exception:
            return None
        if results is None or len(getattr(results, "pitch", [])) == 0:
            return None
        # L2CS returns arrays (one per detected face); take the first face.
        yaw = float(results.yaw[0])
        pitch = float(results.pitch[0])
        return (yaw, pitch)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
