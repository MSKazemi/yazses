"""`yazses autostart disable` is remembered.

"Never set up" and "turned off on purpose" both look like a missing login entry. So
`yazses start` used to put a disabled autostart straight back (and tell the user to
run `yazses autostart disable` to undo it), and `doctor` listed the choice as
"1 problem to fix" on every run. See `system/autostart_choice.py`.
"""
from __future__ import annotations

import sys

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.system import doctor
from yazses.system.autostart_choice import (
    FILENAME,
    clear_opt_out,
    opted_out,
    record_opt_out,
)

runner = CliRunner()


# ---- the marker -------------------------------------------------------------


def test_no_choice_is_recorded_by_default(tmp_path):
    assert not opted_out(tmp_path)


def test_recording_then_clearing_round_trips(tmp_path):
    record_opt_out(tmp_path)
    assert opted_out(tmp_path)
    assert "autostart enable" in (tmp_path / FILENAME).read_text(encoding="utf-8")
    clear_opt_out(tmp_path)
    assert not opted_out(tmp_path)


def test_clearing_without_a_choice_is_a_no_op(tmp_path):
    clear_opt_out(tmp_path)
    assert not opted_out(tmp_path)


def test_recording_creates_a_missing_data_dir(tmp_path):
    data = tmp_path / "not-yet"
    record_opt_out(data)
    assert opted_out(data)


def test_a_directory_named_like_the_marker_is_not_a_choice(tmp_path):
    (tmp_path / FILENAME).mkdir()
    assert not opted_out(tmp_path)


# ---- the commands -----------------------------------------------------------


class _Lifecycle:
    def __init__(self, installed=False):
        self.installed = installed

    def is_autostart_installed(self):
        return self.installed

    def install_autostart(self):
        self.installed = True

    def uninstall_autostart(self):
        self.installed = False


class _Paths:
    def __init__(self, data_dir):
        self.data_dir = data_dir


class _Platform:
    def __init__(self, data_dir, installed=False):
        self.lifecycle = _Lifecycle(installed)
        self.paths = _Paths(data_dir)


@pytest.fixture
def platform(monkeypatch, tmp_path):
    p = _Platform(tmp_path, installed=True)
    monkeypatch.setattr(cli, "get_platform", lambda: p)
    return p


def test_disable_records_the_choice(platform, tmp_path):
    r = runner.invoke(cli.app, ["autostart", "disable"])
    assert r.exit_code == 0, r.output
    assert not platform.lifecycle.installed
    assert opted_out(tmp_path)


def test_enable_forgets_the_choice(platform, tmp_path):
    record_opt_out(tmp_path)
    platform.lifecycle.installed = False
    r = runner.invoke(cli.app, ["autostart", "enable"])
    assert r.exit_code == 0, r.output
    assert platform.lifecycle.installed
    assert not opted_out(tmp_path)


def test_disable_that_cannot_be_remembered_says_how_to_keep_it_off(platform, monkeypatch):
    def refuse(data_dir):
        raise PermissionError("read-only profile")

    monkeypatch.setattr("yazses.system.autostart_choice.record_opt_out", refuse)
    r = runner.invoke(cli.app, ["autostart", "disable"])
    assert r.exit_code == 0, r.output  # autostart IS off; only the memory failed
    assert "could not remember" in r.output
    assert "--no-autostart" in r.output


def test_status_names_the_choice_and_still_answers_no(platform, tmp_path):
    record_opt_out(tmp_path)
    platform.lifecycle.installed = False
    r = runner.invoke(cli.app, ["autostart", "status"])
    assert r.exit_code == 1  # "will it come back after a reboot?" is still "no"
    assert "you turned it off" in r.output


def test_status_without_a_choice_is_unchanged(platform):
    platform.lifecycle.installed = False
    r = runner.invoke(cli.app, ["autostart", "status"])
    assert r.exit_code == 1
    assert "will NOT come back" in r.output


# ---- doctor -----------------------------------------------------------------


@pytest.fixture
def on_linux(monkeypatch):
    # The row is only shown where doctor can describe the mechanism accurately.
    monkeypatch.setattr(sys, "platform", "linux")


def test_doctor_reports_the_choice_as_skipped_not_failed(on_linux, tmp_path):
    record_opt_out(tmp_path)
    label, status, detail = doctor._autostart_check(_Platform(tmp_path, installed=False))
    assert (label, status) == ("Starts at login", "SKIP")
    assert "autostart enable" in detail


def test_doctor_still_fails_a_missing_autostart_nobody_chose(on_linux, tmp_path):
    _, status, _ = doctor._autostart_check(_Platform(tmp_path, installed=False))
    assert status == "FAIL"


def test_doctor_reports_ok_when_autostart_is_back_whatever_the_marker_says(on_linux, tmp_path):
    record_opt_out(tmp_path)  # e.g. the installer re-added it
    _, status, _ = doctor._autostart_check(_Platform(tmp_path, installed=True))
    assert status == "OK"
