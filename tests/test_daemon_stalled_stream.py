"""A stalled input stream is reported as one, not as a quiet microphone."""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform


class _StalledRecorder:
    has_clip = True
    stream_interrupted = False
    stream_stalled = True
    current_device_name = "USB PnP Audio Device"
    device = None

    def stop(self) -> np.ndarray:
        return np.array([], dtype="float32")


def _daemon(mocker, *, notify: bool = True) -> Daemon:
    cfg = Config()
    cfg.streaming.enabled = False
    cfg = replace(cfg, audio=replace(cfg.audio, silent_streak_notify=notify,
                                     silent_streak_threshold=3, auto_heal_device=True))
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _StalledRecorder()
    d._engine = mocker.MagicMock(name="engine")
    d._injector = mocker.MagicMock(name="injector")
    d._padding_buffer = None
    d._corpus = mocker.MagicMock(name="corpus")
    d._adaptive_vad = mocker.MagicMock(name="adaptive_vad")
    # Never touch the host: no config.toml rewrite, no desktop toast, no device query.
    d._maybe_retune_threshold = mocker.MagicMock(name="retune")
    d._notify_mic = mocker.MagicMock(name="notify_mic")
    d._active_device_name = lambda: "USB PnP Audio Device"
    return d


def test_it_is_named_a_stall_and_teaches_the_gate_nothing(mocker):
    d = _daemon(mocker)
    d._on_hold_end()
    assert d._corpus.write.call_args[0][0]["discard_reason"] == "stream_stalled"
    d._engine.transcribe.assert_not_called()
    d._injector.inject.assert_not_called()
    d._adaptive_vad.observe_discard.assert_not_called()
    d._maybe_retune_threshold.assert_not_called()
    title, body = d._notify_mic.call_args[0]
    assert "no audio" in title
    assert "stalled" in body and "mic-level" not in body


def test_repeated_stalls_still_auto_heal_with_one_toast_each(mocker):
    d = _daemon(mocker)
    d._state.last_good_device = "Built-in Microphone"
    for _ in range(3):
        d._on_hold_end()
    assert d._recorder.device == "Built-in Microphone"
    assert d._silent_streak.streak == 3
    assert d._notify_mic.call_count == 3, "no second, generic 'isn't hearing you' toast"
    assert "Built-in Microphone" in d._notify_mic.call_args[0][1]
    assert all("mic-level" not in c[0][1] for c in d._notify_mic.call_args_list)


def test_the_notification_opt_out_is_respected(mocker):
    d = _daemon(mocker, notify=False)
    d._on_hold_end()
    d._notify_mic.assert_not_called()


def test_an_empty_clip_without_a_stall_is_still_silent(mocker):
    """A quick tap hands back no samples too; that path is unchanged."""
    d = _daemon(mocker)
    d._recorder.stream_stalled = False
    d._on_hold_end()
    assert d._corpus.write.call_args[0][0]["discard_reason"] == "silent"
