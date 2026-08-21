"""Asking the human a question out loud, on an agent's behalf (ADR-020 §1, §4).

The one genuinely novel thing YazSes can offer another agent is not transcription
— it is **a human**. An agent stalled on a decision only a person can make has, at
present, one route: put text on a screen and wait for someone to notice, read and
type it. Voice is the cheapest interrupt a working person can service, because it
needs neither their eyes nor their hands.

ADR-020 is explicit that the plumbing is the easy half, and that the feature does
not exist without its restraints: *"`ask_human` ships with these, or does not
ship."* All five live here or are enforced here:

* **off by default**, like everything;
* **a budget** with no way for a caller to exceed it by asking harder
  (:mod:`yazses.mcp.budget`);
* **never during a hold** — the user is speaking, and the question waits;
* **the caller is named** in what is spoken, so "who is asking" is never ambiguous;
* **the answer goes back to the caller, not into the focused window.**

That last one is why this lives on the daemon side. The daemon owns the microphone,
knows whether a hold is in progress, and owns the injector that must *not* fire: a
dictation burst answering an agent must not also type into whatever the user had
open. That is the no-text-target guard's failure mode in reverse, and it is the one
that would be discovered by a user, in a document, at the worst moment.

Everything external is injected — speaking, listening, the clock — so the policy is
tested without a microphone, speakers, or a daemon process.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from yazses.mcp.budget import InterruptBudget

log = logging.getLogger(__name__)


class Refusal(RuntimeError):
    """Why the question was not asked, in terms the calling agent can act on."""

    def __init__(
        self, message: str, *, retry_after_s: float | None = None, deferred: bool = False
    ) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s
        #: True when the answer is "not now" rather than "no" — the user is
        #: mid-sentence. Kept distinct because an agent should re-ask after a
        #: deferral and should not after a spent budget.
        self.deferred = deferred


class AskHumanService:
    """Speak a question, capture the spoken answer, hand it back to the caller."""

    #: A caller asking for a ten-minute wait is holding the microphone hostage:
    #: nothing else can be dictated while the daemon is listening for an answer.
    #: Two minutes is long enough for someone to walk back to the desk.
    MAX_TIMEOUT_S = 120.0

    def __init__(
        self,
        *,
        speaker,
        listener: Callable[[float], str],
        max_per_hour: int,
        enabled: bool,
        is_holding: Callable[[], bool],
        clock: Callable[[], float],
    ) -> None:
        self._speaker = speaker
        self._listener = listener
        self._enabled = enabled
        self._is_holding = is_holding
        self._clock = clock
        self._budget = InterruptBudget(max_per_hour=max_per_hour)
        #: Deliberately never set to anything. Its presence is the assertion: the
        #: answer travels back to the caller and is not typed anywhere. A test
        #: watches it, so a future change that injects here fails loudly.
        self._injector: Callable[[str], None] | None = None

    def ask(self, question: str, *, caller: str, timeout_s: float) -> str:
        """Ask *question* aloud and return what the human said.

        Raises :class:`Refusal` for every not-asked case, each carrying enough for
        the agent to decide whether to try again.
        """
        if not self._enabled:
            raise Refusal(
                "Spoken questions are not enabled on this machine "
                "(`[mcp] ask_human = true`, then `yazses restart`)."
            )

        text = (question or "").strip()
        if not text:
            raise Refusal("An empty question cannot be asked.")

        now = self._clock()
        verdict = self._budget.allow(caller, now=now, holding=self._is_holding())
        if not verdict.ok:
            raise Refusal(
                verdict.reason, retry_after_s=verdict.retry_after_s, deferred=verdict.deferred
            )

        # Named, so the human knows who is asking before deciding whether to care.
        spoken = f"{caller} asks: {text}"
        # Bounded by the caller, capped by us — see MAX_TIMEOUT_S.
        wait = max(1.0, min(float(timeout_s), self.MAX_TIMEOUT_S))

        try:
            self._speaker.speak(spoken)
            answer = self._listener(wait)
        except Exception as exc:  # noqa: BLE001 - reported to the agent, never raised on
            # The slot is *not* charged: speaking or listening can fail after
            # permission was granted (no audio device, the user walked away), and
            # an agent should not lose its hour to a question nobody heard.
            log.debug("ask_human failed while speaking or listening", exc_info=True)
            raise Refusal(f"The question could not be asked: {exc}") from exc

        if not (answer or "").strip():
            # Distinct from an empty answer on purpose. "They said nothing
            # meaningful" and "they never answered" are different facts, and an
            # agent will act differently on each.
            raise Refusal("No answer was heard before the timeout.", retry_after_s=wait)

        # Charged only now — one question asked, one answer heard.
        self._budget.record(caller, now=now)
        return answer.strip()
