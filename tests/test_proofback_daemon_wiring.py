"""Interruptible Proofreading wired through the daemon (ADR-v2-108), with fakes only.

Drives the real ``_on_hold_start`` / ``_on_hold_end`` / ``_maybe_read_back`` /
``_speak_readback`` with a fake TTS backend that reports its playback to the listener
and lets the test press the key mid-playback. No audio, model, or keyboard.

The end-to-end shape pinned here: dictate "send the wrong file", hear it read back,
press the key while "wrong" is playing, say "right file" — the screen ends up holding
"send the right file", typed as 10 backspaces then "right file". Every refusal types
the second burst as ordinary dictation and erases nothing.
"""
from __future__ import annotations

import threading

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import TrayState, get_platform
from yazses.proofback.bargein import ProofbackController
from yazses.system.features import EXPERIMENTAL, _registry, enable_caveat, unwired_slugs

SR = 1000  # 1 sample == 1 ms
FIRST = "send the wrong file"


class _Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class _FakeRecorder:
    def __init__(self) -> None:
        self.audio = np.full(16000, 0.5, dtype="float32")

    def start(self) -> None:
        pass

    def stop(self):
        return self.audio


class _FakeEngine:
    def __init__(self) -> None:
        self.text = ""

    def transcribe(self, *a, **k):
        return self.text


class _Injector:
    def __init__(self) -> None:
        self.ops: list[tuple[str, object]] = []

    def inject(self, text):
        self.ops.append(("type", text))

    def inject_backspaces(self, n):
        self.ops.append(("backspace", n))

    def inject_key_sequence(self, keys):
        self.ops.append(("keys", tuple(keys)))


class _ProofTts:
    """Reports one chunk to the playback listener, then runs `during` mid-playback."""

    name = "fake"

    def __init__(self) -> None:
        self.listener = None
        self.listener_sets: list = []
        self.spoken: list[str] = []
        self.cancels = 0
        self.during = None

    def begin(self) -> None:
        pass

    def set_playback_listener(self, fn) -> None:
        self.listener = fn
        self.listener_sets.append(fn)

    def speak(self, text: str) -> None:
        self.spoken.append(text)
        if self.listener is not None:
            # One chunk starting at t=100 s, 100 ms per character-weight unit.
            self.listener(text, 100 * sum(ch.isalnum() for ch in text), SR, 100.0)
        if self.during is not None:
            during, self.during = self.during, None
            during()

    def synthesize(self, text):
        return iter(())

    def cancel(self) -> None:
        self.cancels += 1


_RealThread = threading.Thread


class _DeferReadback:
    """Defers only the read-back worker so the test decides when playback happens."""

    pending: list = []

    def __new__(cls, *args, **kwargs):
        if kwargs.get("name") == "readback":
            obj = object.__new__(cls)
            obj._target = kwargs.get("target")
            return obj
        return _RealThread(*args, **kwargs)

    def __init__(self, *args, **kwargs) -> None:
        pass  # state was set in __new__; only reached for the deferred read-back

    def start(self) -> None:
        _DeferReadback.pending.append(self._target)


class _ThreadingProxy:
    """`threading` as the daemon module sees it, with only `Thread` replaced.

    Patching the attribute on the real `threading` module would also change what any
    module imported mid-test subclasses; this keeps the substitution to the daemon.
    """

    Thread = _DeferReadback

    def __getattr__(self, name):
        return getattr(threading, name)


def _daemon(monkeypatch, *, proofback=True, **cfg_overrides):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    cfg.accessibility.speech_presence_check = False
    cfg.tts.enabled = True
    cfg.accessibility.read_back = "final"
    cfg.revise.enabled = True
    cfg.proofback.enabled = proofback
    for dotted, value in cfg_overrides.items():
        section, key = dotted.split("__")
        setattr(getattr(cfg, section), key, value)
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder()
    d._engine = _FakeEngine()
    d._padding_buffer = None
    d._injector = _Injector()
    tts = _ProofTts()
    d._tts = tts
    monkeypatch.setattr(d, "_detect_target_async", lambda: None)
    _DeferReadback.pending = []
    monkeypatch.setattr("yazses.core.daemon.threading", _ThreadingProxy())
    clock = _Clock()
    if proofback:
        d._proofback = ProofbackController(clock=clock)
    return d, tts, clock


def _dictate(d, text: str) -> None:
    d._engine.text = text
    d._on_hold_start(0)
    d._on_hold_end()


def _play_readback_and_press_at(d, tts, clock, t: float) -> None:
    """Run the deferred read-back; the key goes down at monotonic time *t*."""
    def press():
        clock.t = t
        d._on_hold_start(0)

    tts.during = press
    worker = _DeferReadback.pending.pop(0)
    worker()


