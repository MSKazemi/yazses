"""Source-specific behaviour of the biosignal CLI: squeeze expectation and monitor's integrity gate.

``squeeze_expected`` decides whether doctor asks for a muscle-squeeze calibration. A
ThinkGear headset is one EEG forehead electrode, so it must not ask. ``monitor`` wraps its
source in the same stream-integrity guard the daemon uses, so a stream whose timestamps go
backwards closes the event gate in monitor too.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from yazses.biosignal import cli_impl
from yazses.biosignal.cli_impl import OK, run_monitor, squeeze_expected
from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind
from yazses.config import Config


@pytest.fixture
def cfg() -> Config:
    """A default config: biosignal off, no source."""
    return Config()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


class TimedSource:
    """A finite fake source whose block timestamps are given explicitly.

    It carries two EMG-labelled channels at 250 Hz of low-level noise, so the signal-quality
    monitor judges it on its own merits and any integrity verdict comes from the timestamps.
    """

    def __init__(self, t0s: list[float]) -> None:
        self.fs = 250.0
        self.channels = (ChannelInfo("ch1", SignalKind.EMG), ChannelInfo("ch2", SignalKind.EMG))
        self.available = True
        self.last_error = ""
        self._t0s = list(t0s)
        self._rng = np.random.default_rng(0)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def read(self) -> SampleBlock:
        if not self._t0s:
            raise EOFError
        t0 = self._t0s.pop(0)
        return SampleBlock(self._rng.normal(0.0, 10.0, (2, 50)), 250.0, self.channels, t0)


def _clean_t0s() -> list[float]:
    return [0.2 * k for k in range(40)]


def _backwards_t0s() -> list[float]:
    # Eight good blocks, then the timestamp jumps back to 0.0, then a monotonic run again.
    return [0.2 * k for k in range(8)] + [0.0] + [0.2 * k for k in range(1, 30)]


# ---------------------------------------------------------------------------
# squeeze_expected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", ["thinkgear:/dev/ttyUSB0", "thinkgear:COM3", "THINKGEAR:x"])
def test_thinkgear_headset_has_no_muscle_squeeze(spec):
    """One EEG forehead electrode: a squeeze calibration cannot apply, so none is asked for."""
    assert squeeze_expected(spec) is False


def test_muse_board_still_has_no_muscle_squeeze():
    """The EEG-only BrainFlow board the table lists (Muse 2, id 38) stays False."""
    assert squeeze_expected("brainflow:38") is False


@pytest.mark.parametrize("spec", ["myo:", "bitalino:", "lsl:", "file:/tmp/rec.csv"])
def test_sources_with_muscle_channels_expect_a_squeeze(spec):
    assert squeeze_expected(spec) is True


# ---------------------------------------------------------------------------
# monitor
# ---------------------------------------------------------------------------


def test_monitor_synthetic_with_a_time_limit_still_exits_ok(cfg, data_dir, capsys):
    """The synthetic demo is paced by the harness, so it is exempt from the arrival check."""
    assert run_monitor(cfg, data_dir, source="synthetic", seconds=1.0, interval=0.2) == OK
    out = capsys.readouterr().out
    assert "Stopped (time limit reached)" in out
    assert "stream integrity" not in out


def test_monitor_clean_stream_shows_no_integrity_message(cfg, data_dir, monkeypatch, caplog, capsys):
    """A monotonic stream keeps the gate open: no integrity warning is logged."""
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: TimedSource(_clean_t0s()))
    with caplog.at_level("WARNING", logger="yazses.biosignal.integrity"):
        assert run_monitor(cfg, data_dir, source="fakeclean:", seconds=0.0, interval=0.2) == OK
    assert "Stopped (end of recording)" in capsys.readouterr().out
    assert "stream integrity" not in caplog.text


def test_monitor_closes_the_gate_when_t0_goes_backwards(cfg, data_dir, monkeypatch, caplog, capsys):
    """A backwards timestamp is a stream-integrity violation: monitor logs it and holds events.

    The integrity warning goes to the ``yazses.biosignal.integrity`` logger, not stdout. The
    hold itself (``suppress_events`` for the next second of data) was checked by probing the
    gate block by block; this test pins the logged violation and the run's clean exit.
    """
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: TimedSource(_backwards_t0s()))
    with caplog.at_level("WARNING", logger="yazses.biosignal.integrity"):
        assert run_monitor(cfg, data_dir, source="fakejump:", seconds=0.0, interval=0.2) == OK
    assert "stream integrity: t0_backwards" in caplog.text
    assert "events are held until the stream has been clean" in caplog.text
    assert "Detections:" in capsys.readouterr().out
