"""The tray must never leave a blue "idle" icon on screen when the daemon is not there.

Two exits of the poll thread used to `return` without telling the tray anything: the
"daemon never booted" give-up and the "poller crashed" handler. The icon stayed on
whatever it last drew (or, on Linux, on the empty-status default, which renders as idle
blue) while the process kept the single-instance lock. And the "daemon starting",
"restarting" and "stopping" decisions used the dataclass default `IDLE`, so a daemon that
was still booting looked exactly like a ready one.

These drive the real `run()` with a fake platform and a fake tray: no Qt, no desktop, no
daemon. They prove the state machine, not how a given OS draws it.
"""
from __future__ import annotations

import threading
import time
import types
from pathlib import Path

import pytest

import yazses.tray.app as app
from yazses.ipc.client import IpcUnreachableError
from yazses.platform import TrayModel, TrayState
from yazses.tray.app import (
    _DAEMON_BOOT_TIMEOUT_S,
    _RECONNECT_GRACE_S,
    unreachable_decision,
)
from yazses.tray.menu import icon_spec, status_from_model


class _FakeTray:
    """Records every `set_state`; `run()` waits for the poller like the real loop would."""

    def __init__(self, *, quit_after_first_state: bool = False) -> None:
        self.states: list[TrayModel] = []
        self.stopped = False
        self._quit_after_first_state = quit_after_first_state

    def set_state(self, model: TrayModel) -> None:
        self.states.append(model)

    def notify(self, title: str, body: str) -> None:
        return None

    def stop(self) -> None:
        self.stopped = True

    def run(self, on_quit) -> None:  # noqa: ANN001
        if self._quit_after_first_state:
            deadline = time.monotonic() + 5.0
            while not self.states and time.monotonic() < deadline:
                time.sleep(0.01)
            on_quit()
        for t in threading.enumerate():
            if t.name == "tray-poller":
                t.join(5.0)


class _Client:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def call(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        raise self._exc


def _drive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tray: _FakeTray,
    client: _Client,
    *,
    boot_timeout: float,
) -> list[TrayModel]:
    plat = types.SimpleNamespace(
        name="fake",
        tray_factory=lambda: tray,
        ipc_client_factory=lambda _path: client,
        paths=types.SimpleNamespace(data_dir=tmp_path, ipc_socket=tmp_path / "s"),
        lifecycle=types.SimpleNamespace(
            is_running=lambda: False, start_daemon_detached=lambda: None
        ),
        update_launcher=None,
    )
    monkeypatch.setattr(app, "get_platform", lambda: plat)
    monkeypatch.setattr(app, "_DAEMON_BOOT_TIMEOUT_S", boot_timeout)
    app.run()
    return tray.states


# ---- the two exits that used to be silent, and are no longer exits at all ---------------
#
# Giving up and crashing both used to `return`: first with the icon frozen on idle, then
# (after the fix) on ERROR -- but the poller was still dead, so once the user did what the
# tooltip said (`yazses start`) the icon stayed ERROR for as long as the tray lived. Both
# now show ERROR and keep polling, slowly, so the icon recovers to the real state.


class _RecordingEvent(threading.Event):
    """`threading.Event` whose timed waits are recorded and do not sleep."""

    waits: list[float] = []  # noqa: RUF012 - replaced per test by `_drive_script`

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is None:
            return super().wait()
        self.waits.append(timeout)
        return self.is_set()


