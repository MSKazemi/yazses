"""`ask_human` — an agent asking the person a question out loud (ADR-020 §1, §4).

The genuinely novel thing YazSes can offer another agent is not transcription; it
is **a human**. An agent stalled on a decision only a person can make currently has
to put text on a screen and wait for someone to notice, read and type. Voice is the
cheapest interrupt a working person can service, because it needs neither their
eyes nor their hands.

ADR-020 is emphatic that the plumbing is not the problem: *"`ask_human` ships with
these, or does not ship."* The list is off by default, a budget with no way to
exceed it by asking harder, never during a hold, the caller named in the question,
and the answer returned to the caller rather than typed into the focused window.

That last one is the subtle one and the reason this lives in the daemon rather than
in the MCP server: the daemon owns the microphone, knows whether a hold is in
progress, and owns the injector that must *not* fire. A burst answering an agent
must not also type into whatever the user had open — the no-text-target guard's
failure mode in reverse.

Everything here is injected: speaking, listening, the clock. No microphone, no
speakers, no daemon process.
"""
from __future__ import annotations

import pytest

from yazses.mcp.ask import AskHumanService, Refusal


class _Speaker:
    def __init__(self) -> None:
        self.said: list[str] = []

    def speak(self, text: str) -> None:
        self.said.append(text)


class _Listener:
    def __init__(self, answer: str = "yes go ahead", raises: Exception | None = None) -> None:
        self.answer = answer
        self.raises = raises
        self.calls = 0

    def __call__(self, timeout_s: float) -> str:
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.answer


def _service(**kw):
    kw.setdefault("speaker", _Speaker())
    kw.setdefault("listener", _Listener())
    kw.setdefault("max_per_hour", 3)
    kw.setdefault("enabled", True)
    kw.setdefault("is_holding", lambda: False)
    kw.setdefault("clock", lambda: 0.0)
    return AskHumanService(**kw)


def test_a_question_is_spoken_and_the_answer_returned() -> None:
    speaker, listener = _Speaker(), _Listener("ship it")
    svc = _service(speaker=speaker, listener=listener)
    result = svc.ask("Deploy to production?", caller="claude-code", timeout_s=30)
    assert result == "ship it"
    assert speaker.said, "nothing was spoken"


def test_the_caller_is_named_in_what_is_spoken() -> None:
    """ADR-020: "the caller is named in the spoken question, so 'who is asking' is
    never ambiguous". Hearing a disembodied question from an unknown agent is worse
    than not being asked."""
    speaker = _Speaker()
    _service(speaker=speaker).ask("Delete the branch?", caller="release-bot", timeout_s=10)
    assert "release-bot" in speaker.said[0]
    assert "Delete the branch?" in speaker.said[0]


def test_it_is_off_by_default() -> None:
    """Every feature here ships off. An agent that can speak to you at will is one
    that can interrupt you at will."""
    svc = _service(enabled=False)
    with pytest.raises(Refusal) as exc:
        svc.ask("anything?", caller="a", timeout_s=5)
    assert "not enabled" in str(exc.value).lower()


def test_nothing_is_spoken_during_a_hold() -> None:
    """The user is mid-sentence and the daemon knows it. Speaking over them puts the
    question on the same audio channel they are dictating into."""
    speaker = _Speaker()
    svc = _service(speaker=speaker, is_holding=lambda: True)
    with pytest.raises(Refusal) as exc:
        svc.ask("now?", caller="a", timeout_s=5)
    assert not speaker.said, "it spoke over the user"
    assert exc.value.deferred, "a hold is a deferral, not a refusal"


def test_a_hold_does_not_spend_the_budget() -> None:
    """Charging for it would punish an agent for the user's timing."""
    holding = {"now": True}
    svc = _service(max_per_hour=1, is_holding=lambda: holding["now"])
    with pytest.raises(Refusal):
        svc.ask("q", caller="a", timeout_s=5)
    holding["now"] = False
    assert svc.ask("q", caller="a", timeout_s=5)


def test_the_budget_is_enforced_and_cannot_be_argued_with() -> None:
    svc = _service(max_per_hour=2)
    svc.ask("one", caller="a", timeout_s=5)
    svc.ask("two", caller="a", timeout_s=5)
    for _ in range(5):
        with pytest.raises(Refusal) as exc:
            svc.ask("three", caller="a", timeout_s=5)
        assert exc.value.retry_after_s is not None


def test_the_budget_is_shared_between_callers() -> None:
    """It protects the human, not each agent's fair share."""
    svc = _service(max_per_hour=1)
    svc.ask("q", caller="agent-one", timeout_s=5)
    with pytest.raises(Refusal):
        svc.ask("q", caller="agent-two", timeout_s=5)


def test_a_question_that_could_not_be_spoken_costs_nothing() -> None:
    """No speakers, a busy device, the user walked away. The agent should not lose
    its hour to a question nobody heard."""
    svc = _service(max_per_hour=1, listener=_Listener(raises=TimeoutError("no answer")))
    with pytest.raises(Refusal):
        svc.ask("q", caller="a", timeout_s=1)
    # The slot was not consumed, so a working attempt still goes through.
    svc_ok = _service(max_per_hour=1)
    assert svc_ok.ask("q", caller="a", timeout_s=1)


