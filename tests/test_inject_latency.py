"""Latency work on the path from transcript to typed text, and the guards it must keep.

Two changes, each of which keeps the typed text and the safety ordering identical:

* the ydotool flood guard releases the keys this burst's ``type`` can have pressed,
  not a fixed 60-key sweep that cost ~720 ms of ydotool's per-key delay every burst;
* the hold-end hotkey key-up runs alongside the decode, and every keystroke waits
  for it, instead of sitting in series in front of the decode.

All subprocesses are mocked; nothing here types anything.
"""
from __future__ import annotations

import string
import subprocess
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.inject import ydotool as yd
from yazses.inject.keycodes import KEYCODES
from yazses.platform import get_platform

_FULL_SWEEP = set(yd._RELEASE_ALL_TYPED_KEYS)
_TYPABLE = [c for c in string.printable if c not in "\r\x0b\x0c"]


def _codes(tokens):
    return {int(t.split(":")[0]) for t in tokens}


# --- the flood guard's key set ------------------------------------------------


@pytest.mark.parametrize("ch", _TYPABLE)
def test_every_typable_character_has_its_key_released(ch):
    tokens = yd.release_tokens_after_typing(ch)
    assert yd._US_ASCII_KEYCODES[ch] in _codes(tokens)
    assert all(t.endswith(":0") for t in tokens)  # key-ups only, never a press


def test_the_release_never_reaches_outside_the_original_sweep():
    # A narrower guard, not a different one: every token was already being sent.
    assert set(yd.release_tokens_after_typing("".join(_TYPABLE))) <= _FULL_SWEEP


def test_hotkey_modifiers_shifts_and_space_are_always_released():
    codes = _codes(yd.release_tokens_after_typing("x"))
    for name in ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT", "KEY_LEFTCTRL", "KEY_LEFTALT",
                 "KEY_SPACE"):
        assert KEYCODES[name] in codes, name
    assert {97, 100, 125, 126} <= codes  # right_ctrl, right_alt, both metas


def test_the_us_table_is_the_evdev_us_layout():
    # Spot checks against input-event-codes.h, the table ydotool 1.x compiles in.
    assert yd._US_ASCII_KEYCODES["a"] == yd._US_ASCII_KEYCODES["A"] == 30
    assert yd._US_ASCII_KEYCODES["!"] == yd._US_ASCII_KEYCODES["1"] == 2
    assert yd._US_ASCII_KEYCODES["\n"] == 28
    assert yd._US_ASCII_KEYCODES[" "] == 57
    assert yd._US_ASCII_KEYCODES["/"] == yd._US_ASCII_KEYCODES["?"] == 53


def test_a_character_outside_the_table_falls_back_to_the_full_sweep():
    assert yd.release_tokens_after_typing("ok\rok") == yd._RELEASE_ALL_TYPED_KEYS


def test_non_ascii_characters_do_not_widen_or_break_the_release():
    # Typed by UnicodeInjector on its own device; ydotoold key-ups cannot reach it.
    assert yd.release_tokens_after_typing("café") == yd.release_tokens_after_typing("caf")


def test_a_short_burst_sends_far_fewer_delayed_key_ups():
    # The point of the change, in ydotool `key` events (each followed by its 12 ms delay).
    assert len(yd.release_tokens_after_typing("Sounds good.")) <= 20 < len(_FULL_SWEEP)


class _Run:
    def __init__(self, type_exc=None):
        self.type_exc = type_exc
        self.argvs: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.argvs.append(list(argv))
        if argv[1] == "type" and self.type_exc is not None:
            raise self.type_exc
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def test_success_releases_exactly_the_keys_of_the_text(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _Run()
    monkeypatch.setattr(subprocess, "run", run)
    yd.YdotoolInjector().inject("Hi there")
    assert [a[1] for a in run.argvs] == ["type", "key"]
    assert run.argvs[1][2:] == yd.release_tokens_after_typing("Hi there")


def test_a_failed_type_still_sends_the_full_sweep(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _Run(type_exc=subprocess.TimeoutExpired(["ydotool", "type"], 10.0))
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.TimeoutExpired):
        yd.YdotoolInjector().inject("Hi there")
    assert run.argvs[-1] == ["ydotool", "key", *yd._RELEASE_ALL_TYPED_KEYS]


def test_mixed_text_releases_the_keys_of_every_ascii_run(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _Run()
    monkeypatch.setattr(subprocess, "run", run)

    class _Uni:
        def ensure_producible(self, text):
            pass

        def inject(self, text):
            pass

        def close(self):
            pass

    monkeypatch.setattr("yazses.inject.unicode.UnicodeInjector", _Uni)
    yd.YdotoolInjector().inject("ab é xy")
    assert [a[1] for a in run.argvs] == ["type", "type", "key"]
    released = _codes(run.argvs[-1][2:])
    for ch in "abxy":
        assert yd._US_ASCII_KEYCODES[ch] in released


# --- the hotkey release overlaps the decode ---------------------------------


class _Recorder:
    def stop(self):
        return np.full(16000, 0.5, dtype="float32")


class _Injector:
    def __init__(self, log):
        self.log = log

    def inject(self, text):
        self.log.append(("inject", text))

    def inject_backspaces(self, n):
        self.log.append(("backspace", n))

    def inject_key_sequence(self, keys):
        self.log.append(("keys", list(keys)))


def _daemon(log, decode_started: threading.Event, release_may_finish: threading.Event):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _Recorder()
    d._padding_buffer = None
    d._injector = _Injector(log)

    class _Engine:
        def transcribe(self, audio, sample_rate=16000, initial_prompt=None, task=None):
            decode_started.set()
            log.append(("decode", None))
            return "hello world"

    d._engine = _Engine()

    def slow_release():
        # Finishes only once the decode has begun: if the release still ran in
        # series in front of the decode, this would wait out its timeout.
        release_may_finish.wait(timeout=5)
        time.sleep(0.05)
        log.append(("release", None))

    d._release_hotkey_modifier = slow_release  # type: ignore[method-assign]
    return d


def test_the_release_runs_while_the_decode_does_and_lands_before_any_keystroke():
    log: list = []
    decode_started = threading.Event()
    d = _daemon(log, decode_started, decode_started)
    d._on_hold_end()
    kinds = [k for k, _ in log]
    assert kinds == ["decode", "release", "inject"]  # overlapped, and still first
    assert ("inject", "hello world") in log
    assert d._hotkey_release_thread is None


def test_a_discarded_burst_still_waits_for_the_release_before_returning():
    log: list = []
    go = threading.Event()
    d = _daemon(log, threading.Event(), go)
    d._recorder.stop = lambda: np.zeros(16000, dtype="float32")  # silent -> discarded
    go.set()
    d._on_hold_end()
    assert [k for k, _ in log] == ["release"]  # it ran, and _on_hold_end waited for it


def test_active_injector_waits_for_an_inflight_release():
    log: list = []
    go = threading.Event()
    d = _daemon(log, threading.Event(), go)
    d._release_hotkey_modifier_overlapped()
    go.set()
    d._active_injector().inject("x")
    assert [k for k, _ in log] == ["release", "inject"]


def test_with_streaming_partials_on_screen_the_release_stays_synchronous():
    log: list = []
    go = threading.Event()
    go.set()
    d = _daemon(log, threading.Event(), go)
    d._stream_injector = object()  # partials exist; a cancel bypasses _active_injector
    d._release_hotkey_modifier_overlapped()
    assert log == [("release", None)]  # already done on return: no thread involved
    assert d._hotkey_release_thread is None
