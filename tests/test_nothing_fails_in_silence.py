"""Nothing fails in silence: permissions, downloads and installs all announce.

The rule these pin: if YazSes hits an error or needs a permission, it says so with
a reason the user can act on — and it says it somewhere they will actually see,
which for a large part of the install base is not a terminal.

Each test names the population it protects, because that is what decides whether a
`print` counts as telling someone.
"""

from __future__ import annotations

import io
import json
import threading
import types

import pytest

from yazses.core.daemon import Daemon
from yazses.system import notify as notify_mod
from yazses.system import permission_alerts as pa
from yazses.system import toast_memory
from yazses.system.diagnosis import diagnose

# ------------------------------------------------ which denials speak


def test_a_denied_keyboard_grant_is_announced():
    alerts = pa.alerts_for(pa.PermissionProbe(keyboard=pa.DENIED, keyboard_fix="do this"))
    assert [a.key for a in alerts] == ["keyboard-capture"]
    assert "do this" in alerts[0].body


def test_unknown_never_becomes_a_finding():
    """macOS reports a mic nobody was asked about as NotDetermined -> UNKNOWN, and a
    missing PyObjC reports UNKNOWN too. An unrun probe must not redden a working
    install."""
    probe = pa.PermissionProbe(keyboard=pa.UNKNOWN, microphone=pa.UNKNOWN, input_monitoring=None)
    assert pa.alerts_for(probe) == []


def test_ok_and_not_applicable_are_silent():
    probe = pa.PermissionProbe(keyboard=pa.OK, microphone=pa.NOT_APPLICABLE)
    assert pa.alerts_for(probe) == []


def test_the_most_blocking_grant_is_named_first():
    """Without the keyboard, dictation cannot begin at all; a microphone only fails
    once you got that far."""
    probe = pa.PermissionProbe(
        keyboard=pa.DENIED, microphone=pa.DENIED, input_monitoring=pa.DENIED
    )
    assert [a.key for a in pa.alerts_for(probe)] == [
        "keyboard-capture",
        "input-monitoring",
        "microphone",
    ]


def test_every_alert_carries_the_remedy_from_the_platform_backend():
    """This module invents no advice — one source of truth per OS."""
    probe = pa.PermissionProbe(
        keyboard=pa.DENIED,
        microphone=pa.DENIED,
        input_monitoring=pa.DENIED,
        keyboard_fix="KFIX",
        microphone_fix="MFIX",
        input_monitoring_fix="IFIX",
    )
    assert [a.fix for a in pa.alerts_for(probe)] == ["KFIX", "IFIX", "MFIX"]


# ------------------------------------------------ the daemon announces them


class _Perms:
    def __init__(self, keyboard="denied", mic="ok"):
        self._keyboard = keyboard
        self._mic = mic

    def check_keyboard_capture(self):
        return types.SimpleNamespace(value=self._keyboard)

    def check_microphone(self):
        return types.SimpleNamespace(value=self._mic)

    def how_to_grant(self):
        return "sudo usermod -aG input $USER"

    def how_to_grant_microphone(self):
        return "check your sound settings"


def _daemon(tmp_path, perms, seen=None):
    """A stand-in `self` carrying the *real* persistence methods.

    Stubbing those out would leave the crash-loop test asserting against a fake,
    which is the one thing it must not do — the behaviour under test is precisely
    that the record reaches disk and is read back by the next process.
    """
    namespace = types.SimpleNamespace(
        _platform=types.SimpleNamespace(
            permissions=perms,
            paths=types.SimpleNamespace(data_dir=tmp_path),
        ),
        _lock=threading.RLock(),
        _diagnosed_at=seen if seen is not None else {},
    )
    namespace._shown_notices_path = lambda: Daemon._shown_notices_path(namespace)
    namespace._persist_shown_notices = lambda: Daemon._persist_shown_notices(namespace)
    return namespace


def test_the_daemon_tells_the_user_about_a_denied_permission(tmp_path, monkeypatch):
    """#182's symptom: daemon starts, tray paints healthy, the key does nothing and
    nothing anywhere says why."""
    toasts: list[tuple] = []
    monkeypatch.setattr(notify_mod, "notify", lambda t, b, **kw: toasts.append((t, b)))

    Daemon._announce_permissions(_daemon(tmp_path, _Perms(keyboard="denied")))

    assert toasts, "a denied grant reached only `yazses doctor` before"
    assert "usermod" in toasts[0][1], "the toast must carry the actual fix"


