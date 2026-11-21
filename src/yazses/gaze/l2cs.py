"""L2CS-Net gaze backend (l2cs + opencv — manual-install, see pyproject note).

Estimates gaze ``(yaw, pitch)`` from one webcam frame using the pretrained L2CS-Net
pipeline. Imported only when ``[gaze] enabled`` and the deps are installed; the
factory falls back to None otherwise, so look-to-pane stays dormant without them.
The camera is opened lazily and a frame is read only when ``estimate`` is called —
frames are processed in-RAM and never stored or transmitted (ADR-011).
"""
from __future__ import annotations

import threading


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

    def _ensure_camera(self):
        with self._camera_lock:
            if self._camera_off:
                return None  # switched off at runtime (perception/switch.py): hold nothing
            if self._cap is None:
                self._cap = self._cv2.VideoCapture(self._camera_index)
                if not self._cap.isOpened():
                    self._camera_failure = (
                        f"camera {self._camera_index} is in use or permission was denied"
                    )
                    self._cap.release()
                    self._cap = None
                    return None
                self._camera_failure = ""
            return self._cap

    # -- camera on/off switch (perception/switch.py) ---------------------------

    def pause_camera(self) -> None:
        """Release the device and stay off it until :meth:`resume_camera`."""
        with self._camera_lock:
            self._camera_off = True
            self.close()

    def set_camera_index(self, index: int) -> None:
        """Open camera *index* at the next (re)open."""
        self._camera_index = int(index)

    def resume_camera(self) -> None:
        """Reopen the device now, so ``camera status`` is truthful and a failure is reported.

        A busy or denied camera is recorded in :attr:`camera_failure`, never raised.
        """
        with self._camera_lock:
            self._camera_off = False
            try:
                self._ensure_camera()
            except Exception as exc:  # a driver error must not reach the switch
                self._camera_failure = f"could not open camera {self._camera_index}: {exc}"[:200]
                self._cap = None

    @property
    def camera_held(self) -> bool:
        return self._cap is not None

    @property
    def camera_failure(self) -> str:
        return self._camera_failure

    def estimate(self) -> tuple[float, float] | None:
        cap = self._ensure_camera()
        if cap is None:
            return None
        ok, frame = cap.read()
        if not ok or frame is None:
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
