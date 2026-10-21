"""A dictation into an administrator window goes to the clipboard, not into the void.

UIPI drops input from a normal process into an elevated one, and `SendInput` still
reports every event sent. Measured on Windows 11 22H2 with an elevated Task Manager in
front: 2/2 sent, GetLastError 0, nothing delivered. So the dictation vanished without
even a log line. The no-text-target guard now asks the platform first whether the focused
window will take our input at all (`platform/windows/integrity.py`).
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import replace

import pytest

from yazses.inject.target import TargetDetector
from yazses.platform.windows import integrity

MEDIUM, HIGH, SYSTEM = 0x2000, 0x3000, 0x4000


# ---- the rule UIPI applies --------------------------------------------------


@pytest.mark.parametrize(
    "ours, theirs, blocked",
    [
        (MEDIUM, HIGH, True),     # a normal YazSes, an elevated window: dropped
        (MEDIUM, SYSTEM, True),
        (MEDIUM, MEDIUM, False),  # the everyday case
        (HIGH, HIGH, False),      # YazSes run as administrator reaches admin windows
        (HIGH, MEDIUM, False),
        (None, HIGH, False),      # cannot tell is never a block (ADR-021)
        (MEDIUM, None, False),
    ],
)
def test_input_is_blocked_only_into_a_higher_integrity_level(ours, theirs, blocked):
    assert integrity.blocks_input(ours, theirs) is blocked


def _probe(monkeypatch, ours, theirs, fg_pid=4321):
    monkeypatch.setattr(integrity, "foreground_pid", lambda: fg_pid)
    levels = {os.getpid(): ours, fg_pid: theirs}
    monkeypatch.setattr(integrity, "process_integrity", lambda pid: levels.get(pid))
    return integrity.foreground_input_block()


def test_the_probe_names_an_elevated_foreground_window(monkeypatch):
    assert _probe(monkeypatch, MEDIUM, HIGH) == "elevated"


def test_the_probe_is_quiet_for_an_ordinary_window(monkeypatch):
    assert _probe(monkeypatch, MEDIUM, MEDIUM) is None


def test_the_probe_is_quiet_with_no_foreground_window(monkeypatch):
    assert _probe(monkeypatch, MEDIUM, HIGH, fg_pid=None) is None


def test_the_probe_is_quiet_when_a_level_cannot_be_read(monkeypatch):
    assert _probe(monkeypatch, MEDIUM, None) is None


@pytest.mark.skipif(sys.platform != "win32", reason="reads a real process token")
def test_our_own_integrity_level_is_readable_on_windows():
    level = integrity.process_integrity(os.getpid())
    assert level is not None and level >= MEDIUM


@pytest.mark.skipif(sys.platform == "win32", reason="the off-Windows answer")
def test_off_windows_nothing_is_readable_and_nothing_is_blocked():
    assert integrity.process_integrity(os.getpid()) is None
    assert integrity.foreground_input_block() is None


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows platform bundle")
def test_the_windows_platform_offers_the_probe():
    from yazses.platform.windows import build_platform

    assert build_platform().input_block_probe is integrity.foreground_input_block


# ---- the detector -------------------------------------------------------------


def test_a_block_is_a_definite_no_and_says_why():
    d = TargetDetector(xdotool_fn=lambda: True, block_probe=lambda: "elevated")
    assert d.resolve() is False
    assert d.last_block_reason == "elevated"


def test_without_a_block_the_usual_answer_stands():
    d = TargetDetector(xdotool_fn=lambda: None, block_probe=lambda: None)
    assert d.resolve() is None
    assert d.last_block_reason is None


def test_a_probe_that_raises_is_cannot_tell_not_a_block():
    def boom():
        raise OSError("token gone")

    d = TargetDetector(xdotool_fn=lambda: None, block_probe=boom)
    assert d.resolve() is None
    assert d.last_block_reason is None


def test_the_reason_does_not_outlive_its_dictation():
    answers = iter(["elevated", None])
    d = TargetDetector(xdotool_fn=lambda: None, block_probe=lambda: next(answers))
    d.resolve()
    d.resolve()
    assert d.last_block_reason is None


# ---- the daemon ---------------------------------------------------------------


def _daemon(mocker, guard):
    from yazses.config import Config, InjectionConfig
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = replace(Config(), injection=InjectionConfig(target_guard=guard))
    d = Daemon(config=cfg, platform=get_platform())
    d._notify_mic = mocker.MagicMock()
    d._state.target_ok = False
    d._state.target_block = "elevated"
    return d


def test_clipboard_mode_saves_the_words_and_names_the_real_cause(mocker):
    d = _daemon(mocker, "clipboard")
    set_clip = mocker.patch("yazses.system.clipboard.set_clipboard", return_value=True)
    assert d._handle_no_target("hello") is True  # nothing typed into the void
    set_clip.assert_called_once_with("hello")
    title, body = d._notify_mic.call_args.args[:2]
    assert "administrator" in body and "Ctrl+V" in body
    assert "No text field" not in body  # the field is right there; that is not the cause


def test_warn_mode_still_types_but_says_nothing_will_appear(mocker):
    d = _daemon(mocker, "warn")
    set_clip = mocker.patch("yazses.system.clipboard.set_clipboard")
    assert d._handle_no_target("hello") is False
    set_clip.assert_not_called()
    assert "administrator" in d._notify_mic.call_args.args[1]


def test_the_detector_reason_reaches_the_daemon_state(mocker):
    d = _daemon(mocker, "clipboard")
    d._state.target_block = None
    d._target_detector = TargetDetector(xdotool_fn=lambda: True, block_probe=lambda: "elevated")
    d._command_mode = False
    d._detect_target_async()
    deadline = time.monotonic() + 2
    while d._state.target_ok is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert (d._state.target_ok, d._state.target_block) == (False, "elevated")
