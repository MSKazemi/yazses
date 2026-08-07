"""Non-keyboard activation sources: the EMG backend is finally constructed.

The EMG squeeze-to-talk backend existed since v0.4.0 but no code path ever
built it — `[emg] device_port` was config that nothing read. These pin the new
daemon seam: `_build_activation_sources` constructs an `EMGBackend` when the
port is set, routes squeeze → command-mode callbacks (or plain hold-to-talk in
`full_text` mode), and shutdown stops every source.
"""
from __future__ import annotations

from dataclasses import replace

from yazses.config import Config, EmgConfig
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.platform.emg.backend import EMGBackend


def _daemon(**emg) -> Daemon:
    cfg = replace(Config(), emg=replace(EmgConfig(), **emg))
    return Daemon(config=cfg, platform=get_platform())


def test_no_port_builds_no_sources():
    d = _daemon()
    assert d._build_activation_sources(d._config) == []


def test_port_builds_emg_backend_in_command_mode():
    d = _daemon(device_port="/dev/ttyUSB0", mode="command")
    sources = d._build_activation_sources(d._config)
    assert len(sources) == 1
    backend = sources[0]
    assert isinstance(backend, EMGBackend)
    # A squeeze must arm force-command mode, exactly like the command key.
    assert backend._on_hold_start == d._on_command_hold_start
    assert backend._on_hold_end == d._on_command_hold_end


def test_full_text_mode_drives_plain_hold_to_talk():
    d = _daemon(device_port="/dev/ttyUSB0", mode="full_text")
    backend = d._build_activation_sources(d._config)[0]
    assert backend._on_hold_start == d._on_hold_start
    assert backend._on_hold_end == d._on_hold_end


def test_shutdown_stops_activation_sources():
    class _FakeSource:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True

    d = _daemon()
    source = _FakeSource()
    d._extra_activations = [source]
    d.shutdown()
    assert source.stopped


def test_a_failing_source_stop_never_breaks_shutdown():
    class _Exploding:
        def stop(self):
            raise RuntimeError("boom")

    d = _daemon()
    d._extra_activations = [_Exploding()]
    d.shutdown()  # must not raise
