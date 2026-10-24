"""`yazses restart` run from inside the daemon's own service must outlive the stop.

The tray starts Settings, Settings runs `yazses restart`, and the tray is a child of the
daemon -- so that `restart` sits in the `yazses.service` cgroup. Its first step is
`systemctl --user stop yazses`, and systemd kills every process in the unit's cgroup (the
default `KillMode=control-group`), `setsid` or not. The restart died between its "stop" and
its "start", and the daemon stayed down: `Restart=on-failure` does not revive a clean exit.

The fix moves the command into a `systemd-run --scope` of its own, and the tray starts
Settings (and its Restart item) the same way, so the window outlives the restart too.
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.system import service_escape

runner = CliRunner()

UNIT = "yazses.service"
V2_IN_UNIT = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/yazses.service\n"
V2_IN_SESSION = (
    "0::/user.slice/user-1000.slice/user@1000.service/app.slice/"
    "app-gnome-gnome\\x2dterminal-4242.scope\n"
)
V1_IN_UNIT = (
    "12:cpu,cpuacct:/user.slice\n"
    "1:name=systemd:/user.slice/user-1000.slice/user@1000.service/app.slice/yazses.service\n"
)


# ---- the pure decision ------------------------------------------------------


def test_cgroup_v2_path_of_the_unit_is_inside():
    assert service_escape.inside_unit_cgroup(V2_IN_UNIT, UNIT)


def test_cgroup_v1_systemd_hierarchy_line_is_inside():
    assert service_escape.inside_unit_cgroup(V1_IN_UNIT, UNIT)


def test_a_terminal_scope_is_not_inside():
    assert not service_escape.inside_unit_cgroup(V2_IN_SESSION, UNIT)


@pytest.mark.parametrize(
    "path",
    [
        "0::/app.slice/yazses.service.d\n",         # a different component that merely starts with it
        "0::/app.slice/not-yazses.service\n",       # one that merely ends with it
        "0::/app.slice/yazses-tray.service\n",
        "",                                          # unreadable / empty
        "garbage without a colon\n",
    ],
)
def test_lookalikes_and_junk_are_not_inside(path):
    assert not service_escape.inside_unit_cgroup(path, UNIT)


def test_scope_argv_is_a_scope_so_environment_stdio_and_exit_code_survive():
    argv = service_escape.scope_argv(["/x/yazses", "restart", "--force"])
    assert argv[0] == "systemd-run"
    assert argv[-3:] == ["/x/yazses", "restart", "--force"]
    # A scope, not a service: a service would drop DISPLAY / WAYLAND_DISPLAY and the
    # caller's stdio, and the exit code would need --wait --pipe to come back at all.
    assert "--scope" in argv and "--user" in argv and "--collect" in argv
    assert "--pipe" not in argv and "--wait" not in argv


def test_current_process_inside_unit_reads_the_cgroup_through_the_seam():
    assert service_escape.current_process_inside_unit(lambda: V2_IN_UNIT)
    assert not service_escape.current_process_inside_unit(lambda: V2_IN_SESSION)


def test_current_process_inside_unit_is_false_when_the_cgroup_is_unreadable():
    def unreadable():
        raise OSError("no /proc")

    assert not service_escape.current_process_inside_unit(unreadable)


def test_current_process_inside_unit_is_false_off_linux(monkeypatch):
    monkeypatch.setattr(service_escape.sys, "platform", "darwin")
    assert not service_escape.current_process_inside_unit(lambda: V2_IN_UNIT)


def test_detached_argv_wraps_only_inside_the_unit_with_systemd_run(monkeypatch):
    monkeypatch.setattr(service_escape.shutil, "which", lambda name: f"/usr/bin/{name}")
    argv = ["yazses", "settings"]
    assert service_escape.detached_argv(argv, inside=lambda: True) == service_escape.scope_argv(argv)
    assert service_escape.detached_argv(argv, inside=lambda: False) == argv
    monkeypatch.setattr(service_escape.shutil, "which", lambda name: None)
    assert service_escape.detached_argv(argv, inside=lambda: True) == argv


def test_run_outside_service_reports_an_unlaunchable_systemd_run_as_none(monkeypatch):
    monkeypatch.setattr(service_escape.shutil, "which", lambda name: "/usr/bin/systemd-run")

    def boom(*a, **k):
        raise OSError("exec failed")

    monkeypatch.setattr(service_escape.subprocess, "run", boom)
    assert service_escape.run_outside_service(["yazses", "restart"]) is None


# ---- the commands -----------------------------------------------------------


class _Boom(Exception):
    pass


@pytest.fixture
def _spy(monkeypatch):
    calls = {"run": [], "restart": 0}
    monkeypatch.setattr(cli, "_warn_unmet_prereqs", lambda: None)
    monkeypatch.setattr(cli, "_offer_dormant_install", lambda p: None)
    monkeypatch.setattr(cli, "get_platform", lambda: object())
    monkeypatch.setattr(cli, "_refuse_while_finalizing", lambda *a, **k: None)

    def _restart(_p):
        calls["restart"] += 1
        raise _Boom("the in-process restart must not run inside the unit's cgroup")

    monkeypatch.setattr(cli, "_restart_daemon", _restart)
    monkeypatch.setattr(service_escape.shutil, "which", lambda name: f"/usr/bin/{name}")
    return calls


def _fake_run(calls, returncode):
    class _Done:
        pass

    def run(argv, **_kw):
        calls["run"].append(argv)
        done = _Done()
        done.returncode = returncode
        return done

    return run


def test_restart_inside_the_service_hands_off_to_systemd_run(monkeypatch, _spy):
    monkeypatch.setattr(cli, "_in_service_cgroup", lambda: True)
    monkeypatch.setattr(service_escape.subprocess, "run", _fake_run(_spy, 0))
    result = runner.invoke(cli.app, ["restart"])
    assert result.exit_code == 0, result.output
    assert _spy["restart"] == 0
    (argv,) = _spy["run"]
    assert argv[0] == "systemd-run"
    assert argv[-1] == "restart"


def test_restart_inside_the_service_forwards_force_and_the_exit_code(monkeypatch, _spy):
    monkeypatch.setattr(cli, "_in_service_cgroup", lambda: True)
    monkeypatch.setattr(service_escape.subprocess, "run", _fake_run(_spy, 3))
    result = runner.invoke(cli.app, ["restart", "--force"])
    assert result.exit_code == 3
    assert _spy["run"][0][-2:] == ["restart", "--force"]


def test_start_of_a_running_daemon_inside_the_service_also_hands_off(monkeypatch, _spy):
    monkeypatch.setattr(cli, "_in_service_cgroup", lambda: True)
    monkeypatch.setattr(service_escape.subprocess, "run", _fake_run(_spy, 0))
    result = runner.invoke(cli.app, ["start", "--no-autostart"])
    assert result.exit_code == 0, result.output
    assert _spy["restart"] == 0
    assert _spy["run"][0][-2:] == ["start", "--no-autostart"]


def test_restart_outside_the_service_runs_in_process(monkeypatch, _spy):
    monkeypatch.setattr(cli, "_in_service_cgroup", lambda: False)
    monkeypatch.setattr(service_escape.subprocess, "run", _fake_run(_spy, 0))
    result = runner.invoke(cli.app, ["restart"])
    assert _spy["run"] == []
    assert _spy["restart"] == 1
    assert isinstance(result.exception, _Boom)


def test_without_systemd_run_inside_the_service_falls_back_in_process(monkeypatch, _spy):
    monkeypatch.setattr(cli, "_in_service_cgroup", lambda: True)
    monkeypatch.setattr(service_escape.shutil, "which", lambda name: None)
    monkeypatch.setattr(service_escape.subprocess, "run", _fake_run(_spy, 0))
    result = runner.invoke(cli.app, ["restart"])
    assert _spy["run"] == []
    assert _spy["restart"] == 1
    assert isinstance(result.exception, _Boom)


# ---- the tray ---------------------------------------------------------------


def _tray_spawns(monkeypatch, inside):
    from yazses.tray.controller import TrayController

    monkeypatch.setattr(service_escape, "current_process_inside_unit", lambda *a, **k: inside)
    monkeypatch.setattr(service_escape.shutil, "which", lambda name: f"/usr/bin/{name}")
    spawned = []
    ctrl = TrayController(client=None, launcher=lambda argv: spawned.append(argv))
    return ctrl, spawned


def test_tray_restart_and_settings_leave_the_unit_when_inside_it(monkeypatch):
    from yazses.tray.launch import settings_command

    ctrl, spawned = _tray_spawns(monkeypatch, inside=True)
    assert ctrl.restart() is True
    assert ctrl.launch_settings() is True
    assert spawned == [
        service_escape.scope_argv(settings_command("restart")),
        service_escape.scope_argv(settings_command()),
    ]


def test_tray_launches_are_untouched_outside_the_unit(monkeypatch):
    from yazses.tray.launch import settings_command

    ctrl, spawned = _tray_spawns(monkeypatch, inside=False)
    ctrl.restart()
    ctrl.launch_settings()
    assert spawned == [settings_command("restart"), settings_command()]
