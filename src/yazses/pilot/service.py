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

The pending action follows the gate's rules, deliberately:

* **Anything else discards it.** There is no modal state that swallows dictation until
  the magic word is said; a user who has moved on loses the click, never their speech.
* **It expires** after :data:`PENDING_TTL_S`. A "confirm" said minutes later, about
  something else, must not click a button in a window the user has long left.
* **It acts on the node that was matched**, through the same backend instance that read
  it -- never on a fresh match of the same words, which could be a different control.

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
from yazses.pilot.plan import ACT, CONFIRM, Element, PilotDecision, decide, parse_command

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

    verdict: str          # act | confirm | none | confirmed | cancelled | discarded | failed
    message: str | None
    consumed: bool = True


@dataclass(frozen=True)
class _Pending:
    entity_id: str
    action_name: str
    label: str
    at: float


def elements_from_candidates(candidates: Iterable) -> list[Element]:
    """Plan elements from snapshot candidates: label, role, actions and the id. Pure."""
    out: list[Element] = []
    for c in candidates:
        label = getattr(c, "label", None) or ""
        if not label:
            continue
        out.append(Element(label=label, role=getattr(c, "role", "") or "",
                           actions=tuple(getattr(c, "actions", ()) or ()),
                           entity_id=getattr(c, "entity_id", "") or ""))
    return out


def _show(label: str) -> str:
    text = " ".join((label or "").split())
    if len(text) > _LABEL_CHARS:
        text = text[: _LABEL_CHARS - 1] + "…"
    return f"'{wrap_user_text(text)}'"


_VERB_PAST = {"activate": "Clicked", "toggle": "Toggled", "focus": "Focused"}
_VERB_NOW = {"activate": "click", "toggle": "toggle", "focus": "focus"}


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
        """Handle "click/press/toggle/check <label>". Always consumed once routed here."""
        self._pending = None  # a new command replaces whatever was held
        if parse_command(phrase) is None:
            return PilotOutcome("none", None, consumed=False)
        candidates = self._reader.read()
        if candidates is None:
            reason = self._unavailable_reason or (
                "the focused window's accessibility tree could not be read")
            return PilotOutcome("none", f"Voice Pilot did nothing: {reason}.")
        decision = decide(phrase, elements_from_candidates(candidates),
                          threshold=self._threshold,
                          confirm_ambiguous=self._confirm_ambiguous)
        if decision is None:  # pragma: no cover - parse_command already said yes
            return PilotOutcome("none", None, consumed=False)
        log.info("Voice Pilot: %s (%s), %d candidate(s) read.",
                 decision.verdict, decision.reason, len(candidates))
        if decision.verdict == ACT:
            return self._act(decision)
        if decision.verdict == CONFIRM:
            return self._hold(decision)
        return PilotOutcome("none", self._no_match_message(decision))

    def _act(self, decision: PilotDecision) -> PilotOutcome:
        elem = decision.element
        assert elem is not None and decision.action_name is not None
        verb = decision.command.action
        if self._reader.perform(elem.entity_id, decision.action_name):
            return PilotOutcome("act", f"{_VERB_PAST.get(verb, 'Activated')} {_show(elem.label)}.")
        return PilotOutcome("failed", f"Could not {_VERB_NOW.get(verb, 'activate')} "
                                      f"{_show(elem.label)}: the control did not respond.")

    def _hold(self, decision: PilotDecision) -> PilotOutcome:
        elem = decision.element
        assert elem is not None and decision.action_name is not None
        self._pending = _Pending(elem.entity_id, decision.action_name, elem.label,
                                 self._clock())
        verb = _VERB_NOW.get(decision.command.action, "activate")
        what = f"{verb} {_show(elem.label)}"
        if decision.reason == "destructive":
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


__all__ = ["PENDING_TTL_S", "PilotOutcome", "PilotService", "elements_from_candidates"]
