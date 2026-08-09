"""TrayController maps menu actions to daemon IPC calls / subprocess (all injected)."""
from yazses.tray.controller import TrayController


class _FakeClient:
    def __init__(self, reply=None):
        self.calls = []
        self._reply = reply or {"ok": True}

    def call(self, method, **params):
        self.calls.append((method, params))
        return self._reply


def test_pin_calls_pin_mic():
    c = _FakeClient({"ok": True, "device": "USB"})
    ctrl = TrayController(c)
    res = ctrl.pin("USB")
    assert c.calls == [("pin_mic", {"device": "USB"})]
    assert res == {"ok": True, "device": "USB"}


def test_unpin_pins_empty():
    c = _FakeClient()
    TrayController(c).unpin()
    assert c.calls == [("pin_mic", {"device": ""})]


def test_recalibrate_calls_recalibrate_mic():
    c = _FakeClient({"ok": True, "started": True})
    TrayController(c).recalibrate()
    assert c.calls == [("recalibrate_mic", {})]


def test_stop_daemon_calls_shutdown():
    c = _FakeClient()
    TrayController(c).stop_daemon()
    assert c.calls == [("shutdown", {})]


def test_restart_shells_out_to_cli():
    spawned = []
    ctrl = TrayController(_FakeClient(), launcher=lambda argv: spawned.append(argv))
    ctrl.restart()
    assert spawned == [["yazses", "restart"]]


def test_launch_settings_shells_out_to_cli():
    spawned = []
    ctrl = TrayController(_FakeClient(), launcher=lambda argv: spawned.append(argv))
    assert ctrl.launch_settings() is True
    assert spawned == [["yazses", "settings"]]


def test_launch_settings_does_not_raise_when_launch_fails():
    def _boom(argv):
        raise OSError("no such file")

    ctrl = TrayController(_FakeClient(), launcher=_boom)
    # Must not raise — the tray stays responsive — but must report the failure, so the
    # click is not silently swallowed and left looking like a frozen menu.
    assert ctrl.launch_settings() is False


def test_restart_reports_whether_the_launch_happened():
    def _boom(argv):
        raise OSError("no such file")

    assert TrayController(_FakeClient(), launcher=lambda argv: None).restart() is True
    assert TrayController(_FakeClient(), launcher=_boom).restart() is False


def test_status_returns_dict_and_swallows_errors():
    class _Boom:
        def call(self, *a, **k):
            raise RuntimeError("unreachable")

    assert TrayController(_Boom()).status() == {}


def test_call_wraps_failure():
    class _Boom:
        def call(self, *a, **k):
            raise RuntimeError("nope")

    res = TrayController(_Boom()).pin("X")
    assert res["ok"] is False and "nope" in res["error"]
