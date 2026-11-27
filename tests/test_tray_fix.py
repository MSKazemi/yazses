"""The tray's one fix: the same decision as the window's Overview page, and its effect.

`tray/menu.py::fix_entry` asks `settingsui/overview.py::health`; `tray/fix.py` carries the
click out. No Qt, no daemon, no subprocess.
"""

from __future__ import annotations

import subprocess

import pytest

from yazses.platform.base import TrayModel, TrayState
from yazses.settingsui import overview
from yazses.settingsui.pages import PAGE_KEYS
from yazses.system.relaunch import Mode, command_for
from yazses.system.service_escape import detached_argv
from yazses.tray import fix as tray_fix
from yazses.tray.controller import TrayController
from yazses.tray.launch import settings_command
from yazses.tray.menu import (
    DAEMON_DOWN,
    DAEMON_UNRESPONSIVE,
    SETTINGS_PAGE,
    build_menu_model,
    fix_entry,
    status_from_model,
)


def _status(**extra) -> dict:
    return {
        "state": "idle", "ready": True, "silent_streak": 0,
        "silent_streak_threshold": 3, "target_ok": None, **extra,
    }


# ---- one rule, two surfaces ---------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"state": "error", "last_error": "model file is missing"},
        {"silent_streak": 1},
        {"silent_streak": 3},
        {"silent_streak": 3, "silent_streak_threshold": 5},
        {"silent_streak": 3, "ready": False},
        {"state": "error", "silent_streak": 9},
        {"state": "recording", "target_ok": False},
        {"state": "loading", "ready": False},
        {"meeting_active": True, "state": "meeting"},
    ],
)
def test_the_menu_offers_exactly_what_the_overview_page_offers(extra):
    status = _status(**extra)
    health = overview.health(status)
    entry = fix_entry(status)
    if not health.action:
        assert entry is None
    else:
        assert entry is not None
        assert entry.action == health.action
        # The window's button text and heading, not a second wording of them.
        assert health.action_label in entry.text and health.title in entry.text


def test_a_silent_microphone_offers_recalibration():
    entry = fix_entry(_status(silent_streak=3))
    assert entry is not None and entry.action == tray_fix.RECALIBRATE


def test_an_error_offers_a_restart():
    entry = fix_entry(_status(state="error"))
    assert entry is not None and entry.action == tray_fix.RESTART


def test_a_daemon_that_is_not_running_offers_a_start_whatever_the_state_says():
    entry = fix_entry({"state": "error", "daemon_reach": DAEMON_DOWN})
    assert entry is not None and entry.action == tray_fix.START
    assert overview.health(None).action_label in entry.text


def test_a_daemon_that_did_not_answer_offers_nothing():
    assert fix_entry({"state": "error", "daemon_reach": DAEMON_UNRESPONSIVE}) is None


def test_nothing_known_yet_offers_nothing():
    assert fix_entry({}) is None
    assert fix_entry(status_from_model(TrayModel())) is None


def test_the_static_trays_get_the_fix_through_the_shared_bridge():
    silent = TrayModel(silent_streak=3)
    assert fix_entry(status_from_model(silent)).action == tray_fix.RECALIBRATE
    # The daemon's own limit travels, so a raised threshold is honoured on every OS.
    patient = TrayModel(silent_streak=3, silent_streak_threshold=5)
    assert fix_entry(status_from_model(patient)) is None
    loading = TrayModel(silent_streak=3, ready=False)
    assert fix_entry(status_from_model(loading)) is None
    broken = TrayModel(state=TrayState.ERROR, last_error="boom")
    assert fix_entry(status_from_model(broken)).action == tray_fix.RESTART
    gone = TrayModel(state=TrayState.ERROR, daemon_reach=DAEMON_DOWN)
    assert fix_entry(status_from_model(gone)).action == tray_fix.START


def test_the_menu_model_carries_the_fix():
    assert build_menu_model(_status(), [], "").fix is None
    model = build_menu_model(_status(silent_streak=4), [], "")
    assert model.fix == fix_entry(_status(silent_streak=4))


