"""Doctor's serial-port check must not judge a Windows COM name as a file path.

``[emg] device_port = "COM3"`` is a correct Windows config. The old check was
``Path(port).exists()``, which is a question about the filesystem, so a COM name always
came out FAIL. A COM name cannot be checked by a file lookup, so the answer is SKIP ("will
be tried at start"), never OK and never FAIL. POSIX device paths keep the existence check:
a missing ``/dev/ttyUSB0`` still FAILs. Pure helpers only: no platform branch, no hardware.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from yazses.system import doctor


@pytest.mark.parametrize(
    "port",
    ["COM3", "COM12", "com3", "Com12", r"\\.\COM3", r"\\.\com3", r"\\.\COM12", " COM3 "],
)
def test_windows_com_names_are_skipped_not_failed(port):
    status, detail = doctor.serial_port_status(port)
    assert status == "SKIP"
    assert "cannot be checked this way" in detail
    assert "will be tried when YazSes starts" in detail


def test_com3_is_not_a_file_yet_the_row_is_not_fail(tmp_path, monkeypatch):
    """Reproduces the reported defect: nothing called COM3 exists on disk, and it must not FAIL."""
    monkeypatch.chdir(tmp_path)
    assert not Path("COM3").exists()
    row = doctor._emg_port_check("COM3")
    assert row is not None
    assert row[0] == "EMG serial port"
    assert row[1] == "SKIP"


@pytest.mark.parametrize("port", ["COMX", "COM", "/dev/COM3", "tty COM3", "COM3x"])
def test_names_that_are_not_com_ports_keep_the_file_check(port, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    status, detail = doctor.serial_port_status(port)
    assert status == "FAIL"
    assert "not found" in detail


def test_missing_dev_port_still_fails(tmp_path):
    missing = tmp_path / "ttyUSB0"
    status, detail = doctor.serial_port_status(str(missing))
    assert status == "FAIL"
    assert detail == f"{missing} not found"


def test_present_port_path_is_still_ok(tmp_path):
    present = tmp_path / "ttyUSB0"
    present.write_bytes(b"")
    status, detail = doctor.serial_port_status(str(present))
    assert status == "OK"
    assert detail == f"{present} accessible"


def test_emg_row_for_a_missing_dev_port_is_fail(tmp_path):
    row = doctor._emg_port_check(str(tmp_path / "ttyUSB0"))
    assert row is not None
    assert row[1] == "FAIL"


def test_no_port_configured_gives_no_row():
    assert doctor._emg_port_check("") is None
    assert doctor._emg_port_check("   ") is None
