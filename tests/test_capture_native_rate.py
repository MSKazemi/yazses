"""An input that refuses 16 kHz is captured at its own rate and converted.

A pinned device that only opens at, say, 48 kHz failed every recording with PortAudio's
"Invalid sample rate". No audio stack is touched: ``sounddevice`` is a fake throughout.
"""
from __future__ import annotations

import logging
import sys
import weakref

import numpy as np
import pytest

from yazses.audio import devices, recorder
from yazses.audio.devices import (
    InputDevice,
    fallback_sample_rates,
    is_sample_rate_refusal,
    open_at_supported_rate,
    reinit_portaudio,
)
from yazses.audio.recorder import AudioRecorder
from yazses.system import miclevel


class PortAudioError(Exception):
    """Shaped like ``sounddevice.PortAudioError``: ``(message, code)``."""


def _refusal() -> PortAudioError:
    return PortAudioError(
        "Error opening InputStream: Invalid sample rate [PaErrorCode -9997]", -9997
    )


def _busy() -> PortAudioError:
    return PortAudioError("Error opening InputStream: Device unavailable", -9985)


class _Stream:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.active = False
        self.closed = False

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    def close(self) -> None:
        self.closed = True

    def deliver(self, audio: np.ndarray, block: int = 960) -> None:
        for at in range(0, audio.size, block):
            data = audio[at : at + block].reshape(-1, 1)
            self.callback(data, data.shape[0], None, None)


