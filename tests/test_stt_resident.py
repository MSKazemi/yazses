"""`[stt] idle_unload_s`: the engine wrapper that releases the model and reloads it (ADR-029).

`stt/resident.py::IdleUnloadEngine` is the mechanism; the decision is
`system/residency.py`'s `IdleTracker`, tested in `test_residency.py`. Here the clock is a
list the test advances, the "model" is a counting fake, and the background reload's
thread is replaced by a callable the test runs when it chooses, so no test sleeps or
loads anything.

What these pin, in the order a user would meet them:

* nothing is released before the keep-alive, and something is at it;
* a decode after a release reloads, through the loader, exactly once;
* a release never happens while a decode is counted in, while a reload is in flight, or
  while anyone holds the lock -- and it never waits for any of them;
* every decode method reloads, and the reload is shared rather than repeated;
* the press-time prefetch starts the reload in the background and only restarts the
  keep-alive when the model is in.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from yazses.stt.resident import IdleUnloadEngine


class _Model:
    """A stand-in engine that records what it was asked to decode."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.decoded: list[int] = []

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        self.decoded.append(int(audio.size))
        return f"{self.name}:{audio.size}"

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        self.decoded.append(int(audio.size))
        return f"{self.name}:{audio.size}", []

    def decode_window(self, audio):
        self.decoded.append(int(audio.size))
        return f"{self.name}:window"


class _Rig:
    """An `IdleUnloadEngine` over a fake model, a hand-driven clock and deferred spawns."""

    def __init__(self, idle_s: float = 60.0) -> None:
        self.now = [0.0]
        self.built: list[_Model] = []
        self.spawned: list = []
        self.loaded_calls = 0
        self.first = _Model("first")
        self.engine = IdleUnloadEngine(
            self._load,
            idle_s,
            engine=self.first,
            clock=lambda: self.now[0],
            spawn=self.spawned.append,
            on_loaded=self._on_loaded,
        )

    def _load(self) -> _Model:
        model = _Model(f"reload{len(self.built) + 1}")
        self.built.append(model)
        return model

    def _on_loaded(self) -> None:
        self.loaded_calls += 1

    def at(self, t: float) -> IdleUnloadEngine:
        self.now[0] = t
        return self.engine


AUDIO = np.zeros(16000, dtype=np.float32)


def test_zero_or_negative_is_not_a_wrapper_it_is_the_plain_engine() -> None:
    """0 = never unload, which the daemon expresses by not wrapping at all."""
    for bad in (0, -5):
        with pytest.raises(ValueError):
            IdleUnloadEngine(lambda: _Model("x"), bad, engine=_Model("x"))


def test_the_engine_built_at_start_is_used_without_a_second_load() -> None:
    rig = _Rig()
    assert rig.engine.is_resident
    assert rig.at(1.0).transcribe(AUDIO) == "first:16000"
    assert rig.built == [] and rig.engine.reloads == 0


def test_nothing_is_released_before_the_keep_alive() -> None:
    rig = _Rig(idle_s=60)
    assert rig.at(59.9).detach_if_idle() is None
    assert rig.engine.is_resident


def test_the_model_is_released_at_the_keep_alive_and_handed_back() -> None:
    rig = _Rig(idle_s=60)
    released = rig.at(60.0).detach_if_idle()
    assert released is rig.first, "the caller must get the last reference to drop"
    assert not rig.engine.is_resident
    assert rig.engine.unloads == 1
    assert rig.engine.idle_s() is None
    assert rig.at(500.0).detach_if_idle() is None, "an unloaded model is not released twice"


def test_a_decode_restarts_the_keep_alive_from_its_end() -> None:
    rig = _Rig(idle_s=60)
    rig.at(50.0).transcribe(AUDIO)
    assert rig.at(100.0).detach_if_idle() is None       # 50 s after the decode
    assert rig.at(110.0).detach_if_idle() is rig.first  # 60 s after it


def test_a_touch_restarts_the_keep_alive_without_decoding() -> None:
    rig = _Rig(idle_s=60)
    rig.at(55.0).touch()
    assert rig.at(60.0).detach_if_idle() is None
    assert rig.first.decoded == []


def test_the_next_decode_after_a_release_reloads_once_and_decodes_the_audio() -> None:
    rig = _Rig(idle_s=60)
    rig.at(60.0).detach_if_idle()
    assert rig.at(61.0).transcribe(AUDIO) == "reload1:16000"
    assert rig.at(62.0).transcribe(AUDIO) == "reload1:16000"
    assert len(rig.built) == 1 and rig.engine.reloads == 1
    assert rig.loaded_calls == 1, "the daemon's loading-state hook ends exactly once"
    assert rig.engine.is_resident


@pytest.mark.parametrize("method", ["transcribe", "transcribe_words", "decode_window"])
def test_every_decode_method_reloads(method: str) -> None:
    rig = _Rig(idle_s=60)
    rig.at(60.0).detach_if_idle()
    getattr(rig.at(61.0), method)(AUDIO)
    assert len(rig.built) == 1
    assert rig.built[0].decoded == [16000]


