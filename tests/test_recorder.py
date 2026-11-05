import numpy as np
import pytest

from yazses.audio import recorder
from yazses.audio.recorder import AudioRecorder


@pytest.fixture(autouse=True)
def _no_sleep(mocker):
    # Keep retry tests fast — don't actually wait between attempts.
    mocker.patch.object(recorder.time, "sleep")


@pytest.fixture()
def sd(mocker):
    """Stand in for the sounddevice module the recorder imports on first use.

    Patching `recorder._sd` rather than the real module keeps these tests runnable on a
    host with no audio system at all, where merely *importing* sounddevice raises
    (see tests/test_no_audio_device_is_not_an_import_error.py).
    """
    fake = mocker.MagicMock(name="sounddevice")
    mocker.patch.object(recorder, "_sd", return_value=fake)
    return fake


def _fake_stream(mocker):
    stream = mocker.MagicMock()
    return stream


def test_start_opens_stream_on_first_try(mocker, sd):
    stream = _fake_stream(mocker)
    sd.InputStream.return_value = stream
    rec = AudioRecorder()
    rec.start()
    sd.InputStream.assert_called_once()
    stream.start.assert_called_once()
    recorder.time.sleep.assert_not_called()


def test_start_retries_then_succeeds(mocker, sd):
    good = _fake_stream(mocker)
    # First two opens fail, third succeeds.
    sd.InputStream.side_effect = [
        RuntimeError("device busy"),
        RuntimeError("device busy"),
        good,
    ]
    rec = AudioRecorder()
    rec.start()
    assert sd.InputStream.call_count == 3
    good.start.assert_called_once()
    assert recorder.time.sleep.call_count == 2


def test_start_raises_after_all_attempts_fail(sd):
    sd.InputStream.side_effect = RuntimeError("device busy")
    rec = AudioRecorder()
    with pytest.raises(RuntimeError, match="Could not open microphone"):
        rec.start()


def test_stop_swallows_close_errors(mocker, sd):
    stream = _fake_stream(mocker)
    stream.stop.side_effect = RuntimeError("already closed")
    sd.InputStream.return_value = stream
    rec = AudioRecorder()
    rec.start()
    # Feed a chunk so stop() has audio to return.
    rec._callback(np.ones((10, 1), dtype=np.float32), 10, None, None)
    out = rec.stop()              # must not raise
    assert out.shape[0] == 10


def test_stop_during_start_closes_the_stream_it_was_opening(mocker, sd):
    """A stop() that runs while start() is still opening the device (the X11 key-up
    racing the hold timer) must not leave the microphone open."""
    rec = AudioRecorder()
    stream = _fake_stream(mocker)

    def start_then_stop_arrives():
        rec.stop()  # the key-up, landing while the device is still opening

    stream.start.side_effect = start_then_stop_arrives
    sd.InputStream.return_value = stream
    rec.start()
    stream.stop.assert_called_once()
    stream.close.assert_called_once()
    assert rec._stream is None
    assert not rec.has_clip


def test_start_after_start_closes_the_stream_it_would_orphan(mocker, sd):
    first, second = _fake_stream(mocker), _fake_stream(mocker)
    sd.InputStream.side_effect = [first, second]
    rec = AudioRecorder()
    rec.start()
    rec.start()  # no stop() between them
    first.close.assert_called_once()
    second.close.assert_not_called()
    assert rec._stream is second
