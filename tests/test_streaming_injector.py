"""Tests for StreamingInjector state machine (ADR-004)."""
from __future__ import annotations

from unittest.mock import MagicMock

from yazses.inject.streaming import StreamingInjector


def make_mock_injector():
    m = MagicMock()
    m.inject = MagicMock()
    m.inject_backspaces = MagicMock()
    m.inject_key_sequence = MagicMock()
    return m


def test_inject_partial_increments_counter():
    inj = make_mock_injector()
    si = StreamingInjector(inj)
    si.inject_partial("hello")
    assert si.chars_injected == 5
    si.inject_partial(" world")
    assert si.chars_injected == 11


def test_inject_partial_calls_injector():
    inj = make_mock_injector()
    si = StreamingInjector(inj)
    si.inject_partial("hi")
    inj.inject.assert_called_once_with("hi")


def test_commit_issues_shift_left_then_injects():
    inj = make_mock_injector()
    si = StreamingInjector(inj)
    si.inject_partial("hel")  # 3 chars
    si.inject_partial("lo")   # 2 more = 5 chars total
    si.commit("hello world")
    inj.inject_key_sequence.assert_called_once_with(["shift+Left"] * 5)
    inj.inject.assert_called_with("hello world")


def test_commit_resets_counter():
    inj = make_mock_injector()
    si = StreamingInjector(inj)
    si.inject_partial("test")
    si.commit("test final")
    assert si.chars_injected == 0


def test_commit_with_zero_chars_just_injects():
    inj = make_mock_injector()
    si = StreamingInjector(inj)
    si.commit("hello")
    inj.inject_key_sequence.assert_not_called()
    inj.inject.assert_called_once_with("hello")


def test_cancel_issues_backspaces():
    inj = make_mock_injector()
    si = StreamingInjector(inj)
    si.inject_partial("abc")  # 3 chars
    si.cancel()
    inj.inject_backspaces.assert_called_once_with(3)


def test_cancel_resets_counter():
    inj = make_mock_injector()
    si = StreamingInjector(inj)
    si.inject_partial("test")
    si.cancel()
    assert si.chars_injected == 0


def test_cancel_with_no_partial_is_noop():
    inj = make_mock_injector()
    si = StreamingInjector(inj)
    si.cancel()
    inj.inject_backspaces.assert_not_called()


def test_reset_clears_counter_without_injection():
    inj = make_mock_injector()
    si = StreamingInjector(inj)
    si.inject_partial("hello")
    si.reset()
    assert si.chars_injected == 0
    # reset() should NOT inject anything
    assert inj.inject_backspaces.call_count == 0
    assert inj.inject_key_sequence.call_count == 0
