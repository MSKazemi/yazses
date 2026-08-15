"""The interrupt budget for `ask_human` (ADR-020 §4).

ADR-020 decides that YazSes may expose two MCP tools, and says of the second:
*"`ask_human` ships with these, or does not ship."* The list is not a nice-to-have,
it is the condition of the feature existing, and this module is most of it.

The asymmetry the budget exists for: **a voice interrupt is cheap for the agent
and expensive for the human.** An agent can ask a hundred times an hour at no cost
to itself, and each one lands in the middle of the user's sentence, on the same
audio channel they are dictating into. Notification fatigue is the ordinary
outcome; the unusual thing would be avoiding it.

So this is deliberately a *budget* rather than a rate-limiter with a retry: there
is no way for a caller to exceed it by asking harder, and a refusal names when the
next slot frees rather than inviting a poll.
"""
from __future__ import annotations

import pytest

from yazses.mcp.budget import InterruptBudget


def _ask(budget: InterruptBudget, caller: str, now: float, *, holding: bool = False):
    """One real question: ask permission, and charge only if it was granted.

    Every caller of the budget does this pair, so the tests do too — testing
    `allow` alone would pass while the real flow double-charged or never charged.
    """
    verdict = budget.allow(caller, now=now, holding=holding)
    if verdict.ok:
        budget.record(caller, now=now)
    return verdict


def test_the_first_question_is_allowed() -> None:
    budget = InterruptBudget(max_per_hour=3)
    assert budget.allow("claude-code", now=0.0).ok


def test_the_budget_is_spent_and_then_refuses() -> None:
    budget = InterruptBudget(max_per_hour=2)
    assert _ask(budget, "a", 0.0).ok
    assert _ask(budget, "a", 10.0).ok
    verdict = _ask(budget, "a", 20.0)
    assert not verdict.ok
    assert "2" in verdict.reason, verdict.reason


def test_asking_harder_does_not_earn_more() -> None:
    """The whole point: no retry, no backoff, no priority flag buys another slot."""
    budget = InterruptBudget(max_per_hour=1)
    assert _ask(budget, "a", 0.0).ok
    for attempt in range(10):
        assert not _ask(budget, "a", 1.0 + attempt).ok


def test_the_window_slides_so_the_budget_recovers() -> None:
    budget = InterruptBudget(max_per_hour=1)
    assert _ask(budget, "a", 0.0).ok
    assert not _ask(budget, "a", 3599.0).ok
    assert _ask(budget, "a", 3601.0).ok, "an hour later the slot is free again"


def test_a_refusal_says_when_the_next_slot_frees() -> None:
    """A refusal that does not say when is an invitation to poll."""
    budget = InterruptBudget(max_per_hour=1)
    _ask(budget, "a", 0.0)
    verdict = _ask(budget, "a", 600.0)
    assert not verdict.ok
    assert verdict.retry_after_s == pytest.approx(3000.0)


def test_the_budget_is_shared_across_callers() -> None:
    """It protects the *human*, not each agent's fair share. Five agents with one
    question each are five interrupts, which is the thing being limited."""
    budget = InterruptBudget(max_per_hour=2)
    assert _ask(budget, "agent-one", 0.0).ok
    assert _ask(budget, "agent-two", 1.0).ok
    assert not _ask(budget, "agent-three", 2.0).ok


def test_zero_means_never_ask() -> None:
    """`max_per_hour = 0` is a real setting: the tool is listed but always refuses,
    which is different from the tool not existing (the caller learns why)."""
    budget = InterruptBudget(max_per_hour=0)
    verdict = budget.allow("a", now=0.0)
    assert not verdict.ok
    assert verdict.retry_after_s is None, "never is not a wait"


def test_a_hold_in_progress_defers_rather_than_spends() -> None:
    """The user is mid-sentence. The question waits — and must not cost a slot,
    or an unlucky agent is punished for the user's timing."""
    budget = InterruptBudget(max_per_hour=1)
    verdict = _ask(budget, "a", 0.0, holding=True)
    assert not verdict.ok
    assert verdict.deferred, "a hold defers; it is not a refusal"
    assert _ask(budget, "a", 1.0).ok, "the slot was not consumed"


def test_a_deferral_is_not_an_error_the_caller_should_retry_forever() -> None:
    budget = InterruptBudget(max_per_hour=1)
    verdict = budget.allow("a", now=0.0, holding=True)
    assert verdict.retry_after_s is not None and verdict.retry_after_s > 0


def test_spending_is_explicit_so_a_failed_question_is_not_charged() -> None:
    """`allow` answers "may I"; the slot is spent by `record`. If speaking fails —
    no audio device, the user walks away — the agent has not used its budget."""
    budget = InterruptBudget(max_per_hour=1)
    assert budget.allow("a", now=0.0).ok
    assert budget.allow("a", now=1.0).ok, "allow alone must not consume"
    budget.record("a", now=1.0)
    assert not budget.allow("a", now=2.0).ok
