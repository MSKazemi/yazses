"""Daemon auto-heal + notify wiring for audio-input trouble.

Drives the resilience hooks directly (no model / no real mic) to prove: a run of
silent-discards switches capture back to the last-good device and notifies once; a
good capture resets the streak and records the device; the default-device-change
callback notifies and updates status.
"""
from __future__ import annotations

from dataclasses import replace

from yazses.config import AudioConfig, Config
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request
from yazses.platform import get_platform


class _FakeRecorder:
    def __init__(self, name="USB PnP Audio Device"):
        self.device = None
        self.current_device_name = name


def _daemon(mocker, audio: AudioConfig | None = None):
    cfg = Config()
    if audio is not None:
        cfg = replace(cfg, audio=audio)
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder()
    # Never touch a real notifier in tests.
    d._notify_mic = mocker.MagicMock()
    return d


def test_good_capture_records_last_good_and_resets(mocker):
    d = _daemon(mocker)
    d._silent_streak.record_silent()
    d._note_good_capture()
    assert d._silent_streak.streak == 0
    assert d._state.last_good_device == "USB PnP Audio Device"
    assert d._state.input_device == "USB PnP Audio Device"


def test_silent_streak_auto_heals_to_last_good(mocker):
    d = _daemon(
        mocker,
        AudioConfig(silent_streak_threshold=3, auto_heal_device=True, silent_streak_notify=True),
    )
    # Establish a last-good device via a prior success.
    d._recorder.current_device_name = "AT Translated Set 2 keyboard"
    d._note_good_capture()
    # The default flipped to a dead monitor input; now three silent clips in a row.
    d._recorder.device = "monitor audio"
    d._state.input_device = "monitor audio"
    d._note_silent_discard()
    d._note_silent_discard()
    assert d._recorder.device == "monitor audio"  # not yet at threshold
    assert d._notify_mic.call_count == 0
    d._note_silent_discard()  # 3rd -> heal + notify
    assert d._recorder.device == "AT Translated Set 2 keyboard"
    assert d._notify_mic.call_count == 1
    # Further silent clips in the same streak don't re-fire.
    d._note_silent_discard()
    assert d._notify_mic.call_count == 1


def test_silent_streak_notifies_without_last_good(mocker):
    d = _daemon(
        mocker,
        AudioConfig(silent_streak_threshold=2, auto_heal_device=True, silent_streak_notify=True),
    )
    d._note_silent_discard()
    d._note_silent_discard()
    # No last-good device known → can't heal, but the user is still told.
    assert d._notify_mic.call_count == 1
    assert d._state.last_good_device is None


def test_silent_streak_notify_can_be_disabled(mocker):
    d = _daemon(
        mocker,
        AudioConfig(silent_streak_threshold=1, auto_heal_device=False, silent_streak_notify=False),
    )
    d._note_silent_discard()
    assert d._notify_mic.call_count == 0


def test_default_device_change_notifies_and_updates_status(mocker):
    d = _daemon(mocker)
    d._on_default_device_changed("MicA", "MicB")
    assert d._state.input_device == "MicB"
    assert d._state.device_changed_at is not None
    assert d._notify_mic.call_count == 1


def test_status_exposes_audio_health(mocker):
    d = _daemon(mocker)
    d._note_good_capture()
    d._state.ready = True
    status = d._handle_status(Request(id=1, method="status", params={}))
    assert status["last_good_device"] == "USB PnP Audio Device"
    assert status["input_device"] == "USB PnP Audio Device"
    assert status["silent_streak"] == 0
