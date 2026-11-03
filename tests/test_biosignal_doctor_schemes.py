"""`yazses doctor`'s biosignal row, for the four non-BrainFlow sources and the count-unit armbands.

The row must say what is true for each scheme, and it must never open hardware: these tests
only check the spec, the serial port path and the installed packages (the package lookup is
pinned, so the result does not depend on which extras this machine has).
"""

from __future__ import annotations

import dataclasses
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yazses.config import BiosignalConfig, Config
from yazses.system.doctor import _biosignal_check

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def _cfg(**bio) -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), enabled=True, **bio)
    return cfg


@pytest.fixture
def libs_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every optional package reported as installed, so only the spec decides the row."""
    real = importlib.util.find_spec

    def fake(name, *args, **kwargs):
        if name in {"pylsl", "serial", "bleak", "brainflow"}:
            return object()
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake)


def _row(source: str, tmp_path: Path):
    return _biosignal_check(_cfg(source=source), tmp_path, brainflow_present=True, now=NOW)


def test_thinkgear_without_a_port_names_the_port(libs_present, tmp_path):
    status, detail = _row("thinkgear:", tmp_path)[1:3]
    assert status != "OK"
    assert "needs a serial port" in detail
    assert "thinkgear:/dev/ttyUSB0" in detail


def test_bitalino_without_a_port_names_the_port(libs_present, tmp_path):
    status, detail = _row("bitalino:", tmp_path)[1:3]
    assert status != "OK"
    assert "needs a serial port" in detail


def test_a_serial_port_that_is_not_there_is_reported_for_thinkgear(libs_present, tmp_path):
    missing = tmp_path / "rfcomm9"
    status, detail = _row(f"thinkgear:{missing}", tmp_path)[1:3]
    assert status == "WARN"
    assert f"serial port {missing} is not there" in detail


def test_a_thinkgear_with_a_real_port_gets_the_channel_advice(libs_present, tmp_path):
    port = tmp_path / "rfcomm0"
    port.write_text("", encoding="utf-8")
    status, detail = _row(f"thinkgear:{port}", tmp_path)[1:3]
    assert status == "OK"
    assert "neurosky-thinkgear: 1 channel at 512 Hz (Fp1)" in detail


def test_bitalino_with_a_real_port_gets_its_channel_advice(libs_present, tmp_path):
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")
    status, detail = _row(f"bitalino:{port}", tmp_path)[1:3]
    assert status != "FAIL"   # a missing calibration is a true WARN for a bitalino (squeeze)
    assert "bitalino: up to 6 analog channels at up to 1000 Hz" in detail


@pytest.mark.parametrize("source", ["thinkgear:<port>", "bitalino:<port>", "myo:<address>"])
def test_a_template_still_holding_its_placeholder_is_not_ok(libs_present, tmp_path, source):
    status, detail = _row(source, tmp_path)[1:3]
    assert status != "OK"
    assert "placeholder" in detail


def test_myo_says_its_values_are_counts(libs_present, tmp_path):
    status, detail = _row("myo:AA:BB:CC:DD:EE:FF", tmp_path)[1:3]
    assert status != "FAIL"   # a missing calibration profile is a WARN, not a problem with the spec
    assert "myo: 8 EMG channels at 200 Hz, as counts (not microvolts)" in detail
    assert "absolute amplitude checks are skipped" in detail


def test_lsl_is_described_without_inventing_a_rate_or_kind(libs_present, tmp_path):
    status, detail = _row("lsl:type=EEG", tmp_path)[1:3]
    assert status != "FAIL"
    assert "lsl-stream" in detail
    assert "channels, rate and kind come from the stream" in detail
    assert "mixed" not in detail


def test_gforce_through_brainflow_says_its_values_are_counts(libs_present, tmp_path):
    status, detail = _row("brainflow:16", tmp_path)[1:3]
    assert status != "FAIL"
    assert "counts, not microvolts" in detail


def test_a_brainflow_eeg_board_is_not_described_as_counts(libs_present, tmp_path):
    status, detail = _row("brainflow:38", tmp_path)[1:3]
    assert status == "OK"
    assert "counts" not in detail


def test_an_unfilled_myo_address_names_what_is_missing_with_a_real_example(libs_present, tmp_path):
    """`myo:<address>` used to stop at the parser ("has no valid address") with the generic fix."""
    status, detail = _row("myo:<address>", tmp_path)[1:3]
    assert status == "WARN"
    assert "still holds a placeholder (myo:<address>)" in detail
    assert "no Bluetooth address is set" in detail
    assert "myo:AA:BB:CC:DD:EE:FF" in detail
    assert "has no valid address" not in detail


def test_a_myo_address_that_is_wrong_rather_than_unfilled_still_fails(libs_present, tmp_path):
    status, detail = _row("myo:not-an-address", tmp_path)[1:3]
    assert status == "FAIL"
    assert "is not usable" in detail


# -- a Windows port: the drive letter is not the port ----------------------------------------
#
# CI on windows-latest failed `...not_there_is_reported_for_thinkgear` because tmp_path there is
# `C:\Users\...`, and the doctor split the spec at its FIRST colon, reading the port as `C`.
# The source parsers split at the last colon (options are `key=value`), so they keep the drive
# letter. These use literal Windows-style strings so the defect reproduces on any platform.

WIN_MISSING = r"C:\yazses-no-such-dir\rfcomm9"


@pytest.mark.parametrize("scheme", ["thinkgear", "bitalino"])
def test_a_windows_drive_path_that_is_not_there_is_reported(libs_present, tmp_path, scheme):
    status, detail = _row(f"{scheme}:{WIN_MISSING}", tmp_path)[1:3]
    assert status == "WARN"
    assert f"serial port {WIN_MISSING} is not there" in detail


@pytest.mark.parametrize("scheme", ["thinkgear", "bitalino"])
def test_options_after_a_windows_drive_path_do_not_hide_it(libs_present, tmp_path, scheme):
    option = "baud=57600" if scheme == "thinkgear" else "baud=115200"
    status, detail = _row(f"{scheme}:{WIN_MISSING}:{option}", tmp_path)[1:3]
    assert status == "WARN"
    assert f"serial port {WIN_MISSING} is not there" in detail


@pytest.mark.parametrize("port", ["COM3", "com12", r"\\.\COM3"])
@pytest.mark.parametrize("scheme", ["thinkgear", "bitalino"])
def test_a_windows_com_name_is_not_called_missing(libs_present, tmp_path, scheme, port):
    """A COM name is not a file; a file lookup would wrongly call it missing."""
    detail = _row(f"{scheme}:{port}", tmp_path)[2]
    assert "is not there" not in detail


@pytest.mark.parametrize(
    ("port", "expected"),
    [("/dev/ttyUSB0", True), (r"C:\dev\x", True), ("c:/dev/x", True),
     ("COM3", False), (r"\\.\COM3", False), ("", False), ("C", False)],
)
def test_which_ports_are_paths_whose_existence_can_be_checked(port, expected):
    from yazses.system.doctor import port_is_a_path

    assert port_is_a_path(port) is expected


def test_the_doctor_reads_the_port_the_way_the_source_parser_does():
    from yazses.biosignal.thinkgear import parse_thinkgear_spec
    from yazses.system.doctor import _spec_port

    spec = rf"thinkgear:{WIN_MISSING}:baud=57600"
    assert _spec_port("thinkgear", spec) == parse_thinkgear_spec(spec)["port"] == WIN_MISSING
    assert _spec_port("thinkgear", "thinkgear:/dev/ttyUSB0") == "/dev/ttyUSB0"
    assert _spec_port("thinkgear", "thinkgear:") == ""            # unparsable: falls back, no raise
