"""X11GrabHotkey: hold-start (a Timer thread) and hold-end (the listener thread) must not
overlap. A key-up that arrives while ``on_hold_start`` is still opening the microphone used
to run ``on_hold_end`` first and leave a live stream behind (daemon idle, mic open).

No Xlib and no sound device is touched -- only fakes -- so this runs on every platform.
"""
from __future__ import annotations

import queue
import sys
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


def test_hold_end_runs_only_after_hold_start_has_fully_returned():
    """Pins the hotkey's own serialisation (the recorder's generation check alone would
    also close the stream): with the key-up delivered while hold-start is blocked, the
    ordered log must show start finishing before end begins."""
    order: list[str] = []
    entered, release_open, ended = threading.Event(), threading.Event(), threading.Event()

    def hold_start(_leaked):
        order.append("start_begin")
        entered.set()
        release_open.wait(_WAIT)
        order.append("start_done")

    def hold_end():
        order.append("end")
        ended.set()

    hk = X11GrabHotkey("right_alt", 1, hold_start, hold_end)
    hk._handle_press()
    assert entered.wait(_WAIT)
    released = threading.Thread(target=hk._handle_release)
    released.start()
    # Unserialised, hold-end completes here while the open is pending; serialised, this
    # just times out. Only the resulting ORDER is asserted.
    ended.wait(0.3)
    release_open.set()
    released.join(_WAIT)
    assert not released.is_alive()
    assert ended.wait(_WAIT)
    assert order == ["start_begin", "start_done", "end"]


class _SpyLock:
    """A Lock that says when a thread other than the one that holds it has to wait."""

    def __init__(self, waiting: threading.Event) -> None:
        self._lock = threading.Lock()
        self._waiting = waiting

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if self._lock.acquire(blocking=False):
            return True
        self._waiting.set()
        return self._lock.acquire(blocking, timeout)

    def release(self) -> None:
        self._lock.release()


def _install_fake_xlib(monkeypatch, events: queue.Queue):
    x = types.SimpleNamespace(
        KeyPress=2, KeyRelease=3, AnyModifier=0x8000, GrabModeAsync=1,
        KeyPressMask=1, KeyReleaseMask=2,
    )
    xk = types.SimpleNamespace(string_to_keysym=lambda name: 1)

    class _Root:
        def grab_key(self, *a): pass
        def ungrab_key(self, *a): pass
        def change_attributes(self, **kw): pass

    class _Display:
        def screen(self): return types.SimpleNamespace(root=_Root())
        def keysym_to_keycode(self, keysym): return 50
        def flush(self): pass
        def close(self): pass
        def pending_events(self): return events.qsize()
        def next_event(self): return events.get_nowait()

    display = types.SimpleNamespace(Display=_Display)
    pkg = types.SimpleNamespace(X=x, XK=xk, display=display)
    for name, mod in (("Xlib", pkg), ("Xlib.X", x), ("Xlib.XK", xk), ("Xlib.display", display)):
        monkeypatch.setitem(sys.modules, name, mod)
    return x


def test_stop_during_a_blocked_hold_start_lets_run_return(monkeypatch):
    """The listener thread must not be parked on the hotkey lock while the microphone
    opens: stop() has to be able to end run() (else the daemon cannot shut down)."""
    events: queue.Queue = queue.Queue()
    x = _install_fake_xlib(monkeypatch, events)
    entered, never_set, waiting = threading.Event(), threading.Event(), threading.Event()
    ended: list[int] = []

    def hold_start(_leaked):
        entered.set()
        never_set.wait(_WAIT)  # recorder.start() stuck opening the device

    hk = X11GrabHotkey("right_alt", 1, hold_start, lambda: ended.append(1))
    hk._lock = _SpyLock(waiting)  # type: ignore[assignment]
    runner = threading.Thread(target=hk.run, daemon=True)
    runner.start()
    try:
        events.put(types.SimpleNamespace(type=x.KeyPress, detail=50))
        assert entered.wait(_WAIT), "hold-start never began"
        events.put(types.SimpleNamespace(type=x.KeyRelease, detail=50))
        assert waiting.wait(_WAIT), "the listener never reached the lock"
        hk.stop()
        runner.join(_WAIT)
        assert not runner.is_alive(), "run() did not return: the listener is stuck on the lock"
        assert ended == []  # the abandoned release did not run hold-end behind start's back
    finally:
        never_set.set()  # free the Timer thread whatever happened
        runner.join(_WAIT)
