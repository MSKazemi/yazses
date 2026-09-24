"""Webcam face-gesture activation source — implements HotkeyBackend (#102).

Holds the "key" while a chosen facial movement is held: MediaPipe's FaceLandmarker
reports 52 blendshape activations per frame, :mod:`yazses.facegesture.detector`
turns one of them into hold-start / hold-end, and those are the same two callbacks
the keyboard hotkey, the command key and the EMG armband already drive
(``_build_activation_sources``, ADR-v2-129).

opencv and mediapipe are optional (the ``gaze`` extra — the same two packages, and
the same ~3.7 MB model, that Glance-Type already uses). Missing either makes
:meth:`run` a logged no-op rather than a startup failure, exactly like the EMG
backend. Frames are processed in-RAM and never stored or transmitted (ADR-011).
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from yazses.facegesture.detector import (
    DEFAULT_GESTURE,
    GESTURES,
    GestureSwitch,
    blendshape_scores,
    gesture_score,
)

log = logging.getLogger(__name__)


class FaceGestureBackend:
    """HotkeyBackend implementation driven by a held facial gesture.

    Conforms to the HotkeyBackend Protocol by duck-typing, like ``EMGBackend``.
    """

    def __init__(
        self,
        config,
        on_hold_start: Callable[[int], None] = lambda n: None,
        on_hold_end: Callable[[], None] = lambda: None,
    ) -> None:
        self._cfg = config
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end
        self._stop_event = threading.Event()
        # `.lower()` because `configcheck` validates enum values case-insensitively
        # and then stores what was written: without it `gesture = "Jaw_Open"` passes
        # config validation and is silently replaced by the default here.
        gesture = (getattr(config, "gesture", "") or DEFAULT_GESTURE).strip().lower()
        if gesture not in GESTURES:
            # Never silently substitute a *different* body movement: say which one
            # is being used, because the user will otherwise be holding a face the
            # daemon is not watching and have no way to find that out.
            log.warning(
                "[facegesture] gesture = %r is not a gesture; using %r. Valid values: %s.",
                gesture, DEFAULT_GESTURE, ", ".join(GESTURES),
            )
            gesture = DEFAULT_GESTURE
        self._gesture = gesture
        self._switch = GestureSwitch(
            hold_threshold=getattr(config, "hold_threshold", 0.5),
            release_threshold=getattr(config, "release_threshold", 0.35),
            min_hold_frames=getattr(config, "min_hold_frames", 3),
            min_release_frames=getattr(config, "min_release_frames", 2),
        )
        if self._switch.repaired_release:
            hold, release = self._switch.thresholds
            log.warning(
                "[facegesture] release_threshold must be below hold_threshold "
                "(otherwise the switch chatters); using %.2f / %.2f.", hold, release,
            )
        fps = int(getattr(config, "fps", 15) or 15)
        self._interval = 1.0 / max(1, min(60, fps))

    # ------------------------------------------------------------------
    # HotkeyBackend protocol
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Watch the camera and drive the hold callbacks until stop() is called."""
        landmarker = self._build_landmarker()
        if landmarker is None:
            return
        cap, cv2 = self._open_camera()
        if cap is None:
            if hasattr(landmarker, "close"):
                landmarker.close()
            return

        log.info(
            "Face-gesture switch watching %r (hold %.2f / release %.2f).",
            self._gesture, *self._switch.thresholds,
        )
        # Normally guaranteed: _build_landmarker imported mediapipe to build the
        # landmarker it just returned. That only holds while the seam is the real
        # one, and an absent optional extra must not skip the shutdown drain in the
        # finally below, so this resolves to None rather than raising past it.
        try:
            import mediapipe as mp  # noqa: PLC0415
        except ImportError:
            mp = None

        try:
            self._loop(landmarker, cap, cv2, mp)
        finally:
            # A hold open at shutdown would leave the daemon RECORDING with no key
            # to release, so the switch is drained before the camera goes away.
            if self._switch.reset() == "end":
                self._fire("end")
            try:
                cap.release()
            except Exception:
                log.debug("face-gesture: camera release failed", exc_info=True)
            if hasattr(landmarker, "close"):
                try:
                    landmarker.close()
                except Exception:
                    log.debug("face-gesture: landmarker close failed", exc_info=True)
            log.info("Face-gesture switch stopped.")

    def stop(self) -> None:
        """Signal run() to exit at the next frame."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_landmarker(self):
        """The FaceLandmarker with blendshapes on, or None with a reason logged."""
        try:
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision

            from yazses.gaze.download import ensure_face_landmarker
        except ImportError as exc:
            log.warning(
                "Face-gesture switch is enabled but mediapipe is not installed (%s); "
                "run: yazses features enable facegesture", exc,
            )
            return None
        try:
            model = (getattr(self._cfg, "model_path", "") or "").strip() or str(
                ensure_face_landmarker()
            )
            opts = vision.FaceLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=model),
                num_faces=1,
                output_face_blendshapes=True,
                running_mode=vision.RunningMode.IMAGE,
            )
            return vision.FaceLandmarker.create_from_options(opts)
        except Exception:
            log.warning("Face-gesture switch could not load the face model; "
                        "continuing without it.", exc_info=True)
            return None

    def _open_camera(self):
        try:
            import cv2  # noqa: PLC0415 - optional dependency, probed at run time
        except ImportError as exc:
            log.warning("Face-gesture switch is enabled but opencv is not installed "
                        "(%s); run: yazses features enable facegesture", exc)
            return None, None
        index = int(getattr(self._cfg, "camera_index", 0) or 0)
        try:
            cap = cv2.VideoCapture(index)
        except Exception:
            log.warning("Face-gesture switch could not open camera %d.", index, exc_info=True)
            return None, None
        if not cap.isOpened():
            log.warning("Face-gesture switch could not open camera %d "
                        "(in use, or no permission).", index)
            cap.release()
            return None, None
        return cap, cv2

    def _loop(self, landmarker, cap, cv2, mp) -> None:
        # Every heavy handle is injected rather than imported here: it keeps the
        # frame plumbing testable with fakes, which is the only way a mistake in
        # the three-deep MediaPipe result shape gets caught before a user's face.
        while not self._stop_event.is_set():
            started = time.monotonic()
            event = None
            try:
                event = self._switch.update(self._score(landmarker, cap, cv2, mp))
            except Exception:
                # One bad frame must not end the user's only input method. The
                # switch state is untouched, so a held gesture stays held.
                log.debug("face-gesture: frame failed", exc_info=True)
            if event is not None:
                self._fire(event)
            # Sleep on the stop event, so stop() is honoured within one frame
            # rather than after a full interval of an unrelated sleep.
            self._stop_event.wait(max(0.0, self._interval - (time.monotonic() - started)))

    def _score(self, landmarker, cap, cv2, mp) -> float | None:
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(image)
        shapes = getattr(result, "face_blendshapes", None)
        if not shapes:
            return None
        return gesture_score(blendshape_scores(shapes[0]), self._gesture)

    def _fire(self, event: str) -> None:
        """Call a daemon callback without letting it kill the capture thread."""
        try:
            if event == "start":
                self._on_hold_start(0)
            else:
                self._on_hold_end()
        except Exception:
            log.warning("face-gesture: %s callback raised", event, exc_info=True)
