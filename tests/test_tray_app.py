"""Tests for the tray poll loop's reaction to an unreachable daemon."""
from __future__ import annotations

from yazses.platform import TrayState
from yazses.tray.app import (
    _DAEMON_BOOT_TIMEOUT_S,
    _RECONNECT_GRACE_S,
    unreachable_decision,
)


def test_waiting_for_first_boot_keeps_polling() -> None:
    """The tray spawns the daemon, so a not-yet-listening socket is expected."""
    decision = unreachable_decision(ever_connected=False, waiting_s=1.0)

    assert decision.give_up is False
    assert decision.state is TrayState.IDLE
    assert decision.last_error == "daemon starting"


def test_daemon_that_never_boots_stops_the_poll() -> None:
    """Nothing ever answered — there is no daemon to poll, so stop."""
    decision = unreachable_decision(
        ever_connected=False, waiting_s=_DAEMON_BOOT_TIMEOUT_S + 1.0
    )

    assert decision.give_up is True


def test_restart_blip_does_not_stop_the_poll() -> None:
    """Regression: `yazses restart` must not permanently freeze the tray icon.

    The boot deadline used to be computed once when the poll thread started and never
    reset, so it also governed every later outage. Any tray older than the boot timeout
    — i.e. any tray in normal use — stopped polling on the first blip a restart caused,
    froze on whatever icon it had last drawn, and kept the single-instance lock so no
    replacement tray could start.
    """
    decision = unreachable_decision(
        ever_connected=True, waiting_s=_DAEMON_BOOT_TIMEOUT_S + 600.0
    )

    assert decision.give_up is False


def test_brief_outage_after_connecting_stays_calm() -> None:
    """A restart takes a second or two; the icon should not flash red for it."""
    decision = unreachable_decision(ever_connected=True, waiting_s=1.0)

    assert decision.give_up is False
    assert decision.state is TrayState.IDLE
    assert decision.last_error == "daemon restarting"


def test_prolonged_outage_after_connecting_shows_a_problem() -> None:
    """Past the grace period the daemon really is gone — say so instead of showing idle."""
    decision = unreachable_decision(
        ever_connected=True, waiting_s=_RECONNECT_GRACE_S + 1.0
    )

    assert decision.give_up is False
    assert decision.state is TrayState.ERROR
    assert decision.last_error == "daemon not responding"