def test_a_release_never_happens_while_a_decode_is_in_flight() -> None:
    """The point of the module: an unload cannot pull the model out from under a decode."""
    rig = _Rig(idle_s=60)
    inner = rig.engine._acquire()           # a decode that has started and not finished
    try:
        assert rig.at(1000.0).detach_if_idle() is None
        assert rig.engine.is_resident
    finally:
        rig.engine._release()
    # Released at t=1000, so the keep-alive restarts there.
    assert rig.at(1059.0).detach_if_idle() is None
    assert rig.at(1060.0).detach_if_idle() is inner


def test_a_release_never_waits_for_the_lock() -> None:
    """The daemon calls it holding its own state lock; blocking here would stall a press."""
    rig = _Rig(idle_s=60)
    rig.now[0] = 1000.0
    held = threading.Event()
    done = threading.Event()

    def _hold_the_lock() -> None:
        with rig.engine._cond:
            held.set()
            done.wait(5)

    t = threading.Thread(target=_hold_the_lock, daemon=True)
    t.start()
    try:
        assert held.wait(5)
        assert rig.engine.detach_if_idle() is None, "it must give up, not wait"
    finally:
        done.set()
        t.join(5)
    assert rig.engine.detach_if_idle() is rig.first


def test_a_failed_reload_raises_ends_the_loading_state_and_can_be_retried() -> None:
    attempts: list[int] = []

    def _flaky() -> _Model:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("model files gone")
        return _Model("second-try")

    now = [0.0]
    loaded: list[int] = []
    engine = IdleUnloadEngine(
        _flaky, 60, engine=_Model("first"), clock=lambda: now[0],
        spawn=lambda fn: None, on_loaded=lambda: loaded.append(1),
    )
    now[0] = 60.0
    engine.detach_if_idle()
    with pytest.raises(RuntimeError):
        engine.transcribe(AUDIO)
    assert loaded == [1], "a failed load must still end a 'loading' state"
    assert not engine.is_loading and not engine.is_resident
    assert engine.transcribe(AUDIO) == "second-try:16000"


def test_prefetch_starts_the_reload_in_the_background_when_the_model_is_out() -> None:
    rig = _Rig(idle_s=60)
    rig.at(60.0).detach_if_idle()
    assert rig.at(61.0).prefetch() is True
    assert rig.built == [], "the reload must run on the spawned thread, not the caller's"
    assert len(rig.spawned) == 1
    rig.spawned.pop()()                      # the background thread runs
    assert rig.engine.is_resident and len(rig.built) == 1
    # The burst's decode then uses the reloaded model without loading again.
    assert rig.at(62.0).transcribe(AUDIO) == "reload1:16000"
    assert len(rig.built) == 1


def test_prefetch_with_the_model_in_only_restarts_the_keep_alive() -> None:
    rig = _Rig(idle_s=60)
    assert rig.at(50.0).prefetch() is False
    assert rig.spawned == []
    assert rig.at(100.0).detach_if_idle() is None, "a long hold must not unload under the speaker"
    assert rig.at(110.0).detach_if_idle() is rig.first


def test_prefetch_while_a_reload_is_in_flight_does_not_start_another() -> None:
    rig = _Rig(idle_s=60)
    rig.at(60.0).detach_if_idle()
    rig.engine._loading = True              # another thread is loading right now
    assert rig.at(61.0).prefetch() is False
    assert rig.spawned == []
    assert rig.engine.detach_if_idle() is None


def test_a_failed_prefetch_is_swallowed_so_the_burst_reports_it_instead() -> None:
    def _broken() -> _Model:
        raise RuntimeError("no disk")

    spawned: list = []
    now = [0.0]
    engine = IdleUnloadEngine(_broken, 60, engine=_Model("first"),
                              clock=lambda: now[0], spawn=spawned.append)
    now[0] = 60.0
    engine.detach_if_idle()
    engine.prefetch()
    spawned.pop()()                          # must not raise into the thread
    assert not engine.is_resident and not engine.is_loading


def test_concurrent_decodes_share_one_reload() -> None:
    """Two threads that both need the model after a release load it once, not twice."""
    gate = threading.Event()
    built: list[_Model] = []

    def _slow_load() -> _Model:
        gate.wait(5)
        model = _Model(f"m{len(built)}")
        built.append(model)
        return model

    now = [0.0]
    engine = IdleUnloadEngine(_slow_load, 60, engine=_Model("first"), clock=lambda: now[0])
    now[0] = 60.0
    engine.detach_if_idle()
    results: list[str] = []
    threads = [
        threading.Thread(target=lambda: results.append(engine.transcribe(AUDIO)), daemon=True)
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join(5)
    assert len(built) == 1
    assert results == ["m0:16000", "m0:16000"]


def test_unknown_attributes_delegate_only_while_the_model_is_in() -> None:
    """An attribute probe must never cost a reload."""
    rig = _Rig(idle_s=60)
    assert rig.engine.name == "first"
    rig.at(60.0).detach_if_idle()
    with pytest.raises(AttributeError):
        _ = rig.engine.name
    assert not hasattr(rig.engine, "name")
    assert rig.built == []


def test_it_satisfies_the_engine_protocol() -> None:
    from yazses.stt.base import SttEngine

    assert isinstance(_Rig().engine, SttEngine)
