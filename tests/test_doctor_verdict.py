"""`yazses doctor` bottom-line verdict — the one 'what do I do next' line."""
from __future__ import annotations

import types

from yazses.system import doctor


class _Plat:
    default_hotkey = "right_alt"


def _cfg(key="right_ctrl"):
    return types.SimpleNamespace(hotkey=types.SimpleNamespace(key=key))


def test_verdict_fail_takes_priority():
    checks = [("A", "OK", ""), ("B", "FAIL", ""), ("C", "WARN", "")]
    line = doctor._verdict_line(checks, _cfg(), _Plat())
    assert "✗" in line
    assert "yazses doctor" in line
    assert "1 problem" in line  # singular


def test_verdict_warn_only_says_good_to_go():
    checks = [("A", "OK", ""), ("B", "WARN", ""), ("C", "WARN", "")]
    line = doctor._verdict_line(checks, _cfg(), _Plat())
    assert "▲" in line
    assert "2 optional warnings" in line
    assert "yazses start" in line
    assert "right_ctrl" in line  # resolved hotkey in the dictate hint


def test_verdict_all_ok_is_green_checkmark():
    checks = [("A", "OK", ""), ("B", "OK", "")]
    line = doctor._verdict_line(checks, _cfg(), _Plat())
    assert "✓" in line
    assert "Everything looks good" in line


def test_verdict_running_daemon_skips_start_prompt():
    checks = [("Daemon", "OK", "running"), ("B", "OK", "")]
    line = doctor._verdict_line(checks, _cfg(), _Plat())
    assert "all set" in line
    assert "yazses start" not in line  # already running → don't tell them to start


def test_verdict_resolves_auto_hotkey_to_platform_default():
    checks = [("A", "OK", "")]
    line = doctor._verdict_line(checks, _cfg(key="auto"), _Plat())
    assert "right_alt" in line  # sentinel resolved to the platform default
