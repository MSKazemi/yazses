"""The clipboard backend's X11 key paths must send what the xdotool backend sends.

On X11 ``ClipboardInjector`` shells out to xdotool for backspaces and key
sequences, but it carried its own copies of those argv lists, and they drifted
from ``XdotoolInjector``:

* backspaces went out **without** ``--clearmodifiers``. The daemon erases leaked
  characters at hold start, while the hold-to-talk modifier can still be
  physically down, so a held Ctrl turned each BackSpace into Ctrl+BackSpace and
  deleted whole words of the user's text instead of single characters.
  ``XdotoolInjector`` got this fix; the clipboard copy did not.
* key combos were not mapped ``meta`` -> ``super``. xdotool's ``meta`` is Meta_L,
  not the Windows/Super key (#544), so ``meta+k`` sent the wrong key.

These tests pin the clipboard path's argv to the xdotool backend's.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from yazses.inject.clipboard import ClipboardInjector


@pytest.fixture
def x11_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("yazses.inject.clipboard.subprocess.run", fake_run)
    return calls


def test_x11_backspaces_clear_held_modifiers(x11_calls: list[list[str]]) -> None:
    ClipboardInjector().inject_backspaces(3)

    assert len(x11_calls) == 1
    cmd = x11_calls[0]
    assert cmd[:2] == ["xdotool", "key"]
    assert "--clearmodifiers" in cmd
    assert cmd[-3:] == ["--repeat", "3", "BackSpace"]


def test_x11_key_sequence_maps_meta_to_super(x11_calls: list[list[str]]) -> None:
    ClipboardInjector().inject_key_sequence(["meta+k", "ctrl+v"])

    assert x11_calls == [["xdotool", "key", "--clearmodifiers", "super+k", "ctrl+v"]]


def test_x11_key_sequence_leaves_a_key_named_like_a_modifier_alone(x11_calls: list[list[str]]) -> None:
    # Token-wise mapping: only a ``meta`` *part* is rewritten, never a substring.
    ClipboardInjector().inject_key_sequence(["Meta_L", "shift+Left"])

    assert x11_calls == [["xdotool", "key", "--clearmodifiers", "Meta_L", "shift+Left"]]


def test_zero_backspaces_send_nothing(x11_calls: list[list[str]]) -> None:
    ClipboardInjector().inject_backspaces(0)

    assert x11_calls == []
