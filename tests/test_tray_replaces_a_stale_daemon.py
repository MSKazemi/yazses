"""The tray replaces a daemon that is older than it, or that predates a permission grant.

#578: on macOS a daemon reads its Input Monitoring grant when its keyboard tap is created,
at start. A daemon started before the grant (or before an upgrade) keeps that answer, and
until now nothing replaced it: opening the app again started a *tray*, the tray found a
daemon running and used it, and the daemon-side takeover (`core/takeover.is_older`,
v2.43.1) never ran because no second daemon was started. The running daemon already
*says* so -- `stale_permissions` (2ca4c8d0) and `version` are on its `status` reply -- so
the tray, which polls that reply every second, now acts on it: it hands off to
`yazses restart` once, while the daemon is idle, never during a recording or a meeting.

A daemon shuts down the tray it launched, so a tray that restarts its own parent is
replaced by a fresh tray. The once-per-tray rule alone would therefore not stop a loop;
the hand-off is also recorded on disk and not repeated within an hour.

Everything is faked: the launcher, the clock, the record (under `tmp_path`). No process
is started, and nothing on the host is read or written.
"""

from __future__ import annotations

import threading
import types
from pathlib import Path

import pytest

import yazses.tray.app as app
from yazses.core.takeover import REPLACE_SILENCE_S, replacement_reason
from yazses.platform import TrayModel
from yazses.tray.app import StaleDaemonReplacer

_MINE = "2.50.0"
_IDLE = {"state": "idle", "version": _MINE}


# ---- the pure rule ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ({"state": "idle", "version": "2.43.1"}, "older"),
        ({"state": "error", "version": "2.43.1"}, "older"),
        ({**_IDLE, "stale_permissions": ["input_monitoring"]}, "permissions"),
        ({"state": "error", "version": _MINE, "stale_permissions": ["input_monitoring"]},
         "permissions"),
        # Older AND stale: one restart fixes both; the version is the reason given.
        ({"state": "idle", "version": "2.43.1", "stale_permissions": ["input_monitoring"]},
         "older"),
        (_IDLE, None),                                        # a healthy, current daemon
        ({"state": "idle", "version": "2.51.0"}, None),       # never displace a newer one
        ({"state": "idle"}, None),                            # an old daemon: no version
        ({**_IDLE, "stale_permissions": []}, None),
        ({**_IDLE, "stale_permissions": "input_monitoring"}, None),  # wrong shape
        ({**_IDLE, "stale_permissions": [1, None]}, None),
        ({**_IDLE, "stale_permissions": None}, None),
        (None, None),
        ("idle", None),
        ([], None),
    ],
)
def test_which_daemons_are_replaced(status, expected):
    assert replacement_reason(status, _MINE) == expected


@pytest.mark.parametrize(
    "state",
    ["recording", "transcribing", "injecting", "readback", "meeting", "loading",
     "paused", "enrolling", "remote_setup", "remote_active", "", None, "nonsense",
     ["idle"], {"idle": 1}],
)
def test_a_daemon_that_is_not_idle_is_left_alone(state):
    """Restarting mid-dictation loses the words; only idle and error qualify."""
    status = {"state": state, "version": "2.43.1", "stale_permissions": ["input_monitoring"]}
    assert replacement_reason(status, _MINE) is None


@pytest.mark.parametrize("key", ["meeting_active", "meeting_finalizing"])
def test_a_meeting_in_progress_is_never_interrupted(key):
    status = {"state": "idle", "version": "2.43.1", key: True}
    assert replacement_reason(status, _MINE) is None


def test_an_unreadable_own_version_still_acts_on_a_stale_grant():
    """A source checkout reports `dev`: the version rule abstains, the grant rule does not."""
    stale = {**_IDLE, "stale_permissions": ["input_monitoring"]}
    assert replacement_reason({"state": "idle", "version": "2.43.1"}, "dev") is None
    assert replacement_reason(stale, "dev") == "permissions"


# ---- the tray's hand-off ---------------------------------------------------------------


class _Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _replacer(tmp_path: Path, launched: list[list[str]], clock: _Clock | None = None,
              mine: str = _MINE) -> StaleDaemonReplacer:
    return StaleDaemonReplacer(
        tmp_path,
        mine=mine,
        launcher=launched.append,
        command=lambda: ["yazses", "restart"],
        wall=clock or _Clock(),
    )


def test_a_daemon_that_predates_the_grant_is_restarted_once(tmp_path):
    launched: list[list[str]] = []
    r = _replacer(tmp_path, launched)
    stale = {**_IDLE, "stale_permissions": ["input_monitoring"]}

    assert r.check(stale) == "permissions"
    assert launched == [["yazses", "restart"]]
    # The poll keeps reading `stale_permissions` until the new daemon answers.
    assert r.check(stale) is None
    assert r.check(stale) is None
    assert len(launched) == 1


def test_an_older_daemon_is_restarted(tmp_path):
    launched: list[list[str]] = []
    assert _replacer(tmp_path, launched).check({"state": "idle", "version": "2.43.1"}) == "older"
    assert launched == [["yazses", "restart"]]


def test_a_current_daemon_is_never_restarted(tmp_path):
    launched: list[list[str]] = []
    r = _replacer(tmp_path, launched)
    for _ in range(5):
        assert r.check(_IDLE) is None
    assert launched == []
    assert not any(tmp_path.iterdir()), "nothing to record, so nothing written"


def test_a_busy_daemon_is_restarted_once_it_goes_idle(tmp_path):
    launched: list[list[str]] = []
    r = _replacer(tmp_path, launched)
    stale = {"stale_permissions": ["input_monitoring"], "version": _MINE}

    assert r.check({**stale, "state": "recording"}) is None
    assert r.check({**stale, "state": "idle", "meeting_active": True}) is None
    assert launched == []
    assert r.check({**stale, "state": "idle"}) == "permissions"
    assert len(launched) == 1


