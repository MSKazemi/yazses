"""Predictive Completion is reachable from the daemon, end to end (ADR-v2-016, #164).

Drives the real `Daemon._on_hold_end` in the style of `test_scratch_that_ordering.py`:
a fake recorder, a fake STT engine, a recording injector and a fake completion model,
so no microphone, no Whisper and no llama.cpp. The worker runs `threaded=False` and the
test calls `run_pending()` where the background thread would — the same code path.

What is pinned, in the user's terms:

* a dictated burst is typed, then a suggestion is offered in a notification;
* saying "accept" types the suggestion — never the word "accept";
* a decline, an expired offer, or no editable target types nothing;
* anything else said withdraws the offer and is dictated as usual;
* "scratch that" withdraws it too, so a later "accept" cannot type a suggestion for
  text that is gone;
* with no model the feature says so once in the log and stays dormant;
* the suggestion never reaches the log above DEBUG.
"""
from __future__ import annotations

import inspect
import logging

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.predict.runtime import PredictRuntime
from yazses.predict.session import SUGGESTION_TTL_S

FIRST = "the meeting is moved to"
SUGGESTED = " three pm on Friday"


class _FakeRecorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _FakeEngine:
    def __init__(self, text=""):
        self.text = text

    def transcribe(self, *args, **kwargs):
        return self.text


class _Injector:
    def __init__(self):
        self.calls: list[str] = []
        self.key_sequences: list[list[str]] = []

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        self.key_sequences.append(list(keys))


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class _FakeCompleter:
    def __init__(self, reply: str = SUGGESTED) -> None:
        self.reply = reply
        self.contexts: list[str] = []

    def complete(self, context: str) -> str:
        self.contexts.append(context)
        return self.reply


def _cfg(*, revise: bool = False) -> Config:
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.revise.enabled = revise
    # Off so each injected call is exactly the burst (no continuation space).
    cfg.injection.continuation_window_ms = 0
    cfg.predict.enabled = True
    return cfg


def _daemon(monkeypatch, *, revise: bool = False, reply: str = SUGGESTED,
            patch_notify: bool = True):
    d = Daemon(config=_cfg(revise=revise), platform=get_platform())
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    inj = _Injector()
    d._injector = inj
    shown: list[tuple[str, str, dict]] = []
    if patch_notify:
        monkeypatch.setattr(
            "yazses.system.notify.notify",
            lambda title, body, **kw: shown.append((title, body, kw)),
        )
    clock = _Clock()
    completer = _FakeCompleter(reply)
    d._predict = PredictRuntime(completer, d._offer_prediction, clock=clock, threaded=False)
    return d, inj, shown, clock, completer


def _say(d, text):
    d._engine.text = text
    d._on_hold_end()


def _offer(d):
    """Dictate FIRST and let the worker produce its offer."""
    _say(d, FIRST)
    offered = d._predict.run_pending()
    assert offered is not None, "no suggestion was offered after a typed burst"
    return offered


# ---- off by default ------------------------------------------------------------

def test_it_is_off_by_default_and_a_default_daemon_never_builds_it():
    assert Config().predict.enabled is False
    cfg = _cfg()
    cfg.predict.enabled = False
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    d._injector = _Injector()
    _say(d, FIRST)
    assert d._predict is None
    assert d._predict_dormant is False


# ---- the offer -------------------------------------------------------------------

def test_a_typed_burst_is_offered_a_completion_in_a_notification(monkeypatch):
    d, inj, shown, _clock, completer = _daemon(monkeypatch)
    _offer(d)
    assert inj.calls == [FIRST], "the dictation itself must be typed first, unchanged"
    assert completer.contexts == [FIRST]
    title, body, kw = shown[-1]
    assert "suggestion" in title
    assert SUGGESTED.strip() in body
    assert "accept" in body
    assert kw.get("log_body") is False, "the suggestion must not be written to the log"
    assert kw.get("expire_ms") == int(SUGGESTION_TTL_S * 1000)


def test_accept_types_the_suggestion_and_not_the_word(monkeypatch):
    d, inj, _shown, clock, _ = _daemon(monkeypatch)
    _offer(d)
    clock.t += 2.0
    _say(d, "accept")
    assert inj.calls == [FIRST, SUGGESTED]
    assert all("accept" not in call.lower() for call in inj.calls)
    assert d._predict.pending is None


def test_take_it_works_too(monkeypatch):
    d, inj, _shown, _clock, _ = _daemon(monkeypatch)
    _offer(d)
    _say(d, "Take it.")
    assert inj.calls == [FIRST, SUGGESTED]


def test_decline_types_nothing(monkeypatch):
    d, inj, _shown, _clock, _ = _daemon(monkeypatch)
    _offer(d)
    _say(d, "discard")
    assert inj.calls == [FIRST]
    assert d._predict.pending is None


def test_other_speech_dismisses_the_offer_and_is_dictated(monkeypatch):
    d, inj, _shown, _clock, _ = _daemon(monkeypatch)
    _offer(d)
    _say(d, "and bring the slides")
    assert inj.calls == [FIRST, "and bring the slides"]
    assert d._predict.pending is None
    # The new words are what the model is asked about next.
    nxt = d._predict.run_pending()
    assert nxt is not None


