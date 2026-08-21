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


def test_a_stale_running_daemon_is_not_told_to_start():
    """The closing line must agree with the warning three lines above it.

    Found by running `yazses doctor` on a real machine whose daemon predated the
    upgrade. It printed, in this order:

        [WARN] Daemon: running (PID 4054, ...) -- run `yazses restart` ...
        > Good to go (3 optional warnings above) -- run `yazses start`, ...

    `running` was inferred from the check's *tag* (`== "OK"`), which held only
    because a running daemon was always OK. v2.24.0 introduced a running-but-WARN
    state for a stale daemon and never updated this line, so a demonstrably
    running daemon read as stopped and doctor named the wrong command.
    """
    checks = [("Daemon", "WARN", "running (PID 4054) — run `yazses restart` ...")]
    line = doctor._verdict_line(checks, _cfg(), _Plat())
    assert "yazses start" not in line, (
        "doctor told a running daemon to start; it is already running"
    )
    assert "yazses restart" in line, "the stale daemon's actual fix must be named"


def test_the_daemon_check_and_the_verdict_cannot_drift_apart():
    """The verdict reads the detail the daemon check writes; pin them together.

    A guard against the same defect returning by a different route: if a running
    branch of `_daemon_check` stops opening with the shared prefix, the verdict
    silently decides the daemon is stopped again.
    """
    import inspect

    source = inspect.getsource(doctor._daemon_check)
    running_returns = [
        ln for ln in source.splitlines()
        if "return (" in ln and "Daemon" in ln and "not running" not in ln
    ]
    assert running_returns, "no running branch found — has the check been rewritten?"
    for ln in running_returns:
        assert "_RUNNING_PREFIX" in ln, (
            f"a running branch hardcodes its prefix instead of sharing the constant "
            f"the verdict reads, so the two can drift: {ln.strip()}"
        )