# "send the wrong file": weights 4,3,5,4 (x100 ms) from t=100 → "wrong" is [100.7, 101.2).
WRONG_AT = 100.9


def test_proofback_is_wired_experimental_and_explains_its_prerequisite():
    assert "proofback" not in unwired_slugs()
    definition = next(d for d in _registry() if d.slug == "proofback")
    assert definition.tier == EXPERIMENTAL
    assert "Read-Back" in definition.why
    off = Config()
    assert enable_caveat("proofback", off) is not None
    on = Config()
    on.tts.enabled = True
    on.accessibility.read_back = "final"
    assert enable_caveat("proofback", on) is None


def test_off_by_default_and_the_read_back_call_is_unchanged(monkeypatch):
    assert Config().proofback.enabled is False
    d, tts, _clock = _daemon(monkeypatch, proofback=False)
    assert d._proofback is None
    calls = []
    # The one-argument shape existing callers and tests replace it with.
    d._speak_readback = lambda text: calls.append(text)
    d._maybe_read_back("hello world")
    assert calls == ["hello world"]


def test_barge_in_replaces_from_the_interrupted_word(monkeypatch):
    d, tts, clock = _daemon(monkeypatch)
    _dictate(d, FIRST)
    assert d._injector.ops == [("type", FIRST)]
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    assert tts.cancels >= 1, "the barge-in must still stop playback"
    armed = d._proofback.armed
    assert armed is not None and armed.word == "wrong"

    d._engine.text = "right file"
    d._on_hold_end()

    assert d._injector.ops == [
        ("type", FIRST),
        ("backspace", len("wrong file")),
        ("type", "right file"),
    ]
    # The undo record follows the screen: "send the " + "right file".
    assert d._ledger.last_text() == "right file"
    assert len(d._ledger) == 2
    assert d._proofback.armed is None


def test_the_listener_is_installed_for_dictation_and_cleared_for_say(monkeypatch):
    d, tts, _clock = _daemon(monkeypatch)
    _dictate(d, FIRST)
    _DeferReadback.pending.pop(0)()
    assert tts.listener_sets and tts.listener_sets[-1] is not None
    d._speak_readback("a status line")
    _DeferReadback.pending.pop(0)()
    assert tts.listener_sets[-1] is None


def test_a_press_during_say_arms_nothing(monkeypatch):
    d, tts, clock = _daemon(monkeypatch)
    d._speak_readback("send the wrong file")  # `yazses say`, not a dictation
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    assert d._proofback.armed is None


def test_a_hold_outside_read_back_disarms(monkeypatch):
    d, tts, clock = _daemon(monkeypatch)
    _dictate(d, FIRST)
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    assert d._proofback.armed is not None
    with d._lock:
        d._state.state = TrayState.IDLE
    d._on_hold_start(0)
    assert d._proofback.armed is None


def test_a_press_before_the_first_word_plays_arms_nothing(monkeypatch):
    d, tts, clock = _daemon(monkeypatch)
    _dictate(d, FIRST)
    tts.set_playback_listener = lambda fn: None  # a backend that reports no chunks
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    assert d._proofback.armed is None
    d._engine.text = "next sentence"
    d._on_hold_end()
    assert ("type", "next sentence") in d._injector.ops
    assert not [op for op in d._injector.ops if op[0] == "backspace"]


def test_text_typed_since_the_read_back_is_never_erased(monkeypatch):
    d, tts, clock = _daemon(monkeypatch)
    _dictate(d, FIRST)
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    d._last_dictation_monotonic = (d._last_dictation_monotonic or 0.0) + 5.0  # e.g. a punch-in
    d._engine.text = "right file"
    d._on_hold_end()
    assert ("type", "right file") in d._injector.ops
    assert not [op for op in d._injector.ops if op[0] == "backspace"]


def test_no_editable_target_reports_and_erases_nothing(monkeypatch):
    d, tts, clock = _daemon(monkeypatch, injection__target_guard="off")
    _dictate(d, FIRST)
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    with d._lock:
        d._state.target_ok = False
    d._engine.text = "right file"
    d._on_hold_end()
    assert not [op for op in d._injector.ops if op[0] == "backspace"]


def test_an_armed_target_dies_with_the_burst_that_follows(monkeypatch):
    d, tts, clock = _daemon(monkeypatch)
    _dictate(d, FIRST)
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    d._engine.text = ""  # nothing decoded: the burst is discarded
    d._on_hold_end()
    assert d._proofback.armed is None
    assert not [op for op in d._injector.ops if op[0] == "backspace"]


def test_a_truncated_read_back_word_is_reported_not_replaced(monkeypatch):
    d, tts, clock = _daemon(monkeypatch, tts__max_readback_chars=12)
    _dictate(d, FIRST)  # read back as "send the wro…"
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    assert tts.spoken[-1].endswith("…")
    assert d._proofback.armed is None
