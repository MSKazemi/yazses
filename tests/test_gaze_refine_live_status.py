"""A click observer that failed to start is named by `doctor` and `gaze status` (#607).

#607's acceptance: "A failed hook or a denied permission leaves dictation working and names
the reason in `doctor` / `gaze status`." Before this file, both commands read only
``Platform.click_observer_factory`` -- whether a backend is *registered* -- so on a Mac
whose Input Monitoring grant was missing, or an X11 session whose XInput2 was refused,
they printed a green "registered" while the daemon had logged that it could not start.
The answer lives in the daemon, a separate process, so it travels in the `status` payload
(``gaze_refine``) beside `handsfree` and `biosignal`, and the two commands read it there.

Every test here is hermetic: the observer, the camera lease and the IPC client are fakes,
and no host daemon, pid file, config directory or input device is touched.
"""
from __future__ import annotations

import dataclasses
import types
from pathlib import Path

import numpy as np
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.clicks import ClickEvent, ClickObserverError
from yazses.gaze.refine_runtime import (
    RefinementLiveStatus,
    build_refinement_runtime,
    live_status_from_payload,
    refinement_status_payload,
)
from yazses.gaze.store import save_calibration
from yazses.platform import get_platform

runner = CliRunner()

IDENT = CalibrationMap(A=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]))

