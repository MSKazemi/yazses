"""Toggle dictation: press once to start, press again to stop (#869).

The latch itself is pure (`yazses.hotkeys.toggle`) and is tested with plain numbers; the
daemon wiring is tested on an unstarted daemon with the hold handlers replaced by recorders.
"""
from __future__ import annotations

import threading

import pytest

from yazses.config import Config, load_config
from yazses.hotkeys.toggle import DEFAULT_MODE, MODES, Press, ToggleTurn, normalise_mode
from yazses.platform.base import TrayState

# --- the pure latch -------------------------------------------------------------------


def _idle(turn: ToggleTurn, now: float) -> Press:
    return turn.press(now, recording=False, busy=False)


def _rec(turn: ToggleTurn, now: float) -> Press:
    return turn.press(now, recording=True, busy=False)


def test_first_press_starts_and_second_press_stops():
    turn = ToggleTurn(max_seconds=300)
    assert _idle(turn, 0.0) is Press.START
    assert turn.latched
    turn.release(0.2)  # the first release does nothing
    assert turn.latched
    assert _rec(turn, 5.0) is Press.STOP
    assert not turn.latched
    turn.release(5.1)
    assert _idle(turn, 9.0) is Press.START  # and the next press starts again


def test_a_long_press_still_only_starts():
    turn = ToggleTurn()
    assert _idle(turn, 0.0) is Press.START
    turn.release(4.0)  # held for four seconds: still latched, unlike hold-to-talk
    assert turn.latched


def test_key_auto_repeat_neither_stops_nor_restarts():
    turn = ToggleTurn()
    assert _idle(turn, 0.0) is Press.START
    for t in (0.5, 0.53, 0.56, 2.0):  # key-downs with no key-up between them
        assert _rec(turn, t) is Press.IGNORE
    assert turn.latched
    turn.release(2.1)
    assert _rec(turn, 3.0) is Press.STOP
    for t in (3.5, 3.6):  # holding the stopping press must not start a new recording
        assert _idle(turn, t) is Press.IGNORE
    assert not turn.latched


def test_a_press_while_busy_is_ignored_and_does_not_latch():
    turn = ToggleTurn()
    assert turn.press(0.0, recording=False, busy=True) is Press.IGNORE
    assert not turn.latched
    turn.release(0.1)
    assert _idle(turn, 1.0) is Press.START


def test_a_press_while_another_source_records_is_ignored():
    turn = ToggleTurn()
    assert _rec(turn, 0.0) is Press.IGNORE  # not this latch's recording
    assert not turn.latched


def test_a_recording_that_ended_elsewhere_makes_the_next_press_a_start():
    turn = ToggleTurn()
    assert _idle(turn, 0.0) is Press.START
    turn.release(0.1)
    # The microphone vanished and the daemon went idle without telling the latch.
    assert _idle(turn, 3.0) is Press.START
    assert turn.latched


def test_the_cap_ends_a_latched_recording_once():
    turn = ToggleTurn(max_seconds=10)
    _idle(turn, 0.0)
    assert turn.expired(9.9) is False
    assert turn.expired(10.0) is True
    assert turn.expired(11.0) is False  # exactly once
    assert not turn.latched


def test_a_press_after_the_cap_starts_rather_than_stops():
    turn = ToggleTurn(max_seconds=10)
    _idle(turn, 0.0)
    turn.release(0.1)
    assert turn.expired(10.0)
    assert _idle(turn, 12.0) is Press.START


def test_zero_max_seconds_means_no_cap():
    turn = ToggleTurn(max_seconds=0)
    _idle(turn, 0.0)
    assert turn.expired(1e9) is False
    assert turn.latched


def test_cancel_drops_the_latch():
    turn = ToggleTurn()
    _idle(turn, 0.0)
    turn.cancel()
    assert not turn.latched
    assert turn.expired(1e9) is False


def test_cap_and_second_press_racing_end_the_turn_exactly_once():
    for _ in range(200):
        turn = ToggleTurn(max_seconds=1)
        _idle(turn, 0.0)
        turn.release(0.1)
        ended: list[str] = []
        barrier = threading.Barrier(2)

        def cap() -> None:
            barrier.wait()
            if turn.expired(5.0):
                ended.append("cap")

        def press() -> None:
            barrier.wait()
            if _rec(turn, 5.0) is Press.STOP:
                ended.append("press")

        threads = [threading.Thread(target=cap), threading.Thread(target=press)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=10)
            assert not th.is_alive()
        assert len(ended) == 1


