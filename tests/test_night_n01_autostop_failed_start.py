"""A tap whose microphone failed to open must not latch a hands-free turn.

With `[autostop]` on, a short press latches the turn open and the release is swallowed so
the recording continues. When `_on_hold_start` could not open the microphone there is no
recording to continue, yet the release was still swallowed. `_on_hold_end` never ran, so:

* the streaming decode loop was never asked to stop (one Whisper decode per interval, for
  the rest of the process -- the leak `_on_hold_end`'s own comment describes);
* for the dedicated command key, `_command_mode` survived into the user's next ordinary
  dictation, which was then classified as a command and typed nothing.

Nothing here opens a microphone, a keyboard device or a thread that outlives a test.
"""
from __future__ import annotations

import threading

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.platform.base import TrayState


class _Earcon:
    def __init__(self) -> None:
        self.played: list[str] = []

    def play(self, name: str) -> None:
        self.played.append(name)


class _FailingRecorder:
    """A recorder whose device cannot be opened; it never holds a clip."""

    has_clip = False

    def __init__(self, fail: bool = True) -> None:
        self.fail = fail
        self.started = 0

    def start(self) -> None:
        if self.fail:
            raise RuntimeError("PortAudio: device unavailable")
        self.started += 1

    def stop(self) -> np.ndarray:
        return np.zeros(0, dtype=np.float32)


class _Engine:
    def transcribe(self, *args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("a burst that never recorded was transcribed")


class _Injector:
    def __init__(self) -> None:
        self.backspaces = 0

    def inject(self, text):  # pragma: no cover - must not be reached
        raise AssertionError(f"typed {text!r} for a burst that never recorded")

    def inject_backspaces(self, count):
        self.backspaces += count

    def inject_key_sequence(self, keys):  # pragma: no cover
        pass


class _StreamEngine:
    def __init__(self) -> None:
        self.started = 0
        self.stop_requests = 0

    def start(self) -> None:
        self.started += 1

    def push(self, chunk) -> None:  # pragma: no cover - padding is disabled
        pass

    def get_partial(self):
        return None

    def request_stop(self) -> None:
        self.stop_requests += 1


def _daemon(monkeypatch, *, fail: bool = True, streaming: bool = False) -> Daemon:
    cfg = Config()
    cfg.autostop.enabled = True
    cfg.streaming.enabled = streaming
    d = Daemon(config=cfg, platform=get_platform())
    d._autostop = d._build_autostop(cfg)
    d._earcon = _Earcon()
    d._recorder = _FailingRecorder(fail=fail)
    d._engine = _Engine()
    d._injector = _Injector()
    d._padding_buffer = None
    d._endpoint = None
    d._detect_target_async = lambda: None
    d._prefetch_stt_engine = lambda: None
    failures: list[object] = []
    d._report_failure = lambda exc, *a, **k: failures.append(exc)
    d._test_failures = failures  # type: ignore[attr-defined]
    watchers: list[bool] = []
    watched = threading.Event()

    def _watch() -> None:  # runs on the "autostop-watch" thread
        watchers.append(True)
        watched.set()

    monkeypatch.setattr(d, "_autostop_watch", _watch)
    d._test_watchers = watchers  # type: ignore[attr-defined]
    d._test_watched = watched  # type: ignore[attr-defined]
    with d._lock:
        d._state.state = TrayState.IDLE
    return d


def _tap(monkeypatch, start, end) -> None:
    """Press at t=0.0 and release 100 ms later: a tap by any hold threshold."""
    monkeypatch.setattr("yazses.core.daemon.time.monotonic", lambda: 0.0)
    start(0)
    monkeypatch.setattr("yazses.core.daemon.time.monotonic", lambda: 0.1)
    end()


def test_a_tap_on_a_failed_microphone_does_not_latch_the_turn(monkeypatch):
    d = _daemon(monkeypatch)
    _tap(monkeypatch, d._on_hold_start, d._on_hold_end)
    assert len(d._test_failures) == 1, "the user was not told the microphone failed"
    assert d._autostop.latched is False, "a turn latched open with no recording behind it"
    assert d._test_watchers == [], "a watcher was started for a burst that never began"
    assert d._state.state == TrayState.IDLE


def test_a_failed_command_tap_does_not_leave_command_mode_armed(monkeypatch):
    d = _daemon(monkeypatch)
    _tap(monkeypatch, d._on_command_hold_start, d._on_command_hold_end)
    assert d._command_mode is False, (
        "the next ordinary dictation would be classified as a command"
    )


def test_a_failed_start_stops_the_streaming_decode_loop_it_started(monkeypatch):
    d = _daemon(monkeypatch, streaming=True)
    engine = _StreamEngine()
    d._stream_engine = engine
    monkeypatch.setattr("yazses.core.daemon.time.monotonic", lambda: 0.0)
    d._on_hold_start(0)
    assert engine.started == 1
    # Before any release: the handler that started the loop also stops it.
    assert engine.stop_requests >= 1, "the decode loop was left spinning"
    assert d._stream_injector is None, "a dead burst's injector was kept for the next one"
    if d._poll_thread is not None:
        d._poll_thread.join(timeout=5)
        assert not d._poll_thread.is_alive()


def test_a_tap_on_a_working_microphone_still_latches(monkeypatch):
    d = _daemon(monkeypatch, fail=False)
    _tap(monkeypatch, d._on_hold_start, d._on_hold_end)
    assert d._recorder.started == 1
    assert d._state.state == TrayState.RECORDING
    assert d._autostop.latched is True
    assert d._test_watched.wait(timeout=5)
    assert d._test_watchers == [True]


def test_a_failure_does_not_disarm_the_next_working_tap(monkeypatch):
    d = _daemon(monkeypatch)
    _tap(monkeypatch, d._on_hold_start, d._on_hold_end)
    d._recorder.fail = False  # the user plugged the microphone back in
    _tap(monkeypatch, d._on_hold_start, d._on_hold_end)
    assert d._autostop.latched is True
    assert d._test_watched.wait(timeout=5)
    assert d._test_watchers == [True]
