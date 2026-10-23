"""Predictive Completion's background worker and llama.cpp backend (ADR-v2-016).

The model is always a fake: nothing here imports llama_cpp, loads a GGUF or touches the
network. `PredictRuntime(threaded=False)` is driven step by step through `run_pending`,
which is the exact body the worker thread runs; one test runs the real thread to show
the hand-off works off the caller's thread.
"""
from __future__ import annotations

import logging
import threading

import pytest

from yazses.predict.generator import LlamaCompleter, dormant_reason
from yazses.predict.runtime import PredictRuntime
from yazses.predict.session import ACCEPT, DROPPED, PredictSession

CONTEXT = "the meeting is moved to"


class _Clock:
    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class _FakeCompleter:
    def __init__(self, reply: str = " three pm on Friday") -> None:
        self.reply = reply
        self.contexts: list[str] = []

    def complete(self, context: str) -> str:
        self.contexts.append(context)
        return self.reply


def _runtime(reply: str = " three pm on Friday"):
    completer = _FakeCompleter(reply)
    offers: list = []
    clock = _Clock()
    rt = PredictRuntime(completer, offers.append, clock=clock, threaded=False)
    return rt, completer, offers, clock


# ---- PredictRuntime ---------------------------------------------------------------

def test_a_typed_burst_produces_one_offer():
    rt, completer, offers, _ = _runtime()
    assert rt.submit(CONTEXT) is True
    sug = rt.run_pending()
    assert sug is not None and offers == [sug]
    assert completer.contexts == [CONTEXT]
    assert rt.pending == sug


def test_too_little_context_never_reaches_the_model():
    rt, completer, offers, _ = _runtime()
    assert rt.submit("hello") is False
    assert rt.run_pending() is None
    assert completer.contexts == [] and offers == []


def test_a_new_burst_discards_the_request_before_the_model_runs():
    rt, completer, offers, _ = _runtime()
    rt.submit(CONTEXT)
    rt.begin_burst()
    assert rt.run_pending() is None
    assert completer.contexts == [], "a stale request must not cost a generation"
    assert offers == []


def test_a_result_that_arrives_after_a_new_burst_began_is_dropped():
    """The race the epoch exists for: generation finishes mid-recording."""
    session = PredictSession()
    offers: list = []

    class _SlowCompleter:
        def complete(self, context: str) -> str:
            rt.begin_burst()  # the user pressed the key while the model was running
            return " three pm on Friday"

    rt = PredictRuntime(_SlowCompleter(), offers.append, session=session, threaded=False)
    rt.submit(CONTEXT)
    assert rt.run_pending() is None
    assert offers == [] and rt.pending is None


def test_only_the_latest_request_is_served():
    rt, completer, _, _ = _runtime()
    rt.submit(CONTEXT)
    rt.submit(" and lunch is at")
    rt.run_pending()
    assert completer.contexts == [CONTEXT + " and lunch is at"]
    assert rt.run_pending() is None  # nothing left queued


def test_resolve_accept_returns_the_completion():
    rt, _, _, clock = _runtime()
    rt.submit(CONTEXT)
    rt.run_pending()
    clock.t += 3.0
    res = rt.resolve("take it")
    assert res.action == ACCEPT and res.typed == " three pm on Friday"


def test_resolve_other_speech_drops_the_offer():
    rt, _, _, _ = _runtime()
    rt.submit(CONTEXT)
    rt.run_pending()
    assert rt.resolve("and bring the slides").action == DROPPED
    assert rt.pending is None


def test_interrupt_forgets_the_offer_and_the_queued_request():
    rt, completer, _, _ = _runtime()
    rt.submit(CONTEXT)
    rt.interrupt()
    assert rt.run_pending() is None
    assert completer.contexts == []


def test_a_failing_display_never_breaks_the_worker():
    completer = _FakeCompleter()

    def _boom(_s):
        raise RuntimeError("no notification daemon")

    rt = PredictRuntime(completer, _boom, threaded=False)
    rt.submit(CONTEXT)
    assert rt.run_pending() is not None  # offered, even though showing it failed


def test_close_stops_everything():
    rt, completer, offers, _ = _runtime()
    rt.submit(CONTEXT)
    rt.close()
    assert rt.run_pending() is None
    assert rt.submit(CONTEXT) is False
    assert completer.contexts == [] and offers == []


