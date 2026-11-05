"""Writers of the tray state must not forget a running meeting or an in-flight burst.

Several places set `TrayState.IDLE` / `RECORDING` unconditionally. This file pins the ones
that were fixed:

* a dictation burst during a meeting overwrote MEETING with RECORDING and ended in IDLE,
  so the tray believed the meeting was over and the device monitor was told it was safe
  to re-initialise PortAudio under the meeting's live input stream. The burst now returns
  to MEETING, and the device monitor's idle checks count a running meeting;
* `remote_stop` (and a failed `remote_start`, on its own thread) set IDLE whatever the
  daemon was doing, cancelling a recording in progress. Both now reset only the remote
  session's own states.

What it does NOT pin, because the code still does it: `_on_hold_start` sets RECORDING
unconditionally (a burst during a meeting is restored afterwards, not prevented), and
`_handle_remote_start` still sets REMOTE_SETUP -- and its success path REMOTE_ACTIVE --
without comparing the current state first.
"""

from __future__ import annotations

import types

import numpy as np
import pytest

from yazses.audio.device_monitor import DeviceMonitor
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request
from yazses.platform import get_platform
from yazses.platform.base import TrayState


class _Rec:
    def start(self):
        pass

    def stop(self):
        return np.full(16000, 0.5, dtype="float32")


class _Eng:
    def transcribe(self, *a, **k):
        return "hello world"


class _Inj:
    def inject(self, t):
        pass

    def inject_backspaces(self, n):
        pass

    def inject_key_sequence(self, k):
        pass


def _daemon(mocker):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder, d._engine, d._padding_buffer, d._injector = _Rec(), _Eng(), None, _Inj()
    d._earcon = mocker.MagicMock()
    d._state.ready = True
    return d


def _in_a_meeting(d, mocker):
    d._meeting_controller = mocker.MagicMock()
    d._meeting_recorder = mocker.MagicMock()
    d._state.state = TrayState.MEETING


def test_a_dictation_burst_during_a_meeting_returns_to_meeting(mocker, sandbox_paths):
    d = _daemon(mocker)
    _in_a_meeting(d, mocker)
    d._on_hold_start(0)
    assert d._state.state is TrayState.RECORDING
    d._on_hold_end()
    assert d._state.state is TrayState.MEETING, d._state.state
    assert not d._audio_idle(), "the device monitor may re-init PortAudio under the meeting"
    assert d._recording_in_flight()


def test_control_a_burst_with_no_meeting_returns_to_idle(mocker, sandbox_paths):
    d = _daemon(mocker)
    d._on_hold_start(0)
    d._on_hold_end()
    assert d._state.state is TrayState.IDLE
    assert d._audio_idle()
    assert not d._recording_in_flight()


def test_an_unavailable_microphone_during_a_meeting_does_not_end_the_meeting_state(
    mocker, sandbox_paths
):
    mocker.patch("yazses.system.notify.notify")
    d = _daemon(mocker)
    _in_a_meeting(d, mocker)
    d._recorder.start = mocker.MagicMock(side_effect=OSError("device busy"))
    d._on_hold_start(0)
    assert d._state.state is TrayState.MEETING, d._state.state


def test_a_meeting_alone_makes_the_audio_busy_whatever_the_state_reads(mocker, sandbox_paths):
    d = _daemon(mocker)
    _in_a_meeting(d, mocker)
    d._state.state = TrayState.IDLE  # a stray writer got there first
    assert not d._audio_idle()
    assert d._recording_in_flight()


def test_the_device_monitor_does_not_reinit_portaudio_after_a_burst_in_a_meeting(
    mocker, sandbox_paths
):
    d = _daemon(mocker)
    _in_a_meeting(d, mocker)
    reinits: list[int] = []
    mon = DeviceMonitor(
        poll_fn=lambda: reinits.append(1) or "mic",
        is_idle=d._audio_idle,
        on_change=lambda a, b: None,
        recording=d._recording_in_flight,
    )
    mon.poll_once()
    assert not reinits, "sanity: no re-init while the meeting shows MEETING"
    d._on_hold_start(0)
    d._on_hold_end()
    mon.poll_once()
    assert not reinits, "PortAudio was re-initialised under the live meeting stream"


@pytest.mark.parametrize(
    "state", [TrayState.RECORDING, TrayState.TRANSCRIBING, TrayState.MEETING]
)
def test_remote_stop_leaves_a_busy_state_alone(mocker, sandbox_paths, state):
    d = _daemon(mocker)
    if state is TrayState.MEETING:
        _in_a_meeting(d, mocker)
    d._state.state = state
    reply = d._handle_remote_stop(Request(method="remote_stop", params={}, id=1))
    assert reply["ok"] is True
    assert d._state.state is state, d._state.state


@pytest.mark.parametrize("state", [TrayState.REMOTE_SETUP, TrayState.REMOTE_ACTIVE])
def test_control_remote_stop_ends_a_remote_session(mocker, sandbox_paths, state):
    d = _daemon(mocker)
    d._state.state = state
    d._handle_remote_stop(Request(method="remote_stop", params={}, id=1))
    assert d._state.state is TrayState.IDLE


def test_remote_stop_during_a_remote_session_inside_a_meeting_restores_meeting(
    mocker, sandbox_paths
):
    d = _daemon(mocker)
    _in_a_meeting(d, mocker)
    d._state.state = TrayState.REMOTE_ACTIVE
    d._handle_remote_stop(Request(method="remote_stop", params={}, id=1))
    assert d._state.state is TrayState.MEETING


def test_a_failed_remote_connect_does_not_cancel_a_recording(mocker, sandbox_paths):
    d = _daemon(mocker)
    mocker.patch(
        "yazses.core.daemon.RemoteForwarder",
        side_effect=OSError("ssh: no route to host"),
    )
    started = {}

    class _Inline:
        """Run the connect thread's body synchronously, after the user began dictating."""

        def __init__(self, target, **_kw):
            started["target"] = target

        def start(self):
            pass

    # A stub namespace for the daemon module's own `threading` name, not a patch of
    # `threading.Thread` itself: that is the interpreter-wide class, and any other thread
    # created while it is replaced would silently never start.
    mocker.patch("yazses.core.daemon.threading", types.SimpleNamespace(Thread=_Inline))
    d._handle_remote_start(
        Request(method="remote_start", params={"host": "example.invalid"}, id=1)
    )
    assert d._state.state is TrayState.REMOTE_SETUP
    d._state.state = TrayState.RECORDING  # the user holds the key before the connect fails
    started["target"]()
    assert d._state.state is TrayState.RECORDING, d._state.state
    assert d._state.last_error
