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
from yazses.platform.windows.injector import INJECTED_TAG, _utf16_units
from yazses.platform.windows.ipc import _pipe_name_from_path
from yazses.platform.windows.lifecycle import (
    resolve_daemon_command,
    resolve_tray_command,
)

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


# ---- Self-injection guard ----------------------------------------------


def test_injected_tag_is_non_zero():
    """The hook compares dwExtraInfo against this tag to skip our own
    SendInput traffic; a zero tag would match every real keypress."""
    assert INJECTED_TAG != 0


# ---- Lifecycle command resolution --------------------------------------


def test_frozen_daemon_command_uses_the_argv_dispatch_flag():
    """The regression that made a fresh .exe install do nothing.

    The bundle dispatches on argv; `-m yazses.main` matches no mode, falls
    through to the Typer CLI and exits non-zero parsing `-m`. Because the
    build is windowed, that failure is silent — the tray spawned nothing and
    reported "not running" forever.
    """
    argv = resolve_daemon_command(r"C:\Users\ada\YazSes\YazSes.exe", frozen=True)
    assert argv == [r"C:\Users\ada\YazSes\YazSes.exe", "--daemon"]
    assert "-m" not in argv


def test_pip_install_daemon_command_still_uses_the_module():
    argv = resolve_daemon_command(r"C:\Python312\python.exe", frozen=False)
    assert argv == [r"C:\Python312\python.exe", "-m", "yazses.main"]


def test_frozen_tray_command_is_quoted_for_profiles_containing_spaces():
    """An unquoted REG_SZ breaks for every user whose profile has a space."""
    cmd = resolve_tray_command(
        r"C:\Users\Ada Lovelace\YazSes\YazSes.exe", frozen=True, tray_script=None
    )
    assert cmd == r'"C:\Users\Ada Lovelace\YazSes\YazSes.exe" --tray'
    assert cmd.startswith('"')


def test_frozen_tray_command_matches_what_the_installer_writes():
    """installer.iss writes `"{app}\\YazSes.exe" --tray`. The in-app toggle
    manages the same registry value, so the two must agree exactly or
    toggling autostart silently rewrites the installer's entry."""
    exe = r"C:\Users\ada\AppData\Local\Programs\YazSes\YazSes.exe"
    assert resolve_tray_command(exe, frozen=True, tray_script=None) == f'"{exe}" --tray'


def test_tray_command_prefers_the_console_script_when_not_frozen(tmp_path):
    script = tmp_path / "yazses-tray.exe"
    script.write_bytes(b"")
    cmd = resolve_tray_command(r"C:\py\python.exe", frozen=False, tray_script=script)
    assert cmd == f'"{script}"'


def test_tray_command_falls_back_to_the_module_when_no_script(tmp_path):
    cmd = resolve_tray_command(
        r"C:\py\python.exe", frozen=False, tray_script=tmp_path / "absent.exe"
    )
    assert cmd == r'"C:\py\python.exe" -m yazses.tray.app'
