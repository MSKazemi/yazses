"""X11GrabHotkey: hold-start (a Timer thread) and hold-end (the listener thread) must not
overlap. A key-up that arrives while ``on_hold_start`` is still opening the microphone used
to run ``on_hold_end`` first and leave a live stream behind (daemon idle, mic open).

No Xlib and no sound device is touched -- only fakes -- so this runs on every platform.
"""
from __future__ import annotations

import threading
import types

from yazses.audio import recorder as rec_mod
from yazses.audio.recorder import AudioRecorder
from yazses.platform.linux.hotkey_xgrab import X11GrabHotkey

_WAIT = 5.0


class _Stream:
    def __init__(self, gate: threading.Event, entered: threading.Event) -> None:
        self.gate, self.entered = gate, entered
        self.closed = False
        self.active = False

    def start(self) -> None:
        self.entered.set()
        self.gate.wait(_WAIT)
        self.active = True

    def stop(self) -> None:
        self.active = False

    def close(self) -> None:
        self.closed = True


def _recorder(monkeypatch, gate, entered):
    streams: list[_Stream] = []

    def make(**_kw):
        s = _Stream(gate, entered)
        streams.append(s)
        return s

    monkeypatch.setattr(rec_mod, "_sd", lambda: types.SimpleNamespace(InputStream=make))
    monkeypatch.setattr(AudioRecorder, "_resolve_device", lambda self: None)
    monkeypatch.setattr(AudioRecorder, "_opened_device_name", lambda self, i: "fake")
    return AudioRecorder(16000, 300), streams


def test_release_during_recorder_start_does_not_leave_a_live_stream(monkeypatch):
    gate, entered = threading.Event(), threading.Event()
    recorder, streams = _recorder(monkeypatch, gate, entered)
    ended, start_done = threading.Event(), threading.Event()

    def hold_start(_leaked):
        try:
            recorder.start()
        finally:
            start_done.set()

    def hold_end():
        recorder.stop()
        ended.set()

    hk = X11GrabHotkey("right_alt", 1, hold_start, hold_end)
    hk._handle_press()  # arms the real Timer (1 ms)
    assert entered.wait(_WAIT), "recorder.start() never reached stream.start()"

    # The key-up arrives on the listener thread while start() is still opening the mic.
    released = threading.Thread(target=hk._handle_release)
    released.start()
    # Without serialisation hold-end completes here, while the open is still pending;
    # with it, the release waits for the open, so this wait simply times out. Either way
    # nothing is asserted on the outcome of the wait -- it only lets the buggy order happen.
    ended.wait(0.3)
    gate.set()  # let the open finish
    released.join(_WAIT)
    assert not released.is_alive()
    assert ended.wait(_WAIT), "hold-end never ran"
    assert start_done.wait(_WAIT), "hold-start never returned"

    live = [s for s in streams if s.active and not s.closed]
    assert not live, "the microphone stream was left open after the key was released"
    assert recorder._stream is None
    assert not hk._recording


def test_stale_timer_cannot_start_a_recording_after_release():
    """A Timer whose press was already released (``cancel`` cannot stop a callback that
    has begun) must not start a recording that nothing will ever end."""
    starts: list[int] = []
    hk = X11GrabHotkey("right_alt", 10_000, starts.append, lambda: None)
    hk._handle_press()
    stale_gen = hk._press_gen
    hk._handle_release()
    hk._fire_hold_start(stale_gen)  # the Timer thread arrives late
    assert starts == []
    assert not hk._recording

    # ... and it cannot fire into a *newer* press either.
    hk._handle_press()
    hk._fire_hold_start(stale_gen)
    assert starts == []
    hk._handle_release()
    hk._cancel_timer()


def test_release_before_timer_fires_never_starts():
    starts: list[int] = []
    ends: list[int] = []
    hk = X11GrabHotkey("right_alt", 10_000, starts.append, lambda: ends.append(1))
    hk._handle_press()
    hk._handle_release()
    assert starts == [] and ends == []
    assert hk._press_time is None


def test_normal_hold_still_starts_then_ends():
    started, ended = threading.Event(), threading.Event()
    hk = X11GrabHotkey("right_alt", 1, lambda leaked: started.set(), ended.set)
    hk._handle_press()
    assert started.wait(_WAIT)
    hk._handle_release()
    assert ended.is_set()
