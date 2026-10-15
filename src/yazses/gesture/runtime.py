"""Run Gesture Chords: lease the shared camera, poll it, drive the engine (EYE-GESTURE-001).

The thin, impure shell around :class:`~yazses.gesture.sensors.SensorTokens` and
:class:`~yazses.gesture.engine.ChordEngine`, shaped like ``headpointer/runtime.py`` and for the
same reasons. It owns exactly what the pure layers must not: a **lease** on the one shared
camera (``perception/source.py``), a **poll loop**, and the **construction rules** that decide
whether the feature runs at all. It never opens a camera and never imports OpenCV or MediaPipe.

**Dormant unless asked, and quiet about why not.** :func:`build_gesture` returns a runtime
with no runner when ``[gesture]`` is off (the shipped state), when no chord is bound (the
shipped mapping), or when there is no shared camera source. Nothing is leased and no thread
starts; the reason is kept so ``yazses gesture status`` can say *why* nothing happens.

**Actions are injected, abstract and few.** A chord resolves to a string. This module turns
the string into a call on something that already exists: the global hands-free stop
(``HandsFreeSafety.pause``), the Head-Pointer's own command surface (``pause``, ``recenter``)
or one spoken-command phrase handed to the daemon's ``run_command`` -- which the daemon routes
through ``activation/pipeline.handle_intent``, so a command the policy does not call
reversible is held for confirmation and, with no prompt wired, refused. No chord reaches a
destructive operation any other way, and the pointer is never touched here: freezing it for the
gesture is a *clutch* on the Head-Pointer's existing public command, held under the source
name ``gesture`` and released by the engine.

**A crash in this loop must not take dictation with it.** Anything the poll raises resets the
engine (tokens released, freeze dropped) and is logged once; the thread keeps polling.
"""
from __future__ import annotations

import functools
import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from yazses.gesture.engine import (
    COMMAND_PREFIX,
    DEFAULT_HOLD_S,
    SAFETY_SOURCE,
    ChordEngine,
    parse_chords,
)
from yazses.gesture.headmotion import HEAD_TOKENS, HeadMotionSettings
from yazses.gesture.sensors import FaceSwitchSettings, SensorSettings, SensorTokens
from yazses.handsfree.safety import HandsFreeSafety
from yazses.perception.signals import FacePerceptionSource

__all__ = [
    "CLUTCH_SOURCE",
    "SOURCE_NAME",
    "GestureRunner",
    "GestureRuntime",
    "build_gesture",
    "command_runner",
    "engine_params",
    "hold_param",
    "rewind_param",
    "no_echo_injector",
    "sensor_settings",
]

log = logging.getLogger(__name__)

#: The camera-lease name, and the gate name, for this feature.
SOURCE_NAME = SAFETY_SOURCE

#: The name this feature holds the Head-Pointer's clutch under.
CLUTCH_SOURCE = "gesture"

_MIN_INTERVAL_S = 1.0 / 120.0
_MAX_INTERVAL_S = 1.0 / 10.0


