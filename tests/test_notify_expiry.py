"""A failure toast must clear itself unless it is asking you something.

Both daemon call sites sent **every** failure at `urgency="critical"`, and the freedesktop
spec exempts that level from expiry on purpose — an alert must not be missed. Applied to a
dictation burst that failed to inject, which is transient and already over, the result was
a pop-up outranking everything on screen, waiting for a click, with no button to click.
One real desktop accumulated 33 of them; see `test_notify_does_not_orphan.py` for the
process half of the same defect.

The rule now: **answerable → persistent; informational → self-clearing.**
"""
from __future__ import annotations

import pytest

from yazses.system import notify as N
from yazses.system.notify import NotifyAction, build_notify_argv, toast_policy


def test_an_informational_toast_expires():
    urgency, expire_ms = toast_policy(actionable=False)
    assert urgency == "normal", "critical is exempt from expiry — it would never clear"
    assert expire_ms and expire_ms > 0


def test_an_actionable_toast_does_not_expire():
    """It is waiting for an answer; a prompt that vanishes mid-read discards the question."""
    urgency, expire_ms = toast_policy(actionable=True)
    assert urgency == "critical"
    assert expire_ms is None


def test_the_expire_time_reaches_the_argv():
    argv = build_notify_argv("T", "B", expire_ms=10_000)
    assert "--expire-time" in argv
    assert argv[argv.index("--expire-time") + 1] == "10000"


def test_no_expire_time_when_none_is_asked_for():
    assert "--expire-time" not in build_notify_argv("T", "B")


def test_the_plain_path_passes_the_timeout_through(mocker):
    runner = mocker.MagicMock()
    N.notify("T", "B", available=True, actions_supported=False, runner=runner, expire_ms=7000)
    argv = runner.call_args.args[0]
    assert argv[argv.index("--expire-time") + 1] == "7000"


def test_the_actionable_path_never_carries_a_timeout(mocker):
    """Even if a caller passes one — `--wait` and an expiry are contradictory."""
    proc = mocker.MagicMock()
    proc.communicate.return_value = ("", "")
    spawner = mocker.MagicMock(return_value=proc)
    N.notify(
        "T",
        "B",
        actions=[NotifyAction("report", "Prepare a bug report")],
        available=True,
        actions_supported=True,
        spawner=spawner,
        spawn=False,
        expire_ms=7000,
    )
    argv = spawner.call_args.args[0]
    assert "--wait" in argv
    assert "--expire-time" not in argv


@pytest.mark.parametrize("site", ["_report_failure", "_notify_mic"])
def test_no_daemon_call_site_hardcodes_critical(site):
    """The policy must stay in one place — a second literal is how the two drift apart."""
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[1] / "src/yazses/core/daemon.py"
    ).read_text(encoding="utf-8")
    assert 'urgency="critical"' not in src, (
        "a daemon call site hardcodes critical again; route it through "
        "notify.toast_policy() so answerable and informational cannot drift apart"
    )
    assert src.count("toast_policy(") >= 2, "both notification call sites must use the policy"
