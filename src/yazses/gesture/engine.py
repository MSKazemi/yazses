"""The chord engine: abstract tokens in, abstract actions out (pure) -- EYE-GESTURE-001.

ADR-v2-043 made the chord *resolver* (``gesture/chords.py``) input-agnostic and left the
sensors for later. This module is the runtime around that resolver: it decides *when* a set of
tokens is a chord, then asks ``resolve_chord`` what it means. It does not re-implement
normalisation or lookup -- every chord id in this file comes from ``normalize_chord`` and
every resolution from ``resolve_chord``.

.. code-block:: text

    sensors -> tokens -> ChordEngine -> resolve_chord -> handler (injected, abstract action)

Five rules carry the design, each pinned by a test:

**Unmapped means nothing.** The mapping is empty by default. A token that appears in no bound
chord is not even remembered, so it cannot complete one or spoil one. A set of tokens that is
not *exactly* a bound chord fires nothing -- never the nearest chord, never a subset.

**Collisions fire neither.** Two spellings of one chord (``"jaw_open+nod"`` and
``"nod+jaw_open"``) normalise to the same id. Keeping the first would bind a face to an
action the user may have meant for the other, so both are refused with a reason.

**A chord fires once per engagement.** Tokens made within ``window_s`` of the first count as
one chord; it fires when the window closes (or at once, when no longer chord could still
absorb the tokens seen), and then nothing fires until every held token is released and
``refractory_s`` has passed. A chord that is not bound is *also* an engagement: it is not
retried as more tokens arrive. One exception, because a head gesture takes about a second to
recognise: tokens that are *held* and could still become a longer bound chord keep the
engagement open for as long as they stay held, so "hold the jaw open, then nod" works
however long the nod takes. Letting go ends it.

**The stop path is outside the gate; nothing else is.** ``pause_pointer`` can only move the
system toward stopped, so it runs when the global hands-free gate is closed. Every other
action is suppressed under pause, fault or staleness, and what was pending is dropped, not
replayed on resume.

**``hold`` is a token the engine makes itself.** A sensor cannot report "held long enough": it
reports presses and releases, and the engine already owns the clock. ``hold`` becomes true when the
tokens now held (at least one, and it must be one that *can* be held: a face gesture or ``tilt``)
have been held **unchanged** for ``hold_s`` seconds of the clock the caller passes in, so
``jaw_open+hold`` is "keep the jaw open for ``hold_s``", ``jaw_open+smile+hold`` is "both, together,
for ``hold_s``", and a third token joining or one letting go starts the count again. It is measured
in time, never in frames, so it takes the same wall time at 15 and at 60 fps (to within one runner
tick). It is released the moment any held token is. A chord and the same chord with ``+hold`` can
not both be bound -- the plain one would fire first -- so ``parse_chords`` refuses both.

**Consequences are not decided here.** The handlers are injected abstract actions. The daemon
routes any that could do harm through the existing confirmation policy
(``activation/confirm.py``); this module performs nothing.

**The pointer holds still for the gesture** (ADR-v2-147, "Interaction with Head-Pointer"; the
failure observed in Project Gameface). While any token of a bound chord is engaged -- or its
onset has been reported with :meth:`ChordEngine.onset` -- and for ``freeze_tail_s`` after, the
engine asks for a pointer freeze through ``on_freeze``. It is a request to a clutch source,
not an action: nothing here touches a pointer.

When the caller says which camera frame began the engagement (``at_s``), the engine remembers it
as :attr:`ChordEngine.freeze_started_s` for the duration of the ``on_freeze(True)`` call. That is
the "chord may be starting" signal: it lets the clutch take back the one step a pointer runner
polling on its own thread may already have made for that frame. The engine adds no earlier
trigger of its own -- the frame is the first one a detector already calls an onset -- so it can
fire no more often than the freeze already did.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping
from typing import Protocol

from yazses.facegesture.detector import GESTURES
from yazses.facegesture.switches import SAFE_ACTIONS
from yazses.gesture.chords import normalize_chord, resolve_chord
from yazses.gesture.headmotion import HEAD_TOKENS, TILT

__all__ = [
    "ACTIONS",
    "COMMAND_PREFIX",
    "DEFAULT_HOLD_S",
    "HOLD",
    "HOLDABLE",
    "SAFETY_SOURCE",
    "TOKENS",
    "ChordEngine",
    "parse_chords",
]

log = logging.getLogger(__name__)

#: The name this feature uses for itself towards the hands-free safety gate.
SAFETY_SOURCE = "gesture"

#: The one token no sensor reports: "the tokens now held have stayed held" (see the module
#: docstring). The engine makes it from its own clock.
HOLD = "hold"

#: Default for how long a state must be held to count as ``hold``. **Provisional:** nothing has
#: measured how long people can hold a face gesture on purpose, nor how long they hold one by
#: accident; it only has to be clearly longer than the 0.4 s chord window, so a hold is never the
#: same thing as a quick press.
DEFAULT_HOLD_S = 0.8

#: Every token a chord may use: the face gestures ``facegesture/detector.py`` already names,
#: the head gestures of ``gesture/headmotion.py``, and ``hold``.
TOKENS: tuple[str, ...] = (*GESTURES, *HEAD_TOKENS, HOLD)

#: The tokens that stay engaged until released, i.e. the ones ``hold`` can be a duration *of*.
#: ``nod`` and ``shake`` are over as they are recognised, so "nod+hold" has no meaning.
HOLDABLE: frozenset[str] = frozenset((*GESTURES, TILT))

#: Spelled in config for an action that routes a spoken command phrase through the existing
#: confirmation policy: ``"command:undo"``. Everything after the colon is the phrase.
COMMAND_PREFIX = "command:"

#: The abstract actions a chord may be bound to (a vocabulary, not a promise that this build
#: has a handler for each -- an unwired one is accepted and does nothing, with one warning).
#: ``pause_pointer`` is the global stop; ``recenter`` makes the current head pose neutral;
#: ``command:<phrase>`` runs a command from the existing grammar, and anything the activation
#: policy does not consider reversible is held for confirmation (and, with no prompt wired,
#: refused).
ACTIONS: tuple[str, ...] = ("pause_pointer", "recenter", f"{COMMAND_PREFIX}<phrase>")

#: Actions that may run while the safety gate is closed (see the module docstring).
_SAFE: frozenset[str] = SAFE_ACTIONS


class _Gate(Protocol):
    """The slice of :class:`~yazses.handsfree.safety.HandsFreeSafety` the engine uses."""

    def gate(self, source: str) -> object: ...
    def sample(self, source: str) -> None: ...


def _valid_action(action: str) -> bool:
    if action in ("pause_pointer", "recenter"):
        return True
    return action.startswith(COMMAND_PREFIX) and bool(action[len(COMMAND_PREFIX):].strip())


def parse_chords(raw: object) -> tuple[dict[str, str], list[str]]:
    """``[gesture.chords]`` as ``{chord_id: action}``, plus the reasons anything was refused.

    Never raises. An entry that cannot be honoured is **skipped with a reason**, not coerced
    to a neighbouring token or action: binding a face to the wrong action is worse than
    binding it to none. Chord ids are produced by ``normalize_chord``, so they are
    order-independent; an empty or missing mapping is the safe default and returns ``({}, [])``.
    """
    if raw in (None, {}, [], ()):
        return {}, []
    if not isinstance(raw, Mapping):
        return {}, [f"chords should be a table of 'token+token' = 'action', got {type(raw).__name__}"]
    bound: dict[str, str] = {}
    collided: set[str] = set()
    problems: list[str] = []
    for key, value in raw.items():
        where = f"chords[{key!r}]"
        if not isinstance(key, str) or not isinstance(value, str):
            problems.append(f"{where} should map a string to a string; ignored")
            continue
        tokens = [t.strip().lower() for t in key.split("+")]
        unknown = [t for t in tokens if t not in TOKENS]
        if not key.strip() or unknown or "" in tokens:
            problems.append(
                f"{where}: {', '.join(repr(t) for t in (unknown or [key]))} is not a token; "
                f"ignored. Valid: {', '.join(TOKENS)}"
            )
            continue
        action = value.strip()
        if not _valid_action(action):
            problems.append(
                f"{where}: {value!r} is not an action; ignored. "
                f"Valid: pause_pointer, recenter, {COMMAND_PREFIX}<phrase>"
            )
            continue
        chord = normalize_chord(tokens)
        if HOLD in tokens and not HOLDABLE.intersection(tokens):
            problems.append(
                f"{where}: 'hold' needs a token that can be held to be a duration of "
                f"({', '.join(sorted(HOLDABLE))}); nod and shake are momentary. Ignored"
            )
            continue
        if chord in bound or chord in collided:
            problems.append(f"{where}: the chord {chord!r} is bound twice; neither binding is used")
            bound.pop(chord, None)
            collided.add(chord)
            continue
        bound[chord] = action
    # "jaw_open" and "jaw_open+hold" together: the plain chord fires when its window closes, long
    # before the hold can complete, so the hold variant could never run. Refuse both rather
    # than silently run the one the user may not have meant.
    for chord in sorted(c for c in bound if HOLD in c.split("+")):
        plain = normalize_chord(t for t in chord.split("+") if t != HOLD)
        if chord in bound and plain in bound:
            problems.append(
                f"chords: {plain!r} and {chord!r} are both bound; the plain chord would always fire "
                f"first, so neither binding is used"
            )
            del bound[chord], bound[plain]
    return bound, problems


class ChordEngine:
    """Turns token presses, pulses and releases into at most one action per engagement."""

    def __init__(
        self,
        bindings: Mapping[str, str],
        handlers: Mapping[str, Callable[[], object]],
        *,
        window_s: float = 0.4,
        refractory_s: float = 1.0,
        freeze_tail_s: float = 0.3,
        hold_s: float = DEFAULT_HOLD_S,
        gate: _Gate | None = None,
        on_freeze: Callable[[bool], None] | None = None,
        source: str = SAFETY_SOURCE,
    ) -> None:
        self._bindings = {normalize_chord(k.split("+")): v for k, v in bindings.items()}
        self._handlers = dict(handlers)
        self._window = _nonneg(window_s, 0.4)
        self._refractory = _nonneg(refractory_s, 1.0)
        self._tail = _nonneg(freeze_tail_s, 0.3)
        self._hold_s = _nonneg(hold_s, DEFAULT_HOLD_S)
        self._gate = gate
        self._on_freeze = on_freeze
        self._source = source
        # Only tokens some chord uses are remembered; the rest cannot take part in anything.
        self._vocab = frozenset(t for chord in self._bindings for t in chord.split("+"))
        self._chord_sets = [frozenset(c.split("+")) for c in self._bindings]
        self._held: set[str] = set()
        self._onset: set[str] = set()
        self._seen: set[str] = set()
        self._state = "idle"  # idle | gather | spent
        self._opened_s = 0.0
        self._cooldown_until = -math.inf
        self._freeze_until = -math.inf
        self._freeze = False
        self._since_hint: float | None = None
        self._freeze_since: float | None = None
        self._set_since: float | None = None  # when the tokens now held last changed
        self._hold_on = False
        self._paused = False
        self._warned: set[str] = set()

    # ------------------------------------------------------------------ introspection

    @property
    def bindings(self) -> dict[str, str]:
        """A copy of the ``{chord_id: action}`` table in force."""
        return dict(self._bindings)

    @property
    def vocabulary(self) -> frozenset[str]:
        """The tokens some bound chord uses -- the only ones a sensor needs to watch."""
        return self._vocab

    @property
    def freeze_pointer(self) -> bool:
        """True while the pointer is being asked to hold still for a gesture."""
        return self._freeze

    @property
    def freeze_started_s(self) -> float | None:
        """The camera-frame time that began the current pointer freeze, if the caller gave one.

        Meaningful inside the ``on_freeze(True)`` callback (and while the freeze lasts); ``None``
        when the freeze began from something with no frame of its own (a head pulse, a tail).
        """
        return self._freeze_since

    @property
    def paused(self) -> bool:
        return self._paused

    def unwired(self) -> list[str]:
        """Bound actions with no handler in this build, sorted. They do nothing."""
        return sorted({a for a in self._bindings.values() if a not in self._handlers})

    # ------------------------------------------------------------------ token input

    def press(self, token: str, now_s: float, at_s: float | None = None) -> None:
        """A held token became held (a face gesture, a tilt).

        ``at_s`` is the camera frame that made it so, when the caller has one (see
        :attr:`freeze_started_s`).
        """
        if token not in self._vocab or token == HOLD:
            return
        self._settle(now_s)
        if token not in self._held:
            self._held.add(token)
            self._held_changed(now_s)
        self._seen.add(token)
        self._onset.discard(token)
        self._open(now_s)
        self._since_hint = at_s
        self._step(now_s)

    def release(self, token: str, now_s: float) -> None:
        """A held token let go. Never gated: a release only ever makes things quieter."""
        if token in self._held or token in self._onset:
            self._freeze_until = now_s + self._tail   # the effort fades after the detector says so
        if token in self._held:
            self._held.discard(token)
            self._held_changed(now_s)
        self._onset.discard(token)
        self._step(now_s)

    def pulse(self, token: str, now_s: float) -> None:
        """A momentary token (a nod, a shake) just happened."""
        if token not in self._vocab or token == HOLD:
            return
        self._settle(now_s)
        self._seen.add(token)
        self._freeze_until = now_s + self._tail
        self._open(now_s)
        self._step(now_s)

    def onset(self, token: str, engaged: bool, now_s: float, at_s: float | None = None) -> None:
        """The expression behind ``token`` has begun but is not yet a token.

        Only the pointer freeze reads this: a facial effort moves the head *before* a
        detector has seen enough frames to call it a gesture. ``at_s`` is the camera frame
        that showed it (see :attr:`freeze_started_s`).
        """
        if token not in self._vocab or token == HOLD:
            return
        if engaged and token not in self._held:
            self._onset.add(token)
            self._since_hint = at_s
        elif token in self._onset:
            self._onset.discard(token)
            self._freeze_until = now_s + self._tail
        self._step(now_s)

    def tick(self, now_s: float) -> None:
        """Advance time with no new token (the window closing, the freeze tail ending)."""
        self._step(now_s)

    def frame(self, has_signal: bool, now_s: float) -> None:
        """Once per runner tick: report liveness, and drop everything if now suppressed.

        Samples the gate only when the tick carried a signal, so a camera that goes blind
        ages the source out (ADR-v2-148) instead of looking healthy. When the gate is closed
        the engagement in flight is *discarded*: tokens still physically held must be let go
        of before another chord can fire, so nothing is replayed on resume.
        """
        try:
            if self._gate is not None and has_signal:
                self._gate.sample(self._source)
            if self._state != "idle" and (self._paused or not self._allowed()):
                self._spend()
        except Exception:
            log.debug("gesture: gate poll failed", exc_info=True)
        self._step(now_s)

    def set_paused(self, paused: bool) -> None:
        """Pause or resume chord actions locally (the ``yazses gesture`` command)."""
        self._paused = bool(paused)
        if self._paused and self._state != "idle":
            self._spend()

    def reset(self, now_s: float = 0.0) -> None:
        """Forget every token and release the freeze (signal lost, shutdown). Idempotent."""
        self._held.clear()
        self._onset.clear()
        self._seen.clear()
        self._set_since = None
        self._hold_on = False
        self._state = "idle"
        self._freeze_until = -math.inf
        self._set_freeze(False)

    # ------------------------------------------------------------------ the state machine

    def _open(self, now_s: float) -> None:
        if self._state == "idle":
            self._state = "gather"
            self._opened_s = now_s

    def _settle(self, now_s: float) -> None:
        """Leave ``spent`` once every token is released and the refractory has passed."""
        if self._state == "spent" and not self._held and now_s >= self._cooldown_until:
            self._seen.clear()
            self._state = "idle"

    def _held_changed(self, now_s: float) -> None:
        """The set of held tokens just changed: a ``hold`` in progress starts over."""
        if self._hold_on:
            self._hold_on = False
            self._seen.discard(HOLD)
        self._set_since = now_s if self._held else None

    def _advance_hold(self, now_s: float) -> None:
        """Make ``hold`` true once the held tokens have been held unchanged for ``hold_s``."""
        if (
            HOLD in self._vocab
            and not self._hold_on
            and self._held
            and self._set_since is not None
            and now_s - self._set_since >= self._hold_s
            # a holdable token let go of earlier in this engagement was not held *with* the rest
            and (self._seen & HOLDABLE) <= self._held
        ):
            self._hold_on = True
            if self._state == "gather":  # a spent engagement stays spent
                self._seen.add(HOLD)

    def _step(self, now_s: float) -> None:
        self._advance_hold(now_s)
        hint, self._since_hint = self._since_hint, None
        if self._held or self._onset:
            self._freeze_until = now_s + self._tail
        self._set_freeze(bool(self._held or self._onset) or now_s < self._freeze_until, hint)
        if self._state == "gather" and (
            now_s - self._opened_s >= self._window or not self._could_grow()
        ) and not self._waiting_for_a_pulse():
            self._fire(now_s)
        self._settle(now_s)

    def _waiting_for_a_pulse(self) -> bool:
        """Held tokens that are not a chord yet but could become one, and still are held.

        A head gesture takes about a second to recognise, longer than the window, so a face
        gesture held *while* it is made would otherwise have been spent before the nod
        completed. Waiting is bounded by the hold itself: letting go ends the engagement.
        """
        return (
            bool(self._held)
            and resolve_chord(sorted(self._seen), self._bindings) is None
            and self._could_grow()
        )

    def _could_grow(self) -> bool:
        """Could the tokens seen so far still become a *longer* bound chord?"""
        return any(self._seen < chord for chord in self._chord_sets)

    def _fire(self, now_s: float) -> None:
        chord = sorted(self._seen)
        action = resolve_chord(chord, self._bindings)
        self._seen.clear()
        self._state = "spent"
        self._cooldown_until = now_s + self._refractory
        if action is None:
            return
        handler = self._handlers.get(action)
        if handler is None:
            if action not in self._warned:
                self._warned.add(action)
                log.warning(
                    "[gesture] %r is bound to %r, which nothing implements in this build; "
                    "the chord does nothing.", normalize_chord(chord), action,
                )
            return
        if action not in _SAFE and (self._paused or not self._allowed()):
            return
        try:
            handler()
        except Exception:
            log.warning("gesture: %s handler raised", action, exc_info=True)

    def _spend(self) -> None:
        self._seen.clear()
        self._state = "spent"
        self._cooldown_until = -math.inf

    def _allowed(self) -> bool:
        if self._gate is None:
            return True
        decision = self._gate.gate(self._source)
        return bool(getattr(decision, "allowed", False))

    def _set_freeze(self, now: bool, since_s: float | None = None) -> None:
        if now == self._freeze:
            return
        self._freeze = now
        self._freeze_since = since_s if now else None
        callback = self._on_freeze
        if callback is not None:
            try:
                callback(now)
            except Exception:
                log.warning("gesture: freeze callback raised", exc_info=True)


def _nonneg(value: object, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) and number >= 0.0 else default
