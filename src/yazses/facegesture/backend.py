"""Webcam face-gesture activation source — implements HotkeyBackend (#102).

Holds the "key" while a chosen facial movement is held: MediaPipe's FaceLandmarker
reports 52 blendshape activations per frame, :mod:`yazses.facegesture.detector`
turns each watched gesture into hold-start / hold-end, and this module turns those
into **switch intents** (ADR-v2-147) -- ``SwitchIntent(gesture, press|release)`` --
and nothing else. It never calls a desktop action. What an intent *does* is decided
by :class:`yazses.facegesture.switches.SwitchMapper`, which is the only place a
gesture meets an action; the default mapping binds the one configured gesture to the
same two hold callbacks the keyboard hotkey, the command key and the EMG armband
drive (``_build_activation_sources``, ADR-v2-129), so a single-gesture install behaves
exactly as before.

opencv and mediapipe are optional (the ``gaze`` extra — the same two packages, and
the same ~3.7 MB model, that Glance-Type already uses). Missing either makes
:meth:`run` a logged no-op rather than a startup failure, exactly like the EMG
backend. Frames are processed in-RAM and never stored or transmitted (ADR-011).
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping

from yazses.facegesture.calibration import Baseline, Reading
from yazses.facegesture.detector import (
    DEFAULT_GESTURE,
    GESTURES,
    GestureSwitch,
    blendshape_scores,
    gesture_score,
)
from yazses.facegesture.switches import (
    SwitchAction,
    SwitchIntent,
    SwitchMapper,
    legacy_action,
    make_intent,
    parse_bindings,
)
from yazses.perception.mediapipe_backend import DEFAULT_PRESENCE_CONFIDENCE

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
        *,
        baselines: Mapping[str, Baseline] | None = None,
        on_intent: Callable[[SwitchIntent], object] | None = None,
        actions: Mapping[str, SwitchAction] | None = None,
        safety=None,
    ) -> None:
        # `on_hold_start` / `on_hold_end` are the handlers for the one legacy binding
        # (`gesture` + `mode`). `actions` supplies handlers for every other abstract
        # action the daemon implements, `safety` is the optional hands-free gate, and
        # `on_intent` replaces the whole default mapping with a caller's own sink.
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

        # The mapping: which gesture means which abstract action. With no
        # `[[facegesture.switches]]` this is exactly {gesture: hold-to-talk/command}.
        mode = getattr(config, "mode", "full_text")
        bindings, problems = parse_bindings(getattr(config, "switches", None), gesture, mode)
        for problem in problems:
            log.warning("[facegesture] %s", problem)
        # Resolved at call time, not captured, so the handler is whatever the
        # attributes hold when a hold begins (the daemon's callbacks, or a test's).
        handlers: dict[str, SwitchAction] = dict(actions or {})
        handlers[legacy_action(mode)] = SwitchAction(
            press=lambda: self._on_hold_start(0),
            release=lambda: self._on_hold_end(),
        )
        self._mapper = SwitchMapper(bindings, handlers, gate=safety)
        self._sink: Callable[[SwitchIntent], object] = on_intent or self._mapper.handle
        for action in self._mapper.unwired():
            log.warning(
                "[facegesture] %s is mapped but nothing implements it in this build; "
                "that gesture will do nothing.", action,
            )

        # One detector per watched gesture: every bound one, plus the primary (whose
        # detector is `self._switch`, kept for the single-gesture callers and tests).
        floor = getattr(config, "confidence_floor", 0.0)
        self._switches: dict[str, GestureSwitch] = {}
        self._baselines: dict[str, Baseline | None] = {}
        for watched in (gesture, *(g for g in bindings if g != gesture)):
            baseline = self._resolve_baseline(config, baselines, watched)
            self._baselines[watched] = baseline
            self._switches[watched] = GestureSwitch(
                hold_threshold=getattr(config, "hold_threshold", 0.5),
                release_threshold=getattr(config, "release_threshold", 0.35),
                min_hold_frames=getattr(config, "min_hold_frames", 3),
                min_release_frames=getattr(config, "min_release_frames", 2),
                baseline=None if baseline is None else baseline.level,
                confidence_floor=floor,
                refractory_frames=getattr(config, "refractory_frames", 0),
            )
        self._switch = self._switches[gesture]
        self._baseline = self._baselines[gesture]
        try:
            too_strict = float(floor) > DEFAULT_PRESENCE_CONFIDENCE
        except (TypeError, ValueError):
            too_strict = False
        if too_strict:
            # This camera path's landmarker reports no per-frame confidence, only that
            # the face cleared its presence threshold; so a floor above that bound
            # blocks every frame. Say it once, rather than leave a dead switch silent.
            log.warning(
                "[facegesture] confidence_floor = %.2f is above the %.2f this camera path "
                "can report, so no frame will pass and the switch will never fire.",
                float(floor), DEFAULT_PRESENCE_CONFIDENCE,
            )
        if self._switch.repaired_release:
            hold, release = self._switch.thresholds
            log.warning(
                "[facegesture] release_threshold must be below hold_threshold "
                "(otherwise the switch chatters); using %.2f / %.2f.", hold, release,
            )
        fps = int(getattr(config, "fps", 15) or 15)
        self._interval = 1.0 / max(1, min(60, fps))

    def _resolve_baseline(self, config, baselines, gesture: str) -> Baseline | None:
        """``gesture``'s baseline when ``[facegesture] use_baseline`` asks for one.

        Every way of not having a usable one falls back to the absolute thresholds and
        says so once: the alternative to a missing file is a switch that does not work.
        """
        if not getattr(config, "use_baseline", False):
            return None
        found = (baselines or {}).get(gesture)
        if found is None:
            log.warning(
                "[facegesture] use_baseline is on but there is no baseline for %r; using "
                "the absolute thresholds. Run: yazses facegesture calibrate", gesture,
            )
            return None
        if not found.usable:
            log.warning(
                "[facegesture] the %r baseline (%.2f) leaves too little headroom to "
                "normalise against; the switch will not fire. Run: yazses facegesture "
                "calibrate with a relaxed face.", gesture, found.level,
            )
            return found
        hold = float(getattr(config, "hold_threshold", 0.5))
        if not found.separable_from(hold):
            log.warning(
                "[facegesture] the %r baseline is too noisy for hold_threshold = %.2f: "
                "your relaxed face alone can reach it. Re-run calibration, or raise the "
                "threshold.", gesture, hold,
            )
        return found

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
            # to release, so every switch is drained before the camera goes away.
            for name, switch in self._switches.items():
                if switch.reset() == "end":
                    self._emit(name, "end", None)
            self._mapper.release_all()
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
            try:
                self._step(landmarker, cap, cv2, mp)
            except Exception:
                # One bad frame must not end the user's only input method. The
                # switch state is untouched, so a held gesture stays held.
                log.debug("face-gesture: frame failed", exc_info=True)
            # Sleep on the stop event, so stop() is honoured within one frame
            # rather than after a full interval of an unrelated sleep.
            self._stop_event.wait(max(0.0, self._interval - (time.monotonic() - started)))

    def _step(self, landmarker, cap, cv2, mp) -> None:
        """One frame through every watched gesture's detector, then out as intents."""
        shapes = self._blendshapes(landmarker, cap, cv2, mp)
        # Liveness and suppression first: a gate that has closed releases open holds
        # before this frame can start a new one.
        self._mapper.frame(has_signal=shapes is not None)
        for name, switch in self._switches.items():
            reading = self._reading_for(shapes, name)
            event = switch.update(reading.score, reading.confidence)
            if event is not None:
                self._emit(name, event, reading.confidence)

    def _blendshapes(self, landmarker, cap, cv2, mp) -> dict[str, float] | None:
        """The first face's ``{category: score}`` for this frame, or None if there is none.

        An exception (camera, model) propagates: the loop treats the frame as lost and
        leaves every detector untouched.
        """
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(image)
        shapes = getattr(result, "face_blendshapes", None)
        if not shapes:
            return None
        return blendshape_scores(shapes[0])

    @staticmethod
    def _reading_for(shapes: dict[str, float] | None, gesture: str) -> Reading:
        """One gesture as ``(score, confidence)`` -- two inputs, never one number.

        The landmarker's Python result carries no per-face confidence, only the fact that
        a face cleared its presence threshold, so a frame with a face reports that bound
        (:data:`DEFAULT_PRESENCE_CONFIDENCE`, a documented lower bound and not a
        measurement) and a frame without one reports None. A graded confidence needs a
        source that has one; the shared perception layer is where that will arrive.
        """
        if shapes is None:
            return Reading(None, None)
        score = gesture_score(shapes, gesture)
        if score is None:
            return Reading(None, None)
        return Reading(score, DEFAULT_PRESENCE_CONFIDENCE)

    def _reading(self, landmarker, cap, cv2, mp) -> Reading:
        """The primary gesture's reading for one frame (calibration and tests)."""
        return self._reading_for(self._blendshapes(landmarker, cap, cv2, mp), self._gesture)

    def _score(self, landmarker, cap, cv2, mp) -> float | None:
        """The score half of :meth:`_reading` (kept for callers that want only that)."""
        return self._reading(landmarker, cap, cv2, mp).score

    def collect_readings(
        self, landmarker, cap, cv2, mp, seconds: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> list[Reading]:
        """Sample ``seconds`` of frames for calibration; one bad frame is no reading.

        The same frame path the switch runs on, so a baseline is measured on exactly what
        the switch will later see. Frames are consumed and dropped; only the numbers are
        returned (ADR-011).
        """
        frames = max(1, int(float(seconds) / self._interval))
        out: list[Reading] = []
        for _ in range(frames):
            try:
                out.append(self._reading(landmarker, cap, cv2, mp))
            except Exception:
                log.debug("face-gesture: calibration frame failed", exc_info=True)
                out.append(Reading(None, None))
            sleep(self._interval)
        return out

    def _emit(self, gesture: str, event: str, confidence: float | None) -> None:
        """Hand one intent to the sink without letting it kill the capture thread.

        This is the whole of the backend's output: a :class:`SwitchIntent`. What it
        causes is the sink's business (ADR-v2-147).
        """
        try:
            self._sink(make_intent(gesture, event, confidence))
        except Exception:
            log.warning("face-gesture: %s intent sink raised", event, exc_info=True)

    def _fire(self, event: str) -> None:
        """Emit the primary gesture's ``start``/``end`` as an intent."""
        self._emit(self._gesture, event, None)