def test_a_healthy_machine_is_not_nagged(tmp_path, monkeypatch):
    toasts: list[tuple] = []
    monkeypatch.setattr(notify_mod, "notify", lambda t, b, **kw: toasts.append((t, b)))

    Daemon._announce_permissions(_daemon(tmp_path, _Perms(keyboard="ok", mic="ok")))

    assert toasts == []


def test_a_probe_that_raises_is_not_a_finding(tmp_path, monkeypatch):
    """'Could not determine' and 'denied' are opposite facts."""
    class _Boom:
        def check_keyboard_capture(self):
            raise OSError("no such interface")

        def check_microphone(self):
            raise OSError("no such interface")

        def how_to_grant(self):
            return "x"

        def how_to_grant_microphone(self):
            return "y"

    toasts: list[tuple] = []
    monkeypatch.setattr(notify_mod, "notify", lambda t, b, **kw: toasts.append((t, b)))

    Daemon._announce_permissions(_daemon(tmp_path, _Boom()))

    assert toasts == []


def test_a_crash_loop_does_not_repeat_the_same_warning(tmp_path, monkeypatch):
    """`Restart=on-failure` with StartLimitBurst=5 gives five fresh processes in a
    minute. Five identical toasts is what the repeat-silence exists to prevent."""
    toasts: list[tuple] = []
    monkeypatch.setattr(notify_mod, "notify", lambda t, b, **kw: toasts.append((t, b)))

    for _ in range(5):
        # A fresh daemon each time == a fresh process, which is the whole point.
        daemon = _daemon(tmp_path, _Perms(keyboard="denied"))
        Daemon._load_shown_notices(daemon)
        Daemon._announce_permissions(daemon)

    assert len(toasts) == 1, f"one missing grant produced {len(toasts)} toasts"


# ------------------------------------------------ the persisted record


def test_the_record_survives_a_restart(tmp_path):
    path = toast_memory.path_for(tmp_path)
    toast_memory.save(path, {"a": 1000.0}, now=1000.0)
    assert toast_memory.load(path) == {"a": 1000.0}


def test_a_corrupt_record_errs_towards_speaking(tmp_path):
    """A warning shown twice is a nuisance; one swallowed because a JSON file had a
    stray byte is the failure this subsystem exists to prevent."""
    path = toast_memory.path_for(tmp_path)
    path.write_text("{not json", encoding="utf-8")
    assert toast_memory.load(path) == {}


def test_rows_that_still_mean_something_are_kept(tmp_path):
    path = toast_memory.path_for(tmp_path)
    path.write_text(json.dumps({"good": 5.0, "bad": "nonsense"}), encoding="utf-8")
    assert toast_memory.load(path) == {"good": 5.0}


def test_old_entries_do_not_accumulate_forever():
    state = {"ancient": 0.0, "recent": 1_000_000.0}
    assert toast_memory.prune(state, 1_000_001.0) == {"recent": 1_000_000.0}


def test_saving_never_raises_on_an_unwritable_path(tmp_path):
    toast_memory.save(tmp_path / "nope" / "deep" / "x.json", {"a": 1.0})


# ------------------------------------------------ the unattended rule


def test_a_watched_terminal_gets_no_toast():
    """Someone who typed the command is already being told."""
    attended = io.StringIO()
    attended.isatty = lambda: True  # type: ignore[method-assign]
    assert notify_mod.unattended(attended) is False


def test_an_app_grid_launch_gets_a_toast(monkeypatch):
    """App Center / .dmg / app-grid users never see a `print`."""
    sent: list[tuple] = []
    monkeypatch.setattr(notify_mod, "notify", lambda t, b, **kw: sent.append((t, b)))
    piped = io.StringIO()  # StringIO.isatty() is False

    assert notify_mod.notify_when_unattended("t", "b", stream=piped) is True
    assert sent == [("t", "b")]


def test_a_stream_that_cannot_answer_is_treated_as_watched():
    """Conservative on purpose: an odd environment keeps the behaviour it had."""
    class _Odd:
        def isatty(self):
            raise OSError("detached")

    assert notify_mod.unattended(_Odd()) is False


# ------------------------------------------------ the report offer


def test_an_unidentified_failure_offers_a_report():
    assert diagnose(RuntimeError("something nobody has seen"), where="inject").report_worthy


@pytest.mark.parametrize(
    "error",
    [
        PermissionError(13, "Permission denied", "/dev/uinput"),
        RuntimeError("the user cancelled the permission dialog for the portal"),
        OSError("no space left on device"),
    ],
)
def test_a_recognised_failure_does_not_hand_the_user_a_second_chore(error):
    assert diagnose(error, where="inject").report_worthy is False
