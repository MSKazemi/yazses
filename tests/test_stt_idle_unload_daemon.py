"""`[stt] idle_unload_s` in the daemon: off by default, and on, a press survives an unload.

The wrapper's own rules are `test_stt_resident.py`; this file pins how the daemon uses it:

* at the default (`0`) the daemon builds no wrapper, starts no thread, and the hold path
  is exactly the old one;
* the housekeeping tick releases the model only while the daemon is IDLE or PAUSED, and
  never while a decode is counted in;
* after a release, a press starts the reload in the background, the recorder captures
  the whole burst regardless, the tray shows LOADING while the decode waits for the
  model, and the burst is transcribed and typed — the press's audio is not lost;
* a burst that is discarded while the reload is still running leaves the daemon IDLE,
  not stuck on LOADING.

Real `Daemon` objects with the model, recorder stream and injector replaced, the same
way `test_stray_hold_release_types_nothing.py` drives the hold path. No model loads, no
microphone opens, and the clock is a list the test advances.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from yazses.audio import recorder
from yazses.audio.recorder import AudioRecorder
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.platform.base import TrayState
from yazses.stt.resident import IdleUnloadEngine


@pytest.fixture()
def sd(mocker):
    fake = mocker.MagicMock(name="sounddevice")
    mocker.patch.object(recorder, "_sd", return_value=fake)
    return fake


class _Engine:
    """A stand-in model: records the size of every clip it is asked to decode."""

    def __init__(self, name: str = "engine") -> None:
        self.name = name
        self.clips: list[int] = []

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        self.clips.append(int(audio.size))
        return "this sentence is written by my voice"

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        self.clips.append(int(audio.size))
        return "this sentence is written by my voice", []

    def decode_window(self, audio):
        return ""


class _Injector:
    def __init__(self) -> None:
        self.injected: list[str] = []

    def inject(self, text):
        self.injected.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        pass


def _config(idle_unload_s: int = 0) -> Config:
    cfg = Config()
    cfg.stt.idle_unload_s = idle_unload_s
    cfg.filters.disfluency.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    cfg.accessibility.pre_speech_padding_ms = 0
    # The speech detector is not what this file tests; a constant tone must reach decode.
    cfg.accessibility.speech_presence_check = False
    return cfg


def _daemon(idle_unload_s: int = 0) -> Daemon:
    d = Daemon(config=_config(idle_unload_s), platform=get_platform())
    d._recorder = AudioRecorder()
    d._padding_buffer = None
    d._injector = _Injector()
    d._state.target_ok = True
    d._detect_target_async = lambda: None
    with d._lock:
        d._state.ready = True
        d._state.state = TrayState.IDLE
    return d


class _Rig:
    """A daemon whose engine is an `IdleUnloadEngine` on a hand-driven clock.

    The background reload is captured rather than run, so a test decides whether the
    press's prefetch finished before the release or not.
    """

    def __init__(self, idle_unload_s: int = 60) -> None:
        self.d = _daemon(idle_unload_s)
        self.now = [0.0]
        self.first = _Engine("first")
        self.reloaded: list[_Engine] = []
        self.state_during_load: list[TrayState] = []
        self.spawned: list = []
        wrapper = IdleUnloadEngine(
            self._load,
            idle_unload_s,
            engine=self.first,
            clock=lambda: self.now[0],
            spawn=self.spawned.append,
            on_loaded=self.d._on_stt_engine_loaded,
        )
        self.d._engine = wrapper
        self.d._idle_unload_engine = wrapper
        self.engine = wrapper

    def _load(self) -> _Engine:
        with self.d._lock:
            self.state_during_load.append(self.d._state.state)
        model = _Engine(f"reload{len(self.reloaded) + 1}")
        self.reloaded.append(model)
        return model

    def at(self, t: float) -> Daemon:
        self.now[0] = t
        return self.d


def _speak(d: Daemon, seconds: float = 1.0, level: float = 0.5) -> int:
    clip = np.full((int(16000 * seconds), 1), level, dtype=np.float32)
    d._recorder._callback(clip, clip.shape[0], None, None)
    return clip.shape[0]


# ---- off by default ---------------------------------------------------------------


def test_the_key_defaults_to_never() -> None:
    assert Config().stt.idle_unload_s == 0


def test_at_the_default_the_engine_is_not_wrapped() -> None:
    d = _daemon(0)
    engine = _Engine()
    assert d._with_idle_unload(engine) is engine
    assert d._idle_unload_engine is None


def test_at_the_default_no_thread_starts_and_the_tick_does_nothing() -> None:
    d = _daemon(0)
    d._engine = _Engine()
    before = {t.name for t in threading.enumerate()}
    d._start_stt_idle_unloader()
    assert "stt-idle-unload" not in {t.name for t in threading.enumerate()} - before
    assert d._stt_idle_unload_tick() is False
    assert d._stt_reload_pending() is False


def test_at_the_default_a_burst_is_transcribed_as_before(sd) -> None:
    d = _daemon(0)
    d._engine = engine = _Engine()
    d._on_hold_start(0)
    samples = _speak(d)
    d._on_hold_end()
    assert engine.clips == [samples]
    assert d._injector.injected and d._state.state is TrayState.IDLE


def test_a_partial_daemon_never_mistakes_a_test_double_for_the_wrapper() -> None:
    """The helpers read `_idle_unload_engine`, never `_engine`: a MagicMock engine must not
    start a thread or put up LOADING."""
    bare = Daemon.__new__(Daemon)
    assert bare._idle_unload_engine is None
    assert Daemon._stt_reload_pending(bare) is False


# ---- the wiring --------------------------------------------------------------------


def test_a_positive_value_wraps_the_engine_and_reloads_through_the_same_factory(
    monkeypatch,
) -> None:
    import yazses.core.daemon as daemon_mod

    asked: list[object] = []

    def _fake_build(stt):
        asked.append(stt)
        return _Engine("rebuilt")

    monkeypatch.setattr(daemon_mod, "build_engine", _fake_build)
    d = _daemon(30)
    first = _Engine("first")
    wrapped = d._with_idle_unload(first)
    assert isinstance(wrapped, IdleUnloadEngine)
    assert d._idle_unload_engine is wrapped
    assert wrapped.idle_unload_s == 30
    assert asked == [], "wrapping must not load a second copy"
    assert wrapped._load().name == "rebuilt"
    assert asked == [d._config.stt], "a reload goes through build_engine with [stt]"


def test_a_positive_value_starts_the_tick_thread() -> None:
    rig = _Rig(60)
    try:
        rig.d._start_stt_idle_unloader()
        assert "stt-idle-unload" in {t.name for t in threading.enumerate()}
    finally:
        rig.d._stop_event.set()


# ---- the tick ------------------------------------------------------------------------


def test_the_tick_releases_the_model_only_at_the_keep_alive() -> None:
    rig = _Rig(60)
    assert rig.at(59.0)._stt_idle_unload_tick() is False
    assert rig.engine.is_resident
    assert rig.at(60.0)._stt_idle_unload_tick() is True
    assert not rig.engine.is_resident and rig.engine.unloads == 1


@pytest.mark.parametrize(
    "state",
    [TrayState.RECORDING, TrayState.TRANSCRIBING, TrayState.INJECTING,
     TrayState.MEETING, TrayState.READBACK, TrayState.LOADING],
)
def test_the_tick_never_releases_outside_idle_or_paused(state: TrayState) -> None:
    """A press sets RECORDING under the same lock, so it cannot slip between check and unload."""
    rig = _Rig(60)
    with rig.d._lock:
        rig.d._state.state = state
    assert rig.at(10_000.0)._stt_idle_unload_tick() is False
    assert rig.engine.is_resident


def test_the_tick_releases_while_paused() -> None:
    rig = _Rig(60)
    with rig.d._lock:
        rig.d._state.state = TrayState.PAUSED
    assert rig.at(60.0)._stt_idle_unload_tick() is True


def test_the_tick_does_nothing_before_the_daemon_is_ready() -> None:
    rig = _Rig(60)
    with rig.d._lock:
        rig.d._state.ready = False
    assert rig.at(60.0)._stt_idle_unload_tick() is False


def test_the_tick_never_releases_under_a_decode_in_flight() -> None:
    """A decode outside the hold path (a meeting chunk, a spoken answer) runs while IDLE."""
    rig = _Rig(60)
    rig.engine._acquire()
    try:
        assert rig.at(10_000.0)._stt_idle_unload_tick() is False
        assert rig.engine.is_resident
    finally:
        rig.engine._release()


# ---- a press after a release -----------------------------------------------------------


def test_a_press_after_a_release_keeps_its_audio_and_types_it(sd) -> None:
    """The prefetch has not finished when the key is released: the decode waits for it."""
    rig = _Rig(60)
    rig.at(60.0)._stt_idle_unload_tick()

    d = rig.at(100.0)
    d._on_hold_start(0)
    assert d._state.state is TrayState.RECORDING, "capture started without waiting for a model"
    assert len(rig.spawned) == 1, "the press started the reload in the background"
    assert rig.reloaded == [], "and did not load on the hotkey thread"

    samples = _speak(d, seconds=1.5)
    d._on_hold_end()

    assert len(rig.reloaded) == 1 and rig.engine.reloads == 1
    assert rig.reloaded[0].clips == [samples], "the whole burst reached the reloaded model"
    assert rig.first.clips == []
    assert rig.state_during_load == [TrayState.LOADING], "the tray said why it was slow"
    assert len(d._injector.injected) == 1
    assert "written by my voice" in d._injector.injected[0]
    assert d._state.state is TrayState.IDLE

    # The background prefetch then finds the model already in and loads nothing more.
    rig.spawned.pop()()
    assert len(rig.reloaded) == 1


def test_a_press_whose_prefetch_finished_decodes_without_loading_state(sd) -> None:
    rig = _Rig(60)
    rig.at(60.0)._stt_idle_unload_tick()

    d = rig.at(100.0)
    d._on_hold_start(0)
    samples = _speak(d)
    rig.spawned.pop()()               # the background reload finishes while the user speaks
    assert rig.state_during_load == [TrayState.RECORDING]
    assert d._state.state is TrayState.RECORDING, "a finished reload must not end the recording"

    d._on_hold_end()
    assert rig.reloaded[0].clips == [samples]
    assert d._injector.injected
    assert d._state.state is TrayState.IDLE


def test_a_press_with_the_model_in_restarts_its_keep_alive(sd) -> None:
    rig = _Rig(60)
    d = rig.at(50.0)
    d._on_hold_start(0)
    assert rig.spawned == []
    _speak(d)
    with d._lock:
        d._state.state = TrayState.IDLE   # as if released without a decode
    assert rig.at(100.0)._stt_idle_unload_tick() is False, "pressing counted as use"


def test_a_burst_discarded_during_the_reload_leaves_the_daemon_idle(sd) -> None:
    """A silent burst returns before decoding; the burst's LOADING must not outlive it."""
    rig = _Rig(60)
    rig.at(60.0)._stt_idle_unload_tick()
    d = rig.at(100.0)
    d._on_hold_start(0)
    _speak(d, level=0.0)              # silence: discarded before any decode
    d._on_hold_end()
    assert rig.reloaded == [], "nothing was decoded, so nothing had to load inline"
    assert d._state.state is TrayState.IDLE


def test_the_loaded_hook_only_ends_a_reload_loading_state() -> None:
    d = _daemon(60)
    with d._lock:
        d._state.state = TrayState.LOADING
        d._state.ready = False          # start-up's LOADING belongs to run()
    d._on_stt_engine_loaded()
    assert d._state.state is TrayState.LOADING

    with d._lock:
        d._state.ready = True
    d._on_stt_engine_loaded()
    assert d._state.state is TrayState.TRANSCRIBING

    with d._lock:
        d._state.state = TrayState.RECORDING
    d._on_stt_engine_loaded()
    assert d._state.state is TrayState.RECORDING
