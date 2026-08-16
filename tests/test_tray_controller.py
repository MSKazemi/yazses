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


# These two used to assert the literal `["yazses", "restart"]`, which is exactly
# the spelling that made the tray's Settings button impossible on the Windows
# installer build — there is no `yazses` on PATH there. They now assert the
# *contract*: the verb is right and the argv is whatever `settings_command()`
# resolves for this install, whose own rules are pinned in
# tests/test_tray_settings_command.py.


def test_restart_shells_out_to_cli():
    from yazses.tray.launch import settings_command

    spawned = []
    ctrl = TrayController(_FakeClient(), launcher=lambda argv: spawned.append(argv))
    ctrl.restart()
    assert spawned == [settings_command("restart")]
    assert spawned[0][-1] == "restart"


def test_launch_settings_shells_out_to_cli():
    from yazses.tray.launch import settings_command

    spawned = []
    ctrl = TrayController(_FakeClient(), launcher=lambda argv: spawned.append(argv))
    assert ctrl.launch_settings() is True
    assert spawned == [settings_command()]
    # Asserts the *contract* — that the controller spawns whatever the resolver
    # returns — not the argv itself, which depends on how this machine is installed
    # and is covered by tests/test_system_relaunch.py. The literal "settings" was
    # only ever true while every path ended in that word; Settings now has its own
    # `yazses-settings` gui-script, so a frozen bundle ends in `--settings` and a
    # normal install ends in the script name.
    assert spawned[0][-1].endswith(("yazses-settings", "yazses-settings.exe", "--settings"))


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


# ---- help / about / updates ------------------------------------------------


def test_open_url_uses_the_injected_opener():
    opened = []
    ctrl = TrayController(_FakeClient(), opener=lambda url: opened.append(url) or True)
    assert ctrl.open_url("https://example.test/docs") is True
    assert opened == ["https://example.test/docs"]


def test_open_url_reports_a_failure_rather_than_raising():
    def _boom(_url):
        raise RuntimeError("no display")

    ctrl = TrayController(_FakeClient(), opener=_boom)
    assert ctrl.open_url("https://example.test/") is False
    assert TrayController(_FakeClient(), opener=lambda _u: False).open_url("x") is False


def test_check_updates_survives_a_dead_network(monkeypatch):
    """No network is the common case for an offline-first tool; it must not raise."""
    def _boom(_current, **_kw):
        raise OSError("name resolution failed")

    monkeypatch.setattr("yazses.system.updater.check_update", _boom)

    status = TrayController(_FakeClient()).check_updates()
    assert status.latest is None
    assert status.available is False
    assert "name resolution failed" in status.note


def test_check_updates_passes_the_running_version_through(monkeypatch):
    seen = {}

    def _fake(current, **_kw):
        seen["current"] = current
        from yazses.system.updater import UpdateStatus

        return UpdateStatus("uv", current, "9.9.9", True, ["uv", "tool", "upgrade", "yazses"])

    monkeypatch.setattr("yazses.system.updater.check_update", _fake)
    monkeypatch.setattr("yazses.branding.version", lambda: "1.2.3")

    status = TrayController(_FakeClient()).check_updates()
    assert seen["current"] == "1.2.3"
    assert status.latest == "9.9.9"


def test_install_update_runs_the_upgrade_and_verifies_the_version_moved(monkeypatch):
    from yazses.system.updater import UpdateStatus

    ran = []
    monkeypatch.setattr(
        "yazses.system.updater.run_upgrade", lambda s: ran.append(s.command) or 0
    )
    monkeypatch.setattr("yazses.system.updater.installed_version", lambda **kw: "2.0")
    status = UpdateStatus("uv", "1.0", "2.0", True, ["uv", "tool", "upgrade", "yazses"])

    outcome = TrayController(_FakeClient()).install_update(status)

    assert ran == [["uv", "tool", "upgrade", "yazses"]]
    assert outcome.ok and outcome.after == "2.0"


def test_install_update_does_not_call_a_pinned_no_op_a_success(monkeypatch):
    """Exit 0 with an unchanged version is the pinned-install case, not a success."""
    from yazses.system.updater import UpdateStatus

    monkeypatch.setattr("yazses.system.updater.run_upgrade", lambda s: 0)
    monkeypatch.setattr("yazses.system.updater.installed_version", lambda **kw: "1.0")
    status = UpdateStatus("uv", "1.0", "2.0", True, ["uv", "tool", "upgrade", "yazses"])

    outcome = TrayController(_FakeClient()).install_update(status)

    assert outcome.code == 0
    assert not outcome.changed
    assert not outcome.ok


def test_install_update_reports_a_failure_rather_than_raising(monkeypatch):
    def _boom(_status):
        raise OSError("uv is gone")

    monkeypatch.setattr("yazses.system.updater.run_upgrade", _boom)
    outcome = TrayController(_FakeClient()).install_update(object())
    assert outcome.code == 1
    assert not outcome.ok