def _num(value: object, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def sensor_settings(section: Any, facegesture: Any) -> SensorSettings:
    """``[gesture]`` + ``[facegesture]`` as :class:`SensorSettings`. Unreadable values fall back.

    The face thresholds are the face switch's own, so one calibration serves both.
    """
    d = HeadMotionSettings()
    face = FaceSwitchSettings()
    return SensorSettings(
        freshness_s=_num(section.freshness_ms, 500.0) / 1000.0,
        face=FaceSwitchSettings(
            hold_threshold=_num(facegesture.hold_threshold, face.hold_threshold),
            release_threshold=_num(facegesture.release_threshold, face.release_threshold),
            min_hold_frames=int(_num(facegesture.min_hold_frames, face.min_hold_frames)),
            min_release_frames=int(_num(facegesture.min_release_frames, face.min_release_frames)),
            confidence_floor=_num(facegesture.confidence_floor, face.confidence_floor),
            refractory_frames=int(_num(facegesture.refractory_frames, face.refractory_frames)),
        ),
        head=HeadMotionSettings(
            amplitude_rad=math.radians(_num(section.head_amplitude_deg, 10.0)),
            swings=int(_num(section.head_swings, d.swings)),
            window_s=_num(section.head_window_ms, d.window_s * 1000.0) / 1000.0,
            tilt_rad=math.radians(_num(section.tilt_deg, 20.0)),
            tilt_hold_s=_num(section.tilt_hold_ms, d.tilt_hold_s * 1000.0) / 1000.0,
            refractory_s=_num(section.refractory_ms, d.refractory_s * 1000.0) / 1000.0,
            freshness_s=_num(section.freshness_ms, 500.0) / 1000.0,
            min_confidence=_num(section.min_confidence, d.min_confidence),
        ),
    )


def engine_params(section: Any) -> tuple[float, float, float]:
    """``(window_s, refractory_s, freeze_tail_s)`` from ``[gesture]``."""
    return (
        _num(section.chord_window_ms, 400.0) / 1000.0,
        _num(section.refractory_ms, 1000.0) / 1000.0,
        _num(section.freeze_tail_ms, 300.0) / 1000.0,
    )


def hold_param(section: Any) -> float:
    """``[gesture] hold_ms`` as seconds: the ``hold`` token's duration. Unreadable = default."""
    seconds = _num(section.hold_ms, DEFAULT_HOLD_S * 1000.0) / 1000.0
    return seconds if seconds > 0.0 else DEFAULT_HOLD_S


def rewind_param(section: Any) -> float:
    """``[gesture] onset_rewind_ms`` as seconds: how much pointer motion a late freeze may undo.

    Zero (or anything unreadable or negative) is *none*: doubt must not move the pointer.
    """
    seconds = _num(section.onset_rewind_ms, 0.0) / 1000.0
    return seconds if seconds > 0.0 else 0.0


class GestureRunner:
    """Holds the camera lease and polls it into the sensors. ``pump()`` is one poll."""

    def __init__(
        self,
        engine: ChordEngine,
        sensors: SensorTokens,
        lease: FacePerceptionSource,
        *,
        interval_s: float = 1.0 / 30.0,
        clock: Callable[[], float] = time.monotonic,
        thread: bool = True,
    ) -> None:
        self.engine = engine
        self.sensors = sensors
        self._lease = lease
        self._interval_s = min(_MAX_INTERVAL_S, max(_MIN_INTERVAL_S, interval_s))
        self._clock = clock
        self._use_thread = thread
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._leased = False
        self._complained = False

    @property
    def running(self) -> bool:
        return self._leased

    def start(self) -> None:
        """Take the camera lease and start polling. Idempotent; never raises."""
        if self._leased:
            return
        try:
            self._lease.start()
        except Exception:
            log.warning("Gesture Chords could not lease the camera", exc_info=True)
            return
        self._leased = True
        self._stop.clear()
        if self._use_thread:
            self._thread = threading.Thread(target=self._loop, name="gesture", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop polling, release every token and the lease. Idempotent; never raises."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        try:
            self.sensors.reset(self._clock())
        except Exception:
            log.debug("Gesture Chords reset raised", exc_info=True)
        if self._leased:
            self._leased = False
            try:
                self._lease.stop()
            except Exception:
                log.debug("Gesture Chords lease release raised", exc_info=True)

    def pump(self) -> None:
        """One poll: read the newest observation and advance the sensors."""
        now = self._clock()
        try:
            self.sensors.update(self._lease.latest(), now)
        except Exception:
            if not self._complained:
                self._complained = True
                log.warning("Gesture Chords loop failed", exc_info=True)
            try:
                self.sensors.reset(now)
            except Exception:
                log.debug("Gesture Chords reset raised", exc_info=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.pump()
            self._stop.wait(self._interval_s)


@dataclass
class GestureRuntime:
    """What the daemon holds: a runner (or the reason there is none) and the command surface."""

    runner: GestureRunner | None = None
    #: Why there is no runner, or ``""``. Printed by ``yazses gesture status``.
    reason: str = ""
    #: Rules that were refused while reading ``[gesture.chords]``.
    problems: list[str] = field(default_factory=list)
    safety: HandsFreeSafety | None = None

    @property
    def active(self) -> bool:
        return self.runner is not None

    def start(self) -> None:
        if self.runner is not None:
            self.runner.start()

    def stop(self) -> None:
        if self.runner is not None:
            self.runner.stop()

    def command(self, action: str, params: dict[str, Any] | None = None) -> dict[str, object]:
        """The IPC/CLI surface: ``status | pause | resume``."""
        if self.runner is None:
            if action == "status":
                return {"ok": True, "active": False, "reason": self.reason,
                        "problems": list(self.problems)}
            return {"ok": False, "reason": self.reason or "Gesture Chords is not running"}
        engine = self.runner.engine
        if action == "status":
            return {
                "ok": True,
                "active": True,
                "running": self.runner.running,
                "chords": len(engine.bindings),
                "watching": list(self.runner.sensors.watching),
                "paused": engine.paused,
                "pointer_frozen": engine.freeze_pointer,
                "unwired": engine.unwired(),
                "problems": list(self.problems),
            }
        if action == "pause":
            engine.set_paused(True)
            return {"ok": True}
        if action == "resume":
            engine.set_paused(False)
            if self.safety is None:
                return {"ok": True, "reason": ""}
            result = self.safety.resume([SOURCE_NAME])
            return {"ok": result.ok, "reason": "" if result.ok else (
                result.reason or f"{SOURCE_NAME}: not ready to arm")}
        return {"ok": False, "reason": f"unknown action {action!r}"}


def build_gesture(
    config: Any,
    *,
    facegesture: Any,
    perception: Any,
    headpointer: Any = None,
    safety: HandsFreeSafety | None = None,
    run_command: Callable[[str], object] | None = None,
    fps: int = 15,
    clock: Callable[[], float] = time.monotonic,
    thread: bool = True,
) -> GestureRuntime:
    """Gesture Chords for ``[gesture]``, or a runtime that says why there is none.

    ``config`` is the ``[gesture]`` section, ``facegesture`` the ``[facegesture]`` section
    (whose thresholds the face tokens use), ``perception`` the daemon's shared camera source
    (or ``None``), ``headpointer`` its :class:`HeadPointerRuntime` (or ``None``) and
    ``run_command`` the daemon's confirmation-gated phrase runner. Building opens no camera --
    the lease is taken by :meth:`GestureRuntime.start`.
    """
    if not config.enabled:
        return GestureRuntime()
    bindings, problems = parse_chords(config.chords)
    for problem in problems:
        log.warning("[gesture] %s", problem)
    if not bindings:
        return GestureRuntime(
            reason="no chords are bound -- add some under [gesture.chords] "
            "(see `yazses features info gesture`)",
            problems=problems,
        )
    if perception is None:
        return GestureRuntime(
            reason="no shared camera source -- `[perception]` could not be built "
            "(is the `gaze` extra installed? see `yazses doctor`)",
            problems=problems,
        )

    pointer_live = bool(headpointer is not None and headpointer.active)

    def _pointer(action: str, params: dict[str, Any] | None = None) -> object:
        return headpointer.command(action, params) if pointer_live else None

    handlers: dict[str, Callable[[], object]] = {}
    if safety is not None:
        handlers["pause_pointer"] = lambda: safety.pause("gesture chord")
    elif pointer_live:
        handlers["pause_pointer"] = lambda: _pointer("pause")
    if pointer_live:
        handlers["recenter"] = lambda: _pointer("recenter")
    if run_command is not None:
        for action in set(bindings.values()):
            if action.startswith(COMMAND_PREFIX):
                phrase = action[len(COMMAND_PREFIX):].strip()
                handlers[action] = functools.partial(run_command, phrase)

    rewind_s = rewind_param(config)

    def _freeze(frozen: bool) -> None:
        params: dict[str, Any] = {"source": CLUTCH_SOURCE, "active": frozen}
        since = engine.freeze_started_s if frozen else None
        if since is not None and rewind_s > 0.0:
            # The pointer runner polls on its own thread and may already have followed the
            # first disturbed frame; ask the clutch to take that step back (and no more).
            params["since_s"] = since
            params["max_rewind_s"] = rewind_s
        _pointer("clutch", params)

    on_freeze = _freeze if pointer_live else None

    window_s, refractory_s, freeze_tail_s = engine_params(config)
    engine = ChordEngine(
        bindings, handlers, window_s=window_s, refractory_s=refractory_s,
        freeze_tail_s=freeze_tail_s, hold_s=hold_param(config), gate=safety, on_freeze=on_freeze,
    )
    sensors = SensorTokens(engine, sensor_settings(config, facegesture))
    for action in engine.unwired():
        log.warning("[gesture] %s is bound but nothing implements it in this build; "
                    "that chord will do nothing.", action)
    if pointer_live and any(t in engine.vocabulary for t in HEAD_TOKENS):
        log.warning(
            "[gesture] head tokens (%s) and the Head-Pointer share one body channel: the "
            "pointer follows the same motion that makes the gesture. It is frozen once the "
            "gesture is recognised, not before (nothing takes that motion back); face tokens "
            "freeze it from the first frame they are seen.",
            ", ".join(t for t in HEAD_TOKENS if t in engine.vocabulary),
        )
    if getattr(facegesture, "use_baseline", False):
        log.warning("[gesture] [facegesture] use_baseline is not applied to chord tokens; "
                    "the absolute thresholds are used.")
    interval = 1.0 / (2.0 * max(1, int(fps)))
    runner = GestureRunner(
        engine, sensors, perception.consumer(SOURCE_NAME),
        interval_s=interval, clock=clock, thread=thread,
    )
    return GestureRuntime(runner=runner, problems=problems, safety=safety)


class _NoEcho:
    """An injector that will not type the phrase that named the command.

    ``commands.dispatch.dispatch`` falls back to ``injector.inject(intent.raw_text)`` when a
    command raises. For a spoken command that is a sane degradation (the words stay on
    screen); for a chord it would type "undo" into whatever has focus, from a facial
    movement, with nothing said. Everything else -- key sequences, a line number a command
    needs -- passes through untouched.
    """

    def __init__(self, injector: Any, phrase: str) -> None:
        self._injector = injector
        self._phrase = phrase

    def inject(self, text: str, *args: Any, **kwargs: Any) -> Any:
        if text == self._phrase:
            log.warning("[gesture] refused to type the phrase that named a chord command")
            return None
        return self._injector.inject(text, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._injector, name)


def no_echo_injector(injector: Any, phrase: str) -> Any:
    """``injector`` that refuses to type ``phrase`` itself (see :class:`_NoEcho`)."""
    return _NoEcho(injector, phrase)


def command_runner(
    classify: Callable[[str], object],
    dispatch: Callable[[object], None],
    confirm: Callable[[str, Any], bool] | None = None,
) -> Callable[[str], object]:
    """A ``run_command(phrase)`` that sends the phrase through the activation policy.

    Wraps ``activation/pipeline.handle_intent`` with the phrase as the only label in its
    vocabulary and a chord's certainty (1.0: a token match is deterministic, though whether
    the user *meant* it is the false-activation question P5.4 answers). A command the policy
    calls irreversible needs ``confirm``; with none wired it is refused, never run.
    """
    from yazses.activation.intent import ActivationIntent
    from yazses.activation.pipeline import handle_intent

    def run(phrase: str) -> object:
        return handle_intent(
            ActivationIntent(label=phrase, confidence=1.0, source=SOURCE_NAME),
            (phrase,),
            classify=classify,
            dispatch=dispatch,
            confirm=confirm,
        )

    return run
