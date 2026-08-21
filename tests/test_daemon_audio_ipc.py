"""Daemon IPC methods that back the tray: pin_mic + recalibrate_mic."""
from __future__ import annotations

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request
from yazses.platform import get_platform
from yazses.platform.base import TrayState


class _FakeRecorder:
    def __init__(self):
        self.device = None
        self.current_device_name = None


def _daemon(mocker):
    d = Daemon(config=Config(), platform=get_platform())
    d._recorder = _FakeRecorder()
    d._notify_mic = mocker.MagicMock()
    mocker.patch("yazses.system.configedit.set_config_key", return_value="ok")
    return d


def test_pin_mic_applies_live_and_writes_config(mocker):
    d = _daemon(mocker)
    from yazses.system import configedit

    res = d._handle_pin_mic(Request(method="pin_mic", params={"device": "USB"}, id=1))
    assert res == {"ok": True, "device": "USB"}
    assert d._recorder.device == "USB"
    assert d._config.audio.device == "USB"
    assert d._state.input_device == "USB"
    configedit.set_config_key.assert_called_once()
    section, key, value = configedit.set_config_key.call_args.args[1:4]
    assert (section, key, value) == ("audio", "device", "USB")


def test_pin_mic_empty_unpins(mocker):
    d = _daemon(mocker)
    d._recorder.device = "USB"
    res = d._handle_pin_mic(Request(method="pin_mic", params={"device": ""}, id=1))
    assert res == {"ok": True, "device": ""}
    assert d._recorder.device is None           # follow OS default
    assert d._config.audio.device == ""
    assert d._state.input_device is None


def test_recalibrate_mic_starts_when_idle(mocker):
    d = _daemon(mocker)
    d._state.state = TrayState.IDLE
    recal = mocker.patch.object(d, "_recalibrate_mic")
    res = d._handle_recalibrate_mic(Request(method="recalibrate_mic", params={}, id=1))
    assert res == {"ok": True, "started": True}
    # The worker thread runs _recalibrate_mic; give it a beat to be invoked.
    import time as _t

    for _ in range(50):
        if recal.called:
            break
        _t.sleep(0.01)
    assert recal.called


def test_recalibrate_mic_refused_when_busy(mocker):
    d = _daemon(mocker)
    d._state.state = TrayState.RECORDING
    recal = mocker.patch.object(d, "_recalibrate_mic")
    res = d._handle_recalibrate_mic(Request(method="recalibrate_mic", params={}, id=1))
    assert res["ok"] is False and "busy" in res["reason"]
    recal.assert_not_called()


# ---- Notification relay to the tray (Windows / macOS have no libnotify) ----


def test_status_drains_queued_notifications():
    """The daemon holds toasts it cannot show, and `status` hands them over once.

    On Windows and macOS `notify-send` does not exist, so the mic auto-heal, VAD
    retunes and silent-streak warnings were written to a log file and nowhere
    else. The tray is already polling `status`, so that is the delivery channel.
    """
    d = Daemon(config=Config(), platform=get_platform())
    d._queue_notification("Microphone changed", "Switched back to your USB mic.")

    first = d._handle_status(Request(method="status", params={}, id=1))
    assert first["notifications"] == [
        {"title": "Microphone changed", "body": "Switched back to your USB mic."}
    ]
    # Drained: a toast must not be shown again on the next poll (once a second).
    second = d._handle_status(Request(method="status", params={}, id=2))
    assert second["notifications"] == []


def test_the_pending_queue_is_bounded_and_keeps_the_newest():
    """A quit tray must not make the daemon accumulate toasts for the session.

    Oldest are dropped: these are status messages, so "your mic came back" now
    beats the tenth copy of something from ten minutes ago.
    """
    from yazses.core.daemon import _MAX_PENDING_NOTIFICATIONS

    d = Daemon(config=Config(), platform=get_platform())
    for i in range(_MAX_PENDING_NOTIFICATIONS + 5):
        d._queue_notification("t", f"body {i}")

    out = d._handle_status(Request(method="status", params={}, id=1))["notifications"]
    assert len(out) == _MAX_PENDING_NOTIFICATIONS
    assert out[-1]["body"] == f"body {_MAX_PENDING_NOTIFICATIONS + 4}"  # newest kept
    assert out[0]["body"] == "body 5"                                   # oldest dropped