# ---- the effect ---------------------------------------------------------------------


class _Launcher:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self._error = error

    def __call__(self, argv, **options):
        if self._error is not None:
            raise self._error
        self.calls.append((argv, options))


def _cli(*args: str) -> list[str]:
    return detached_argv(command_for(Mode.CLI, *args))


def test_start_runs_yazses_start_without_adding_a_login_item():
    launcher = _Launcher()
    result = tray_fix.start_daemon(launcher, running=lambda: False)
    assert result == {"ok": True}
    (argv, options), = launcher.calls
    assert argv == _cli("start", "--no-autostart")
    # No terminal to answer a question on.
    assert options["stdin"] is subprocess.DEVNULL


def test_start_leaves_a_running_daemon_alone():
    """`yazses start` would restart it, possibly in the middle of writing up a meeting."""
    launcher = _Launcher()
    result = tray_fix.start_daemon(launcher, running=lambda: True)
    assert result["ok"] and result["already_running"]
    assert launcher.calls == []
    assert "already running" in tray_fix.describe(tray_fix.START, result)[1]


def test_start_does_nothing_when_it_cannot_tell_whether_the_daemon_runs():
    def _boom() -> bool:
        raise OSError("no pid file access")

    launcher = _Launcher()
    result = tray_fix.start_daemon(launcher, running=_boom)
    assert not result["ok"] and launcher.calls == []


@pytest.mark.parametrize("action", [tray_fix.START, tray_fix.RESTART])
def test_a_launch_that_fails_is_reported_not_raised(action):
    title, body = tray_fix.run_fix_action(
        action, launcher=_Launcher(OSError("no such file")), running=lambda: False
    )
    assert title == "YazSes" and "no such file" in body


def test_restart_runs_yazses_restart():
    launcher = _Launcher()
    title, body = tray_fix.run_fix_action(tray_fix.RESTART, launcher=launcher)
    assert [argv for argv, _ in launcher.calls] == [_cli("restart")]
    assert "Restarting" in body


class _Client:
    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self._reply, self._error = reply, error

    def call(self, method, **params):
        self.calls.append(method)
        if self._error is not None:
            raise self._error
        return self._reply


def test_recalibrate_asks_the_daemon_and_says_to_stay_quiet_first():
    client = _Client({"ok": True, "started": True})
    _title, body = tray_fix.run_fix_action(tray_fix.RECALIBRATE, client=client)
    assert client.calls == ["recalibrate_mic"]
    assert "quiet first" in body


def test_a_refused_recalibration_shows_the_daemons_words():
    client = _Client({"ok": False, "reason": "busy — try again when idle"})
    assert tray_fix.run_fix_action(tray_fix.RECALIBRATE, client=client)[1] == (
        "busy — try again when idle"
    )


def test_recalibrating_an_unreachable_daemon_does_not_raise():
    client = _Client(error=OSError("socket gone"))
    assert "socket gone" in tray_fix.run_fix_action(tray_fix.RECALIBRATE, client=client)[1]


# ---- the controller and the window launch ---------------------------------------------


def test_the_controller_starts_only_a_daemon_that_is_not_running():
    launcher = _Launcher()
    TrayController(None, launcher=launcher, running=lambda: True).start_daemon()
    assert launcher.calls == []
    TrayController(None, launcher=launcher, running=lambda: False).start_daemon()
    assert [argv for argv, _ in launcher.calls] == [_cli("start", "--no-autostart")]


def test_the_settings_entry_opens_a_page_that_exists():
    assert SETTINGS_PAGE in PAGE_KEYS


def test_the_window_can_be_launched_on_a_page():
    spawned: list[list[str]] = []
    ctrl = TrayController(None, launcher=lambda argv: spawned.append(argv))
    assert ctrl.launch_settings(SETTINGS_PAGE) is True
    assert ctrl.launch_settings() is True
    assert spawned == [
        detached_argv(settings_command(page=SETTINGS_PAGE)),
        detached_argv(settings_command()),
    ]
    assert spawned[0][-2:] == ["--page", SETTINGS_PAGE]
    assert "--page" not in spawned[1]
