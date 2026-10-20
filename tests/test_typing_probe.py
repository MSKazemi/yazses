"""The probe's protocol and parent-side logic, driven by a stub child (no display needed)."""
from __future__ import annotations

import sys
import textwrap

import pytest

from yazses.system import typing_probe as tp
from yazses.system.typing_canary import DELIVERED, NOT_DELIVERED, prove_delivery


def test_protocol_round_trips_awkward_text():
    for text in ["", "hello", 'quote " and \\ slash', "naïve café", "فارسی", "line\nbreak"]:
        assert tp.decode_event(tp.encode_event(tp.TEXT, text)) == (tp.TEXT, text)
    assert tp.decode_event(tp.encode_event(tp.FOCUSED)) == (tp.FOCUSED, "")


@pytest.mark.parametrize("noise", ["", "qt.qpa: something", 'TEXT not-json', "TEXT 42", "FOCUSEDX"])
def test_anything_that_is_not_ours_is_ignored(noise):
    assert tp.decode_event(noise) is None


def test_probe_available_names_the_missing_piece(monkeypatch):
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert "PySide6" in (tp.probe_available({"DISPLAY": ":0"}) or "")


def test_probe_available_reports_no_graphical_session(monkeypatch):
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr("yazses.system.graphical.has_graphical_session", lambda env, **k: False)
    assert "graphical" in (tp.probe_available({}) or "")


def _stub(script: str) -> list[str]:
    return [sys.executable, "-u", "-c", textwrap.dedent(script)]


def test_a_child_that_focuses_and_receives_text_is_delivered():
    stub = _stub(
        """
        import json, sys, time
        print("qt noise that must be ignored")
        print("FOCUSED")
        time.sleep(0.2)
        print("TEXT " + json.dumps("hello"))
        time.sleep(5)
        """
    )
    result = prove_delivery(
        "hello", open_probe=lambda: tp.SubprocessProbe(stub), type_text=lambda t: None,
        focus_timeout=5, text_timeout=5,
    )
    assert result.verdict == DELIVERED


def test_a_child_that_focuses_but_never_receives_text_is_not_delivered():
    stub = _stub('import time; print("FOCUSED"); time.sleep(5)')
    result = prove_delivery(
        "hello", open_probe=lambda: tp.SubprocessProbe(stub), type_text=lambda t: None,
        focus_timeout=5, text_timeout=0.4,
    )
    assert result.verdict == NOT_DELIVERED


def test_a_child_that_dies_without_focus_is_inconclusive_quickly():
    import time

    stub = _stub("import sys; sys.exit(1)")
    t0 = time.monotonic()
    result = prove_delivery(
        "hello", open_probe=lambda: tp.SubprocessProbe(stub), type_text=lambda t: None,
        focus_timeout=5, text_timeout=5,
    )
    assert result.verdict == "inconclusive"
    assert time.monotonic() - t0 < 4, "EOF must end the wait, not the full timeout"


def test_close_terminates_the_child():
    probe = tp.SubprocessProbe(_stub("import time; time.sleep(30)"))
    probe.close()
    assert probe._proc.poll() is not None