def test_a_dictated_no_is_typed_and_dismisses_the_offer(monkeypatch):
    # "No." used to be a decline phrase and was eaten: the user said a word and nothing
    # appeared. It is ordinary dictation now -- typed, and the offer is gone, so a later
    # "accept" cannot type the old suggestion.
    d, inj, _shown, _clock, _ = _daemon(monkeypatch)
    _offer(d)
    _say(d, "No.")
    assert inj.calls == [FIRST, "No."]
    assert d._predict.pending is None
    _say(d, "accept")
    assert SUGGESTED not in inj.calls, "a dismissed suggestion was typed"


def test_an_accept_after_the_offer_expired_types_nothing(monkeypatch):
    d, inj, shown, clock, _ = _daemon(monkeypatch)
    _offer(d)
    clock.t += SUGGESTION_TTL_S + 1.0
    _say(d, "accept")
    assert inj.calls == [FIRST], "neither the stale suggestion nor the word was typed"
    assert "expired" in shown[-1][1]


def test_no_editable_target_means_the_suggestion_is_not_typed(monkeypatch):
    d, inj, shown, _clock, _ = _daemon(monkeypatch)
    _offer(d)
    d._state.target_ok = False
    _say(d, "accept")
    assert inj.calls == [FIRST]
    assert "not typed" in shown[-1][1]


def test_scratch_that_withdraws_the_offer_so_a_later_accept_is_just_a_word(monkeypatch):
    d, inj, _shown, _clock, _ = _daemon(monkeypatch, revise=True)
    _offer(d)
    _say(d, "scratch that")
    assert inj.key_sequences == [["BackSpace"] * len(FIRST)]
    assert d._predict.pending is None
    _say(d, "accept")
    assert SUGGESTED not in inj.calls, "a suggestion for scratched text was typed"
    assert inj.calls[-1] == "accept"


def test_an_accepted_suggestion_can_be_scratched_like_any_burst(monkeypatch):
    d, inj, _shown, _clock, _ = _daemon(monkeypatch, revise=True)
    _offer(d)
    _say(d, "accept")
    _say(d, "scratch that")
    assert inj.key_sequences[-1] == ["BackSpace"] * len(SUGGESTED)


# ---- dormant -----------------------------------------------------------------------

def test_without_a_model_it_says_so_once_and_stays_dormant(monkeypatch, caplog):
    cfg = _cfg()
    cfg.predict.model_path = ""
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    inj = _Injector()
    d._injector = inj
    with caplog.at_level(logging.WARNING):
        _say(d, FIRST)
        _say(d, "and bring the slides")
    assert inj.calls == [FIRST, "and bring the slides"], "dictation must be unaffected"
    assert d._predict is None and d._predict_dormant is True
    notes = [r for r in caplog.records if "[predict]" in r.getMessage()]
    assert len(notes) == 1, [r.getMessage() for r in notes]
    assert "model_path" in notes[0].getMessage()


# ---- privacy -------------------------------------------------------------------------

def test_the_suggestion_never_reaches_the_shareable_log(monkeypatch, caplog):
    sentinel = " quixotrel vambrazine plinthwort"
    d, _inj, _shown, _clock, _ = _daemon(monkeypatch, reply=sentinel, patch_notify=False)
    with caplog.at_level(logging.DEBUG, logger="yazses"):
        _offer(d)
    shareable = [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO]
    for message in shareable:
        assert "quixotrel" not in message, message
    # Positive control: the capture saw the offer at DEBUG, so the list above is not
    # empty by accident.
    debug = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("quixotrel" in m for m in debug)


# ---- the hold-start and shutdown seams -------------------------------------------------

def test_a_new_hold_makes_an_in_flight_generation_stale():
    source = inspect.getsource(Daemon._on_hold_start)
    assert "self._predict.begin_burst()" in source


def test_shutdown_stops_the_worker():
    assert "self._predict.close()" in inspect.getsource(Daemon._shutdown)


# ---- notification log hygiene --------------------------------------------------------

def test_notify_can_keep_a_body_out_of_the_log(caplog):
    from yazses.system.notify import notify

    with caplog.at_level(logging.INFO, logger="yazses"):
        notify("YazSes", "quixotrel vambrazine", available=False, log_body=False)
        notify("YazSes", "plinthwort", available=False)  # the default still logs it
    messages = [r.getMessage() for r in caplog.records]
    assert not any("quixotrel" in m for m in messages)
    assert any("withheld" in m for m in messages)
    assert any("plinthwort" in m for m in messages), "default behaviour changed"


# ---- the registry tells the truth ----------------------------------------------------

def test_predict_is_wired_and_marked_experimental():
    from yazses.system.features import EXPERIMENTAL, _registry, unwired_slugs

    assert "predict" not in unwired_slugs()
    entry = next(d for d in _registry() if d.slug == "predict")
    assert entry.tier == EXPERIMENTAL


def test_enabling_without_a_model_explains_what_is_missing():
    from yazses.system.features import enable_caveat

    cfg = Config()
    cfg.predict.model_path = ""
    caveat = enable_caveat("predict", cfg)
    assert caveat is not None and "model_path" in caveat


def test_enabling_with_a_runnable_model_has_no_caveat(monkeypatch):
    import yazses.predict.generator as generator
    from yazses.system.features import enable_caveat

    monkeypatch.setattr(generator, "dormant_reason", lambda *_a, **_k: None)
    assert enable_caveat("predict", Config()) is None
