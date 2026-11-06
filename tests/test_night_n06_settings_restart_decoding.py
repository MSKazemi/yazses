"""The settings window must decode `yazses restart`'s output as the child wrote it.

`SettingsWindow._run_restart` shells out to `yazses restart` and reports its stderr in
the window's hint when it fails. The CLI child calls
`system/streams.py::ensure_printable_streams`, which switches a piped stdout/stderr to
UTF-8 on a host whose locale encoding cannot carry its characters -- a Windows cp1252
host. The window decoded that output with ``text=True`` alone, i.e. the *locale*
encoding, so on that host:

* a byte cp1252 leaves undefined (0x81 -- the second byte of Cyrillic "с", U+0441) made
  ``subprocess.run`` raise UnicodeDecodeError, and the window reported
  "Restart failed -- 'charmap' codec can't decode ..." instead of the real reason;
* the same happened on a **successful** restart (exit 0) whose stdout carried such a
  byte ("●" is E2 97 8F), so a working restart was shown as a failure.

These tests need no Qt and no subprocess: `subprocess.run` is replaced by a fake that
decodes fixed UTF-8 bytes with whatever ``encoding``/``errors`` the caller passed,
falling back to cp1252 -- what ``text=True`` alone means on that Windows host -- so the
result does not depend on the machine running the suite.
"""

from __future__ import annotations

import subprocess

import pytest

from yazses.settingsui import app as settings_app
from yazses.settingsui.app import SettingsWindow

_REASON = "Не удалось запустить службу — с"  # contains "с" (UTF-8 D1 81)
_STARTED = "● YazSes started. Hold ctrl+alt to dictate."  # "●" is UTF-8 E2 97 8F


def _fake_run(returncode: int, *, stdout: str = "", stderr: str = "", seen: dict):
    def run(cmd, **kwargs):
        seen.update(kwargs)
        # What text=True alone decodes with on a Windows cp1252 host.
        encoding = kwargs.get("encoding") or "cp1252"
        errors = kwargs.get("errors") or "strict"
        return subprocess.CompletedProcess(
            cmd,
            returncode,
            stdout=stdout.encode("utf-8").decode(encoding, errors),
            stderr=stderr.encode("utf-8").decode(encoding, errors),
        )

    return run


@pytest.fixture
def no_real_command(monkeypatch):
    monkeypatch.setattr(settings_app, "command_for", lambda *a, **k: ["yazses", "restart"])


def test_a_failed_restart_reports_the_childs_own_utf8_reason(monkeypatch, no_real_command):
    seen: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run(1, stderr=_REASON, seen=seen))

    ok, detail = SettingsWindow._run_restart()

    assert ok is False
    assert detail == _REASON, detail
    assert "codec" not in detail


def test_a_successful_restart_with_non_cp1252_output_is_a_success(
    monkeypatch, no_real_command
):
    seen: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run(0, stdout=_STARTED, seen=seen))

    assert SettingsWindow._run_restart() == (True, "")


def test_the_restart_is_decoded_as_utf8_with_replacement(monkeypatch, no_real_command):
    """Pin the call itself: UTF-8 like the child, and never an exception on a bad byte."""
    seen: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run(0, seen=seen))

    SettingsWindow._run_restart()

    assert str(seen.get("encoding", "")).replace("-", "").lower() == "utf8"
    assert seen.get("errors") == "replace"
    assert seen.get("timeout") == 90


def test_an_exception_without_a_message_still_names_something(monkeypatch, no_real_command):
    def run(cmd, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(subprocess, "run", run)

    ok, detail = SettingsWindow._run_restart()

    assert ok is False
    assert detail == "TimeoutError"
