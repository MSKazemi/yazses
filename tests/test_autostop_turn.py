"""Hands-free auto-stop is wired -- and only costs anything when it is on (ADR-v2-029, #164).

Three claims:

* **The state machine is right.** `AutoStopTurn` (pure, driven here by explicit timestamps)
  latches a *tap* open, passes a real *hold* straight through, ends on trailing silence after
  speech, never ends before the first word except after a long grace, ends on a second tap,
  and ends a turn exactly once even when the watcher and a second press race.
* **A default install is unchanged.** With `[autostop]` off the daemon builds no turn and the
  two hold handlers run their old bodies; nothing from `yazses.endpoint` is imported.
* **The registry tells the truth.** `autostop` is no longer advertised as unwired.

Nothing here opens a microphone, a keyboard device or a thread that outlives a test.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import pytest

from yazses.config import Config
from yazses.endpoint.autostop import (
    MIN_SILENCE_TIMEOUT_MS,
    NO_SPEECH_GRACE_MS,
    AutoStopTurn,
)


@dataclass
class _Cfg:
    enabled: bool = True
    mode: str = "silence"
    silence_timeout_ms: int = 800
    max_duration_ms: int = 30000


def _tapped(turn: AutoStopTurn, t: float = 0.0) -> float:
    """Press and release 100 ms later; return the time of the release."""
    assert turn.press(t) is False
    assert turn.release(t + 0.1) is True
    return t + 0.1


# ---- tap vs hold ----------------------------------------------------------------

def test_a_tap_latches_the_turn_open():
    turn = AutoStopTurn(_Cfg(), tap_ms=500)
    _tapped(turn)
    assert turn.latched is True


def test_a_real_hold_passes_straight_through_and_never_latches():
    turn = AutoStopTurn(_Cfg(), tap_ms=500)
    assert turn.press(0.0) is False
    assert turn.release(2.0) is False
    assert turn.latched is False
    assert turn.tick(3.0, False) is False  # nothing is latched, so nothing to end


def test_a_release_with_no_press_is_not_swallowed():
    # This is the watcher's own end call, re-entering the handler.
    assert AutoStopTurn(_Cfg()).release(1.0) is False


# ---- ending the turn --------------------------------------------------------------

def test_silence_after_speech_ends_the_turn_at_the_timeout():
    turn = AutoStopTurn(_Cfg(silence_timeout_ms=800), tap_ms=500)
    t = _tapped(turn)
    assert turn.tick(t + 0.5, True) is False  # speaking
    assert turn.tick(t + 1.0, False) is False  # silence begins
    assert turn.tick(t + 1.7, False) is False  # 700 ms of silence: not yet
    assert turn.tick(t + 1.8, False) is True  # 800 ms
    assert turn.latched is False
    assert turn.tick(t + 1.9, False) is False  # ended exactly once


def test_a_pause_shorter_than_the_timeout_does_not_end_the_turn():
    turn = AutoStopTurn(_Cfg(silence_timeout_ms=800), tap_ms=500)
    t = _tapped(turn)
    assert turn.tick(t + 0.5, True) is False
    assert turn.tick(t + 0.6, False) is False
    assert turn.tick(t + 1.2, False) is False  # 600 ms
    assert turn.tick(t + 1.3, True) is False  # speech resumes: the clock restarts
    assert turn.tick(t + 1.9, False) is False
    assert turn.tick(t + 2.6, False) is False  # 700 ms since the resumed silence began
    assert turn.tick(t + 2.8, False) is True


def test_silence_before_the_first_word_does_not_end_the_turn():
    # "Tap, think for a second, then speak" must not end before the user began.
    turn = AutoStopTurn(_Cfg(silence_timeout_ms=800), tap_ms=500)
    t = _tapped(turn)
    for step in range(1, 40):  # 3.9 s of silence, far past the 800 ms timeout
        assert turn.tick(t + step * 0.1, False) is False
    assert turn.tick(t + 4.0, True) is False
    assert turn.latched is True


def test_a_stray_tap_gives_up_after_the_grace_instead_of_running_to_the_cap():
    turn = AutoStopTurn(_Cfg(), tap_ms=500)
    t = _tapped(turn)
    grace = NO_SPEECH_GRACE_MS / 1000.0
    assert turn.tick(t + grace - 0.1, False) is False
    assert turn.tick(t + grace, False) is True


def test_the_hard_duration_cap_ends_a_turn_that_never_goes_quiet():
    turn = AutoStopTurn(_Cfg(max_duration_ms=10000), tap_ms=500)
    t = _tapped(turn)
    assert turn.tick(t + 9.9, True) is False
    assert turn.tick(t + 10.0, True) is True


def test_a_nonsense_silence_timeout_cannot_cut_every_sentence_after_one_word():
    turn = AutoStopTurn(_Cfg(silence_timeout_ms=0), tap_ms=500)
    t = _tapped(turn)
    assert turn.tick(t + 0.2, True) is False
    assert turn.tick(t + 0.3, False) is False  # an ordinary gap between words
    floor = MIN_SILENCE_TIMEOUT_MS / 1000.0
    assert turn.tick(t + 0.3 + floor + 0.01, False) is True


def test_a_second_tap_ends_the_turn_the_ordinary_way():
    turn = AutoStopTurn(_Cfg(), tap_ms=500)
    t = _tapped(turn)
    assert turn.tick(t + 1.0, True) is False
    assert turn.press(t + 2.0) is True  # swallowed: the recording is already running
    assert turn.release(t + 2.1) is False  # passes through, so the handler ends the turn
    assert turn.latched is False


def test_a_second_press_held_long_still_ends_on_its_release():
    turn = AutoStopTurn(_Cfg(), tap_ms=500)
    t = _tapped(turn)
    assert turn.press(t + 2.0) is True
    assert turn.release(t + 5.0) is False
    assert turn.latched is False


def test_the_release_of_a_press_that_raced_the_watcher_ends_nothing_twice():
    turn = AutoStopTurn(_Cfg(max_duration_ms=10000), tap_ms=500)
    t = _tapped(turn)
    assert turn.press(t + 9.99) is True  # second tap goes down ...
    assert turn.tick(t + 10.0, True) is True  # ... the watcher ends the turn first ...
    assert turn.release(t + 10.05) is True  # ... so that tap's release must be swallowed
    assert turn.release(t + 10.1) is False  # and it does not swallow an unrelated later one


def test_only_one_of_several_racing_ticks_ends_the_turn():
    turn = AutoStopTurn(_Cfg(max_duration_ms=1000), tap_ms=500)
    t = _tapped(turn)
    results: list[bool] = []

    def tick() -> None:
        results.append(turn.tick(t + 5.0, True))

    threads = [threading.Thread(target=tick) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results.count(True) == 1


def test_cancel_drops_a_latched_turn_without_ending_it():
    turn = AutoStopTurn(_Cfg(), tap_ms=500)
    _tapped(turn)
    turn.cancel()
    assert turn.latched is False
    assert turn.tick(99.0, False) is False


# ---- the daemon hook -------------------------------------------------------------------

def _daemon(cfg: Config):
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    return Daemon(config=cfg, platform=get_platform())


class _Earcon:
    def __init__(self) -> None:
        self.played: list[str] = []

    def play(self, name: str) -> None:
        self.played.append(name)


def test_a_default_daemon_builds_no_turn():
    cfg = Config()
    assert cfg.autostop.enabled is False
    daemon = _daemon(cfg)
    assert daemon._build_autostop(cfg) is None
    assert daemon._autostop is None


def test_an_enabled_daemon_builds_a_turn_from_the_hotkey_threshold():
    cfg = Config()
    cfg.autostop.enabled = True
    cfg.hotkey.hold_threshold_ms = 400
    turn = _daemon(cfg)._build_autostop(cfg)
    assert isinstance(turn, AutoStopTurn)
    assert turn.press(0.0) is False
    assert turn.release(0.39) is True  # a tap by the user's own hold threshold ...
    turn2 = _daemon(cfg)._build_autostop(cfg)
    turn2.press(0.0)
    assert turn2.release(0.41) is False  # ... and a hold just past it


def test_with_autostop_off_the_end_handler_runs_its_old_body():
    daemon = _daemon(Config())
    daemon._earcon = _Earcon()
    daemon._on_hold_end()
    assert daemon._earcon.played == ["recording_stop"]  # its first act, unchanged


def test_a_tap_defers_the_end_handler_and_starts_the_watcher(monkeypatch):
    cfg = Config()
    cfg.autostop.enabled = True
    daemon = _daemon(cfg)
    daemon._earcon = _Earcon()
    daemon._autostop = daemon._build_autostop(cfg)
    started = threading.Event()
    monkeypatch.setattr(daemon, "_autostop_watch", started.set)
    daemon._autostop.press(0.0)
    monkeypatch.setattr("yazses.core.daemon.time.monotonic", lambda: 0.1)
    daemon._on_hold_end()
    assert started.wait(timeout=5)
    assert daemon._earcon.played == []  # nothing ended: the recording stays open
    assert daemon._autostop.latched is True


def test_the_start_handler_swallows_a_second_tap_while_latched(monkeypatch):
    cfg = Config()
    cfg.autostop.enabled = True
    daemon = _daemon(cfg)
    daemon._earcon = _Earcon()
    daemon._autostop = daemon._build_autostop(cfg)
    _tapped(daemon._autostop)
    monkeypatch.setattr("yazses.core.daemon.time.monotonic", lambda: 5.0)
    daemon._on_hold_start(0)
    assert daemon._earcon.played == []  # no second "recording_start": nothing restarted


def test_the_watcher_ends_the_turn_through_the_ordinary_end_handler(monkeypatch):
    from yazses.platform.base import TrayState

    cfg = Config()
    cfg.autostop.enabled = True
    cfg.autostop.max_duration_ms = 60  # the cap ends it almost at once
    daemon = _daemon(cfg)
    daemon._autostop = daemon._build_autostop(cfg)
    daemon._state.state = TrayState.RECORDING
    ended: list[bool] = []
    monkeypatch.setattr(daemon, "_on_hold_end", lambda: ended.append(True))
    clock = iter(x * 0.05 for x in range(1000))
    monkeypatch.setattr("yazses.core.daemon.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("yazses.core.daemon.time.sleep", lambda s: None)
    daemon._autostop.press(0.0)
    daemon._autostop.release(0.01)  # latched at t=0.01
    daemon._autostop_watch()
    assert ended == [True]


def test_the_watcher_drops_the_latch_when_the_recording_ended_another_way(monkeypatch):
    from yazses.platform.base import TrayState

    cfg = Config()
    cfg.autostop.enabled = True
    daemon = _daemon(cfg)
    daemon._autostop = daemon._build_autostop(cfg)
    daemon._state.state = TrayState.IDLE  # e.g. the microphone vanished
    ended: list[bool] = []
    monkeypatch.setattr(daemon, "_on_hold_end", lambda: ended.append(True))
    monkeypatch.setattr("yazses.core.daemon.time.sleep", lambda s: None)
    _tapped(daemon._autostop)
    daemon._autostop_watch()
    assert ended == []
    assert daemon._autostop.latched is False


# ---- the registry --------------------------------------------------------------------------

def test_autostop_is_no_longer_advertised_as_unwired():
    from yazses.system.features import feature_status, unwired_slugs

    assert "autostop" not in unwired_slugs()
    feature = next(f for f in feature_status(Config()) if f.slug == "autostop")
    assert feature.wired is True


def test_enabling_the_feature_writes_exactly_the_one_key_the_daemon_reads():
    from yazses.system.features import _registry

    definition = next(d for d in _registry() if d.slug == "autostop")
    assert {(s, k, v) for s, k, v, _ in definition.on_writes} == {("autostop", "enabled", "true")}
    assert {(s, k, v) for s, k, v, _ in definition.off_writes} == {("autostop", "enabled", "false")}


@pytest.mark.parametrize("mode", ["silence", "semantic"])
def test_semantic_mode_falls_back_to_silence_instead_of_refusing_to_start(mode):
    cfg = Config()
    cfg.autostop.enabled = True
    cfg.autostop.mode = mode
    assert isinstance(_daemon(cfg)._build_autostop(cfg), AutoStopTurn)
