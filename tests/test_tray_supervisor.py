"""Tests for keeping the tray icon on screen for the whole session.

The icon is the only thing that says whether YazSes is listening, in command mode, or has
nowhere to type. Dictation keeps working without it, which is what makes a dead tray easy
to miss and worth supervising.
"""
from __future__ import annotations

import pytest

from yazses.tray.supervisor import DEFAULT_MAX_RELAUNCHES, decide


def test_a_running_tray_is_left_alone():
    decision = decide(alive=True, relaunches_so_far=0)

    assert decision.relaunch is False
    assert decision.give_up is False


def test_a_dead_tray_is_relaunched():
    decision = decide(alive=False, relaunches_so_far=0)

    assert decision.relaunch is True
    assert decision.reason


def test_a_tray_that_keeps_dying_is_eventually_left_alone():
    """No display or a missing Qt plugin cannot be fixed by spawning it again."""
    decision = decide(alive=False, relaunches_so_far=DEFAULT_MAX_RELAUNCHES)

    assert decision.relaunch is False
    assert decision.give_up is True
    assert "yazses tray" in decision.reason, "tell the user how to see the real error"


def test_the_relaunch_budget_is_not_spent_while_the_tray_is_healthy():
    """A long session with a live tray must not creep toward the give-up threshold."""
    for _ in range(DEFAULT_MAX_RELAUNCHES * 3):
        decision = decide(alive=True, relaunches_so_far=0)
        assert decision.relaunch is False
        assert decision.give_up is False


@pytest.mark.parametrize("n", range(DEFAULT_MAX_RELAUNCHES))
def test_relaunches_continue_up_to_the_budget(n):
    assert decide(alive=False, relaunches_so_far=n).relaunch is True


def test_the_budget_is_configurable():
    assert decide(alive=False, relaunches_so_far=1, max_relaunches=1).give_up is True
    assert decide(alive=False, relaunches_so_far=1, max_relaunches=99).relaunch is True


def test_the_daemon_stops_supervising_on_shutdown():
    """A supervisor that outlived shutdown would resurrect the tray after `yazses stop`."""
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    daemon = Daemon(config=Config(), platform=get_platform())
    assert not daemon._stop_event.is_set()

    daemon.shutdown()

    assert daemon._stop_event.is_set()