DENIED = (
    "the macOS event tap was refused: grant Input Monitoring and Accessibility to the "
    "app that runs YazSes"
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeObserver:
    def __init__(self, *, refuse: str | None = None, running: bool | None = None) -> None:
        self.refuse = refuse
        self.on_click = None
        self.starts = self.stops = 0
        if running is not None:
            self.is_running = running

    def start(self, on_click) -> None:
        if self.refuse is not None:
            raise ClickObserverError(self.refuse)
        self.starts += 1
        self.on_click = on_click

    def stop(self) -> None:
        self.stops += 1


class FakeLease:
    def __init__(self) -> None:
        self.starts = self.stops = 0

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1

    def latest(self):
        return None


class FakePerception:
    def __init__(self) -> None:
        self.lease = FakeLease()

    def consumer(self, name):
        return self.lease


def _section(enabled: bool = True):
    section = Config().gaze_refine
    section.enabled = enabled
    return section


def _runtime(observer: FakeObserver, tmp_path: Path):
    return build_refinement_runtime(
        _section(),
        targeter=types.SimpleNamespace(calibration=IDENT, set_calibration=lambda m: None),
        perception=FakePerception(),
        gaze_on_shared_source=True,
        observer_factory=lambda: observer,
        data_dir=tmp_path,
        calibration_verified=True,
        spawn=lambda body: None,
    )


# --------------------------------------------------------------------------- #
# The pure payload
# --------------------------------------------------------------------------- #


def test_a_default_install_reports_no_block_at_all() -> None:
    assert refinement_status_payload(enabled=False, runtime=None, reason="") is None


def test_a_dormant_runtime_carries_the_reason_the_daemon_logged() -> None:
    payload = refinement_status_payload(
        enabled=True, runtime=None, reason=f"the click observer could not start ({DENIED})"
    )
    assert payload == {
        "active": False,
        "reason": f"the click observer could not start ({DENIED})",
        "clicks": 0,
        "paired": 0,
    }


def test_a_dormant_runtime_without_a_reason_still_says_something() -> None:
    payload = refinement_status_payload(enabled=True, runtime=None, reason="")
    assert payload is not None and payload["active"] is False
    assert payload["reason"], "an empty reason is the symptomless failure #607 forbids"


def test_a_running_runtime_reports_counts_and_nothing_else(tmp_path) -> None:
    observer = FakeObserver()
    runtime, reason = _runtime(observer, tmp_path)
    assert runtime is not None, reason
    assert observer.on_click is not None
    observer.on_click(ClickEvent(1.0, 10.0, 20.0))
    observer.on_click(ClickEvent(2.0, 30.0, 40.0))

    payload = refinement_status_payload(enabled=True, runtime=runtime, reason="")
    # Privacy: a flag, a sentence and two counts. Never a coordinate, a window or a time.
    assert payload == {"active": True, "reason": "", "clicks": 2, "paired": 0}
    runtime.stop()


def test_an_observer_that_died_after_starting_reads_as_dormant(tmp_path) -> None:
    """The X11 loop exits on a lost display connection and says so only in the log."""
    observer = FakeObserver(running=True)
    runtime, _reason = _runtime(observer, tmp_path)
    assert runtime is not None
    observer.is_running = False

    payload = refinement_status_payload(enabled=True, runtime=runtime, reason="")
    assert payload is not None
    assert payload["active"] is False
    assert "stopped" in str(payload["reason"]) and "restart" in str(payload["reason"])
    runtime.stop()


def test_an_observer_that_cannot_say_whether_it_runs_is_taken_at_its_start(tmp_path) -> None:
    observer = FakeObserver()  # no `is_running` attribute, like the Windows/macOS hooks
    runtime, _reason = _runtime(observer, tmp_path)
    assert runtime is not None
    payload = refinement_status_payload(enabled=True, runtime=runtime, reason="")
    assert payload is not None and payload["active"] is True
    runtime.stop()


# --------------------------------------------------------------------------- #
# Reading it back (the payload crossed a process boundary; trust nothing)
# --------------------------------------------------------------------------- #


def test_reading_back_a_payload_round_trips() -> None:
    status = live_status_from_payload({"active": False, "reason": "why", "clicks": 3, "paired": 1})
    assert status == RefinementLiveStatus(active=False, reason="why", clicks=3, paired=1)


def test_reading_back_rejects_what_is_not_a_status_block() -> None:
    for junk in (None, "on", 3, [], {"reason": "no active flag"}, {"active": "yes"}):
        assert live_status_from_payload(junk) is None, junk


def test_reading_back_tolerates_missing_or_bad_counts() -> None:
    status = live_status_from_payload({"active": True, "clicks": "many", "paired": -4})
    assert status == RefinementLiveStatus(active=True, reason="", clicks=0, paired=0)


# --------------------------------------------------------------------------- #
# The daemon puts it in `status`
# --------------------------------------------------------------------------- #


def _daemon(observer: FakeObserver | None, *, enabled: bool = True) -> Daemon:
    cfg = Config()
    cfg.gaze_refine.enabled = enabled
    platform = dataclasses.replace(
        get_platform(),
        click_observer_factory=(None if observer is None else (lambda: observer)),
        click_observer_unavailable_reason=None,
    )
    daemon = Daemon(config=cfg, platform=platform)
    daemon._gaze_targeter = types.SimpleNamespace(calibration=IDENT, set_calibration=lambda m: None)
    daemon._perception = FakePerception()
    daemon._gaze_on_shared_source = True
    daemon._gaze_calibration_facts = (True, "explicit", None)
    return daemon


def test_the_daemon_reports_nothing_while_refinement_is_off() -> None:
    daemon = _daemon(FakeObserver(), enabled=False)
    daemon._gaze_refinement = daemon._build_gaze_refinement(daemon._config)
    assert daemon._gaze_refine_payload() is None


def test_a_refused_hook_reaches_the_status_payload_with_its_reason() -> None:
    daemon = _daemon(FakeObserver(refuse=DENIED))
    daemon._gaze_refinement = daemon._build_gaze_refinement(daemon._config)
    assert daemon._gaze_refinement is None, "a refused hook must leave refinement off"

    payload = daemon._gaze_refine_payload()
    assert payload is not None
    assert payload["active"] is False
    assert DENIED in str(payload["reason"])


def test_a_started_observer_reaches_the_status_payload_as_active() -> None:
    observer = FakeObserver()
    daemon = _daemon(observer)
    daemon._gaze_refinement = daemon._build_gaze_refinement(daemon._config)
    try:
        payload = daemon._gaze_refine_payload()
        assert payload is not None and payload["active"] is True
    finally:
        if daemon._gaze_refinement is not None:
            daemon._gaze_refinement.stop()


def test_a_builder_that_raises_is_reported_not_hidden(monkeypatch) -> None:
    import yazses.gaze.refine_runtime as runtime_module

    def boom(*a, **k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(runtime_module, "build_refinement_runtime", boom)
    daemon = _daemon(FakeObserver())
    daemon._gaze_refinement = daemon._build_gaze_refinement(daemon._config)
    payload = daemon._gaze_refine_payload()
    assert payload is not None and payload["active"] is False
    assert "RuntimeError" in str(payload["reason"])


def test_the_status_payload_names_the_block() -> None:
    """The key is in the literal dict `_handle_status` returns (the redaction guard reads it)."""
    import ast
    import inspect

    import yazses.core.daemon as daemon_module

    tree = ast.parse(inspect.getsource(daemon_module))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_handle_status":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                    keys |= {
                        k.value for k in sub.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    }
    assert "gaze_refine" in keys


# --------------------------------------------------------------------------- #
# `yazses doctor`
# --------------------------------------------------------------------------- #


def _refine_on() -> Config:
    cfg = Config()
    cfg.gaze_refine.enabled = True
    return cfg


def _doctor_platform(factory, reason=None):
    return types.SimpleNamespace(
        click_observer_factory=factory, click_observer_unavailable_reason=reason
    )


def test_doctor_names_a_refused_hook_from_the_running_daemon() -> None:
    from yazses.system.doctor import _click_observer_check

    live = {"active": False, "reason": f"the click observer could not start ({DENIED})",
            "clicks": 0, "paired": 0}
    row = _click_observer_check(_refine_on(), _doctor_platform(object), live=live)
    assert row is not None
    _name, status, detail = row
    assert status == "WARN"
    assert DENIED in detail
    assert "dictation" in detail.lower(), "the row must say dictation is unaffected"


def test_doctor_reports_a_running_observer_with_its_counts() -> None:
    from yazses.system.doctor import _click_observer_check

    live = {"active": True, "reason": "", "clicks": 12, "paired": 7}
    row = _click_observer_check(_refine_on(), _doctor_platform(object), live=live)
    assert row is not None and row[1] == "OK"
    assert "12" in row[2] and "7" in row[2]


def test_doctor_without_a_daemon_answer_keeps_the_registration_row() -> None:
    from yazses.system.doctor import _click_observer_check

    row = _click_observer_check(_refine_on(), _doctor_platform(object), live=None)
    assert row is not None and row[1] == "OK"
    assert "registered" in row[2]


def test_doctor_stays_silent_on_a_default_install_whatever_the_daemon_says() -> None:
    from yazses.system.doctor import _click_observer_check

    live = {"active": False, "reason": "x", "clicks": 0, "paired": 0}
    assert _click_observer_check(Config(), _doctor_platform(object), live=live) is None


# --------------------------------------------------------------------------- #
# `yazses gaze status`
# --------------------------------------------------------------------------- #


class FakeClient:
    def __init__(self, reply=None, *, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    def call(self, method, **params):
        self.calls.append((method, params))
        if self.fail:
            raise ConnectionRefusedError("no daemon")
        return self.reply


def _status(monkeypatch, tmp_path: Path, *, running: bool, client: FakeClient | None):
    platform = types.SimpleNamespace(
        paths=types.SimpleNamespace(
            config_file=tmp_path / "config.toml", data_dir=tmp_path,
            ipc_socket=tmp_path / "daemon.sock",
        ),
        click_observer_factory=object,
        click_observer_unavailable_reason=None,
        lifecycle=types.SimpleNamespace(is_running=lambda: running),
        ipc_client_factory=lambda _socket: client,
    )
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    monkeypatch.setattr("yazses.config.load_config", lambda _p: _refine_on())
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _cfg: None)
    monkeypatch.setattr("yazses.gaze.desktop.build_desktop", lambda: object())
    save_calibration(IDENT, tmp_path)
    return runner.invoke(cli.app, ["gaze", "status"])


def test_gaze_status_names_a_refused_hook_from_the_running_daemon(monkeypatch, tmp_path) -> None:
    client = FakeClient({"gaze_refine": {
        "active": False, "reason": f"the click observer could not start ({DENIED})",
        "clicks": 0, "paired": 0,
    }})
    result = _status(monkeypatch, tmp_path, running=True, client=client)
    assert result.exit_code == 0, result.output
    assert "✓ click observer: registered for this session" in result.output
    assert f"✗ implicit refinement: dormant in the running daemon -- the click observer could not start ({DENIED})" in result.output
    # Read-only: the call must not take a toast off the tray's queue.
    assert client.calls == [("status", {"consume_notifications": False})]


def test_gaze_status_shows_a_running_observer_with_its_counts(monkeypatch, tmp_path) -> None:
    client = FakeClient({"gaze_refine": {"active": True, "reason": "", "clicks": 12, "paired": 7}})
    result = _status(monkeypatch, tmp_path, running=True, client=client)
    assert result.exit_code == 0, result.output
    assert "✓ implicit refinement: running in the daemon (12 clicks seen, 7 paired with gaze)" in result.output


def test_gaze_status_with_no_daemon_asks_nothing_and_says_so(monkeypatch, tmp_path) -> None:
    client = FakeClient({"gaze_refine": {"active": True}})
    result = _status(monkeypatch, tmp_path, running=False, client=client)
    assert result.exit_code == 0, result.output
    assert client.calls == []
    assert "implicit refinement: the daemon is not running" in result.output


def test_gaze_status_survives_a_daemon_that_does_not_answer(monkeypatch, tmp_path) -> None:
    result = _status(monkeypatch, tmp_path, running=True, client=FakeClient(fail=True))
    assert result.exit_code == 0, result.output
    assert "✓ click observer: registered for this session" in result.output
    assert "implicit refinement: dormant" not in result.output


def test_gaze_status_from_an_older_daemon_without_the_block_adds_no_line(monkeypatch, tmp_path) -> None:
    result = _status(monkeypatch, tmp_path, running=True, client=FakeClient({"state": "idle"}))
    assert result.exit_code == 0, result.output
    assert "implicit refinement:" not in result.output
