"""What the daemon does with a face switch's ``select`` / ``confirm`` / ``cancel`` (pure).

ADR-v2-147 lets a gesture be bound to the abstract actions in
:data:`~yazses.facegesture.switches.ACTIONS`; :class:`~yazses.facegesture.switches.SwitchMapper`
decides *whether* a gesture reaches a handler (bound, gate open, no double press). This module is
the decision *behind* three of those handlers, kept apart from the daemon so every branch is a
plain function a test can drive with fakes -- no camera, no pointer, no notification, no thread
(AGENTS.md rule 5). The daemon glue is the thin part: it supplies the two injected effects (a
click, a way to release a held command) and nothing else.

**Every outcome is one of three words, and none is silent.** ``done`` (the effect happened),
``refused`` (something was bound and asked for, and a stated reason said no) and ``noop`` (there
was nothing to act on). The log keeps the newest of each action so ``yazses facegesture status``
and the hands-free state can show *why a gesture did nothing* -- for a user whose only input is a
camera, "nothing happened" with no explanation is the whole failure (EYE-OBS-001).

**``select`` is a commit.** One left click at wherever the Head-Pointer already is, never a move
and never a position taken from this module. It acts only when the pointer is running, tracking,
not paused, not clutched by anyone else, and the hands-free gate allows it
(:func:`select_refusal`); and a :class:`SelectLimiter` makes one gesture one click -- a held
expression cannot repeat, and a flickering one cannot machine-gun, because a second click inside
the minimum interval is refused with that reason. The mapper's own freeze (``on_freeze``) holds the
pointer still while a commit gesture is down, so the click lands where the user aimed rather than
where the facial effort pushed the head; the clutch it takes is this switch's own and is excluded
from the "clutched" test, otherwise every select would refuse itself.

**``confirm`` / ``cancel`` only resolve a confirmation that already exists.** They never create
one, never choose what is confirmed, and with nothing pending are a ``noop`` -- not an error and
not an action (:func:`resolve_confirmation`). They go through the same holder the spoken "confirm"
uses, so a face switch is a second way to *answer*, never a way around the question: a command
the daemon holds as dangerous is still held until somebody confirms it.

**Rule 9 (a guard is judged on how rarely it fires).** Every refusal here is a specific,
checkable fact (paused, clutched, no signal, gate closed, too soon) rather than a heuristic about
what the user "probably" meant, and the gesture itself already passed the detector's hold-time and
refractory rules before it got here.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "DONE",
    "NOOP",
    "REFUSED",
    "SELECT_MIN_INTERVAL_S",
    "SWITCH_CLUTCH_SOURCE",
    "TRACKED_ACTIONS",
    "ActionOutcome",
    "SelectLimiter",
    "SwitchOutcomeLog",
    "line_from_row",
    "perform_select",
    "resolve_confirmation",
    "select_refusal",
]

DONE = "done"
REFUSED = "refused"
NOOP = "noop"

#: The three actions this module owns. ``pause_pointer`` and the holds already had handlers.
TRACKED_ACTIONS: tuple[str, ...] = ("select", "confirm", "cancel")

#: Smallest gap between two ``select`` clicks, in seconds. **PROVISIONAL -- not a measured
#: value.** No data exists on how fast people legitimately re-trigger a deliberate facial
#: switch, or on how often a held expression flickers across the detector's thresholds; one
#: second is a placeholder chosen to be well above any single hold's flicker and well below a
#: deliberate double-select, and it errs long because a swallowed second click is recoverable
#: (make the gesture again) while a repeated one on a "Delete" button is not. To be replaced
#: by measurement (design/eye-control/GOVERNANCE.md requires it before a default is
#: recommended).
SELECT_MIN_INTERVAL_S = 1.0

#: The name the face-switch freeze holds the Head-Pointer clutch under. Excluded from the
#: "is the pointer clutched?" test for a select, because it is this very gesture.
SWITCH_CLUTCH_SOURCE = "faceswitch"


@dataclass(frozen=True)
class ActionOutcome:
    """What one switch action did. Names and a fixed-vocabulary reason -- never a value.

    ``reason`` is always one of this module's own sentences (or a held-command *kind*), never
    a coordinate, a score or the text that was held: the outcome is printed by ``status`` and
    pasted into issues.
    """

    action: str
    result: str
    reason: str = ""
    at_s: float = 0.0

    @property
    def line(self) -> str:
        """``select: refused (the pointer is paused)`` -- one glance-sized line."""
        text = f"{self.action}: {self.result}"
        return f"{text} ({self.reason})" if self.reason else text


class SwitchOutcomeLog:
    """The newest outcome per action, plus counts. Thread-safe: written from the camera thread,
    read from IPC."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._last: dict[str, ActionOutcome] = {}
        self._counts: dict[str, dict[str, int]] = {}

    def record(self, outcome: ActionOutcome) -> ActionOutcome:
        with self._lock:
            self._last[outcome.action] = outcome
            per = self._counts.setdefault(outcome.action, {DONE: 0, REFUSED: 0, NOOP: 0})
            per[outcome.result] = per.get(outcome.result, 0) + 1
        return outcome

    def last(self, action: str) -> ActionOutcome | None:
        with self._lock:
            return self._last.get(action)

    def snapshot(self, bound: Iterable[str]) -> list[dict[str, object]]:
        """One row per *bound* tracked action, in :data:`TRACKED_ACTIONS` order. JSON-safe.

        An action that is bound and has never fired reports ``"result": "unused"``: the user
        can tell "wired and waiting" from "not bound" (absent from the list). Names, words,
        counts and an age -- no value from the camera.
        """
        wanted = set(bound)
        now = self._clock()
        rows: list[dict[str, object]] = []
        with self._lock:
            for action in TRACKED_ACTIONS:
                if action not in wanted:
                    continue
                last = self._last.get(action)
                counts = dict(self._counts.get(action, {DONE: 0, REFUSED: 0, NOOP: 0}))
                rows.append(
                    {
                        "action": action,
                        "result": last.result if last else "unused",
                        "reason": last.reason if last else "",
                        "age_s": None if last is None else round(max(0.0, now - last.at_s), 1),
                        "done": counts.get(DONE, 0),
                        "refused": counts.get(REFUSED, 0),
                        "noop": counts.get(NOOP, 0),
                    }
                )
        return rows

    def lines(self, bound: Iterable[str]) -> tuple[str, ...]:
        """:meth:`snapshot` as one line per action, for the hands-free state. Pure."""
        return tuple(line_from_row(row) for row in self.snapshot(bound))


