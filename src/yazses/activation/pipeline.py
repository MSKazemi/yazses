"""Route a decoded intent to an action, or to a confirmation (#137 + #138).

Pure orchestration with every side effect injected, so the whole decision path
is unit-testable without a decoder, a desktop, or an injector. The daemon wires
the real ``classify``/``dispatch``/``confirm`` in; tests pass fakes.

The order is deliberate and each step is a refusal the next one no longer has to
worry about:

1. **validate** against the source's declared vocabulary — a label the source
   never advertised never reaches the grammar.
2. **classify** with the *existing* command grammar, so a silent "undo" and a
   spoken "undo" resolve identically. A label the grammar does not recognise as
   a command is dropped rather than typed: a decoder is not a keyboard, and
   ~68% WER prose (Gaddy & Klein) is not text anyone asked for.
3. **decide** act / confirm / reject on confidence × consequence.
4. **act** — via the same dispatcher a spoken command uses.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from yazses.activation.confirm import (
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_FLOOR,
    Decision,
    classify_consequence,
    decide,
)
from yazses.activation.intent import ActivationIntent, Rejection, validate

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Outcome:
    """What happened to an intent. Returned so callers can log or test it."""

    decision: Decision | None          # None when refused before the policy ran
    rejection: Rejection | None = None
    action: str = ""
    confirmed: bool | None = None      # None when no confirmation was needed

    @property
    def executed(self) -> bool:
        return self.decision is Decision.ACT or self.confirmed is True


def handle_intent(
    intent: ActivationIntent,
    vocabulary: tuple[str, ...],
    *,
    classify: Callable[[str], object],
    dispatch: Callable[[object], None],
    confirm: Callable[[str, ActivationIntent], bool] | None = None,
    threshold: float = DEFAULT_CONFIRM_THRESHOLD,
    floor: float = DEFAULT_REJECT_FLOOR,
) -> Outcome:
    """Validate, classify, gate and (maybe) dispatch one intent.

    ``classify`` returns the project's ``CommandIntent`` (or ``None``);
    ``confirm`` shows an actionable prompt and returns the user's answer.
    A missing ``confirm`` makes every CONFIRM decision a refusal — failing
    closed, because a system that cannot ask must not assume yes.
    """
    rejection = validate(intent, vocabulary)
    if rejection is not None:
        log.info("Activation intent refused (%s): %r", rejection.value, intent.label)
        return Outcome(decision=None, rejection=rejection)

    command = classify(intent.label)
    action = getattr(command, "action", "") or ""
    # A DICTATE classification means the grammar found no command in the label.
    # Typing it would turn a decoder into a very bad keyboard.
    if command is None or not action or _is_dictate(command):
        log.info("Activation intent %r is not a command; ignoring.", intent.label)
        return Outcome(decision=None, rejection=Rejection.OUT_OF_VOCABULARY)

    decision = decide(
        intent.confidence, classify_consequence(action), threshold=threshold, floor=floor
    )
    if decision is Decision.REJECT:
        log.info("Activation intent %r rejected (confidence %.2f).",
                 intent.label, intent.confidence)
        return Outcome(decision=decision, action=action)

    if decision is Decision.CONFIRM:
        if confirm is None:
            log.warning("Activation intent %r needs confirmation but no prompt is "
                        "available; not acting.", intent.label)
            return Outcome(decision=decision, action=action, confirmed=False)
        if not confirm(action, intent):
            log.info("Activation intent %r declined by the user.", intent.label)
            return Outcome(decision=decision, action=action, confirmed=False)
        dispatch(command)
        return Outcome(decision=decision, action=action, confirmed=True)

    dispatch(command)
    return Outcome(decision=decision, action=action)


def _is_dictate(command: object) -> bool:
    """True when the grammar classified the label as plain text, not a command."""
    intent_type = getattr(command, "intent", None)
    return getattr(intent_type, "name", "") == "DICTATE"
