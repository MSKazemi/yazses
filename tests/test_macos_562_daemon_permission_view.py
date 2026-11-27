"""#562: `doctor` and the menu bar show what the *daemon* is allowed to do, not only the caller.

On #562 `doctor`, typed into Terminal, said Accessibility and Input Monitoring were denied
while System Settings showed YazSes switched on. The daemon now reports its own answers and
two surfaces read them. Nothing here proves macOS behaviour: backends are fakes.
"""
from __future__ import annotations

import ast
import dataclasses
import types
from pathlib import Path

import pytest

from yazses.core.daemon import Daemon
from yazses.platform.base import PermissionState, TrayModel
from yazses.platform.macos.permissions import MacosPermissions
from yazses.platform.macos.tray import _PERMISSIONS_HINT
from yazses.system import doctor
from yazses.system import permission_alerts as pa
from yazses.tray.menu import status_from_model, status_lines, top_warning

ROOT = Path(__file__).resolve().parent.parent
_ALL_OK = {"keyboard_capture": "ok", "input_monitoring": "ok", "microphone": "ok"}


class _Perms:
    def __init__(self, keyboard="ok", input_monitoring="ok", microphone="ok") -> None:
        self.answers = (keyboard, input_monitoring, microphone)
        self.probes = 0

    def _answer(self, index: int) -> PermissionState:
        self.probes += 1
        return PermissionState(self.answers[index])

    def check_keyboard_capture(self) -> PermissionState:
        return self._answer(0)

    def check_input_monitoring(self) -> PermissionState:
        return self._answer(1)

    def check_microphone(self) -> PermissionState:
        return self._answer(2)


# ---- what the daemon reports -------------------------------------------------


def test_the_view_has_one_answer_per_switch() -> None:
    assert pa.daemon_view(_Perms("denied", "ok", "unknown")) == {
        "keyboard_capture": "denied",
        "input_monitoring": "ok",
        "microphone": "unknown",
    }


def test_a_probe_that_is_missing_or_raises_is_unknown() -> None:
    class _Broken:
        def check_keyboard_capture(self):
            raise RuntimeError("no")

    assert set(pa.daemon_view(_Broken()).values()) == {"unknown"}


def _self(at_start: dict, perms: object) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        _grants_at_start=at_start,
        _permissions_checked_at=0.0,
        _permissions_cached={},
        _platform=types.SimpleNamespace(permissions=perms),
    )


def test_off_macos_the_daemon_reports_nothing_and_probes_nothing() -> None:
    perms = _Perms()
    assert Daemon._permission_view(_self({}, perms)) is None
    assert perms.probes == 0


def test_the_view_is_throttled_because_status_is_polled(monkeypatch) -> None:
    perms = _Perms()
    me = _self({"input_monitoring": "ok"}, perms)
    clock = iter([100.0, 101.0, 140.0])
    monkeypatch.setattr("yazses.core.daemon.time.monotonic", lambda: next(clock))
    for _ in range(3):
        assert Daemon._permission_view(me) == _ALL_OK
    assert perms.probes == 6  # three switches, asked at 100.0 and again at 140.0


def test_status_carries_the_view() -> None:
    tree = ast.parse((ROOT / "src/yazses/core/daemon.py").read_text(encoding="utf-8"))
    handler = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_handle_status"
    )
    values = {
        k.value: ast.unparse(v)
        for n in ast.walk(handler)
        if isinstance(n, ast.Dict)
        for k, v in zip(n.keys, n.values, strict=True)
        if isinstance(k, ast.Constant)
    }
    assert values.get("permissions") == "self._permission_view()"


# ---- how a doctor row is corrected -------------------------------------------


@pytest.mark.parametrize("view", [None, {}, "denied", {"input_monitoring": "unknown"}])
def test_without_a_definite_answer_the_row_is_unchanged(view) -> None:
    row = ("FAIL", "denied — fix it")
    assert pa.reconcile_with_daemon("input_monitoring", *row, view) == row


def test_the_daemons_ok_overrules_a_terminals_denied() -> None:
    status, detail = pa.reconcile_with_daemon(
        "input_monitoring", "FAIL", "denied — long advice", _ALL_OK
    )
    assert status == "OK"
    assert "may be judging the terminal" in detail
    assert "long advice" not in detail


def test_agreement_on_ok_leaves_the_row_alone() -> None:
    assert pa.reconcile_with_daemon("microphone", "OK", "ok", _ALL_OK) == ("OK", "ok")