def test_a_new_tray_does_not_restart_again_within_the_silence(tmp_path):
    """The daemon closes the tray it launched, so the next tray is a fresh process."""
    launched: list[list[str]] = []
    clock = _Clock()
    stale = {**_IDLE, "stale_permissions": ["input_monitoring"]}

    assert _replacer(tmp_path, launched, clock).check(stale) == "permissions"
    clock.now += REPLACE_SILENCE_S - 1
    assert _replacer(tmp_path, launched, clock).check(stale) is None
    assert len(launched) == 1

    clock.now += 2  # past the silence: a grant that is still stale is acted on again
    assert _replacer(tmp_path, launched, clock).check(stale) == "permissions"
    assert len(launched) == 2


def test_the_two_reasons_are_silenced_separately(tmp_path):
    launched: list[list[str]] = []
    clock = _Clock()
    assert _replacer(tmp_path, launched, clock).check(
        {"state": "idle", "version": "2.43.1"}) == "older"
    assert _replacer(tmp_path, launched, clock).check(
        {**_IDLE, "stale_permissions": ["input_monitoring"]}) == "permissions"
    assert len(launched) == 2


def test_a_failed_launch_never_raises_and_is_not_retried_every_second(tmp_path):
    def refuse(_argv):
        raise OSError("no such file")

    r = StaleDaemonReplacer(
        tmp_path, mine=_MINE, launcher=refuse, command=lambda: ["yazses", "restart"],
        wall=_Clock(),
    )
    stale = {**_IDLE, "stale_permissions": ["input_monitoring"]}
    assert r.check(stale) is None
    assert r.check(stale) is None


def test_an_unwritable_record_still_restarts_once_per_tray(tmp_path):
    launched: list[list[str]] = []
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    r = _replacer(blocker, launched)
    stale = {**_IDLE, "stale_permissions": ["input_monitoring"]}
    assert r.check(stale) == "permissions"
    assert r.check(stale) is None
    assert len(launched) == 1


def test_a_replacer_with_no_data_dir_is_inert(tmp_path):
    launched: list[list[str]] = []
    r = StaleDaemonReplacer(
        None, mine=_MINE, launcher=launched.append, command=lambda: ["x"], wall=_Clock(),
    )
    assert r.check({**_IDLE, "stale_permissions": ["input_monitoring"]}) is None
    assert launched == []


# ---- wired into the real poll loop -----------------------------------------------------


class _Tray:
    def __init__(self, done: threading.Event) -> None:
        self.states: list[TrayModel] = []
        self._done = done

    def set_state(self, model: TrayModel) -> None:
        self.states.append(model)

    def notify(self, title: str, body: str) -> None:
        return None

    def stop(self) -> None:
        return None

    def run(self, on_quit) -> None:  # noqa: ANN001
        assert self._done.wait(5.0), "the poller never read a status"
        on_quit()
        for t in threading.enumerate():
            if t.name == "tray-poller":
                t.join(5.0)


class _Client:
    def __init__(self, reply: dict, done: threading.Event) -> None:
        self._reply = reply
        self._done = done
        self.calls: list[str] = []
        self.polls = 0

    def call(self, method: str, **_kwargs):  # noqa: ANN201
        self.calls.append(method)
        if method == "status":
            self.polls += 1
            if self.polls >= 3:
                self._done.set()
            return dict(self._reply)
        return {"ok": True}


def _run_tray(monkeypatch, tmp_path, reply: dict) -> tuple[list[list[str]], _Client]:
    done = threading.Event()
    tray = _Tray(done)
    client = _Client(reply, done)
    plat = types.SimpleNamespace(
        name="fake",
        tray_factory=lambda: tray,
        ipc_client_factory=lambda _path: client,
        paths=types.SimpleNamespace(data_dir=tmp_path, ipc_socket=tmp_path / "s"),
        lifecycle=types.SimpleNamespace(
            is_running=lambda: True, start_daemon_detached=lambda: None
        ),
        update_launcher=None,
    )
    launched: list[list[str]] = []
    monkeypatch.setattr(app, "get_platform", lambda: plat)
    monkeypatch.setattr(app, "start_addon_refetch", lambda *a, **k: None)
    monkeypatch.setattr(app, "_POLL_INTERVAL_S", 0.0)
    monkeypatch.setattr(app, "_launch_restart", launched.append)
    monkeypatch.setattr(app, "_restart_command", lambda: ["yazses", "restart"])
    monkeypatch.setattr(app, "_tray_version", lambda: _MINE)
    app.run()
    return launched, client


def test_the_running_tray_restarts_a_daemon_that_predates_the_grant(monkeypatch, tmp_path):
    launched, client = _run_tray(
        monkeypatch, tmp_path, {**_IDLE, "stale_permissions": ["input_monitoring"]}
    )
    assert launched == [["yazses", "restart"]]
    assert client.polls >= 3


def test_the_running_tray_restarts_an_older_daemon_it_found_at_launch(monkeypatch, tmp_path):
    """The reporter's flow: reopen the upgraded app while the old daemon still runs."""
    launched, _ = _run_tray(monkeypatch, tmp_path, {"state": "idle", "version": "2.43.1"})
    assert launched == [["yazses", "restart"]]


def test_the_running_tray_leaves_a_current_daemon_alone(monkeypatch, tmp_path):
    launched, _ = _run_tray(monkeypatch, tmp_path, dict(_IDLE))
    assert launched == []