@pytest.mark.parametrize(
    ("raw", "mode"),
    [("hold", "hold"), ("toggle", "toggle"), (" Toggle ", "toggle"), ("latch", "hold"),
     ("", "hold"), (None, "hold"), (1, "hold")],
)
def test_normalise_mode(raw, mode):
    assert normalise_mode(raw) == mode


def test_mode_constants():
    assert DEFAULT_MODE == "hold"
    assert MODES == ("hold", "toggle")


def test_configcheck_validates_the_same_modes():
    from yazses.configcheck import _ENUMS

    assert _ENUMS["hotkey.mode"] == MODES


# --- config ---------------------------------------------------------------------------


def test_the_default_is_hold_to_talk():
    assert Config().hotkey.mode == "hold"


def test_mode_loads_from_toml(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[hotkey]\nmode = "toggle"\n', encoding="utf-8")
    assert load_config(p).hotkey.mode == "toggle"


# --- daemon wiring --------------------------------------------------------------------


_DAEMONS: list = []


def _daemon(cfg: Config):
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    daemon = Daemon(config=cfg, platform=get_platform())
    _DAEMONS.append(daemon)
    return daemon


@pytest.fixture(autouse=True)
def _stop_toggle_watchers():
    """End every `toggle-watch` thread a test started.

    A latched recording leaves its watcher polling for as long as the process lives, and a
    later test that replaces ``time.sleep`` (the injection-delay tests do) would otherwise
    share the process with it.
    """
    yield
    while _DAEMONS:
        daemon = _DAEMONS.pop()
        daemon._stop_event.set()
        daemon._toggle_gen += 1
    for t in threading.enumerate():
        if t.name == "toggle-watch":
            t.join(timeout=5)
            assert not t.is_alive()


def _toggle_cfg(max_seconds: int = 300) -> Config:
    cfg = Config()
    cfg.hotkey.mode = "toggle"
    cfg.audio.max_record_seconds = max_seconds
    return cfg


class _Calls:
    """Stand-ins for the hold handlers that also move the daemon's state like the real ones."""

    def __init__(self, daemon, *, fail_start: bool = False) -> None:
        self.daemon = daemon
        self.log: list[str] = []
        self.fail_start = fail_start
        self.ended = threading.Event()

    def start(self, leaked: int) -> None:
        self.log.append("start")
        self.daemon._hold_start_failed = self.fail_start
        if not self.fail_start:
            self.daemon._state.state = TrayState.RECORDING

    def end(self) -> None:
        self.log.append("end")
        self.daemon._state.state = TrayState.IDLE
        self.ended.set()


def _wired(monkeypatch, cfg: Config, **kw):
    daemon = _daemon(cfg)
    daemon._toggle = daemon._build_toggle(cfg)
    daemon._state.state = TrayState.IDLE  # an unstarted daemon is still LOADING
    calls = _Calls(daemon, **kw)
    monkeypatch.setattr(daemon, "_on_hold_start", calls.start)
    monkeypatch.setattr(daemon, "_on_hold_end", calls.end)
    return daemon, calls


def test_a_default_daemon_builds_no_toggle():
    cfg = Config()
    assert _daemon(cfg)._build_toggle(cfg) is None


def test_an_unknown_mode_falls_back_to_hold(caplog):
    cfg = Config()
    cfg.hotkey.mode = "sticky"
    assert _daemon(cfg)._build_toggle(cfg) is None
    assert "using hold-to-talk" in caplog.text


def test_toggle_mode_builds_a_latch_capped_by_max_record_seconds():
    cfg = _toggle_cfg(120)
    turn = _daemon(cfg)._build_toggle(cfg)
    assert isinstance(turn, ToggleTurn)
    assert turn.max_seconds == 120


def test_press_starts_release_keeps_recording_press_stops(monkeypatch):
    daemon, calls = _wired(monkeypatch, _toggle_cfg())
    daemon._on_toggle_press(0)
    daemon._on_toggle_release()
    assert calls.log == ["start"]
    assert daemon._state.state == TrayState.RECORDING
    daemon._on_toggle_press(0)
    daemon._on_toggle_release()
    assert calls.log == ["start", "end"]


def test_a_press_during_transcription_is_ignored(monkeypatch):
    daemon, calls = _wired(monkeypatch, _toggle_cfg())
    daemon._state.state = TrayState.TRANSCRIBING
    daemon._on_toggle_press(0)
    daemon._on_toggle_release()
    assert calls.log == []
    assert not daemon._toggle.latched


def test_a_failed_microphone_leaves_nothing_latched(monkeypatch):
    daemon, calls = _wired(monkeypatch, _toggle_cfg(), fail_start=True)
    daemon._on_toggle_press(0)
    daemon._on_toggle_release()
    assert calls.log == ["start"]
    assert not daemon._toggle.latched
    daemon._on_toggle_press(0)  # the next press tries again rather than "stopping"
    assert calls.log == ["start", "start"]


def test_the_cap_watcher_ends_a_recording_left_running(monkeypatch):
    monkeypatch.setattr("yazses.core.daemon._TOGGLE_POLL_S", 0.01)
    daemon, calls = _wired(monkeypatch, _toggle_cfg(max_seconds=1))
    clock = [100.0]
    monkeypatch.setattr("yazses.core.daemon.time.monotonic", lambda: clock[0])
    daemon._on_toggle_press(0)
    daemon._on_toggle_release()
    clock[0] = 101.5
    assert calls.ended.wait(timeout=5)
    assert calls.log == ["start", "end"]
    assert not daemon._toggle.latched


def test_the_watcher_drops_the_latch_when_the_recording_ends_elsewhere(monkeypatch):
    monkeypatch.setattr("yazses.core.daemon._TOGGLE_POLL_S", 0.01)
    daemon, calls = _wired(monkeypatch, _toggle_cfg())
    daemon._on_toggle_press(0)
    daemon._on_toggle_release()
    daemon._state.state = TrayState.IDLE  # mic lost, shutdown: not via the hotkey
    for _ in range(500):
        if not daemon._toggle.latched:
            break
        threading.Event().wait(0.01)
    assert not daemon._toggle.latched
    assert calls.log == ["start"]  # nothing was ended twice


def test_the_command_key_does_nothing_while_a_toggle_dictation_is_open(monkeypatch):
    daemon, calls = _wired(monkeypatch, _toggle_cfg())
    daemon._on_toggle_press(0)
    daemon._on_toggle_release()
    daemon._on_command_hold_start(0)
    daemon._on_command_hold_end()
    assert calls.log == ["start"]
    assert daemon._command_mode is False
    assert daemon._toggle.latched


def test_hold_mode_leaves_the_command_key_unchanged(monkeypatch):
    daemon = _daemon(Config())
    daemon._state.state = TrayState.IDLE
    calls = _Calls(daemon)
    monkeypatch.setattr(daemon, "_on_hold_start", calls.start)
    monkeypatch.setattr(daemon, "_on_hold_end", calls.end)
    daemon._on_command_hold_start(0)
    daemon._on_command_hold_end()
    assert calls.log == ["start", "end"]


def _watchers() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "toggle-watch"]


def test_the_watcher_ends_when_the_daemon_stops(monkeypatch):
    """A latched recording must not leave a thread polling after the daemon is gone."""
    daemon, _calls = _wired(monkeypatch, _toggle_cfg())
    daemon._on_toggle_press(0)
    assert len(_watchers()) == 1
    daemon._stop_event.set()
    for t in _watchers():
        t.join(timeout=5)
    assert _watchers() == []


def test_the_watcher_does_not_depend_on_time_sleep(monkeypatch):
    """It waits on the stop event, so a replaced ``time.sleep`` cannot make it spin.

    ``test_windows_injection_reaches_the_app`` swaps ``time.sleep`` for a function that
    records its calls; a watcher looping on the real one flooded that list and crashed
    the worker on the FreeBSD leg.
    """
    calls_to_sleep: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: calls_to_sleep.append(s))
    daemon, _calls = _wired(monkeypatch, _toggle_cfg())
    daemon._on_toggle_press(0)
    assert len(_watchers()) == 1
    daemon._stop_event.set()
    for t in _watchers():
        t.join(timeout=5)
    assert _watchers() == []
    assert calls_to_sleep == []
