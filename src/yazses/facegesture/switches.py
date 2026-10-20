"""Face-switch intents and the mapping that turns them into actions (pure) — EYE-FACE-002.

ADR-v2-147: a face detector may emit only a normalised, abstract switch event. It never
imports or calls a PointerSink, a command dispatcher, an injector or the daemon. Before this
module, ``facegesture/backend.py`` took the dictation start/stop callbacks directly, so the one
shipped gesture could do exactly one thing — hold the microphone. Now the backend produces
:class:`SwitchIntent` values and hands them to a sink; this module is the sink that decides what
an intent *means*, and it is the only place a gesture meets an action.

.. code-block:: text

    blendshape trace -> GestureSwitch -> SwitchIntent -> SwitchMapper -> action handler
                        (detector)       (this file)     (this file)     (injected)

Four rules carry the design, each pinned by a test:

**Unmapped means nothing.** A gesture with no binding reaches no handler. Not a default one, not
the hold-to-talk one: the mapper looks the gesture up and, finding nothing, returns.

**The mapping is data, validated before it is trusted.** Unknown gestures and unknown actions are
rejected with a reason, never coerced to the nearest thing — a typo in ``intent`` must not
quietly bind a facial movement to a *different* action.

**A suppressed source stays suppressed.** With a :class:`~yazses.handsfree.safety.HandsFreeSafety`
gate supplied, a press is acted on only when the gate allows it, and a hold that is open when the
gate closes is released at once. Only :data:`SAFE_ACTIONS` (pausing) bypass the gate, because
they can only move the system toward the stopped state. A *release* is never gated: refusing to
close the microphone is the failure the gate exists to prevent.

**Consequences are not decided here.** The handlers are injected and are the daemon's own
entry points, which are themselves behind the existing confirmation policy
(``activation/confirm.py``). This module carries no notion of "destructive" because it performs
nothing.

Pure and dependency-free by contract (AGENTS.md rule 5): no camera, no daemon, no thread. The
``HandsFreeSafety`` it accepts is another pure module, taken structurally.
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from yazses.facegesture.detector import GESTURES

log = logging.getLogger(__name__)

#: The only name this module uses for itself towards the hands-free safety gate.
SAFETY_SOURCE = "facegesture"

PRESS = "press"
RELEASE = "release"

#: The abstract actions a gesture may be bound to. A *vocabulary*, not a promise that every
#: entry has a handler in this build: an action nothing implements is accepted by the
#: validator (so a config written for a later build still loads) and then does nothing, with
#: one warning at start-up — see :meth:`SwitchMapper.unwired`.
ACTIONS: tuple[str, ...] = (
    "hold_to_talk",      # open the mic while the gesture is held (dictation)
    "hold_to_command",   # open the mic as a command while held
    "select",            # click / select at the current target
    "confirm",           # accept the pending confirmation
    "cancel",            # dismiss the pending confirmation
    "pause_pointer",     # pause hands-free actions (the stop path)
)

#: Actions that stay open while the gesture does: a press starts them, a release ends them.
HOLD_ACTIONS: frozenset[str] = frozenset({"hold_to_talk", "hold_to_command"})

#: How long the face must be back, unbroken, before a hold-only face switch re-arms itself after
#: the global stop disarmed it for a stale signal (looking away). PROVISIONAL and unmeasured:
#: long enough that a face flickering in and out of view does not re-arm, short enough that
#: looking back at the screen and closing the eyes works without pressing Resume.
REARM_AFTER_MS = 1000.0


def rearms_on_face_return(actions: frozenset[str] | set[str]) -> bool:
    """May a face switch bound to ``actions`` re-arm itself when the face comes back? Pure.

    Only if every binding is a hold: the worst a hold can do is open the microphone while the
    gesture is held, and a lost face already forces it closed. A click, confirm or pause
    binding acts on the world in one frame, so it keeps the explicit-Resume rule.
    """
    return bool(actions) and set(actions) <= HOLD_ACTIONS

#: Actions whose expression the pointer should hold still for (ADR-v2-147, "Interaction with
#: Head-Pointer"): the facial effort of a commit gesture can move the head, and with it the
#: target. A hold-to-talk is not a commit.
COMMIT_ACTIONS: frozenset[str] = frozenset({"select", "confirm"})


def stuck_consequence(action: object) -> str | None:
    """What a gesture bound to ``action`` leaves stuck if it can never let go, or None.

    ``"microphone"`` for a hold (the mic stays open), ``"pointer"`` for a commit action (the
    pointer stays frozen for as long as the gesture lasts, and the gesture cannot fire again),
    None for an action that holds nothing open (``cancel``, ``pause_pointer``). Pure.
    """
    if action in HOLD_ACTIONS:
        return "microphone"
    if action in COMMIT_ACTIONS:
        return "pointer"
    return None


#: Actions that may run while the safety gate is closed, because they can only make the
#: system *more* stopped. Everything else is suppressed under pause, fault or staleness.
SAFE_ACTIONS: frozenset[str] = frozenset({"pause_pointer"})

#: Spelled in config to remove a binding explicitly (e.g. to turn off the default
#: hold-to-talk on the primary gesture). Not an action; there is nothing to do.
UNMAP = "none"


@dataclass(frozen=True)
class SwitchIntent:
    """What the detector says happened — and nothing about what it means.

    ``phase`` is :data:`PRESS` (the gesture became held) or :data:`RELEASE`. ``confidence`` is
    the landmarker confidence of the frame that produced it, or None when the source does not
    report one. No frame, mesh or score is carried (ADR-011, ADR-v2-145): an intent is safe to
    log.
    """

    gesture: str
    phase: str
    timestamp_s: float
    confidence: float | None = None
    source: str = SAFETY_SOURCE


@dataclass(frozen=True)
class SwitchAction:
    """An implementation of one abstract action: ``press`` always, ``release`` for holds."""

    press: Callable[[], None]
    release: Callable[[], None] | None = None


class _Gate(Protocol):
    """The slice of :class:`~yazses.handsfree.safety.HandsFreeSafety` the mapper uses."""

    def gate(self, source: str) -> object: ...
    def sample(self, source: str) -> None: ...


def legacy_action(mode: object) -> str:
    """The action the single-gesture ``[facegesture] gesture`` binding means for ``mode``.

    ``command`` is the command key; every other value is dictation, which is also what the
    daemon does with an unrecognised mode (configcheck repairs it first). Pure.
    """
    return "hold_to_command" if str(mode or "").strip().lower() == "command" else "hold_to_talk"


def parse_bindings(
    switches: object,
    primary_gesture: str,
    mode: object = "full_text",
) -> tuple[dict[str, str], list[str]]:
    """Resolve ``[[facegesture.switches]]`` into ``{gesture: action}``, plus problems. Pure.

    The single-gesture install is the base case: with ``switches`` empty the result is exactly
    ``{primary_gesture: legacy_action(mode)}``, so an existing ``[facegesture]`` section is
    unchanged. Entries then add to or replace that (a gesture maps to one action; the entry
    for the primary gesture replaces the legacy binding, and ``intent = "none"`` removes it).

    Never raises. An entry that cannot be honoured is **skipped, with a reason in the second
    element** — it is not coerced to a neighbouring gesture or action, because binding a
    facial movement to the wrong action is worse than binding it to none.
    """
    bindings: dict[str, str] = {primary_gesture: legacy_action(mode)}
    problems: list[str] = []
    if switches in (None, [], ()):
        return bindings, problems
    if not isinstance(switches, (list, tuple)):
        return bindings, [f"switches should be a list of tables, got {type(switches).__name__}"]

    seen: set[str] = set()
    for index, entry in enumerate(switches):
        where = f"switches[{index}]"
        if not isinstance(entry, Mapping):
            problems.append(f"{where} should be a table, got {type(entry).__name__}; ignored")
            continue
        gesture = str(entry.get("gesture", "") or "").strip().lower()
        action = str(entry.get("intent", "") or "").strip().lower()
        if gesture not in GESTURES:
            problems.append(
                f"{where}: gesture {gesture!r} is not a gesture; ignored. "
                f"Valid: {', '.join(GESTURES)}"
            )
            continue
        if action != UNMAP and action not in ACTIONS:
            problems.append(
                f"{where}: intent {action!r} is not an action; ignored. "
                f"Valid: {', '.join(ACTIONS)}, {UNMAP}"
            )
            continue
        if gesture in seen:
            problems.append(f"{where}: {gesture!r} is already mapped above; ignored")
            continue
        seen.add(gesture)
        if action == UNMAP:
            bindings.pop(gesture, None)
        else:
            bindings[gesture] = action
    return bindings, problems


class SwitchMapper:
    """Turns :class:`SwitchIntent` into calls on injected handlers, under the safety gate."""

    def __init__(
        self,
        bindings: Mapping[str, str],
        handlers: Mapping[str, SwitchAction],
        *,
        gate: _Gate | None = None,
        on_freeze: Callable[[bool], None] | None = None,
        source: str = SAFETY_SOURCE,
    ) -> None:
        self._bindings = dict(bindings)
        self._handlers = dict(handlers)
        self._gate = gate
        self._on_freeze = on_freeze
        self._source = source
        self._down: dict[str, str] = {}   # gesture -> action, while its press is in force
        self._open: dict[str, int] = {}   # hold action -> gestures currently holding it
        self._freeze = False
        self._warned: set[str] = set()

    # ------------------------------------------------------------------ introspection

    @property
    def bindings(self) -> dict[str, str]:
        """A copy of the ``{gesture: action}`` table in force."""
        return dict(self._bindings)

    def unwired(self) -> list[str]:
        """Bound actions with no handler in this build, sorted. They do nothing."""
        return sorted({a for a in self._bindings.values() if a not in self._handlers})

    @property
    def freeze_pointer(self) -> bool:
        """True while a commit gesture is held and the source is allowed to act.

        The composition layer may read this (or take ``on_freeze``) to hold the pointer still
        for the interval of the gesture, so facial effort does not also move the target.
        It is a request, not an action: nothing here touches a pointer.
        """
        return self._freeze

    # ------------------------------------------------------------------ the one entry point

    def handle(self, intent: SwitchIntent) -> bool:
        """Act on one intent. True if a handler was invoked. Never raises.

        An unmapped gesture, an unwired action, a suppressed source and a handler that raises
        all return False — none of them may take the capture thread down.
        """
        action = self._bindings.get(intent.gesture)
        if action is None:
            return False
        if intent.phase == RELEASE:
            return self._release(intent.gesture)
        if intent.phase != PRESS:
            return False
        return self._press(intent.gesture, action)

    def frame(self, has_signal: bool) -> None:
        """Called once per camera frame: report liveness, and drop holds if now suppressed.

        Samples the gate only when the frame carried a face, so a camera that goes blind
        ages the source out (ADR-v2-148) instead of looking healthy. If the gate has closed
        since the last frame, every open hold is released *now*: pausing must not wait for
        the user to relax their face before the microphone closes.
        """
        if self._gate is None:
            return
        try:
            if has_signal:
                self._gate.sample(self._source)
            if self._down and not self._allowed():
                self.release_all()
        except Exception:
            log.debug("face-switch: gate poll failed", exc_info=True)

    def release_all(self) -> None:
        """Release every open hold (shutdown, suppression). Idempotent."""
        for gesture in list(self._down):
            self._release(gesture)

    # ------------------------------------------------------------------ internals

    def _allowed(self) -> bool:
        if self._gate is None:
            return True
        decision = self._gate.gate(self._source)
        return bool(getattr(decision, "allowed", False))

    def _press(self, gesture: str, action: str) -> bool:
        handler = self._handlers.get(action)
        if handler is None:
            if action not in self._warned:
                self._warned.add(action)
                log.warning(
                    "[facegesture] %r is mapped to %r, which nothing implements yet; "
                    "the gesture does nothing.", gesture, action,
                )
            return False
        if action not in SAFE_ACTIONS and not self._allowed():
            return False
        if gesture in self._down:
            return False  # a press without a release in between; the detector prevents this
        self._down[gesture] = action
        self._set_freeze()
        if action in HOLD_ACTIONS:
            self._open[action] = self._open.get(action, 0) + 1
            if self._open[action] > 1:
                return False  # another gesture already holds it; do not start it twice
        return self._call(handler.press, f"{action} press")

    def _release(self, gesture: str) -> bool:
        action = self._down.pop(gesture, None)
        self._set_freeze()
        if action is None:
            # A release with no recorded press. For a hold action it is still delivered:
            # closing a microphone that is already closed is harmless, and dropping the one
            # release that matters is the failure this whole path is built to avoid.
            action = self._bindings.get(gesture)
            if action not in HOLD_ACTIONS:
                return False
            handler = self._handlers.get(action)
            return bool(handler and handler.release and self._call(handler.release, f"{action} release"))
        if action not in HOLD_ACTIONS:
            return False
        remaining = self._open.get(action, 1) - 1
        if remaining > 0:
            self._open[action] = remaining
            return False
        self._open.pop(action, None)
        handler = self._handlers.get(action)
        return bool(handler and handler.release and self._call(handler.release, f"{action} release"))

    def _set_freeze(self) -> None:
        now = any(a in COMMIT_ACTIONS for a in self._down.values())
        if now != self._freeze:
            self._freeze = now
            callback = self._on_freeze
            if callback is not None:
                self._call(lambda: callback(now), "freeze")

    @staticmethod
    def _call(fn: Callable[[], None], what: str) -> bool:
        try:
            fn()
        except Exception:
            log.warning("face-switch: %s handler raised", what, exc_info=True)
            return False
        return True


def make_intent(
    gesture: str, event: str, confidence: float | None = None, now_s: float | None = None
) -> SwitchIntent:
    """The detector's ``"start"`` / ``"end"`` as a :class:`SwitchIntent`. Pure.

    Anything else is refused with ``ValueError``: the backend only forwards real events, and
    an unknown event string reaching here is a bug that should be loud in a test, not an
    intent invented from nothing.
    """
    if event == "start":
        phase = PRESS
    elif event == "end":
        phase = RELEASE
    else:
        raise ValueError(f"not a switch event: {event!r}")
    conf = None
    if confidence is not None and math.isfinite(float(confidence)):
        conf = min(1.0, max(0.0, float(confidence)))
    return SwitchIntent(
        gesture=gesture,
        phase=phase,
        timestamp_s=time.monotonic() if now_s is None else float(now_s),
        confidence=conf,
    )