def line_from_row(row: Mapping[str, object]) -> str:
    """One status line from a :meth:`SwitchOutcomeLog.snapshot` row. Pure.

    Total over a malformed row (it may have crossed IPC): unusable parts become words, never
    an exception.
    """
    action = str(row.get("action", "?"))
    result = str(row.get("result", "unused"))
    reason = str(row.get("reason", "") or "")
    if result == "unused":
        return f"{action}: bound, not used yet"
    text = f"{action}: last {result}"
    return f"{text} ({reason})" if reason else text


# ----------------------------------------------------------------------------- select


class ClickView(Protocol):
    """The facts about the pointer a select may be judged on -- flags and words only.

    ``clutched`` already excludes the face switch's own clutch. ``gate_allowed`` is ``None``
    when no hands-free gate exists (then there is nothing to consult, which is *not* a closed
    gate -- the same rule the face switch itself follows).
    """

    state: str
    paused: bool
    clutched: bool
    faulted: bool
    closed: bool
    gate_allowed: bool | None


class ClickResultLike(Protocol):
    ok: bool
    reason: str


def select_refusal(view: ClickView) -> str:
    """Why a select may not click now, or ``""`` if it may. Pure and total.

    Checked in the order a user would fix them: the pointer exists, it is not broken, nobody
    stopped it, the gate is open, there is a signal.
    """
    if view.closed:
        return "the Head-Pointer is shut down"
    if view.faulted:
        return "the pointer backend faulted; `yazses headpointer resume` clears it"
    if view.paused:
        return "the Head-Pointer is paused"
    if view.clutched:
        return "the pointer is clutched"
    if view.gate_allowed is False:
        return "the hands-free safety gate is closed"
    if view.state in ("waiting", "lost", "suppressed"):
        return "no fresh head-tracking signal"
    return ""


