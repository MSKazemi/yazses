"""#562 and #578, pinned without a Mac: which first-run prompts are raised, and a stale grant.

Nothing here proves macOS behaviour. They hold the parts that are plain logic or that
a fake can stand in for -- which OS prompts a given probe result asks for, and what
`doctor` says about a daemon that predates a grant. Quit itself is pinned by
`tests/test_macos_tray_quit_stops_the_daemon.py`. What a real Mac does with the calls is listed as UNVERIFIED in
`design/macos-quit-and-first-run-permissions.md`.
"""
from __future__ import annotations

import ast
import sys
import threading
import types
from pathlib import Path

import pytest

from yazses.core.daemon import Daemon
from yazses.platform.base import PermissionState
from yazses.platform.macos import permissions as perms_mod
from yazses.system import doctor
from yazses.system import notify as notify_mod
from yazses.system import permission_alerts as pa

ROOT = Path(__file__).resolve().parent.parent


# ---- which OS prompts a probe result asks for (#562) -------------------------


@pytest.mark.parametrize(
    ("keyboard", "mic", "expected"),
    [
        (pa.DENIED, pa.UNKNOWN, ["request_keyboard_capture", "request_microphone"]),
        (pa.DENIED, pa.OK, ["request_keyboard_capture"]),
        (pa.OK, pa.UNKNOWN, ["request_microphone"]),
        (pa.OK, pa.OK, []),
        # A refused microphone is not asked again: macOS would show nothing.
        (pa.OK, pa.DENIED, []),
        (pa.UNKNOWN, pa.UNKNOWN, ["request_microphone"]),
    ],
)
def test_requests_follow_the_probe(keyboard: str, mic: str, expected: list[str]) -> None:
    probe = pa.PermissionProbe(keyboard=keyboard, microphone=mic)
    assert [m for _slug, m in pa.requests_for(probe)] == expected


class _Perms:
    """Probe answers plus recorded prompts. `request_microphone` is optional on purpose."""

    def __init__(self, keyboard: str, mic: str, *, has_mic_request: bool = True) -> None:
        self._k, self._m = keyboard, mic
        self.asked: list[str] = []
        if has_mic_request:
            self.request_microphone = lambda: self.asked.append("microphone")

    def check_keyboard_capture(self) -> PermissionState:
        return PermissionState(self._k)

    def check_microphone(self) -> PermissionState:
        return PermissionState(self._m)

    def request_keyboard_capture(self) -> None:
        self.asked.append("keyboard")

    def how_to_grant(self) -> str:
        return "fix k"

    def how_to_grant_microphone(self) -> str:
        return "fix m"


def _daemon(tmp_path, perms) -> types.SimpleNamespace:
    ns = types.SimpleNamespace(
        _platform=types.SimpleNamespace(
            permissions=perms, paths=types.SimpleNamespace(data_dir=tmp_path)
        ),
        _lock=threading.RLock(),
        _diagnosed_at={},
        _grants_at_start={},
    )
    ns._shown_notices_path = lambda: Daemon._shown_notices_path(ns)
    ns._persist_shown_notices = lambda: Daemon._persist_shown_notices(ns)
    return ns


@pytest.fixture(autouse=True)
def _no_toasts(monkeypatch):
    monkeypatch.setattr(notify_mod, "notify", lambda *a, **k: None)


def test_the_daemon_raises_the_accessibility_prompt_it_never_raised(tmp_path) -> None:
    perms = _Perms("denied", "ok")
    Daemon._announce_permissions(_daemon(tmp_path, perms))
    assert perms.asked == ["keyboard"]


def test_the_microphone_prompt_is_raised_before_the_first_recording(tmp_path) -> None:
    perms = _Perms("ok", "unknown")
    Daemon._announce_permissions(_daemon(tmp_path, perms))
    assert perms.asked == ["microphone"]


def test_a_backend_without_a_microphone_request_is_left_alone(tmp_path) -> None:
    perms = _Perms("ok", "unknown", has_mic_request=False)
    Daemon._announce_permissions(_daemon(tmp_path, perms))
    assert perms.asked == []


def test_a_login_item_does_not_prompt_at_every_start(tmp_path) -> None:
    asked = 0
    for _ in range(4):
        perms = _Perms("denied", "ok")
        d = _daemon(tmp_path, perms)
        Daemon._load_shown_notices(d)
        Daemon._announce_permissions(d)
        asked += len(perms.asked)
    assert asked == 1


def test_a_healthy_machine_is_never_prompted(tmp_path) -> None:
    perms = _Perms("ok", "ok")
    Daemon._announce_permissions(_daemon(tmp_path, perms))
    assert perms.asked == []


# ---- request_microphone against a fake AVFoundation --------------------------


def _fake_av(monkeypatch, status: int) -> list[object]:
    calls: list[object] = []

    class _Device:
        @staticmethod
        def authorizationStatusForMediaType_(_t):  # noqa: N802 - Apple's selector
            return status

        @staticmethod
        def requestAccessForMediaType_completionHandler_(t, handler):  # noqa: N802
            calls.append(t)
            handler(True)

    monkeypatch.setitem(
        sys.modules,
        "AVFoundation",
        types.SimpleNamespace(AVCaptureDevice=_Device, AVMediaTypeAudio="soun"),
    )
    return calls


