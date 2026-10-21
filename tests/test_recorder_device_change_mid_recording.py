"""QA-005: the input device changes (unplugged, switched) while the key is held.

What PortAudio does then depends on the host API, so the cases below are a *model* of
it, not a measurement: the stream stops calling back, its ``active`` flag drops to
False, and ``stop()`` on it may raise a ``PortAudioError``. The expected behaviour on
every one of those shapes is the same two things:

* **no crash** -- releasing the key must hand back whatever was captured before the
  change, and must not raise out of the hold-release hot path;
* **no silently empty transcript** -- a clip cut short by a dead stream must be
  distinguishable from a quiet microphone, or the daemon files it as ``silent``, tells
  the user to retune ``vad_threshold``, and feeds the 0.0 level into the adaptive gate
  that lowers and *persists* the threshold.

The recorder half is fixed here (``stream_interrupted``; ``close()`` survives a raising
``stop()``). The daemon half lives in ``core/daemon.py``, which this sprint does not
own, so it is pinned as a strict xfail naming the fix.

Every test patches ``recorder._sd`` (see ``tests/test_recorder.py``), so no audio stack,
microphone or `sounddevice` import is needed.
"""
from __future__ import annotations

import numpy as np
import pytest

from yazses.audio import recorder
from yazses.audio.recorder import AudioRecorder, _ended_on_its_own

SR = 16000


class PortAudioError(Exception):
    """Stand-in for ``sounddevice.PortAudioError`` (never imported here)."""


class _Stream:
    """A PortAudio input stream whose device can vanish mid-recording."""

    def __init__(self, *, stop_raises: bool = False) -> None:
        self.active = True
        self.closed = False
        self.stop_calls = 0
        self._stop_raises = stop_raises

    def start(self) -> None:
        self.active = True

    def lose_device(self) -> None:
        # What a hot-unplug looks like from the stream: no more callbacks, inactive.
        self.active = False

    def stop(self) -> None:
        self.stop_calls += 1
        if self._stop_raises:
            raise PortAudioError("Unanticipated host error [PaErrorCode -9999]")
        self.active = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def sd(mocker):
    fake = mocker.MagicMock(name="sounddevice")
    mocker.patch.object(recorder, "_sd", return_value=fake)
    mocker.patch.object(recorder.time, "sleep")
    return fake


def _speak(rec: AudioRecorder, seconds: float, value: float = 0.2) -> None:
    n = int(seconds * SR)
    rec._callback(np.full((n, 1), value, dtype=np.float32), n, None, None)


def test_device_lost_mid_recording_keeps_the_audio_before_it(sd):
    stream = _Stream(stop_raises=True)
    sd.InputStream.return_value = stream
    rec = AudioRecorder(sample_rate=SR)
    rec.start()
    _speak(rec, 0.5)
    stream.lose_device()

    audio = rec.stop()  # must not raise

    assert audio.shape[0] == int(0.5 * SR)
    assert rec.stream_interrupted is True


def test_a_raising_stop_still_closes_the_stream(sd):
    """The lost-device path is the one where stop() raises; close() must still run."""
    stream = _Stream(stop_raises=True)
    sd.InputStream.return_value = stream
    rec = AudioRecorder(sample_rate=SR)
    rec.start()
    _speak(rec, 0.2)
    stream.lose_device()
    rec.stop()
    assert stream.stop_calls == 1
    assert stream.closed is True, "PortAudio handle leaked: close() skipped after stop() raised"
    assert rec.has_clip is False


def test_device_lost_before_any_audio_is_flagged_not_just_empty(sd):
    """The case that becomes a silently empty transcript: nothing captured at all."""
    stream = _Stream()
    sd.InputStream.return_value = stream
    rec = AudioRecorder(sample_rate=SR)
    rec.start()
    stream.lose_device()
    audio = rec.stop()
    assert audio.size == 0
    assert rec.stream_interrupted is True


def test_a_normal_release_is_not_reported_as_a_lost_device(sd):
    stream = _Stream()
    sd.InputStream.return_value = stream
    rec = AudioRecorder(sample_rate=SR)
    rec.start()
    _speak(rec, 0.3)
    audio = rec.stop()
    assert audio.shape[0] == int(0.3 * SR)
    assert rec.stream_interrupted is False
    assert stream.closed is True


