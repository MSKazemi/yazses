"""#578: a stop() that reaches the macOS hotkey before its run loop runs is not lost.

The daemon checks its own stop flag right before ``hotkey.run()``, but ``run()`` then
asks for Input Monitoring and creates the tap before it blocks in the run loop. An IPC
``shutdown`` (the tray's Quit) landing in that window called ``CFRunLoopStop`` on a loop
that was not running yet. CoreFoundation keeps a stop request in per-run state that the
next run starts fresh, so ``CFRunLoopRun()`` then blocked for good: the daemon outlived
Quit and kept the permission it had read at start.

Nothing here has run on a real Mac. ``Quartz`` is a stand-in that models exactly the one
property the bug turns on -- a ``CFRunLoopStop`` sent while no run is in progress is
forgotten -- so the suite runs on Linux. That model is read from the open-source
CFRunLoop.c, not observed on macOS.
"""

from __future__ import annotations

import sys
import threading
import types

import pytest

import yazses.platform.macos.hotkey as hotkey_mod
from yazses.platform.macos.hotkey import MacosHotkey, run_loop_until_stopped

_FINISHED, _STOPPED, _TIMED_OUT = 1, 2, 3


class _FakeQuartz(types.ModuleType):
    """The CoreGraphics / CoreFoundation names ``MacosHotkey.run`` and teardown use."""

    kCFRunLoopCommonModes = "common"
    kCFRunLoopDefaultMode = "default"
    kCFRunLoopRunFinished = _FINISHED
    kCFRunLoopRunStopped = _STOPPED
    kCFRunLoopRunTimedOut = _TIMED_OUT
    kCGEventFlagsChanged = 12
    kCGEventKeyDown = 10
    kCGEventKeyUp = 11
    kCGEventTapOptionListenOnly = 1
    kCGHeadInsertEventTap = 0
    kCGSessionEventTap = 1

    def __init__(self) -> None:
        super().__init__("Quartz")
        self._guard = threading.Lock()
        self._current_run: threading.Event | None = None  # per-run "stopped" state
        self.taps_created = 0
        self.tap_enabled: list[bool] = []
        self.sources_removed = 0
        self.on_enable = None  # hook: runs when the tap is enabled (start-up window)

    # -- tap and source ---------------------------------------------------------
    def CGEventMaskBit(self, bit):  # noqa: N802
        return 1 << bit

    def CGEventTapCreate(self, *args):  # noqa: N802
        self.taps_created += 1
        return object()

    def CFMachPortCreateRunLoopSource(self, *args):  # noqa: N802
        return object()

    def CFRunLoopGetCurrent(self):  # noqa: N802
        return "runloop"

    def CFRunLoopAddSource(self, *args):  # noqa: N802
        pass

    def CFRunLoopRemoveSource(self, *args):  # noqa: N802
        self.sources_removed += 1

    def CGEventTapEnable(self, tap, enabled):  # noqa: N802
        self.tap_enabled.append(bool(enabled))
        if enabled and self.on_enable is not None:
            self.on_enable()

    # -- run loop: a stop is remembered only by the run in progress -------------
    def _begin_run(self) -> threading.Event:
        with self._guard:
            self._current_run = threading.Event()
            return self._current_run

    def _end_run(self) -> None:
        with self._guard:
            self._current_run = None

    def CFRunLoopStop(self, rl):  # noqa: N802
        with self._guard:
            if self._current_run is not None:
                self._current_run.set()
            # No run in progress: the request is dropped, as the next run starts
            # with fresh per-run state.

    def CFRunLoopRun(self):  # noqa: N802
        stopped = self._begin_run()
        try:
            stopped.wait(10.0)  # bounded only so a failing test does not hang the suite
        finally:
            self._end_run()

    def CFRunLoopRunInMode(self, mode, seconds, return_after_source):  # noqa: N802
        stopped = self._begin_run()
        try:
            return _STOPPED if stopped.wait(seconds) else _TIMED_OUT
        finally:
            self._end_run()


@pytest.fixture
def quartz(monkeypatch):
    fake = _FakeQuartz()
    monkeypatch.setitem(sys.modules, "Quartz", fake)
    monkeypatch.setattr(hotkey_mod, "_request_input_monitoring", lambda: True)
    # Short passes keep the test fast; the property under test does not depend on it.
    monkeypatch.setattr(hotkey_mod, "_STOP_POLL_S", 0.05, raising=False)
    return fake


def _hotkey() -> MacosHotkey:
    return MacosHotkey("right_option", 300, lambda _t: None, lambda: None)


def _run_in_thread(hk: MacosHotkey) -> threading.Thread:
    t = threading.Thread(target=hk.run, name="fake-macos-hotkey", daemon=True)
    t.start()
    return t


def test_a_stop_before_run_means_run_returns_without_creating_a_tap(quartz):
    hk = _hotkey()
    hk.stop()
    t = _run_in_thread(hk)
    t.join(timeout=3.0)
    assert not t.is_alive(), "run() blocked although stop() had already been called"
    assert quartz.taps_created == 0


def test_a_stop_during_start_up_is_not_lost_and_the_tap_is_torn_down(quartz):
    hk = _hotkey()
    # The IPC shutdown lands after the tap exists but before the loop is running.
    quartz.on_enable = hk.stop
    t = _run_in_thread(hk)
    t.join(timeout=3.0)
    assert not t.is_alive(), "a stop() during start-up was lost; the daemon would outlive Quit"
    assert quartz.tap_enabled == [True, False]
    assert quartz.sources_removed == 1


def test_a_stop_while_running_still_ends_the_loop(quartz):
    hk = _hotkey()
    started = threading.Event()
    quartz.on_enable = started.set
    t = _run_in_thread(hk)
    assert started.wait(3.0)
    hk.stop()
    t.join(timeout=3.0)
    assert not t.is_alive()
    assert quartz.tap_enabled[-1] is False


def test_loop_reads_the_stop_flag_before_the_first_pass():
    calls: list[int] = []
    run_loop_until_stopped(
        lambda: calls.append(1) or _TIMED_OUT,
        lambda: True,
        exit_codes=frozenset({_FINISHED, _STOPPED}),
    )
    assert calls == []


def test_loop_ends_on_an_exit_code_and_keeps_going_on_a_timeout():
    codes = iter([_TIMED_OUT, _TIMED_OUT, _FINISHED, _TIMED_OUT])
    passes: list[int] = []

    def _once() -> int:
        code = next(codes)
        passes.append(code)
        return code

    run_loop_until_stopped(_once, lambda: False, exit_codes=frozenset({_FINISHED, _STOPPED}))
    assert passes == [_TIMED_OUT, _TIMED_OUT, _FINISHED]


def test_loop_notices_a_stop_flag_set_between_passes():
    flag = threading.Event()
    passes = 0

    def _once() -> int:
        nonlocal passes
        passes += 1
        if passes == 2:
            flag.set()  # a stop the run loop itself never saw
        return _TIMED_OUT

    run_loop_until_stopped(_once, flag.is_set, exit_codes=frozenset({_FINISHED, _STOPPED}))
    assert passes == 2
