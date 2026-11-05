"""How often an agent may interrupt the human out loud (ADR-020 §4).

The plumbing of `ask_human` is a tool call. The design problem is that **a voice
interrupt is cheap for the agent and expensive for the human** — an agent can ask
a hundred times an hour at no cost to itself, and each question arrives in the
middle of the user's sentence, on the same audio channel they are dictating into.

So this is a *budget*, not a rate-limiter: there is no retry that earns another
slot, no priority flag, and no backoff to game. A caller that has spent its hour
is told when the next one frees and gets the same answer however hard it asks.

Pure: no clock, no audio, no config reading. `now` and `holding` are passed in, so
the whole policy tests without waiting an hour or holding a key.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field

WINDOW_S = 3600.0

#: How long to tell a caller to wait when the user is mid-dictation. Short,
#: because a hold is seconds long — this is "try again in a moment", not the
#: hour-scale wait a spent budget produces.
HOLD_RETRY_S = 15.0


@dataclass(frozen=True)
class Verdict:
    """Whether the question may be asked, and what to tell the caller if not."""

    ok: bool
    reason: str = ""
    #: Seconds until it is worth asking again. ``None`` means never — the budget
    #: is zero, and a wait would be a lie.
    retry_after_s: float | None = None
    #: True when the refusal is "the user is speaking right now", which is a
    #: different thing from "you have used your hour" and costs no slot.
    deferred: bool = False


@dataclass
class InterruptBudget:
    """A sliding-hour allowance on spoken questions, shared by every caller.

    Shared deliberately. The budget protects *the human*, not each agent's fair
    share: five agents asking one question each are five interrupts, which is
    exactly the quantity being limited. Per-caller budgets would multiply the
    interruption by the number of agents installed.
    """

    max_per_hour: int
    _spent: deque[float] = field(default_factory=deque, repr=False)
    #: Slots promised to questions that are being asked right now. The IPC server runs
    #: one thread per connection, so "check, then speak, then charge" lets N callers all
    #: pass the check before the first is charged; a reservation closes that gap.
    _pending: int = field(default=0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def allow(self, caller: str, *, now: float, holding: bool = False) -> Verdict:
        """May *caller* ask a question right now?

        Answering does **not** consume the slot — `record` does. Speaking can fail
        after this returns (no audio device, the user has walked away), and an
        agent should not lose its hour to a question nobody heard.
        """
        with self._lock:
            return self._decide(now=now, holding=holding)

    def reserve(self, caller: str, *, now: float, holding: bool = False) -> Verdict:
        """:meth:`allow` and, when it says yes, hold the slot — atomically.

        Concurrent callers cannot both be told yes for the last slot. The hold is not a
        charge: settle it with :meth:`commit` once the question was answered, or give it
        back with :meth:`release` if it was not (nothing was heard, or it could not be
        asked), which keeps the rule that an unanswered question costs no slot.
        """
        with self._lock:
            verdict = self._decide(now=now, holding=holding)
            if verdict.ok:
                self._pending += 1
            return verdict

    def commit(self, *, now: float) -> None:
        """Turn a :meth:`reserve` hold into a charge."""
        with self._lock:
            self._pending = max(0, self._pending - 1)
            self._evict(now)
            self._spent.append(now)

    def release(self) -> None:
        """Hand a :meth:`reserve` hold back without charging it."""
        with self._lock:
            self._pending = max(0, self._pending - 1)

    def record(self, caller: str, *, now: float) -> None:
        """Charge one slot — call this once the question has actually been asked."""
        with self._lock:
            self._evict(now)
            self._spent.append(now)

    def _decide(self, *, now: float, holding: bool) -> Verdict:
        """The yes/no, for a caller that already holds ``_lock``."""
        if self.max_per_hour <= 0:
            return Verdict(
                ok=False,
                reason="Spoken questions are switched off (mcp.ask_human_per_hour = 0).",
                retry_after_s=None,
            )
        if holding:
            # The user is mid-sentence and the daemon knows it. Waiting is the
            # whole answer; charging for it would punish an agent for the user's
            # timing.
            return Verdict(
                ok=False,
                reason="The user is dictating right now; the question will keep.",
                retry_after_s=HOLD_RETRY_S,
                deferred=True,
            )
        self._evict(now)
        if len(self._spent) >= self.max_per_hour:
            oldest = self._spent[0]
            return Verdict(
                ok=False,
                reason=(
                    f"{self.max_per_hour} spoken question(s) per hour is the budget, "
                    f"and it is spent. Asking again does not raise it."
                ),
                retry_after_s=max(0.0, oldest + WINDOW_S - now),
            )
        if len(self._spent) + self._pending >= self.max_per_hour:
            # Not spent: a question is being asked right now and may yet go unanswered
            # (which costs nothing). "Not now", so the caller is told to re-ask.
            return Verdict(
                ok=False,
                reason="Another spoken question is being asked right now; try again shortly.",
                retry_after_s=HOLD_RETRY_S,
                deferred=True,
            )
        return Verdict(ok=True)

    def _evict(self, now: float) -> None:
        while self._spent and now - self._spent[0] >= WINDOW_S:
            self._spent.popleft()
