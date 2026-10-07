"""What the first real macOS bug report (#562) taught, pinned without a Mac.

An M2 Mac mini on macOS 26.6.2 ran the 2.40.0 DMG. Its daemon log said a daemon had
been running since Friday; `yazses doctor` said "Daemon: not running". Its
Privacy & Security panes showed YazSes switched on and Terminal switched off; `doctor`
run from Terminal said denied. These tests hold the parts that are plain logic.
What they do **not** prove is that the hotkey now works on that Mac -- only the
reporter can.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from yazses.platform.macos import lifecycle as lc
from yazses.platform.macos.hotkey import tap_started_message
from yazses.platform.macos.permissions import MacosPermissions, terminal_attribution_note

APP_PATH = "/Applications/YazSes.app/Contents/MacOS/YazSes --daemon"


# ---- the daemon the .app started was invisible to `doctor` -------------------


@pytest.mark.parametrize(
    "command",
    [APP_PATH, "/Applications/YazSes.app/Contents/MacOS/YazSes", "python -m yazses.core.daemon"],
)
def test_a_yazses_command_line_is_recognised_whatever_its_case(command: str) -> None:
    assert lc.command_is_yazses(command)


@pytest.mark.parametrize("command", ["/bin/bash", "-zsh", "", "/usr/sbin/cfprefsd agent"])
def test_an_unrelated_process_is_still_rejected(command: str) -> None:
    """The check exists to reject a recycled PID; case-folding must not widen it."""
    assert not lc.command_is_yazses(command)


def _lifecycle(tmp_path, monkeypatch, ps_output: str) -> lc.MacosLifecycle:
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("4242", encoding="utf-8")
    monkeypatch.setattr(lc.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(
        lc.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=ps_output, returncode=0)
    )
    return lc.MacosLifecycle(SimpleNamespace(pid_file=pid_file))


def test_a_running_app_bundle_daemon_is_reported_running(tmp_path, monkeypatch) -> None:
    """The #562 contradiction: log says running, `doctor` said not running."""
    assert _lifecycle(tmp_path, monkeypatch, APP_PATH + "\n").is_running() is True


def test_a_recycled_pid_is_still_reported_not_running(tmp_path, monkeypatch) -> None:
    assert _lifecycle(tmp_path, monkeypatch, "/bin/bash\n").is_running() is False


# ---- the duplicate-daemon message sent a Mac user to systemctl ---------------


def test_the_duplicate_daemon_message_does_not_point_a_mac_at_systemctl(
    tmp_path, monkeypatch, caplog
) -> None:
    from yazses.core.daemon import Daemon

    class _Held:
        def __init__(self, _path) -> None: ...
        def acquire(self) -> bool:
            return False

    monkeypatch.setattr("yazses.system.single_instance.SingleInstanceLock", _Held)
    fake = SimpleNamespace(_platform=SimpleNamespace(paths=SimpleNamespace(data_dir=tmp_path)))
    with caplog.at_level(logging.ERROR, logger="yazses.core.daemon"):
        assert Daemon._acquire_instance_lock(fake) is False
    text = caplog.text
    assert "yazses restart" in text
    # systemctl may be named as the Linux alternative, never as *the* instruction.
    assert "Manage the daemon with: systemctl" not in text


# ---- doctor run from a terminal ----------------------------------------------


def test_no_note_when_nothing_says_a_terminal_started_it() -> None:
    assert terminal_attribution_note({}) == ""


def test_a_terminal_gets_a_hedged_note_that_names_the_evidence() -> None:
    note = terminal_attribution_note({"TERM_PROGRAM": "Apple_Terminal"})
    assert "may judge the permission of the terminal" in note
    assert "Terminal off, YazSes" in note
    assert "daemon.log" in note
    # It must not assert a mechanism nobody has confirmed on a Mac.
    assert "always" not in note.lower() and "because macOS" not in note


def test_both_permission_remedies_carry_the_note_only_from_a_terminal(monkeypatch) -> None:
    perms = MacosPermissions()
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    assert "Run from a terminal?" not in perms.how_to_grant()
    assert "Run from a terminal?" not in perms.how_to_grant_input_monitoring()
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    assert "Run from a terminal?" in perms.how_to_grant()
    assert "Run from a terminal?" in perms.how_to_grant_input_monitoring()


# ---- a tap that exists is not a hotkey that works ----------------------------


def test_a_granted_tap_is_logged_as_enabled_at_info() -> None:
    level, msg = tap_started_message(
        input_monitoring_granted=True, key_id="right_option", kind="modifier"
    )
    assert level == logging.INFO
    assert msg == "CGEventTap enabled for key_id=right_option (modifier)"


def test_an_ungranted_tap_is_a_warning_that_does_not_claim_to_be_enabled() -> None:
    level, msg = tap_started_message(
        input_monitoring_granted=False, key_id="right_option", kind="modifier"
    )
    assert level == logging.WARNING
    assert "enabled" not in msg
    assert "Input Monitoring" in msg and "yazses restart" in msg