class SelectLimiter:
    """At most one click per ``min_interval_s``. Pure given its clock; thread-safe."""

    def __init__(
        self,
        min_interval_s: float = SELECT_MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # A non-positive or non-finite interval cannot express a limit at all, so it falls
        # back to the shipped one rather than being obeyed into "no limit".
        value = float(min_interval_s) if min_interval_s == min_interval_s else 0.0
        self._interval = value if 0.0 < value < float("inf") else SELECT_MIN_INTERVAL_S
        self._clock = clock
        self._lock = threading.Lock()
        self._last: float | None = None

    @property
    def min_interval_s(self) -> float:
        return self._interval

    def refusal(self) -> str:
        """``""`` when a click is allowed now, else the reason. Does not consume the slot."""
        now = self._clock()
        with self._lock:
            if self._last is not None and 0.0 <= now - self._last < self._interval:
                return f"a click was sent less than {self._interval:g} s ago"
        return ""

    def mark(self) -> None:
        """Record a click that really happened."""
        with self._lock:
            self._last = self._clock()


def perform_select(
    commit_click: Callable[[Callable[[ClickView], str]], ClickResultLike],
    limiter: SelectLimiter,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> ActionOutcome:
    """Run one ``select``: judge, then click once if allowed. Never raises.

    ``commit_click(policy)`` is the Head-Pointer's atomic entry point: it builds the
    :class:`ClickView` under its own lock, asks ``policy`` (a non-empty return is a refusal),
    and only then sends the click through its pointer sink. Judging and clicking under one lock
    is what stops a pause landing between "allowed" and "clicked".
    """

    def policy(view: ClickView) -> str:
        return select_refusal(view) or limiter.refusal()

    try:
        result = commit_click(policy)
    except Exception as exc:
        return ActionOutcome("select", REFUSED, f"the click failed ({type(exc).__name__})", clock())
    if result.ok:
        limiter.mark()
        return ActionOutcome("select", DONE, "", clock())
    return ActionOutcome("select", REFUSED, result.reason or "refused", clock())


# ------------------------------------------------------------------ confirm / cancel


class ConfirmationHolder(Protocol):
    """The daemon's pending-confirmation slot -- :class:`~yazses.cmdsafety.classify.ConfirmGate`
    satisfies it as it is."""

    @property
    def pending(self) -> object | None: ...

    def confirm(self) -> object | None: ...

    def cancel(self) -> None: ...


def resolve_confirmation(
    action: str,
    holder: ConfirmationHolder,
    release: Callable[[object], None],
    *,
    on_cancel: Callable[[], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ActionOutcome:
    """Answer the pending confirmation with ``confirm`` or ``cancel``. Never raises.

    With nothing pending this is a ``noop`` and touches nothing: no handler runs, no text is
    typed. ``release(held)`` is the daemon's way of doing what a spoken "confirm" does with the
    held thing (re-run the command, or type the text); it is called exactly once, and only
    after the holder has *given up* the held item, so two answers racing (a spoken "confirm" and
    a gesture) cannot release it twice -- the loser sees ``None`` and is a ``noop``.
    """
    if action not in ("confirm", "cancel"):
        return ActionOutcome(action, REFUSED, "not a confirmation answer", clock())
    try:
        if holder.pending is None:
            return ActionOutcome(action, NOOP, "nothing is waiting for confirmation", clock())
        if action == "cancel":
            holder.cancel()
            if on_cancel is not None:
                on_cancel()
            return ActionOutcome(action, DONE, "dropped the held command", clock())
        held = holder.confirm()
        if held is None:
            return ActionOutcome(action, NOOP, "nothing is waiting for confirmation", clock())
        try:
            release(held)
        except Exception as exc:
            return ActionOutcome(
                action, REFUSED, f"confirmed, but releasing it failed ({type(exc).__name__})", clock()
            )
        return ActionOutcome(action, DONE, "released the held command", clock())
    except Exception as exc:
        return ActionOutcome(action, REFUSED, f"failed ({type(exc).__name__})", clock())