class _SoundDevice:
    def __init__(self, accepts=(48000,), default_rate: float = 48000.0) -> None:
        self.accepts = set(accepts)
        self.default_rate = default_rate
        self.tried: list[int] = []
        self.queries: list[tuple] = []
        self.streams: list[_Stream] = []
        self.recorded: np.ndarray | None = None

    def _check(self, rate: int) -> None:
        self.tried.append(rate)
        if rate not in self.accepts:
            raise _refusal()

    def InputStream(self, *, samplerate, callback, **_kw) -> _Stream:
        self._check(samplerate)
        stream = _Stream(callback)
        self.streams.append(stream)
        return stream

    def rec(self, frames, *, samplerate, **_kw) -> np.ndarray:
        self._check(samplerate)
        self.recorded = np.full((frames, 1), 0.2, dtype=np.float32)
        return self.recorded

    def wait(self) -> None:
        pass

    def query_devices(self, *args, **_kw):
        self.queries.append(args)
        return {"name": "hw mic", "default_samplerate": self.default_rate}

    def _terminate(self) -> None:
        pass

    def _initialize(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _clean_registry(mocker):
    mocker.patch.object(devices, "_PA_USERS", weakref.WeakSet())
    mocker.patch.object(devices, "_reinit_failed", False)
    mocker.patch(
        "yazses.audio.devices.list_input_devices",
        return_value=[InputDevice(3, "hw mic", 1)],
    )


@pytest.fixture()
def sleep(mocker):
    return mocker.patch.object(recorder.time, "sleep")


def _install(mocker, monkeypatch, fake: _SoundDevice) -> _SoundDevice:
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    mocker.patch.object(recorder, "_sd", return_value=fake)
    return fake


# --- the pure rules --------------------------------------------------------------

def test_only_a_rate_refusal_counts():
    assert is_sample_rate_refusal(_refusal())
    assert is_sample_rate_refusal(RuntimeError("Invalid sample rate"))
    assert is_sample_rate_refusal(PortAudioError("localised text", -9997))
    assert not is_sample_rate_refusal(_busy())
    assert not is_sample_rate_refusal(RuntimeError())


def test_the_devices_own_rate_is_tried_first_and_never_twice():
    rates = fallback_sample_rates({"default_samplerate": 44100.0}, 16000)
    assert rates[0] == 44100
    assert len(rates) == len(set(rates)) and 16000 not in rates


@pytest.mark.parametrize("info", [None, {}, {"default_samplerate": None},
                                  {"default_samplerate": float("nan")},
                                  {"default_samplerate": 0}])
def test_an_unknown_device_rate_leaves_the_common_rates(info):
    assert fallback_sample_rates(info, 16000)[:2] == [48000, 44100]


def test_an_accepted_rate_does_not_query_the_device():
    def info():
        raise AssertionError("not needed")

    assert open_at_supported_rate(lambda rate: "s", 16000, info) == ("s", 16000)


def test_only_16_khz_is_ever_converted_to():
    """A refused ``[audio] sample_rate`` of 44100 is still reported, as before."""
    tried: list[int] = []

    def refuse(rate):
        tried.append(rate)
        raise _refusal()

    with pytest.raises(PortAudioError):
        open_at_supported_rate(refuse, 44100, lambda: None)
    assert tried == [44100]


def test_the_original_refusal_is_raised_when_nothing_is_accepted():
    original = _refusal()
    errors = iter([original])

    def never(rate):
        raise next(errors, _refusal())

    with pytest.raises(PortAudioError) as caught:
        open_at_supported_rate(never, 16000, lambda: None)
    assert caught.value is original


# --- the recorder ----------------------------------------------------------------

def test_a_pinned_mic_that_refuses_16k_records_at_its_rate(mocker, monkeypatch, sleep):
    fake = _install(mocker, monkeypatch, _SoundDevice(accepts=(48000,)))
    chunks: list[np.ndarray] = []
    rec = AudioRecorder(device="hw mic", on_chunk=chunks.append)
    rec.start()
    assert fake.tried == [16000, 48000]
    assert (3, "input") in fake.queries
    sleep.assert_not_called()  # no retry pause: speech would be lost during it

    fake.streams[-1].deliver(np.full(48000, 0.2, dtype=np.float32))
    assert all(c.ndim == 1 and c.dtype == np.float32 for c in chunks)
    streamed = sum(c.size for c in chunks)
    audio = rec.stop()

    assert audio.size == 16000, "one second in, one second out, filter tail included"
    assert 15900 < streamed <= 16000
    np.testing.assert_allclose(audio[200:-200], 0.2, atol=1e-4)
    assert rec.stream_stalled is False and rec.stream_interrupted is False
    assert fake.streams[-1].closed and reinit_portaudio(fake)


def test_a_device_that_takes_16k_is_opened_as_before(mocker, monkeypatch):
    fake = _install(mocker, monkeypatch, _SoundDevice(accepts=(16000,)))
    rec = AudioRecorder()
    rec.start()
    assert fake.tried == [16000]
    assert fake.streams[-1].callback == rec._callback
    fake.streams[-1].deliver(np.full(1600, 0.1, dtype=np.float32))
    assert rec.stop().size == 1600


def test_another_open_failure_never_changes_the_rate(mocker, monkeypatch, sleep):
    fake = _install(mocker, monkeypatch, _SoundDevice())
    opened = mocker.patch.object(fake, "InputStream", side_effect=_busy())
    with pytest.raises(RuntimeError, match="Could not open microphone"):
        AudioRecorder().start()
    assert {c.kwargs["samplerate"] for c in opened.call_args_list} == {16000}


def test_a_device_that_refuses_every_rate_names_the_refusal(mocker, monkeypatch, sleep):
    _install(mocker, monkeypatch, _SoundDevice(accepts=()))
    with pytest.raises(RuntimeError, match="Invalid sample rate"):
        AudioRecorder().start()


def test_the_next_recording_starts_clean_on_another_device(mocker, monkeypatch):
    fake = _install(mocker, monkeypatch, _SoundDevice(accepts=(44100,), default_rate=44100.0))
    rec = AudioRecorder()
    rec.start()
    fake.streams[-1].deliver(np.full(44100, 0.2, dtype=np.float32))
    assert rec.stop().size == 16000
    fake.accepts = {16000}
    rec.start()
    fake.streams[-1].deliver(np.full(800, 0.2, dtype=np.float32))
    assert rec.stop().size == 800


def test_the_cap_counts_converted_samples(mocker, monkeypatch):
    fake = _install(mocker, monkeypatch, _SoundDevice())
    rec = AudioRecorder(max_seconds=1)
    rec.start()
    fake.streams[-1].deliver(np.full(96000, 0.2, dtype=np.float32))
    audio = rec.stop()
    assert 15000 < audio.size <= 16000
    assert rec.truncated is True


def test_a_streaming_only_recorder_keeps_nothing_in_memory(mocker, monkeypatch):
    fake = _install(mocker, monkeypatch, _SoundDevice())
    chunks: list[np.ndarray] = []
    rec = AudioRecorder(accumulate=False, max_seconds=0, on_chunk=chunks.append)
    rec.start()
    fake.streams[-1].deliver(np.full(4800, 0.2, dtype=np.float32))
    assert rec.stop().size == 0
    assert sum(c.size for c in chunks) > 1500


def test_the_conversion_is_announced_once(mocker, monkeypatch, caplog):
    _install(mocker, monkeypatch, _SoundDevice())
    rec = AudioRecorder()
    with caplog.at_level(logging.INFO, logger="yazses.audio.recorder"):
        for _ in range(3):
            rec.start()
            rec.stop()
    said = [r for r in caplog.records
            if r.levelno == logging.INFO and "resampling" in r.getMessage()]
    assert len(said) == 1 and "48000" in said[0].getMessage()


# --- a stalled stream ------------------------------------------------------------

@pytest.fixture()
def clock(mocker):
    now = [100.0]
    mocker.patch.object(recorder.time, "monotonic", lambda: now[0])
    return now


@pytest.mark.parametrize("rate", [16000, 48000])
def test_a_stream_that_delivers_nothing_is_stalled(mocker, monkeypatch, clock, rate):
    _install(mocker, monkeypatch, _SoundDevice(accepts=(rate,)))
    rec = AudioRecorder()
    rec.start()
    clock[0] += 2.0
    assert rec.stop().size == 0
    assert rec.stream_stalled is True


def test_a_quick_tap_is_not_a_stall(mocker, monkeypatch, clock):
    _install(mocker, monkeypatch, _SoundDevice(accepts=(16000,)))
    rec = AudioRecorder()
    rec.start()
    clock[0] += 0.2
    rec.stop()
    assert rec.stream_stalled is False


@pytest.mark.parametrize("rate", [16000, 48000])
def test_silence_that_was_delivered_is_not_a_stall(mocker, monkeypatch, clock, rate):
    """Even one tiny block, too small to yield a converted sample, shows a live stream."""
    fake = _install(mocker, monkeypatch, _SoundDevice(accepts=(rate,)))
    rec = AudioRecorder()
    rec.start()
    fake.streams[-1].deliver(np.zeros(16, dtype=np.float32))
    clock[0] += 2.0
    rec.stop()
    assert rec.stream_stalled is False


def test_a_lost_device_is_not_also_a_stall(mocker, monkeypatch, clock):
    fake = _install(mocker, monkeypatch, _SoundDevice(accepts=(16000,)))
    rec = AudioRecorder()
    rec.start()
    fake.streams[-1].active = False
    clock[0] += 2.0
    rec.stop()
    assert rec.stream_interrupted is True and rec.stream_stalled is False


def test_the_stall_flag_resets_on_the_next_start(mocker, monkeypatch, clock):
    _install(mocker, monkeypatch, _SoundDevice(accepts=(16000,)))
    rec = AudioRecorder()
    rec.start()
    clock[0] += 2.0
    rec.stop()
    rec.start()
    assert rec.stream_stalled is False
    rec.stop()


# --- mic-level / re-calibrate ----------------------------------------------------

def test_mic_level_recording_converts_to_the_requested_rate(monkeypatch, mocker):
    fake = _install(mocker, monkeypatch, _SoundDevice())
    audio = miclevel.record(0.5, 16000, device="hw mic")
    assert fake.tried == [16000, 48000]
    assert fake.recorded is not None and fake.recorded.shape[0] == 24000
    assert audio.shape == (8000,)
    np.testing.assert_allclose(audio[200:-200], 0.2, atol=1e-4)


def test_mic_level_recording_at_an_accepted_rate_is_untouched(monkeypatch, mocker):
    fake = _install(mocker, monkeypatch, _SoundDevice(accepts=(16000,)))
    audio = miclevel.record(0.25, 16000)
    assert fake.tried == [16000] and fake.queries == []
    np.testing.assert_array_equal(audio, np.full(4000, 0.2, dtype=np.float32))