def test_only_a_microphone_never_asked_about_is_requested(monkeypatch) -> None:
    calls = _fake_av(monkeypatch, perms_mod._AV_NOT_DETERMINED)
    assert perms_mod.MacosPermissions().request_microphone() is True
    assert calls == ["soun"]


@pytest.mark.parametrize("status", [perms_mod._AV_RESTRICTED, perms_mod._AV_DENIED, perms_mod._AV_AUTHORIZED])
def test_a_decided_microphone_is_not_asked_again(monkeypatch, status: int) -> None:
    calls = _fake_av(monkeypatch, status)
    assert perms_mod.MacosPermissions().request_microphone() is False
    assert calls == []


def test_no_pyobjc_means_no_request(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "AVFoundation", None)  # makes the import fail
    assert perms_mod.MacosPermissions().request_microphone() is False


# ---- a daemon that predates a grant (#578) -----------------------------------


@pytest.mark.parametrize(
    ("was", "now", "stale"),
    [
        (pa.DENIED, pa.OK, ["input_monitoring"]),
        (pa.UNKNOWN, pa.OK, ["input_monitoring"]),
        (pa.OK, pa.OK, []),
        (pa.DENIED, pa.DENIED, []),
        (pa.OK, pa.DENIED, []),
        (pa.DENIED, None, []),
        (None, pa.OK, []),
    ],
)
def test_only_missing_then_present_is_a_stale_grant(was, now, stale) -> None:
    assert pa.grants_given_since_start({"input_monitoring": was}, {"input_monitoring": now}) == stale


class _IM:
    def __init__(self, state: str) -> None:
        self.state, self.probes = state, 0

    def check_input_monitoring(self) -> PermissionState:
        self.probes += 1
        return PermissionState(self.state)


def _stale_self(at_start: dict, perms) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        _grants_at_start=at_start,
        _stale_checked_at=0.0,
        _stale_cached=[],
        _platform=types.SimpleNamespace(permissions=perms),
    )


def test_a_healthy_daemon_never_probes(monkeypatch) -> None:
    perms = _IM("ok")
    me = _stale_self({"input_monitoring": "ok"}, perms)
    assert Daemon._stale_permissions(me) == []
    assert perms.probes == 0


def test_a_daemon_started_before_the_grant_says_so() -> None:
    me = _stale_self({"input_monitoring": "denied"}, _IM("ok"))
    assert Daemon._stale_permissions(me) == ["input_monitoring"]


def test_a_grant_still_missing_is_not_stale() -> None:
    me = _stale_self({"input_monitoring": "denied"}, _IM("denied"))
    assert Daemon._stale_permissions(me) == []


def test_the_probe_is_throttled_because_status_is_polled(monkeypatch) -> None:
    perms = _IM("ok")
    me = _stale_self({"input_monitoring": "unknown"}, perms)
    clock = iter([100.0, 101.0, 140.0])
    monkeypatch.setattr("yazses.core.daemon.time.monotonic", lambda: next(clock))
    for _ in range(3):
        Daemon._stale_permissions(me)
    assert perms.probes == 2  # 101.0 reused the 100.0 answer; 140.0 re-asked


def test_a_backend_without_the_probe_reports_nothing() -> None:
    me = _stale_self({"input_monitoring": "denied"}, object())
    assert Daemon._stale_permissions(me) == []


# ---- doctor names it ---------------------------------------------------------


def _doctor_platform(info: dict):
    class _Client:
        def call(self, _method, **_kw):
            return info

    return types.SimpleNamespace(
        lifecycle=types.SimpleNamespace(is_running=lambda: True, read_pid=lambda: 4242),
        ipc_client_factory=lambda _p: _Client(),
        paths=types.SimpleNamespace(ipc_socket="sock"),
    )


def test_doctor_warns_about_a_daemon_that_predates_a_grant(monkeypatch) -> None:
    monkeypatch.setattr(doctor, "_pkg_version", lambda _n: "9.9.9")
    row, _ = doctor._daemon_check(
        _doctor_platform({"version": "9.9.9", "stale_permissions": ["input_monitoring"]})
    )
    assert row[1] == "WARN"
    assert "Input Monitoring" in row[2]
    assert "restart" in row[2]
    assert "ps aux" in row[2]


def test_doctor_stays_quiet_when_nothing_is_stale(monkeypatch) -> None:
    monkeypatch.setattr(doctor, "_pkg_version", lambda _n: "9.9.9")
    row, _ = doctor._daemon_check(_doctor_platform({"version": "9.9.9", "stale_permissions": []}))
    assert row[1] == "OK"


def test_status_carries_the_daemons_own_answer() -> None:
    """`doctor` reads this key; a status reply that hard-coded `[]` would silence it."""
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
    assert values.get("stale_permissions") == "self._stale_permissions()"
