"""Daemon 'no text target' guard: clipboard fallback vs warn, and status wiring."""
from __future__ import annotations

from dataclasses import replace

from yazses.config import Config, InjectionConfig
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request
from yazses.platform import get_platform


def _daemon(mocker, guard="clipboard"):
    cfg = replace(Config(), injection=InjectionConfig(target_guard=guard))
    d = Daemon(config=cfg, platform=get_platform())
    d._notify_mic = mocker.MagicMock()
    return d


def test_clipboard_action_copies_and_suppresses(mocker):
    d = _daemon(mocker, "clipboard")
    set_clip = mocker.patch("yazses.system.clipboard.set_clipboard", return_value=True)
    suppressed = d._handle_no_target("hello world")
    assert suppressed is True                       # injection is skipped
    set_clip.assert_called_once_with("hello world")
    assert d._notify_mic.call_count == 1


def test_warn_action_notifies_but_types(mocker):
    d = _daemon(mocker, "warn")
    set_clip = mocker.patch("yazses.system.clipboard.set_clipboard")
    suppressed = d._handle_no_target("hello")
    assert suppressed is False                       # caller still types
    set_clip.assert_not_called()
    assert d._notify_mic.call_count == 1


def test_clipboard_failure_still_suppresses_and_notifies(mocker):
    d = _daemon(mocker, "clipboard")
    mocker.patch("yazses.system.clipboard.set_clipboard", return_value=False)
    assert d._handle_no_target("x") is True          # still don't type into the wrong place
    assert d._notify_mic.call_count == 1


def test_detect_target_async_no_detector_sets_none(mocker):
    d = _daemon(mocker)
    d._target_detector = None
    d._detect_target_async()
    assert d._state.target_ok is None


def test_status_exposes_target_ok(mocker):
    d = _daemon(mocker)
    d._state.target_ok = False
    status = d._handle_status(Request(method="status", params={}, id=1))
    assert status["target_ok"] is False
