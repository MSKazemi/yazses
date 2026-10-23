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
"confirm" rather than toggled on a guess (``plan.decide``). "uncheck" on a radio button is
refused with the reason: clicking one selects it, it is turned off by choosing another.

The pending action follows the gate's rules, deliberately:

* **Anything else discards it.** There is no modal state that swallows dictation until
  the magic word is said; a user who has moved on loses the click, never their speech.
* **It expires** after :data:`PENDING_TTL_S`. A "confirm" said minutes later, about
  something else, must not click a button in a window the user has long left.
* **It is decided again at confirm time, for every held verb.** The window can change
  during the hold -- a dialog closes, another identical "Delete" row appears, the user
  ticks the box themselves -- and the snapshot id held since the prompt then names a
  different control, or none. So "confirm" re-reads the window through the same backend
  instance, finds the held control again by its exact label (case and whitespace
  folded), its role and its position among identical controls (``plan.redecide_held``),
  and acts once on that control's *new* id. Gone, renamed, a different role, no longer
  clickable, or a different number of identical controls so it is unclear which was
  meant: nothing is clicked and the user is told why. It never falls back to a fresh
  match of the spoken words, which could be a different control. A held "check" /
  "uncheck" is also re-checked against the state it asked for: already in that state
  now, nothing is clicked.

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
    REFUSED,
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
    # What finds the held control again; the confirm re-reads and re-decides on it. No
    # snapshot id is kept: the one read at hold time must never be acted on.
    target: HeldTarget
    at: float


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
        if decision.verdict == REFUSED:
            return self._radio_uncheck(decision)
        return PilotOutcome("none", self._no_match_message(decision))

    @staticmethod
    def _radio_uncheck(decision: PilotDecision) -> PilotOutcome:
        """"uncheck X" on a radio button: clicking it would select it, never clear it."""
        elem = decision.element
        assert elem is not None
        return PilotOutcome("refused", f"Cannot uncheck {_show(elem.label)}: a radio button "
                                       "is turned off by choosing another option. "
                                       "Nothing was changed.")

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
              target: HeldTarget | None) -> PilotOutcome:
        elem = decision.element
        assert elem is not None and decision.action_name is not None
        if target is None:  # pragma: no cover - decide() picked it from these elements
            # Nothing could find it again at confirm time, so nothing may be held.
            return PilotOutcome("none", f"Could not hold {_show(elem.label)} for a "
                                        "confirm; nothing was clicked.")
        self._pending = _Pending(target, self._clock())
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
            return self._confirm(held.target)
        if control == "cancel":
            return PilotOutcome("cancelled", "Cancelled — nothing was clicked.")
        if parse_command(text) is not None:
            return PilotOutcome("discarded", None, consumed=False)
        return PilotOutcome("discarded", "Discarded the held click — it was not confirmed.",
                            consumed=False)

    def _confirm(self, target: HeldTarget) -> PilotOutcome:
        """Carry out a confirmed held click only if a fresh read still finds its control.

        Every held verb comes here -- a destructive label, a partial match, a tie, a
        "check" on an unread state. The id held since the prompt belongs to the old
        snapshot; the re-read replaces it, so the click goes once to the same control as
        it is *now* -- or nowhere, with the reason told.
        """
        shown = _show(target.label)
        candidates = self._reader.read()
        if candidates is None:
            return PilotOutcome("refused", f"Could not re-read the window to find "
                                           f"{shown} again; nothing was changed.")
        decision = redecide_held(target, elements_from_candidates(candidates))
        log.info("Voice Pilot confirm: %s (%s), %d candidate(s) re-read.",
                 decision.verdict, decision.reason, len(candidates))
        if decision.verdict == REFUSED:
            return self._radio_uncheck(decision)
        if decision.verdict == ALREADY:
            state = "checked" if target.command.want_checked else "unchecked"
            return PilotOutcome("already", f"{shown} is already {state} now; "
                                           "nothing was changed.")
        if decision.verdict == ACT:
            elem = decision.element
            assert elem is not None and decision.action_name is not None
            if target.command.want_checked is None:
                done = f"Done: {shown}."
            else:
                # Unread then and now: what the user confirmed was a toggle, so say so.
                verb = (_verb_past(target.command) if elem.checked is not None
                        else _VERB_PAST["toggle"])
                done = f"Done: {verb.lower()} {shown}."
            if self._reader.perform(elem.entity_id, decision.action_name):
                return PilotOutcome("confirmed", done)
            return PilotOutcome("failed", f"Could not act on {shown}: it did not respond.")
        if decision.reason == HELD_GONE:
            # Vanished, renamed, a different role, or no longer clickable: the prompt
            # named a control that is not there any more as itself.
            why = f"{shown} is no longer in the window as the same control"
        elif decision.reason == HELD_AMBIGUOUS:
            why = (f"the window changed and it is no longer clear which {shown} "
                   "was meant")
        else:  # state_lost
            why = f"whether {shown} is checked can no longer be read"
        return PilotOutcome("refused", f"Did not act: {why}. Nothing was changed.")


__all__ = ["PENDING_TTL_S", "PilotOutcome", "PilotService", "elements_from_candidates"]
