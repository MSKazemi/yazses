"""Settings window apply-and-restart flow (#61). Fake IPC, no Qt, no daemon.

The rule under test throughout: the window may never claim a setting is live when
it is not. A zero exit code is not a running daemon, and a declined restart is a
state to keep showing, not an error to forget.
"""

from __future__ import annotations

import pytest

from yazses.settingsui.restart import (
    RestartState,
    apply_and_restart,
    describe_status,
)


def _flow(*, running=True, confirmed=True, restart_result=(True, ""), statuses=None,
          timeout=5.0):
    """Drive the flow with fakes; `statuses` is what `status()` returns per poll."""
    queue = list(statuses if statuses is not None else [{"state": "idle", "model": "base.en"}])
    calls = {"restart": 0, "status": 0, "slept": 0.0}

    def status():
        calls["status"] += 1
        return queue.pop(0) if queue else None

    def restart():
        calls["restart"] += 1
        if isinstance(restart_result, Exception):
            raise restart_result
        return restart_result

    clock = {"t": 0.0}

    def sleep(seconds):
        calls["slept"] += seconds
        clock["t"] += seconds

    outcome = apply_and_restart(
        is_running=lambda: running,
        confirm=lambda: confirmed,
        restart=restart,
        status=status,
        ready_timeout_s=timeout,
        poll_interval_s=0.5,
        sleep=sleep,
        now=lambda: clock["t"],
    )
    return outcome, calls


# ---- the happy path --------------------------------------------------------


def test_a_successful_restart_reports_the_state_read_back_over_ipc():
    outcome, calls = _flow()
    assert outcome.state is RestartState.RESTARTED
    assert "base.en" in outcome.message
    assert calls["restart"] == 1


def test_readiness_is_polled_rather_than_assumed():
    """A daemon that exits 0 is not a daemon that has loaded its model."""
    outcome, calls = _flow(statuses=[None, None, {"state": "idle", "model": "small.en"}])
    assert outcome.state is RestartState.RESTARTED
    assert calls["status"] >= 3, "should have kept polling until it answered"
    assert calls["slept"] > 0


# ---- declining is a state, not an error ------------------------------------


def test_declining_leaves_a_persistent_pending_hint():
    outcome, calls = _flow(confirmed=False)
    assert outcome.state is RestartState.PENDING
    assert outcome.needs_restart_hint is True
    assert calls["restart"] == 0, "declining must not restart anything"
    assert "take effect when you restart" in outcome.message


def test_a_successful_restart_clears_the_pending_hint():
    outcome, _ = _flow()
    assert outcome.needs_restart_hint is False


# ---- nothing running -------------------------------------------------------


def test_no_daemon_means_no_prompt_at_all():
    """Prompting would be a dialog whose only honest answer is 'nothing to do'."""
    prompted = []
    outcome = apply_and_restart(
        is_running=lambda: False,
        confirm=lambda: prompted.append(1) or True,
        restart=lambda: pytest.fail("must not restart"),
        status=lambda: None,
    )
    assert outcome.state is RestartState.NOT_RUNNING
    assert prompted == []
    assert "not running" in outcome.message


# ---- failure is reported, never dressed up ---------------------------------


def test_a_failing_restart_command_is_reported_with_its_message():
    outcome, _ = _flow(restart_result=(False, "another daemon holds the lock"))
    assert outcome.state is RestartState.FAILED
    assert "another daemon holds the lock" in outcome.message


def test_a_restart_that_raises_is_reported_not_propagated():
    """An exception reaching the Qt event loop is a crash dialog, not a message."""
    outcome, _ = _flow(restart_result=RuntimeError("permission denied"))
    assert outcome.state is RestartState.FAILED
    assert "permission denied" in outcome.message


def test_a_daemon_that_never_answers_is_a_failure_not_a_success():
    """The bug this prevents: 'Restarted!' over a daemon that died on startup."""
    outcome, _ = _flow(statuses=[], timeout=2.0)
    assert outcome.state is RestartState.FAILED
    assert "did not answer" in outcome.message


def test_a_status_call_that_raises_keeps_polling_then_fails_honestly():
    clock = {"t": 0.0}

    def status():
        raise ConnectionRefusedError("socket not there yet")

    outcome = apply_and_restart(
        is_running=lambda: True,
        confirm=lambda: True,
        restart=lambda: (True, ""),
        status=status,
        ready_timeout_s=2.0,
        poll_interval_s=0.5,
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
        now=lambda: clock["t"],
    )
    assert outcome.state is RestartState.FAILED
    assert "socket not there yet" in outcome.message


# ---- what the user reads ---------------------------------------------------


def test_status_description_names_the_state_and_model():
    assert describe_status({"state": "idle", "model": "base.en"}) == "Running (state idle, model base.en)."


def test_status_description_of_nothing_is_empty():
    assert describe_status(None) == ""
    assert describe_status({}) == ""


def test_a_partial_status_still_reads_as_a_sentence():
    assert describe_status({"state": "idle"}) == "Running (state idle)."