class _ScriptedClient:
    """Plays `script` for `status` calls, then snapshots how far the poller got and parks."""

    def __init__(self, script: list[object], tray: _FakeTray, waits: list[float]) -> None:
        self._script = list(script)
        self._tray = tray
        self._waits = waits
        self.exhausted = threading.Event()
        self.release = threading.Event()
        self.states_seen = 0
        self.waits_seen = 0

    def call(self, method: str, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        if method != "status":
            self.release.set()  # `shutdown` from on_quit: let the parked poller go
            return {}
        if not self._script:
            if not self.exhausted.is_set():
                self.states_seen = len(self._tray.states)
                self.waits_seen = len(self._waits)
                self.exhausted.set()
            self.release.wait(5.0)
            raise IpcUnreachableError("parked")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _ScriptTray(_FakeTray):
    client: _ScriptedClient

    def run(self, on_quit) -> None:  # noqa: ANN001
        assert self.client.exhausted.wait(5.0), "the poller stopped before the script ended"
        on_quit()
        for t in threading.enumerate():
            if t.name == "tray-poller":
                t.join(5.0)


def _drive_script(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    script: list[object],
    *,
    boot_timeout: float,
) -> tuple[list[TrayModel], list[float]]:
    """Run the real `run()` against a scripted daemon; no sleeping, no desktop.

    Returns the tray states and the timed waits the poller made *while the script was
    playing*. A poller that exited early never reaches the end of the script, and the
    tray's `run` then fails its "stopped before the script ended" assert.
    """
    waits: list[float] = []

    class _Event(_RecordingEvent):
        pass

    _Event.waits = waits
    tray = _ScriptTray()
    client = _ScriptedClient(script, tray, waits)
    tray.client = client
    plat = types.SimpleNamespace(
        name="fake",
        tray_factory=lambda: tray,
        ipc_client_factory=lambda _path: client,
        paths=types.SimpleNamespace(data_dir=tmp_path, ipc_socket=tmp_path / "s"),
        lifecycle=types.SimpleNamespace(
            is_running=lambda: False, start_daemon_detached=lambda: None
        ),
        update_launcher=None,
    )
    monkeypatch.setattr(app, "get_platform", lambda: plat)
    monkeypatch.setattr(app, "_DAEMON_BOOT_TIMEOUT_S", boot_timeout)
    monkeypatch.setattr(app, "start_addon_refetch", lambda *a, **k: None)
    # Only this module sees the recording Event: `threading` itself is untouched.
    monkeypatch.setattr(
        app,
        "threading",
        types.SimpleNamespace(Event=_Event, Thread=threading.Thread),
    )
    app.run()
    return tray.states[: client.states_seen], waits[: client.waits_seen]


_IDLE = {"state": "idle", "hotkey": "f9", "model": "tiny.en", "uptime_s": 3.0}


def test_daemon_that_never_boots_ends_on_an_error_icon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Give-up used to `return` with no set_state: the icon stayed idle blue."""
    states, _waits = _drive_script(
        monkeypatch, tmp_path, [IpcUnreachableError("no socket")], boot_timeout=0.0
    )

    assert states, "the poller gave up without telling the tray anything"
    last = states[-1]
    assert last.state is TrayState.ERROR
    assert last.last_error
    _color, tip = icon_spec(status_from_model(last))
    assert last.last_error in tip


def test_after_giving_up_the_tray_keeps_polling_and_recovers_when_the_daemon_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The tooltip says `yazses start`; once the user has, the icon must follow the daemon."""
    script: list[object] = [IpcUnreachableError("no socket")] * 3 + [_IDLE]
    states, waits = _drive_script(monkeypatch, tmp_path, script, boot_timeout=0.0)

    assert [m.state for m in states] == [TrayState.ERROR] * 3 + [TrayState.IDLE]
    assert states[0].last_error == app._GIVE_UP_REASON
    assert states[-1].model == "tiny.en" and states[-1].last_error is None
    # Slow and bounded: 5-10 s between looks while there is no daemon, never a tight loop.
    give_up_waits = waits[:3]
    assert give_up_waits == [app._GIVE_UP_POLL_INTERVAL_S] * 3
    assert 5.0 <= app._GIVE_UP_POLL_INTERVAL_S <= 10.0


def test_a_crashed_poller_ends_on_an_error_icon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The crash handler used to `return` with no set_state, so the last icon stayed."""
    states, _waits = _drive_script(
        monkeypatch,
        tmp_path,
        [RuntimeError("secret /home/u/x path")],
        boot_timeout=30.0,
    )

    assert states, "the poller crashed without telling the tray anything"
    last = states[-1]
    assert last.state is TrayState.ERROR
    assert last.last_error
    # The exception text can hold paths or device names; the tray shows a fixed reason.
    assert "secret" not in last.last_error and "/home" not in last.last_error


def test_a_crashed_pass_backs_off_never_shows_idle_and_recovers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script: list[object] = [RuntimeError("boom")] * 5 + [_IDLE, RuntimeError("again"), _IDLE]
    states, waits = _drive_script(monkeypatch, tmp_path, script, boot_timeout=30.0)

    kinds = [m.state for m in states]
    assert kinds == (
        [TrayState.ERROR] * 5 + [TrayState.IDLE, TrayState.ERROR, TrayState.IDLE]
    )  # ERROR is never replaced by anything but the real state
    # 1, 2, 4, 8, 10 (capped), then a successful pass resets the backoff to 1 again.
    crash_waits = [w for w in waits if w != app._POLL_INTERVAL_S]
    assert crash_waits == [1.0, 2.0, 4.0, 8.0, 10.0, 1.0]


def test_crash_backoff_is_bounded_and_monotonic() -> None:
    seq = [app.crash_backoff_s(n) for n in range(1, 40)]
    assert seq[0] == 1.0 and max(seq) == 10.0
    assert seq == sorted(seq)
    assert app.crash_backoff_s(0) == 1.0  # defensive: never a zero-wait spin


def test_a_daemon_still_booting_shows_loading_not_idle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tray = _FakeTray(quit_after_first_state=True)
    states = _drive(
        monkeypatch, tmp_path, tray, _Client(IpcUnreachableError("no socket")), boot_timeout=30.0
    )

    assert states
    assert states[0].state is TrayState.LOADING
    assert states[0].last_error == "daemon starting"


# ---- the decisions -----------------------------------------------------------------


def test_starting_restarting_and_stopping_are_loading_not_idle() -> None:
    starting = unreachable_decision(False, 1.0)
    restarting = unreachable_decision(True, 1.0)
    stopping = unreachable_decision(
        True, _RECONNECT_GRACE_S + 1.0, daemon_running=True, stop_requested=True
    )

    assert (starting.last_error, restarting.last_error, stopping.last_error) == (
        "daemon starting",
        "daemon restarting",
        "daemon stopping",
    )
    for d in (starting, restarting, stopping):
        assert d.state is TrayState.LOADING
        assert not d.give_up and not d.relaunch and not d.close_tray


def test_the_give_up_decision_itself_is_unchanged() -> None:
    d = unreachable_decision(False, _DAEMON_BOOT_TIMEOUT_S + 1.0)
    assert d.give_up is True and d.close_tray is False


# ---- the tooltip -------------------------------------------------------------------


def _tip(**status: object) -> str:
    return icon_spec(status)[1]


def test_error_tooltip_carries_the_reason() -> None:
    tip = _tip(state="error", last_error="daemon not responding", hotkey="f9")
    assert tip.splitlines()[-1] == "⚠ daemon not responding"
    assert len(tip.splitlines()) == 4


def test_error_reason_is_truncated_to_60_and_one_line() -> None:
    raw = 'line one\nTraceback (most recent call last):\n  File "/home/u/x.py"\r\n' + "x" * 200
    tip = _tip(state="error", last_error=raw)
    line = tip.splitlines()[-1]
    assert line.startswith("⚠ ")
    assert len(line) - len("⚠ ") <= 60
    assert len(tip.splitlines()) == 4  # the reason added exactly one line


def test_error_reason_strips_control_characters() -> None:
    tip = _tip(state="error", last_error="bad\x00dev\x1bice\x07\tname")
    line = tip.splitlines()[-1]
    assert not any(ord(c) < 32 or ord(c) == 127 for c in line)
    assert "baddevice name" in line


def test_a_short_reason_is_not_padded_or_ellipsised() -> None:
    assert _tip(state="error", last_error="x" * 60).splitlines()[-1] == "⚠ " + "x" * 60


@pytest.mark.parametrize("last_error", [None, "", "   \n\t"])
def test_error_without_a_usable_reason_adds_no_line(last_error: str | None) -> None:
    assert _tip(state="error", last_error=last_error) == (
        "YazSes — error\nMic: default\nHold ? to dictate"
    )


def test_a_last_error_on_a_non_error_state_is_not_shown() -> None:
    """`loading`/`idle` carry the transient "daemon starting" text; that is not a fault."""
    assert "daemon starting" not in _tip(state="loading", last_error="daemon starting")
    assert "daemon" not in _tip(state="idle", last_error="old news")


# Golden strings captured from the pre-change `icon_spec`: nothing but ERROR may move.
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ({"state": "idle"}, "YazSes — idle\nMic: default\nHold ? to dictate"),
        (
            {"state": "idle", "hotkey": "right_ctrl", "input_device": "USB Mic"},
            "YazSes — idle\nMic: USB Mic\nHold right_ctrl to dictate",
        ),
        (
            {
                "state": "recording",
                "hotkey": "right_ctrl",
                "input_device": "USB Mic",
                "target_ok": False,
            },
            "YazSes — recording\nMic: USB Mic\nHold right_ctrl to dictate\n"
            "⚠ no text field focused — will save to clipboard",
        ),
        (
            {"state": "recording", "command_mode": True, "hotkey": "f9"},
            "YazSes — command mode\nMic: default\nHold f9 to dictate\n"
            "⌘ command mode — parsing a command, not typing",
        ),
        (
            {"state": "idle", "silent_streak": 2, "hotkey": "f9"},
            "YazSes — idle\nMic: default\nHold f9 to dictate\n⚠ 2 silent clip(s) in a row",
        ),
        ({"state": "loading"}, "YazSes — loading\nMic: default\nHold ? to dictate"),
    ],
)
def test_other_tooltips_are_byte_identical_to_before(
    status: dict[str, object], expected: str
) -> None:
    assert icon_spec(status)[1] == expected
