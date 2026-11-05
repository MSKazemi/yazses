"""A stop requested while the daemon is still starting must be honoured.

`Daemon.shutdown()` only sets `_stop_event` and stops whatever hotkey exists. While the
speech model loads there is no hotkey yet, so the request found nothing to stop, and
`run()` -- which never looked at the event again -- went on to block in `hotkey.run()`
for good. `yazses stop` had already reported "stopped".

Pure fakes at the existing seams: no model, no microphone, no keyboard.
"""

from __future__ import annotations

import threading

import pytest

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform

_JOIN_S = 5.0

#: Everything `run()` starts after the pipeline exists, none of which this test is about.
_OPTIONAL_STARTUP = (
    "_maybe_launch_overlay", "_maybe_launch_tray", "_start_update_watcher",
    "_load_shown_notices", "_announce_permissions", "_announce_dormant_features",
    "_warm_portal_session", "_start_portal_idle_reaper", "_start_stt_idle_unloader",
    "_start_latency_pool_evictor", "_start_headpointer", "_start_gesture",
    "_start_morsevox",
)


class _Hotkey:
    key_id = "right_alt"

    def __init__(self) -> None:
        self.stopped = threading.Event()
        self.ran = threading.Event()

    def run(self) -> None:
        self.ran.set()
        self.stopped.wait()

    def stop(self) -> None:
        self.stopped.set()


def _daemon(monkeypatch, hotkey, *, stop_in_build=False, stop_in_startup=False):
    d = Daemon(config=Config(), platform=get_platform())
    shut_down = threading.Event()
    monkeypatch.setattr(d, "_start_ipc_server", lambda: None)
    monkeypatch.setattr(d, "_acquire_instance_lock", lambda: True)
    monkeypatch.setattr(d, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(d, "_configure_logging", lambda: None)
    monkeypatch.setattr(d, "_shutdown", shut_down.set)
    for name in _OPTIONAL_STARTUP:
        monkeypatch.setattr(d, name, lambda *a, **k: None)

    def build() -> None:
        if stop_in_build:
            d.shutdown()  # what SIGTERM or the IPC `shutdown` thread does mid-load
        d._hotkey = hotkey  # the build finishes afterwards: the hotkey exists now
        d._engine = d._recorder = d._injector = object()

    monkeypatch.setattr(d, "_build_pipeline", build)
    if stop_in_startup:
        # The window after the build: the hotkey exists, so `shutdown()` stops it --
        # before it has run, which a real listener may not remember.
        monkeypatch.setattr(d, "_start_morsevox", lambda: d.shutdown())
    return d, shut_down


def _run(d):
    t = threading.Thread(target=d.run, daemon=True, name="test-daemon-run")
    t.start()
    return t


@pytest.mark.parametrize("where", ["during_model_load", "after_load_before_listen"])
def test_a_stop_requested_during_startup_is_honoured(monkeypatch, sandbox_paths, where):
    hk = _Hotkey()
    d, shut_down = _daemon(
        monkeypatch,
        hk,
        stop_in_build=where == "during_model_load",
        stop_in_startup=where == "after_load_before_listen",
    )
    if where == "after_load_before_listen":
        # A listener that, like the real ones, forgets a stop that came before `run()`.
        monkeypatch.setattr(hk, "stop", lambda: None)
    t = _run(d)
    t.join(_JOIN_S)
    alive = t.is_alive()
    hk.stopped.set()  # let a failing run end cleanly
    t.join(_JOIN_S)
    assert not alive, "the daemon ignored a stop requested during start-up; hotkey.run() blocks"
    assert not hk.ran.is_set(), "the listener was started after a stop had been requested"
    assert shut_down.is_set(), "run()'s finally did not tear the daemon down"


def test_control_a_stop_after_the_listener_started_still_ends_run(monkeypatch, sandbox_paths):
    hk = _Hotkey()
    d, shut_down = _daemon(monkeypatch, hk)
    t = _run(d)
    assert hk.ran.wait(_JOIN_S), "the listener never started"
    d.shutdown()
    t.join(_JOIN_S)
    alive = t.is_alive()
    hk.stopped.set()
    assert not alive
    assert shut_down.is_set()
