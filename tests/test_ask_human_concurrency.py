"""`ask_human` budget under concurrency.

The budget used to be checked (``allow``) before the question was spoken and charged
(``record``) only after an answer. The IPC server runs one thread per connection, and
``_handle_ask_human`` takes no lock, so N agents could all pass ``allow()`` before any of
them was charged: with ``max_per_hour = 1``, eight concurrent calls spoke eight questions.

The slot is now reserved atomically with the check and handed back when nothing was heard.
Unanswered questions stay uncharged (audit AGT-02 is a maintainer decision, unchanged);
only the concurrency hole is closed.
"""
from __future__ import annotations

import threading
import time

import pytest

from tests.test_ask_human import _enabled_daemon, _request
from yazses.mcp.ask import AskHumanService, Refusal
from yazses.mcp.budget import InterruptBudget


class _Speaker:
    def __init__(self, hold_s: float = 0.0) -> None:
        self.said: list[str] = []
        self._hold_s = hold_s
        self._lock = threading.Lock()

    def speak(self, text: str) -> None:
        with self._lock:
            self.said.append(text)
        # Holds the question open so every other thread reaches the budget check
        # while this one is still waiting for its answer.
        time.sleep(self._hold_s)


def _service(**kw) -> AskHumanService:
    kw.setdefault("speaker", _Speaker())
    kw.setdefault("listener", lambda _t: "yes")
    kw.setdefault("max_per_hour", 3)
    kw.setdefault("enabled", True)
    kw.setdefault("is_holding", lambda: False)
    kw.setdefault("clock", lambda: 0.0)
    return AskHumanService(**kw)


def _hammer(call, n: int) -> list[object]:
    barrier = threading.Barrier(n)
    out: list[object] = [None] * n

    def worker(i: int) -> None:
        barrier.wait()
        out[i] = call(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert not any(t.is_alive() for t in threads)
    return out


def _ask(service: AskHumanService, i: int) -> object:
    try:
        return service.ask(f"q{i}?", caller="a", timeout_s=1)
    except Refusal as refusal:
        return refusal


@pytest.mark.parametrize("limit", [1, 3])
def test_concurrent_asks_never_speak_more_than_the_budget(limit: int) -> None:
    speaker = _Speaker(hold_s=0.2)
    service = _service(speaker=speaker, max_per_hour=limit)
    results = _hammer(lambda i: _ask(service, i), 8)
    assert len(speaker.said) == limit
    assert sum(isinstance(r, str) for r in results) == limit
    assert all(isinstance(r, (str, Refusal)) for r in results)


def test_a_refusal_for_a_question_in_flight_is_a_deferral() -> None:
    """Not "spent": the in-flight question may yet be released, so the agent should re-ask."""
    gate, entered = threading.Event(), threading.Event()

    class _Blocking:
        def speak(self, text: str) -> None:
            entered.set()
            gate.wait(5)

    service = _service(speaker=_Blocking(), max_per_hour=1)
    t = threading.Thread(target=lambda: _ask(service, 0))
    t.start()
    assert entered.wait(5)
    try:
        with pytest.raises(Refusal) as info:
            service.ask("two?", caller="b", timeout_s=1)
        assert info.value.deferred is True
        assert info.value.retry_after_s
    finally:
        gate.set()
        t.join(5)


def test_a_failed_question_hands_its_slot_back() -> None:
    def broken(_t: float) -> str:
        raise RuntimeError("no mic")

    service = _service(listener=broken, max_per_hour=1)
    for _ in range(3):  # never charged, so never spent
        with pytest.raises(Refusal, match="could not be asked"):
            service.ask("anyone?", caller="a", timeout_s=1)


def test_an_unanswered_question_hands_its_slot_back() -> None:
    """AGT-02 is unchanged: silence is not charged."""
    speaker = _Speaker()
    service = _service(speaker=speaker, listener=lambda _t: "", max_per_hour=1)
    for _ in range(3):
        with pytest.raises(Refusal, match="No answer"):
            service.ask("anyone?", caller="a", timeout_s=1)
    assert len(speaker.said) == 3


def test_an_answered_question_is_charged_exactly_once() -> None:
    service = _service(max_per_hour=1)
    assert service.ask("one?", caller="a", timeout_s=1) == "yes"
    with pytest.raises(Refusal) as info:
        service.ask("two?", caller="a", timeout_s=1)
    assert info.value.deferred is False
    assert info.value.retry_after_s and info.value.retry_after_s > 0


def test_a_refused_check_never_leaks_a_reservation() -> None:
    budget = InterruptBudget(max_per_hour=1)
    assert budget.reserve("a", now=0.0, holding=True).ok is False  # user is dictating
    assert budget.reserve("a", now=0.0).ok is True
    budget.release()
    assert budget.reserve("a", now=0.0).ok is True
    budget.commit(now=0.0)
    assert budget.reserve("a", now=1.0).ok is False


def test_the_daemon_enforces_one_budget_across_simultaneous_requests(monkeypatch) -> None:
    d, shared, _listener = _enabled_daemon(monkeypatch, limit=1)
    slow = _Speaker(hold_s=0.2)
    monkeypatch.setattr(d, "_ask_human_speaker", lambda: slow)
    replies = _hammer(
        lambda i: d._handle_ask_human(_request(question=f"q{i}?", caller="a", timeout_s=1)), 8
    )
    assert len(slow.said) == 1
    assert sum(1 for r in replies if isinstance(r, dict) and r.get("ok")) == 1
    assert shared.said == []  # the replaced speaker was the only one used


def test_the_daemon_builds_its_budget_up_front() -> None:
    """A lazily built budget can be built twice by two first requests."""
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    d = Daemon(config=Config(), platform=get_platform())
    assert isinstance(d._ask_human_budget, InterruptBudget)