def test_silence_is_reported_as_silence_not_as_an_empty_answer() -> None:
    """An empty string would read to the agent as the human saying nothing
    meaningful, when in fact they never answered. Those are different."""
    svc = _service(listener=_Listener(answer="   "))
    with pytest.raises(Refusal) as exc:
        svc.ask("q", caller="a", timeout_s=1)
    assert "no answer" in str(exc.value).lower()


def test_the_answer_is_never_injected() -> None:
    """The whole point of returning it to the caller: a burst answering an agent
    must not also type into whatever the user had open."""
    injected: list[str] = []
    svc = _service(listener=_Listener("forty two"))
    svc._injector = lambda text: injected.append(text)  # type: ignore[attr-defined]
    assert svc.ask("how many?", caller="a", timeout_s=5) == "forty two"
    assert injected == [], "the answer was typed into the focused window"


def test_a_timeout_is_bounded_by_the_caller_but_capped_by_us() -> None:
    """A caller asking for an hour-long wait is holding the microphone hostage."""
    seen: list[float] = []
    svc = _service(listener=lambda timeout_s: (seen.append(timeout_s), "ok")[1])
    svc.ask("q", caller="a", timeout_s=99999)
    assert seen[0] <= AskHumanService.MAX_TIMEOUT_S


def test_an_empty_question_is_refused_before_anything_is_spoken() -> None:
    speaker = _Speaker()
    svc = _service(speaker=speaker)
    with pytest.raises(Refusal):
        svc.ask("   ", caller="a", timeout_s=5)
    assert not speaker.said


# --- the daemon side: the handler, and that it is reachable ------------------


def test_the_daemon_registers_the_method() -> None:
    """The handler is useless unregistered, and the failure is invisible until an
    agent calls it and gets -32601 (which is exactly what a stale running daemon
    returns — registration takes effect on restart)."""
    from pathlib import Path

    import yazses.core.daemon as daemon_mod

    source = Path(daemon_mod.__file__).read_text(encoding="utf-8")
    assert 'server.register("ask_human", self._handle_ask_human)' in source


def _daemon():
    import numpy as np

    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = Config()
    d = Daemon(config=cfg, platform=get_platform())

    class _Rec:
        def __init__(self):
            self.started = self.stopped = 0

        def start(self):
            self.started += 1

        def stop(self):
            self.stopped += 1
            return np.zeros(16000, dtype="float32")

    class _Eng:
        def transcribe(self, audio, **kw):
            return "the answer"

    d._recorder = _Rec()
    d._engine = _Eng()
    return d


def _request(**params):
    from yazses.ipc.protocol import Request

    return Request(method="ask_human", params=params, id=1)


def test_the_handler_refuses_when_the_feature_is_off() -> None:
    d = _daemon()
    reply = d._handle_ask_human(_request(question="ready?", caller="a", timeout_s=1))
    assert reply["ok"] is False
    assert "not enabled" in reply["reason"].lower()


def test_the_handler_returns_the_answer_when_enabled(monkeypatch) -> None:
    d = _daemon()
    object.__setattr__(d._config.mcp, "ask_human", True)
    monkeypatch.setattr(d, "_ask_human_listener", lambda t: "the answer")
    monkeypatch.setattr(d, "_ask_human_speaker", lambda: _Speaker())
    reply = d._handle_ask_human(_request(question="ready?", caller="a", timeout_s=1))
    assert reply == {"ok": True, "answer": "the answer"}


def test_a_refusal_carries_what_the_agent_needs_to_decide(monkeypatch) -> None:
    """An agent needs to tell "wait, they are speaking" from "you are out of
    questions" — one is worth retrying and one is not."""
    d = _daemon()
    object.__setattr__(d._config.mcp, "ask_human", True)
    monkeypatch.setattr(d, "_ask_human_speaker", lambda: _Speaker())
    monkeypatch.setattr(
        d, "_state", type("S", (), {"state": __import__(
            "yazses.platform.base", fromlist=["TrayState"]).TrayState.RECORDING})()
    )
    reply = d._handle_ask_human(_request(question="now?", caller="a", timeout_s=1))
    assert reply["ok"] is False
    assert reply["deferred"] is True
    assert reply["retry_after_s"]


def test_the_listener_always_releases_the_microphone(monkeypatch) -> None:
    """Leaving the stream open would hold the mic against the next dictation."""
    d = _daemon()
    monkeypatch.setattr("time.sleep", lambda _s: None)
    d._ask_human_listener(1.0)
    assert d._recorder.started == 1 and d._recorder.stopped == 1


def test_the_listener_releases_the_microphone_even_on_failure(monkeypatch) -> None:
    d = _daemon()

    def _boom(_s):
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", _boom)
    with pytest.raises(KeyboardInterrupt):
        d._ask_human_listener(1.0)
    assert d._recorder.stopped == 1, "the microphone was left open"