@pytest.mark.parametrize(
    ("key", "pane"),
    [(key, pane) for key, _method, pane in pa.DAEMON_PROBES],
)
def test_the_daemons_denied_fails_a_row_the_command_called_ok(key: str, pane: str) -> None:
    status, detail = pa.reconcile_with_daemon(key, "OK", "ok", {key: "denied"})
    assert status == "FAIL"
    assert pane in detail and "yazses restart" in detail


def test_agreement_on_denied_keeps_the_advice() -> None:
    status, detail = pa.reconcile_with_daemon(
        "keyboard_capture", "FAIL", "denied — long advice", {"keyboard_capture": "denied"}
    )
    assert status == "FAIL"
    assert detail.startswith("denied — long advice")
    assert "as well" in detail


def test_a_grant_the_daemon_predates_is_a_restart_not_an_ok() -> None:
    status, detail = pa.reconcile_with_daemon(
        "input_monitoring", "OK", "ok", _ALL_OK, ["input_monitoring"]
    )
    assert status == "WARN"
    assert "yazses restart" in detail


def test_the_doctor_wrapper_reads_the_status_reply() -> None:
    row = doctor._with_daemon_view(
        ("Input monitoring", "FAIL", "denied"),
        "input_monitoring",
        {"permissions": _ALL_OK, "stale_permissions": []},
    )
    assert row[:2] == ("Input monitoring", "OK")
    # An older daemon, or none: nothing changes.
    old = ("Input monitoring", "FAIL", "denied")
    assert doctor._with_daemon_view(old, "input_monitoring", {}) == old


# ---- the menu bar ------------------------------------------------------------


def test_the_menu_names_every_refused_switch() -> None:
    status = {
        "state": "idle",
        "permissions": {
            "keyboard_capture": "denied",
            "input_monitoring": "denied",
            "microphone": "denied",
        },
    }
    line = top_warning(status)
    assert line is not None and not line.endswith("…")
    for pane in ("Accessibility", "Input Monitoring", "Microphone"):
        assert pane in line


@pytest.mark.parametrize(
    "view", [None, _ALL_OK, {"microphone": "unknown"}, "denied"]
)
def test_the_menu_says_nothing_without_a_refusal(view) -> None:
    assert top_warning({"state": "idle", "permissions": view}) is None


def test_a_daemon_error_still_comes_first() -> None:
    status = {
        "state": "error",
        "last_error": "model missing",
        "permissions": {"input_monitoring": "denied"},
    }
    assert top_warning(status) == "⚠ model missing"


def test_the_tray_model_carries_the_view_to_the_menu() -> None:
    assert "permissions" in {f.name for f in dataclasses.fields(TrayModel)}
    model = TrayModel(permissions={"input_monitoring": "denied"})
    assert "Input Monitoring" in status_lines(status_from_model(model))[-1]
    assert status_from_model(TrayModel())["permissions"] is None


# ---- the .app has no `yazses` command ----------------------------------------


def _cli_row(platform_name="darwin", *, frozen=True, found=None):
    return doctor._bundle_cli_check(
        platform_name,
        frozen=frozen,
        executable="/Applications/Yaz Ses.app/Contents/MacOS/YazSes",
        which=lambda _name: found,
    )


def test_a_dmg_install_is_told_what_to_type() -> None:
    row = _cli_row()
    assert row is not None and row[:2] == ("Command line", "OK")
    # Quoted, so a path with a space can be pasted into a shell.
    assert "'/Applications/Yaz Ses.app/Contents/MacOS/YazSes' --cli <command>" in row[2]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"platform_name": "linux"},
        {"frozen": False},
        {"found": "/usr/local/bin/yazses"},
    ],
)
def test_the_row_is_absent_where_yazses_can_be_typed(kwargs) -> None:
    assert _cli_row(**kwargs) is None


# ---- the advice matches when YazSes actually asks ----------------------------


def test_about_names_all_three_switches() -> None:
    for pane in ("Accessibility", "Input Monitoring", "Microphone"):
        assert pane in _PERMISSIONS_HINT


def test_the_input_monitoring_remedy_does_not_wait_for_a_key_hold() -> None:
    """The request is made when the daemon starts, so holding the key asks nothing."""
    text = MacosPermissions().how_to_grant_input_monitoring()
    assert "hold the dictation key" not in text
    assert "yazses restart" in text


def test_the_accessibility_remedy_does_not_point_at_a_row_above() -> None:
    """`doctor` prints Input monitoring below Keyboard capture, and a toast has no rows."""
    text = MacosPermissions().how_to_grant()
    assert "row above" not in text
    assert "yazses doctor" in text


def test_the_microphone_remedy_says_the_daemon_asks() -> None:
    assert "asks when its daemon starts" in MacosPermissions().how_to_grant_microphone()
