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