def test_the_flag_resets_on_the_next_start(sd):
    first, second = _Stream(), _Stream()
    sd.InputStream.side_effect = [first, second]
    rec = AudioRecorder(sample_rate=SR)
    rec.start()
    first.lose_device()
    rec.stop()
    assert rec.stream_interrupted is True
    rec.start()  # the replacement device
    assert rec.stream_interrupted is False
    _speak(rec, 0.1)
    rec.stop()
    assert rec.stream_interrupted is False


def test_overflow_status_during_a_device_switch_does_not_drop_the_chunk(sd):
    sd.InputStream.return_value = _Stream()
    rec = AudioRecorder(sample_rate=SR)
    rec.start()
    n = 1600
    rec._callback(np.full((n, 1), 0.1, dtype=np.float32), n, None, "input overflow")
    assert rec.stop().shape[0] == n


@pytest.mark.parametrize(
    "stream, expected",
    [
        (type("S", (), {"active": False})(), True),
        (type("S", (), {"active": True})(), False),
        (object(), False),                      # no attribute: a normal stop
        (type("S", (), {"active": 0})(), False),  # not a bool: never a lost device
    ],
)
def test_ended_on_its_own_only_trusts_an_explicit_false(stream, expected):
    assert _ended_on_its_own(stream) is expected


def test_a_mock_stream_is_never_read_as_a_lost_device(mocker, sd):
    """Every existing MagicMock-stream test must keep its old behaviour."""
    sd.InputStream.return_value = mocker.MagicMock()
    rec = AudioRecorder(sample_rate=SR)
    rec.start()
    _speak(rec, 0.1)
    rec.stop()
    assert rec.stream_interrupted is False


# ---- daemon half (core/daemon.py is held by another session) -------------------------

class _CutShortRecorder:
    """A recorder whose stream died before any audio arrived."""

    has_clip = True
    stream_interrupted = True
    current_device_name = "USB PnP Audio Device"
    device = None

    def stop(self) -> np.ndarray:
        return np.array([], dtype="float32")


def _daemon(mocker):
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = Config()
    cfg.streaming.enabled = False
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _CutShortRecorder()
    d._engine = mocker.MagicMock(name="engine")
    d._engine.transcribe.return_value = "should never be decoded"
    d._injector = mocker.MagicMock(name="injector")
    d._padding_buffer = None
    d._corpus = mocker.MagicMock(name="corpus")
    d._adaptive_vad = mocker.MagicMock(name="adaptive_vad")
    # Never touch the host: no config.toml rewrite, no desktop toast.
    d._maybe_retune_threshold = mocker.MagicMock(name="retune")
    d._notify_mic = mocker.MagicMock(name="notify_mic")
    return d


def test_daemon_survives_a_cut_short_clip_and_types_nothing(mocker):
    d = _daemon(mocker)
    d._on_hold_end()  # must not raise
    d._engine.transcribe.assert_not_called()
    d._injector.inject.assert_not_called()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-005 daemon half, held file: in core/daemon.py `_on_hold_end`, right after "
        "`audio = self._recorder.stop()`, when `getattr(self._recorder, "
        "'stream_interrupted', False)` is True set event['discard_reason'] = "
        "'device_lost', log/notify that the input device changed mid-recording, and "
        "return before `is_silent_calibrated` -- so the burst is not filed as 'silent' "
        "and its 0.0 level is not fed to `_adaptive_vad.observe_discard` / "
        "`_maybe_retune_threshold`. Add 'device_lost' to CAPTURE_DOUBTING_DISCARDS in "
        "audio/device_monitor.py in the same change."
    ),
)
def test_daemon_names_a_lost_device_instead_of_a_silent_mic(mocker):
    d = _daemon(mocker)
    d._on_hold_end()
    event = d._corpus.write.call_args[0][0]
    assert event["discard_reason"] == "device_lost"
    d._adaptive_vad.observe_discard.assert_not_called()
