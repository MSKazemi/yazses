"""PortAudio is shared by the whole process, and re-initialising it closes every stream.

The device monitor re-initialises it every few seconds from its own thread. These tests
pin that it cannot do so under a recording or a playback, that an open and a
re-initialisation never overlap, and that one failed ``Pa_Initialize`` does not leave the
daemon deaf for good. No audio stack is touched: ``sounddevice`` is a fake throughout.
"""
from __future__ import annotations

import logging
import sys
import threading
import weakref

import numpy as np
import pytest

from yazses.audio import devices, recorder
from yazses.audio.device_monitor import DeviceMonitor
from yazses.audio.devices import portaudio_in_use, reinit_portaudio
from yazses.audio.recorder import AudioRecorder

_WAIT = 5.0


@pytest.fixture(autouse=True)
def _clean_registry(mocker):
    """Streams other tests left registered must not decide these ones."""
    mocker.patch.object(devices, "_PA_USERS", weakref.WeakSet())
    mocker.patch.object(devices, "_reinit_failed", False)
    mocker.patch.object(recorder.time, "sleep")


class _Stream:
    def __init__(self, *, start_raises: bool = False) -> None:
        self.active = False
        self.closed = False
        self._start_raises = start_raises

    def start(self) -> None:
        if self._start_raises:
            raise OSError("Device unavailable")
        self.active = True

    def stop(self) -> None:
        self.active = False

    def close(self) -> None:
        self.closed = True


class _PortAudio:
    """Enough of ``sounddevice``: the init ref-count and its "not initialized" error."""

    def __init__(self) -> None:
        self.initialized = True
        self.inits = 0
        self.init_failures = 0
        self.streams: list[_Stream] = []
        self.start_failures = 0

    def _terminate(self) -> None:
        if not self.initialized:
            raise OSError("PortAudio not initialized")
        self.initialized = False

    def _initialize(self) -> None:
        if self.init_failures:
            self.init_failures -= 1
            raise OSError("Error initializing PortAudio")
        self.initialized = True
        self.inits += 1

    def InputStream(self, **_kw) -> _Stream:
        if not self.initialized:
            raise OSError("PortAudio not initialized")
        stream = _Stream(start_raises=self.start_failures > 0)
        self.start_failures = max(0, self.start_failures - 1)
        self.streams.append(stream)
        return stream

    def query_devices(self, *_a, **_kw):
        return {"name": "Fake mic"}


@pytest.fixture()
def pa(mocker, monkeypatch):
    fake = _PortAudio()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    mocker.patch.object(recorder, "_sd", return_value=fake)
    return fake


# --- re-initialisation and its users --------------------------------------------

def test_one_failed_initialise_does_not_leave_the_microphone_dead_for_ever(pa, caplog):
    pa.init_failures = 2
    with caplog.at_level(logging.WARNING, logger="yazses.audio.devices"):
        assert reinit_portaudio() is False
        assert reinit_portaudio() is False
    assert len(caplog.records) == 1, "one warning per outage, not one per poll"
    # The audio service is back. terminate() raises "not initialized" now, and that
    # must not stop the initialise.
    assert reinit_portaudio() is True
    AudioRecorder().start()


def test_no_reinit_while_a_recording_stream_is_open(pa):
    rec = AudioRecorder()
    rec.start()
    assert reinit_portaudio() is False
    assert pa.inits == 0
    rec.stop()
    assert reinit_portaudio() is True


def test_no_reinit_during_playback_or_a_one_shot_recording(pa):
    with portaudio_in_use():
        with portaudio_in_use():
            assert reinit_portaudio() is False
        assert reinit_portaudio() is False
    assert reinit_portaudio() is True


def test_a_stream_replaced_by_a_second_start_is_released(pa):
    rec = AudioRecorder()
    rec.start()
    rec.start()
    rec.stop()
    assert reinit_portaudio() is True


def test_an_aborted_open_is_released(pa, mocker):
    rec = AudioRecorder()
    mocker.patch.object(_Stream, "start", lambda self: rec.stop())  # key-up mid-open
    rec.start()
    assert reinit_portaudio() is True


def test_a_reinit_cannot_run_while_a_stream_is_being_opened(pa, mocker):
    """The monitor asked "idle?" just before the key went down: it must still wait."""
    opening, finish = threading.Event(), threading.Event()
    results: list[bool] = []

    def slow_start(self) -> None:
        opening.set()
        finish.wait(_WAIT)
        self.active = True

    mocker.patch.object(_Stream, "start", slow_start)
    rec = AudioRecorder()
    opener = threading.Thread(target=rec.start)
    opener.start()
    assert opening.wait(_WAIT)
    monitor = threading.Thread(target=lambda: results.append(reinit_portaudio()))
    monitor.start()
    monitor.join(0.2)
    assert results == [], "the re-initialisation ran under a half-open stream"
    finish.set()
    opener.join(_WAIT)
    monitor.join(_WAIT)
    assert results == [False] and pa.inits == 0


# --- the recorder's open path ---------------------------------------------------

def test_a_stream_that_opens_but_will_not_start_is_closed(pa):
    pa.start_failures = 1
    rec = AudioRecorder()
    rec.start()
    first, second = pa.streams
    assert first.closed, "the unstarted stream still held the device"
    assert second.active and not second.closed
    rec.stop()
    assert reinit_portaudio() is True


