"""Unit tests for the parts of platform.windows that don't need pywin32 / Win32.

ctypes/pywin32 are not exercised here; the code that uses them imports them
lazily so the modules import cleanly on Linux. The PR-on-Windows CI matrix
exercises the actual hook + SendInput + named pipe path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yazses.platform.windows.hotkey import (
    VK_LCONTROL,
    VK_LMENU,
    VK_RCONTROL,
    VK_RMENU,
    VK_SPACE,
    resolve_key_id,
)
from yazses.platform.windows.injector import _utf16_units
from yazses.platform.windows.ipc import _pipe_name_from_path

# ---- Hotkey resolution -------------------------------------------------


def test_auto_resolves_to_right_ctrl_by_default():
    name, vk = resolve_key_id("auto")
    assert (name, vk) == ("right_ctrl", VK_RCONTROL)


def test_right_ctrl_distinct_from_left_ctrl():
    _, right = resolve_key_id("right_ctrl")
    _, left = resolve_key_id("left_ctrl")
    assert right == VK_RCONTROL
    assert left == VK_LCONTROL
    assert right != left


def test_right_alt_uses_right_menu_vk():
    # AltGr concern is documented; we still expose it for users who explicitly
    # want it. Right Alt = VK_RMENU on Windows.
    _, vk = resolve_key_id("right_alt")
    assert vk == VK_RMENU


def test_right_option_aliases_right_alt_for_xplatform_configs():
    _, alt = resolve_key_id("right_alt")
    _, opt = resolve_key_id("right_option")
    assert alt == opt


def test_left_alt_distinct_from_right_alt():
    _, left = resolve_key_id("left_alt")
    _, right = resolve_key_id("right_alt")
    assert left == VK_LMENU
    assert right == VK_RMENU
    assert left != right


def test_space_resolves():
    name, vk = resolve_key_id("space")
    assert (name, vk) == ("space", VK_SPACE)


def test_unknown_key_raises():
    with pytest.raises(ValueError):
        resolve_key_id("not-a-key")


# ---- UTF-16 encoding ---------------------------------------------------


def test_ascii_text_encodes_to_codepoints():
    assert _utf16_units("hi") == [ord("h"), ord("i")]


def test_emoji_encodes_to_surrogate_pair():
    # 🔴 = U+1F534 → high surrogate U+D83D + low surrogate U+DD34
    units = _utf16_units("🔴")
    assert len(units) == 2
    assert 0xD800 <= units[0] <= 0xDBFF
    assert 0xDC00 <= units[1] <= 0xDFFF


def test_empty_text_yields_no_units():
    assert _utf16_units("") == []


# ---- Named pipe naming -------------------------------------------------


def test_pipe_name_starts_with_pipe_prefix(monkeypatch):
    monkeypatch.setenv("USERNAME", "alice")
    monkeypatch.setenv("USER", "alice")
    name = _pipe_name_from_path(Path("C:/Users/alice/AppData/Roaming/yazses/daemon.sock"))
    assert name.startswith(r"\\.\pipe\yazses-")


def test_pipe_name_includes_path_stem(monkeypatch):
    monkeypatch.setenv("USERNAME", "alice")
    monkeypatch.setenv("USER", "alice")
    name = _pipe_name_from_path(Path("/tmp/custom.sock"))
    assert "custom" in name