def test_the_worker_thread_generates_off_the_callers_thread():
    shown = threading.Event()
    seen: dict = {}

    def _on_offer(sug):
        seen["thread"] = threading.current_thread().name
        seen["sug"] = sug
        shown.set()

    rt = PredictRuntime(_FakeCompleter(), _on_offer)
    try:
        assert rt.submit(CONTEXT) is True
        assert shown.wait(10.0), "the worker never offered a suggestion"
        assert seen["thread"] == "predict-worker"
        assert seen["sug"].display == "three pm on Friday"
    finally:
        rt.close()


# ---- dormant_reason -----------------------------------------------------------------

def test_dormant_without_a_model_path():
    assert "model_path" in dormant_reason("", have_llama=True, model_exists=True)
    assert "model_path" in dormant_reason("   ", have_llama=True, model_exists=True)


def test_dormant_without_llama_cpp():
    reason = dormant_reason("/m.gguf", have_llama=False, model_exists=True)
    assert reason is not None and "llama-cpp-python" in reason


def test_dormant_when_the_path_is_not_a_file():
    reason = dormant_reason("/nope.gguf", have_llama=True, model_exists=False)
    assert reason is not None and "/nope.gguf" in reason


def test_ready_when_everything_is_present():
    assert dormant_reason("/m.gguf", have_llama=True, model_exists=True) is None


def test_the_real_probe_finds_a_missing_file(tmp_path):
    missing = tmp_path / "absent.gguf"
    reason = dormant_reason(str(missing), have_llama=True)
    assert reason is not None and "not a file" in reason


# ---- LlamaCompleter -------------------------------------------------------------------

class _FakeLlama:
    def __init__(self, text: str = " three pm") -> None:
        self.text = text
        self.calls: list[tuple[str, dict]] = []

    def create_completion(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return {"choices": [{"text": self.text}]}


def test_the_model_loads_lazily_and_once():
    built: list[str] = []
    model = _FakeLlama()

    def _factory(path):
        built.append(path)
        return model

    c = LlamaCompleter("/m.gguf", 12, factory=_factory)
    assert built == [], "construction must not load a model"
    assert c.complete(CONTEXT + "  ") == " three pm"
    c.complete(CONTEXT)
    assert len(built) == 1


def test_generation_is_greedy_bounded_and_stops_at_a_newline():
    model = _FakeLlama()
    c = LlamaCompleter("/m.gguf", 7, factory=lambda _p: model)
    c.complete(CONTEXT + " ")
    prompt, kwargs = model.calls[0]
    assert prompt == CONTEXT  # trailing whitespace trimmed
    assert kwargs["max_tokens"] == 7
    assert kwargs["temperature"] == 0.0
    assert kwargs["stop"] == ["\n"]


def test_an_empty_context_asks_nothing():
    model = _FakeLlama()
    c = LlamaCompleter("/m.gguf", 7, factory=lambda _p: model)
    assert c.complete("   ") == ""
    assert model.calls == []


def test_a_load_failure_makes_the_completer_inert(caplog):
    attempts: list[str] = []

    def _factory(path):
        attempts.append(path)
        raise OSError("bad gguf")

    c = LlamaCompleter("/m.gguf", 7, factory=_factory)
    with caplog.at_level(logging.WARNING):
        assert c.complete(CONTEXT) == ""
        assert c.complete(CONTEXT) == ""
    assert c.failed is True
    assert len(attempts) == 1, "a broken model must not be reloaded on every burst"


def test_a_generation_error_returns_nothing_and_logs_no_text(caplog):
    class _Boom:
        def create_completion(self, prompt, **kwargs):
            raise RuntimeError(f"failed on {prompt}")

    c = LlamaCompleter("/m.gguf", 7, factory=lambda _p: _Boom())
    with caplog.at_level(logging.INFO):
        assert c.complete("quixotrel vambrazine plinthwort") == ""
    shared = [r for r in caplog.records if r.levelno >= logging.INFO]
    assert shared, "the failure should be visible in the log"
    for record in shared:
        assert "quixotrel" not in record.getMessage()


@pytest.mark.parametrize("bad", [{}, {"choices": []}, None])
def test_an_odd_reply_shape_returns_nothing(bad):
    class _Odd:
        def create_completion(self, prompt, **kwargs):
            return bad

    c = LlamaCompleter("/m.gguf", 7, factory=lambda _p: _Odd())
    assert c.complete(CONTEXT) == ""
