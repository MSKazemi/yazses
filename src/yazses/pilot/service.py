"""The Voice Pilot as the daemon uses it: read, decide, act or ask (ADR-v2-007, #164).

`plan.py` decides; `grounding/onscreen.py` reads the focused window and acts through the
platform's accessibility backend (AT-SPI on Linux). This module is the thin seam that
joins them for the daemon, so the daemon needs one lazy import and two calls.

**It acts only on a specific, checkable match (ADR-021).** One actionable control whose
label exactly matches what was said is clicked at once. Everything else -- a partial
match, a tie, a destructive label such as "Delete" or "Send" -- is *held*, announced, and
carried out only when the next utterance is a confirm word. The confirm and cancel words
are the Command Safety Gate's own (``[cmdsafety] confirm_words`` / ``cancel_words``,
matched by ``cmdsafety/spoken.py``), so the user learns one vocabulary for "yes, do the
risky thing", not two.

"check X" and "uncheck X" are idempotent: a box already in the asked state is left alone
and the user is told so, and a box whose state the backend could not read is held for
"confirm" rather than toggled on a guess (``plan.decide``).

The pending action follows the gate's rules, deliberately:

* **Anything else discards it.** There is no modal state that swallows dictation until
  the magic word is said; a user who has moved on loses the click, never their speech.
* **It expires** after :data:`PENDING_TTL_S`. A "confirm" said minutes later, about
  something else, must not click a button in a window the user has long left.
* **It acts on the node that was matched**, through the same backend instance that read
  it -- never on a fresh match of the same words, which could be a different control.
* **Except a held "check" / "uncheck", which is decided again.** Its effect depends on a
  state the user can change during the hold, so "confirm" re-reads the window, finds the
  same control by label and role (``plan.redecide_held``) and acts only if it is still
  specifically there and still in the other state. Gone, no longer telling which one, or
  already in the asked state: nothing is clicked and the user is told why.

Messages name the control's label (bidi-isolated, truncated); nothing here logs it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from yazses.bidi import wrap_user_text
from yazses.cmdsafety.spoken import match_control
from yazses.grounding.onscreen import OnScreenReader
from yazses.pilot.plan import (
    ACT,
    ALREADY,
    CONFIRM,
    HELD_AMBIGUOUS,
    HELD_GONE,
    Element,
    HeldTarget,
    PilotCommand,
    PilotDecision,
    decide,
    held_target,
    parse_command,
    redecide_held,
)

log = logging.getLogger(__name__)

#: How long a held click waits for "confirm". Long enough to read a notification and
#: answer; short enough that the window is very likely still the one the user meant.
PENDING_TTL_S = 30.0

#: Labels are user content and can be long (a link's whole sentence); messages show this
#: many characters of one.
_LABEL_CHARS = 60


@dataclass(frozen=True)
class PilotOutcome:
    """What one utterance did. ``consumed`` False means "not mine -- carry on with it"."""

    # act | already | confirm | none | confirmed | cancelled | discarded | failed | refused
    verdict: str
    message: str | None
    consumed: bool = True


@dataclass(frozen=True)
class _Pending:
    entity_id: str
    action_name: str
    label: str
    at: float
    # Set for a held "check"/"uncheck": the confirm re-reads and re-decides on it.
    target: HeldTarget | None = None


def elements_from_candidates(candidates: Iterable) -> list[Element]:
    """Plan elements from snapshot candidates: label, role, actions and the id. Pure."""
    out: list[Element] = []
    for c in candidates:
        label = getattr(c, "label", None) or ""
        if not label:
            continue
        checked = getattr(c, "checked", None)
        out.append(Element(label=label, role=getattr(c, "role", "") or "",
                           actions=tuple(getattr(c, "actions", ()) or ()),
                           # Only a real bool is a state; anything else is "unknown".
                           checked=checked if isinstance(checked, bool) else None,
                           entity_id=getattr(c, "entity_id", "") or ""))
    return out


def _show(label: str) -> str:
    text = " ".join((label or "").split())
    if len(text) > _LABEL_CHARS:
        text = text[: _LABEL_CHARS - 1] + "…"
    return f"'{wrap_user_text(text)}'"


_VERB_PAST = {"activate": "Clicked", "toggle": "Toggled", "focus": "Focused"}
_VERB_NOW = {"activate": "click", "toggle": "toggle", "focus": "focus"}


def _verb_now(cmd: PilotCommand, *, state_known: bool = True) -> str:
    """"check"/"uncheck" when the command asked for a state that was read, else the verb."""
    if cmd.want_checked is not None and state_known:
        return "check" if cmd.want_checked else "uncheck"
    return _VERB_NOW.get(cmd.action, "activate")


def _verb_past(cmd: PilotCommand) -> str:
    if cmd.want_checked is not None:
        return "Checked" if cmd.want_checked else "Unchecked"
    return _VERB_PAST.get(cmd.action, "Activated")


class PilotService:
    """One daemon session's Voice Pilot. Never raises, never types."""

    def __init__(
        self,
        reader: OnScreenReader,
        *,
        threshold: float = 0.5,
        confirm_ambiguous: bool = True,
        confirm_words: Sequence[str] | None = None,
        cancel_words: Sequence[str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        unavailable_reason: str | None = None,
    ) -> None:
        self._reader = reader
        self._threshold = float(threshold)
        self._confirm_ambiguous = bool(confirm_ambiguous)
        self._confirm_words = confirm_words
        self._cancel_words = cancel_words
        self._clock = clock
        self._unavailable_reason = unavailable_reason
        self._pending: _Pending | None = None

    # -- state -------------------------------------------------------------------
    @property
    def pending(self) -> bool:
        """Whether a held action is waiting for confirm (and has not expired)."""
        p = self._pending
        if p is None:
            return False
        if self._clock() - p.at > PENDING_TTL_S:
            self._pending = None
            return False
        return True

    # -- a new command -----------------------------------------------------------
    def command(self, phrase: str) -> PilotOutcome:
        """Handle "click/press/toggle/check/uncheck <label>". Consumed once routed here."""
        self._pending = None  # a new command replaces whatever was held
        if parse_command(phrase) is None:
            return PilotOutcome("none", None, consumed=False)
        candidates = self._reader.read()
        if candidates is None:
            reason = self._unavailable_reason or (
                "the focused window's accessibility tree could not be read")
            return PilotOutcome("none", f"Voice Pilot did nothing: {reason}.")
        elements = elements_from_candidates(candidates)
        decision = decide(phrase, elements,
                          threshold=self._threshold,
                          confirm_ambiguous=self._confirm_ambiguous)
        if decision is None:  # pragma: no cover - parse_command already said yes
            return PilotOutcome("none", None, consumed=False)
        log.info("Voice Pilot: %s (%s), %d candidate(s) read.",
                 decision.verdict, decision.reason, len(candidates))
        if decision.verdict == ACT:
            return self._act(decision)
        if decision.verdict == CONFIRM:
            return self._hold(decision, held_target(decision, elements))
        if decision.verdict == ALREADY:
            return self._already(decision)
        return PilotOutcome("none", self._no_match_message(decision))

    @staticmethod
    def _already(decision: PilotDecision) -> PilotOutcome:
        """"check X" on a checked box, "uncheck X" on an unchecked one: touch nothing."""
        elem = decision.element
        assert elem is not None
        state = "checked" if decision.command.want_checked else "unchecked"
        return PilotOutcome("already", f"{_show(elem.label)} is already {state}; "
                                       "nothing was changed.")

    def _act(self, decision: PilotDecision) -> PilotOutcome:
        elem = decision.element
        assert elem is not None and decision.action_name is not None
        cmd = decision.command
        if self._reader.perform(elem.entity_id, decision.action_name):
            return PilotOutcome("act", f"{_verb_past(cmd)} {_show(elem.label)}.")
        return PilotOutcome("failed", f"Could not {_verb_now(cmd)} "
                                      f"{_show(elem.label)}: the control did not respond.")

    def _hold(self, decision: PilotDecision,
              target: HeldTarget | None = None) -> PilotOutcome:
        elem = decision.element
        assert elem is not None and decision.action_name is not None
        self._pending = _Pending(elem.entity_id, decision.action_name, elem.label,
                                 self._clock(), target)
        # With the state unread, what a confirm does is flip it, so say "toggle".
        verb = _verb_now(decision.command, state_known=elem.checked is not None)
        what = f"{verb} {_show(elem.label)}"
        if decision.reason == "state_unknown":
            lead = f"Could not read whether {_show(elem.label)} is checked."
        elif decision.reason == "destructive":
            lead = f"{_show(elem.label)} may not be undoable."
        elif decision.reason == "ambiguous":
            lead = (f"{decision.matches} controls match. The first is {_show(elem.label)};"
                    " say an ordinal (“the second…”) to pick another.")
        else:
            lead = f"Closest match is {_show(elem.label)}."
        return PilotOutcome("confirm", f"{lead} Say “confirm” to {what}, "
                                       "or “cancel”.")

    @staticmethod
    def _no_match_message(decision: PilotDecision) -> str:
        target = _show(decision.command.target)
        if decision.reason == "ambiguous":
            return (f"{decision.matches} controls match {target}; nothing was clicked. "
                    "Say an ordinal, e.g. “click the second ...”.")
        if decision.reason == "ordinal_out_of_range":
            return f"There are not that many controls matching {target}; nothing was clicked."
        return f"No control on screen matches {target}; nothing was clicked."

    # -- the answer to a held action ----------------------------------------------
    def answer(self, text: str) -> PilotOutcome:
        """Resolve a held action with the next utterance.

        Confirm runs it; cancel drops it; anything else drops it **and is not consumed**,
        so the utterance carries on down the command path exactly as if nothing had been
        held. A new pilot command drops it silently (it is about to replace it).
        """
        if not self.pending:
            return PilotOutcome("none", None, consumed=False)
        held = self._pending
        self._pending = None
        assert held is not None
        control = match_control(text, self._confirm_words, self._cancel_words)
        if control == "confirm":
            if held.target is not None:
                return self._confirm_check(held.target)
            if self._reader.perform(held.entity_id, held.action_name):
                return PilotOutcome("confirmed", f"Done: {_show(held.label)}.")
            return PilotOutcome("failed", f"Could not act on {_show(held.label)}: it is no "
                                          "longer there or did not respond.")
        if control == "cancel":
            return PilotOutcome("cancelled", "Cancelled — nothing was clicked.")
        if parse_command(text) is not None:
            return PilotOutcome("discarded", None, consumed=False)
        return PilotOutcome("discarded", "Discarded the held click — it was not confirmed.",
                            consumed=False)

    def _confirm_check(self, target: HeldTarget) -> PilotOutcome:
        """Carry out a confirmed "check"/"uncheck" only if a fresh read still calls for it.

        The id held since the prompt belongs to the old snapshot; the re-read replaces
        it, so the click goes to the control as it is *now* -- or nowhere.
        """
        shown = _show(target.label)
        candidates = self._reader.read()
        if candidates is None:
            return PilotOutcome("refused", f"Could not re-read the window to check "
                                           f"{shown} again; nothing was changed.")
        decision = redecide_held(target, elements_from_candidates(candidates))
        log.info("Voice Pilot confirm: %s (%s), %d candidate(s) re-read.",
                 decision.verdict, decision.reason, len(candidates))
        if decision.verdict == ALREADY:
            state = "checked" if target.command.want_checked else "unchecked"
            return PilotOutcome("already", f"{shown} is already {state} now; "
                                           "nothing was changed.")
        if decision.verdict == ACT:
            elem = decision.element
            assert elem is not None and decision.action_name is not None
            # Unread then and now: what the user confirmed was a toggle, so say so.
            verb = (_verb_past(target.command) if elem.checked is not None
                    else _VERB_PAST["toggle"])
            if self._reader.perform(elem.entity_id, decision.action_name):
                return PilotOutcome("confirmed", f"Done: {verb.lower()} {shown}.")
            return PilotOutcome("failed", f"Could not act on {shown}: it did not respond.")
        if decision.reason == HELD_GONE:
            why = f"{shown} is no longer in the window"
        elif decision.reason == HELD_AMBIGUOUS:
            why = (f"the window changed and it is no longer clear which {shown} "
                   "was meant")
        else:  # state_lost
            why = f"whether {shown} is checked can no longer be read"
        return PilotOutcome("refused", f"Did not act: {why}. Nothing was changed.")


__all__ = ["PENDING_TTL_S", "PilotOutcome", "PilotService", "elements_from_candidates"]
