"""While `yazses remote` was connected, dictation was typed on the LOCAL machine.

`Daemon._active_injector()` picked the remote injector only while the tray state was
`REMOTE_ACTIVE`. That state is set once, when the SSH tunnel comes up, and a hold-to-talk
burst then moves it through `RECORDING` and `TRANSCRIBING`. `_on_hold_end` sets `INJECTING`
on the line before it asks for the injector. So by the time any dictated text was injected
the state could never be `REMOTE_ACTIVE`: every word went to the local injector, into
whatever window had focus on the client, while the user watched the remote screen.

`tests/test_status_reports_remote_forwarding.py` already records that `state` cannot stand
in for "a remote session is up". The injector choice relied on it anyway. It now uses the
session itself: the remote injector exists exactly while a session is connected, because
`_handle_remote_start` sets it and `_handle_remote_stop` clears it.
"""

from __future__ import annotations

import threading

import pytest

from yazses.core.daemon import Daemon, TrayState, _DaemonState


class _Injector:
    def __init__(self, name: str) -> None:
        self.name = name

    def inject(self, text: str) -> None:  # pragma: no cover - identity is what matters
        pass


def _daemon(*, remote: bool) -> tuple[Daemon, _Injector, _Injector]:
    daemon = Daemon.__new__(Daemon)
    daemon._lock = threading.RLock()
    daemon._state = _DaemonState()
    local, far = _Injector("local"), _Injector("remote")
    daemon._injector = local
    daemon._remote_injector = far if remote else None
    daemon._remote_forwarder = None
    if remote:
        daemon._state.state = TrayState.REMOTE_ACTIVE
    return daemon, local, far


@pytest.mark.parametrize(
    "state",
    [TrayState.RECORDING, TrayState.TRANSCRIBING, TrayState.INJECTING, TrayState.IDLE],
)
def test_a_dictation_burst_during_a_remote_session_is_forwarded(state) -> None:
    """Every state a burst passes through must still pick the remote injector."""
    daemon, _local, far = _daemon(remote=True)
    daemon._state.state = state

    assert daemon._active_injector() is far


def test_the_state_the_injection_site_sets_still_forwards() -> None:
    """`_on_hold_end` sets INJECTING and then asks for the injector, in that order."""
    daemon, _local, far = _daemon(remote=True)
    with daemon._lock:
        daemon._state.state = TrayState.INJECTING

    assert daemon._active_injector() is far


def test_without_a_remote_session_dictation_stays_local() -> None:
    daemon, local, _far = _daemon(remote=False)
    for state in (TrayState.IDLE, TrayState.RECORDING, TrayState.INJECTING):
        daemon._state.state = state
        assert daemon._active_injector() is local


def test_after_remote_stop_dictation_is_local_again() -> None:
    """`_handle_remote_stop` clears the injector; nothing must keep forwarding after it."""
    daemon, local, _far = _daemon(remote=True)
    daemon._remote_injector = None
    daemon._state.state = TrayState.INJECTING

    assert daemon._active_injector() is local