def test_the_last_attempt_refreshes_a_stale_device_list(pa, mocker):
    """A replugged mic is invisible until PortAudio is re-initialised."""
    real = pa.InputStream

    def stale_until_reinit(**kw):
        if pa.inits == 0:
            raise OSError("Invalid device")
        return real(**kw)

    mocker.patch.object(pa, "InputStream", side_effect=stale_until_reinit)
    rec = AudioRecorder()
    rec.start()
    assert pa.inits == 1 and pa.streams[-1].active
    rec.stop()


def test_a_second_start_drops_audio_the_old_stream_delivered_while_closing(pa, mocker):
    rec = AudioRecorder()
    rec.start()

    def late_callback(self) -> None:
        rec._callback(np.ones((10, 1), dtype=np.float32), 10, None, None)

    mocker.patch.object(_Stream, "stop", late_callback)
    rec.start()
    mocker.patch.object(_Stream, "stop", lambda self: None)
    assert rec.stop().size == 0


def test_a_missing_pinned_mic_is_named_once(pa, mocker, caplog):
    mocker.patch("yazses.audio.devices.list_input_devices", return_value=[])
    rec = AudioRecorder(device="USB mic")
    with caplog.at_level(logging.WARNING, logger="yazses.audio.recorder"):
        for _ in range(3):
            rec.start()
            rec.stop()
    warned = [r for r in caplog.records if "was not found" in r.getMessage()]
    assert len(warned) == 1 and "USB mic" in warned[0].getMessage()


# --- hands-free streams that would not reopen -----------------------------------

class _Owner:
    """A level stream whose microphone is gone for the first ``failures`` reopens."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.mic_open = True
        self.mic_engaged = False
        self.reacquires = 0

    def release_mic_for_rescan(self) -> bool:
        was, self.mic_open = self.mic_open, False
        return was

    def reacquire_mic_after_rescan(self):
        self.reacquires += 1
        if self.failures:
            self.failures -= 1
            return False, "could not open the microphone"
        self.mic_open = True
        return True, ""


def test_the_monitor_retries_a_level_stream_that_would_not_reopen():
    owner, now = _Owner(failures=2), [0.0]
    monitor = DeviceMonitor(
        poll_fn=lambda: "Mic", is_idle=lambda: not owner.mic_open,
        on_change=lambda *_: None, level_streams=lambda: [owner],
        recording=lambda: False, clock=lambda: now[0], rescan_every_s=30.0,
    )
    now[0] = 30.0
    monitor.poll_once()  # cycle: released, reopen fails
    assert owner.reacquires == 1 and not owner.mic_open
    now[0] = 33.0
    monitor.poll_once()  # not due yet
    assert owner.reacquires == 1
    now[0] = 60.0
    monitor.poll_once()  # fails again
    now[0] = 90.0
    monitor.poll_once()
    assert owner.reacquires == 3 and owner.mic_open
    now[0] = 93.0
    monitor.poll_once()
    assert owner.reacquires == 3, "nothing left to retry"


def test_the_monitor_does_not_retry_during_a_recording():
    owner, now, recording = _Owner(failures=1), [30.0], [False]
    monitor = DeviceMonitor(
        poll_fn=lambda: "Mic", is_idle=lambda: not owner.mic_open,
        on_change=lambda *_: None, level_streams=lambda: [owner],
        recording=lambda: recording[0], clock=lambda: now[0], rescan_every_s=30.0,
    )
    now[0] = 60.0
    monitor.poll_once()
    recording[0], now[0] = True, 120.0
    monitor.poll_once()
    assert owner.reacquires == 1


class _FlakyRecorder:
    """The runner's recorder: ``broken[0]`` says whether a microphone can be opened."""

    def __init__(self, broken: list[bool]) -> None:
        self._broken = broken

    def start(self) -> None:
        if self._broken[0]:
            raise RuntimeError("Could not open microphone")

    def stop(self):
        return np.zeros(0, dtype=np.float32)


def test_a_morse_listener_is_still_owed_a_reopen_after_a_failed_one():
    import types

    from yazses.morsevox.runtime import build_morse_runner

    broken = [False]
    cfg = types.SimpleNamespace(
        enabled=True, dot_max_ms=200.0, letter_gap_ms=600.0, word_gap_ms=1400.0,
        entry_hum_s=1.5, exit_silence_s=3.0,
    )
    runner, notes = build_morse_runner(
        cfg, threshold=0.02, recorder_factory=lambda _cb: _FlakyRecorder(broken),
        inject=lambda _text: None, thread=False,
    )
    assert runner is not None, notes
    runner.start()
    assert runner.release_mic_for_rescan() is True
    broken[0] = True  # unplugged
    assert runner.reacquire_mic_after_rescan()[0] is False
    broken[0] = False  # plugged back in
    assert runner.reacquire_mic_after_rescan() == (True, "")
    assert runner.mic_open


def test_a_pause_cancels_the_owed_reopen():
    import types

    from yazses.morsevox.runtime import build_morse_runner

    broken = [False]
    cfg = types.SimpleNamespace(
        enabled=True, dot_max_ms=200.0, letter_gap_ms=600.0, word_gap_ms=1400.0,
        entry_hum_s=1.5, exit_silence_s=3.0,
    )
    runner, notes = build_morse_runner(
        cfg, threshold=0.02, recorder_factory=lambda _cb: _FlakyRecorder(broken),
        inject=lambda _text: None, thread=False,
    )
    assert runner is not None, notes
    runner.start()
    runner.release_mic_for_rescan()
    broken[0] = True
    runner.reacquire_mic_after_rescan()
    broken[0] = False
    runner.toggle("pause", [], [])
    runner.reacquire_mic_after_rescan()
    assert not runner.mic_open
