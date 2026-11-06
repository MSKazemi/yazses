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
from yazses.core.takeover import REPLACE_SILENCE_S, may_replace_again, replacement_reason
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


def test_the_silence_rule():
    now = 1_000_000.0
    assert may_replace_again(None, now)
    assert not may_replace_again(now, now)
    assert not may_replace_again(now - REPLACE_SILENCE_S + 1, now)
    assert may_replace_again(now - REPLACE_SILENCE_S, now)


def test_a_record_from_the_future_does_not_block():
    """A clock set back must not silence the rule for as long as the clock is wrong."""
    now = 1_000_000.0
    assert may_replace_again(now + 1.0, now)
    assert may_replace_again(now + REPLACE_SILENCE_S * 10, now)


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


def test_the_record_is_written_before_the_restart_is_launched(tmp_path):
    """The loop guard must not race the restart, which closes the tray that launched it."""
    from yazses.system import toast_memory

    seen: list[dict[str, float]] = []

    def launcher(_argv):
        seen.append(toast_memory.load(tmp_path / "daemon_replacements.json"))

    r = StaleDaemonReplacer(
        tmp_path, mine=_MINE, launcher=launcher, command=lambda: ["yazses", "restart"],
        wall=_Clock(),
    )
    assert r.check({**_IDLE, "stale_permissions": ["input_monitoring"]}) == "permissions"
    assert seen and "permissions" in seen[0]


def test_the_restart_is_launched_without_a_console_window(monkeypatch):
    """No user clicked anything, so a Windows console must not flash up on its own."""
    import subprocess

    calls: list[dict] = []
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: calls.append(kw))
    app._launch_restart(["yazses", "restart"])
    assert calls[0]["creationflags"] == 0x08000000
    assert calls[0]["start_new_session"] is True


def test_no_creationflags_where_the_os_has_none(monkeypatch):
    import subprocess

    calls: list[dict] = []
    monkeypatch.delattr(subprocess, "CREATE_NO_WINDOW", raising=False)
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: calls.append(kw))
    app._launch_restart(["yazses", "restart"])
    assert calls[0]["creationflags"] == 0  # the only value POSIX Popen accepts


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


class _Unreachable:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.polls = 0

    def call(self, method: str, **_kwargs):  # noqa: ANN201
        self.calls.append(method)
        raise ConnectionRefusedError("no daemon")


def _run_tray(monkeypatch, tmp_path, reply: dict, *, client=None,
              tray_factory=None) -> tuple[list[list[str]], _Client]:
    done = threading.Event()
    tray = _Tray(done)
    client = client if client is not None else _Client(reply, done)
    plat = types.SimpleNamespace(
        name="fake",
        tray_factory=tray_factory or (lambda: tray),
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
    """A tray that holds the lock and finds an older daemon running (no older tray around)."""
    launched, _ = _run_tray(monkeypatch, tmp_path, {"state": "idle", "version": "2.43.1"})
    assert launched == [["yazses", "restart"]]


def test_the_running_tray_leaves_a_current_daemon_alone(monkeypatch, tmp_path):
    launched, _ = _run_tray(monkeypatch, tmp_path, dict(_IDLE))
    assert launched == []


# ---- the reporter's flow: an older tray still holds the lock ---------------------------
#
# In #578's log the reopened tray exited at once ("A YazSes tray is already running"),
# because the old daemon's old tray held `tray.lock`. That tray predates this check, so a
# reopened tray that only exits never replaces anything. It asks once on its way out.


@pytest.fixture
def held_tray_lock(tmp_path):
    from yazses.system.single_instance import SingleInstanceLock

    other = SingleInstanceLock(tmp_path / "tray.lock")
    assert other.acquire()
    yield other
    other.release()


def _no_tray():
    raise AssertionError("a duplicate tray must not build a tray icon")


def test_a_duplicate_tray_restarts_a_daemon_that_predates_the_grant(
        monkeypatch, tmp_path, held_tray_lock):
    client = _Client({**_IDLE, "stale_permissions": ["input_monitoring"]}, threading.Event())
    launched, _ = _run_tray(monkeypatch, tmp_path, {}, client=client, tray_factory=_no_tray)
    assert launched == [["yazses", "restart"]]
    assert client.calls == ["status"]


def test_a_duplicate_tray_restarts_an_older_daemon(monkeypatch, tmp_path, held_tray_lock):
    client = _Client({"state": "idle", "version": "2.43.1"}, threading.Event())
    launched, _ = _run_tray(monkeypatch, tmp_path, {}, client=client, tray_factory=_no_tray)
    assert launched == [["yazses", "restart"]]


def test_a_duplicate_tray_leaves_a_current_daemon_alone(monkeypatch, tmp_path, held_tray_lock):
    client = _Client(dict(_IDLE), threading.Event())
    launched, _ = _run_tray(monkeypatch, tmp_path, {}, client=client, tray_factory=_no_tray)
    assert launched == []
    assert client.calls == ["status"]


def test_a_duplicate_tray_with_no_daemon_just_exits(monkeypatch, tmp_path, held_tray_lock):
    client = _Unreachable()
    launched, _ = _run_tray(monkeypatch, tmp_path, {}, client=client, tray_factory=_no_tray)
    assert launched == []
    assert client.calls == ["status"]


def test_a_duplicate_tray_honours_the_silence(monkeypatch, tmp_path, held_tray_lock):
    """The running tray (or an earlier reopen) already restarted it within the hour."""
    stale = {**_IDLE, "stale_permissions": ["input_monitoring"]}
    first, _ = _run_tray(monkeypatch, tmp_path, {},
                         client=_Client(stale, threading.Event()), tray_factory=_no_tray)
    again, _ = _run_tray(monkeypatch, tmp_path, {},
                         client=_Client(stale, threading.Event()), tray_factory=_no_tray)
    assert first == [["yazses", "restart"]]
    assert again == []
