"""The wiring that makes the market-device sources reachable (round 4).

Each device module has its own test file (`test_biosignal_lsl.py`, `..._thinkgear.py`,
`..._bitalino.py`, `..._myo.py`, `..._edf.py`, `..._xdf.py`, `..._integrity.py`,
`..._conformance.py`). This file pins only the seams between them and the rest of the package:
`open_source` dispatches every scheme without opening hardware, `FileReplaySource` reads
EDF/BDF by extension and carries their labels, `RecordingTap` exports EDF, the daemon's
runner puts every source behind the integrity guard, `doctor` names the missing extra, and
`yazses biosignal check-source` reports. No device, port, radio or network is touched.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from yazses.biosignal import cli_impl
from yazses.biosignal.bitalino import BITalinoSource
from yazses.biosignal.cli_impl import FAILED, OK, UNUSABLE, run_check_source, run_evaluate
from yazses.biosignal.edf import write_edf
from yazses.biosignal.integrity import IntegrityGate, IntegrityGuard
from yazses.biosignal.lsl_source import LSLBlockSource
from yazses.biosignal.myo import MyoSource
from yazses.biosignal.runner import build_runner_from_config
from yazses.biosignal.sources import FileReplaySource, RecordingTap, SyntheticSource, open_source
from yazses.biosignal.thinkgear import ThinkGearSource
from yazses.biosignal.types import BioEvent, ChannelInfo, EventKind, SampleBlock, SignalKind
from yazses.config import BiosignalConfig, Config
from yazses.system.doctor import _biosignal_check


def _cfg(**bio) -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), **bio)
    return cfg


def _blocks(seconds: float = 4.0, fs: float = 250.0) -> list[SampleBlock]:
    rng = np.random.default_rng(7)
    chans = (ChannelInfo("Fp1", SignalKind.EEG), ChannelInfo("EMG1", SignalKind.EMG))
    n = int(seconds * fs)
    data = rng.normal(0.0, 10.0, (2, n))
    step = int(fs / 4)
    return [SampleBlock(data[:, i:i + step], fs, chans, i / fs) for i in range(0, n, step)]


# ---- open_source --------------------------------------------------------------------


@pytest.mark.parametrize(("spec", "cls"), [
    ("lsl:type=EEG", LSLBlockSource),
    ("lsl:OpenBCI_EEG", LSLBlockSource),
    ("thinkgear:/dev/rfcomm0", ThinkGearSource),
    ("bitalino:/dev/rfcomm1:A1=emg", BITalinoSource),
    ("myo:AA:BB:CC:DD:EE:FF", MyoSource),
])
def test_every_device_scheme_builds_without_opening_anything(spec, cls):
    """Construction is what `doctor` does on every run: it must not need the library."""
    src = open_source(spec)
    assert isinstance(src, cls)
    # An LSL stream's rate is learned when it resolves, at start(); the others are fixed.
    assert src.fs == 0.0 if cls is LSLBlockSource else src.fs > 0


def test_the_spec_help_names_every_scheme():
    with pytest.raises(ValueError) as err:
        open_source("nope:1")
    for scheme in ("synthetic", "file:", "brainflow:", "lsl:", "thinkgear:", "bitalino:", "myo:"):
        assert scheme in str(err.value)


def test_the_myo_spec_keeps_the_whole_mac_address():
    src = open_source("myo:AA:BB:CC:DD:EE:FF")
    assert "AA:BB:CC:DD:EE:FF" in repr(vars(src))


# ---- files --------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", [".edf", ".bdf"])
def test_a_recording_round_trips_through_edf_and_keeps_its_labels(tmp_path: Path, suffix):
    path = tmp_path / f"session{suffix}"
    blocks = _blocks()
    write_edf(path, blocks, events=[BioEvent(EventKind.DOUBLE_BLINK, 2.0)])
    src = FileReplaySource(path)
    assert src.fs == 250.0
    assert [c.kind for c in src.channels] == [SignalKind.EEG, SignalKind.EMG]
    assert src.duration >= 4.0
    truth = src.ground_truth()
    assert [e.kind for e in truth] == [EventKind.DOUBLE_BLINK]
    assert truth[0].t == pytest.approx(2.0, abs=0.01)
    src.start()
    first = src.read()
    assert first is not None and np.all(np.isfinite(first.data))


def test_a_csv_recording_has_no_embedded_labels(tmp_path: Path):
    csv = tmp_path / "s.csv"
    tap = RecordingTap(SyntheticSource("emg", duration=1.0, seed=1), csv)
    tap.start()
    with pytest.raises(EOFError):
        while True:
            tap.read()
    assert FileReplaySource(csv).ground_truth() == []


def test_the_recording_tap_exports_edf_that_replays(tmp_path: Path):
    path = tmp_path / "rec.edf"
    tap = RecordingTap(SyntheticSource("mixed", duration=2.0, seed=3), path)
    tap.start()
    with pytest.raises(EOFError):
        while True:
            tap.read()
    assert path.is_file()
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600
    replay = FileReplaySource(path)
    assert replay.duration >= 2.0
    assert len(replay.channels) == len(SyntheticSource("mixed").channels)


@pytest.mark.skipif(importlib.util.find_spec("pyxdf") is not None,
                    reason="checks the message shown when the xdf extra is missing")
def test_an_xdf_file_without_pyxdf_is_unusable_not_a_crash(tmp_path: Path):
    xdf = tmp_path / "r.xdf"
    xdf.write_bytes(b"XDF:")
    with pytest.raises(ImportError, match="xdf"):
        FileReplaySource(xdf)
    assert run_evaluate(_cfg(), tmp_path, file=str(xdf)) == UNUSABLE


def test_evaluate_uses_the_labels_inside_an_edf_file(tmp_path: Path, capsys):
    path = tmp_path / "labelled.edf"
    write_edf(path, _blocks(), events=[BioEvent(EventKind.DOUBLE_BLINK, 2.0)])
    code = run_evaluate(_cfg(), tmp_path, file=str(path), as_json=True)
    assert code == OK
    out = json.loads(capsys.readouterr().out)
    assert out["source"] == f"file {path}"


def test_evaluate_still_refuses_a_file_with_no_labels(tmp_path: Path):
    path = tmp_path / "unlabelled.edf"
    write_edf(path, _blocks())
    assert run_evaluate(_cfg(), tmp_path, file=str(path)) == UNUSABLE


# ---- the daemon's runner ------------------------------------------------------------


def test_the_runner_puts_every_source_behind_the_integrity_guard(tmp_path: Path):
    runner = build_runner_from_config(_cfg(enabled=True, source="synthetic:eog"),
                                      data_dir=tmp_path)
    assert runner is not None
    source = runner._source_factory()
    assert isinstance(source, IntegrityGuard)
    source.start()
    try:
        pipeline = runner._pipeline_factory(source)
        assert isinstance(pipeline._parts.quality, IntegrityGate)
    finally:
        source.stop()


# ---- doctor ---------------------------------------------------------------------------


@pytest.mark.parametrize(("spec", "module", "extra"), [
    ("lsl:type=EEG", "pylsl", "lsl"),
    ("thinkgear:/dev/rfcomm0", "serial", "emg"),
    ("bitalino:/dev/rfcomm0", "serial", "emg"),
    ("myo:AA:BB:CC:DD:EE:FF", "bleak", "ble"),
])
def test_doctor_names_the_extra_a_device_source_needs(tmp_path, monkeypatch, spec, module, extra):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a, **k: None if name == module else real(name, *a, **k))
    title, status, detail = _biosignal_check(_cfg(enabled=True, source=spec), tmp_path)
    assert status == "FAIL"
    assert module in detail and extra in detail


# ---- check-source ---------------------------------------------------------------------


def test_check_source_passes_a_recording(tmp_path: Path, capsys, monkeypatch):
    path = tmp_path / "ok.edf"
    write_edf(path, _blocks(seconds=3.0))
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: open_source(spec))
    assert run_check_source(_cfg(), source=f"file:{path}", seconds=2.0) == OK
    assert "pass" in capsys.readouterr().out.lower()


def test_check_source_fails_a_broken_stream(monkeypatch, capsys):
    class Backwards:
        fs = 100.0
        channels = (ChannelInfo("c", SignalKind.EMG),)

        def __init__(self):
            self.t = 0.0

        def start(self):
            self.t = 0.0

        def read(self):
            self.t -= 0.1          # time runs backwards
            return SampleBlock(np.zeros((1, 10)), self.fs, self.channels, self.t)

        def stop(self):
            return None

    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: Backwards())
    assert run_check_source(_cfg(), source="synthetic", seconds=1.0, as_json=True) == FAILED
    out = json.loads(capsys.readouterr().out)
    assert out["passed"] is False


def test_check_source_refuses_a_bad_spec_and_bad_seconds():
    assert run_check_source(_cfg(), source="nope:1") == UNUSABLE
    assert run_check_source(_cfg(), source="synthetic", seconds=0) == UNUSABLE
