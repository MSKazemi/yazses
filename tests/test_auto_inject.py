from unittest.mock import patch

from yazses.inject.auto import get_injector
from yazses.inject.clipboard import ClipboardInjector
from yazses.inject.wtype import WtypeInjector
from yazses.inject.xdotool import XdotoolInjector
from yazses.inject.ydotool import YdotoolInjector


def _which(available: list[str]):
    return lambda cmd: f"/usr/bin/{cmd}" if cmd in available else None


def test_x11_with_xdotool(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    with patch("yazses.inject.auto.shutil.which", side_effect=_which(["xdotool"])):
        assert isinstance(get_injector(), XdotoolInjector)


def test_wayland_prefers_ydotool_when_daemon_running(monkeypatch):
    # ydotool is only chosen when ydotoold's socket exists (it's useless without).
    # On a non-GNOME/KDE compositor (no stuck-key flood) ydotool is preferred.
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    with patch("yazses.inject.auto.shutil.which", side_effect=_which(["ydotool", "wtype"])), \
         patch("yazses.inject.auto.os.path.exists", return_value=True):
        assert isinstance(get_injector(), YdotoolInjector)


def test_gnome_wayland_types_by_default(monkeypatch):
    # Default on GNOME/KDE Wayland is to TYPE (ydotool) — works in every app,
    # terminals included. The flood guard in YdotoolInjector handles the
    # Ubuntu-26 dropped-key-up. Clipboard is not auto-selected here.
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    monkeypatch.delenv("YAZSES_INJECTOR", raising=False)
    with patch("yazses.inject.auto.shutil.which", side_effect=_which(["ydotool", "wl-copy"])), \
         patch("yazses.inject.auto.os.path.exists", return_value=True):
        assert isinstance(get_injector(), YdotoolInjector)


def test_prefer_clipboard_forces_clipboard(monkeypatch):
    # An explicit override (config/env) can force clipboard-paste on Wayland.
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    with patch("yazses.inject.auto.shutil.which", side_effect=_which(["ydotool", "wl-copy"])), \
         patch("yazses.inject.auto.os.path.exists", return_value=True):
        assert isinstance(get_injector("clipboard"), ClipboardInjector)


def test_env_override_clipboard(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("YAZSES_INJECTOR", "clipboard")
    with patch("yazses.inject.auto.shutil.which", side_effect=_which(["ydotool", "wl-copy"])), \
         patch("yazses.inject.auto.os.path.exists", return_value=True):
        assert isinstance(get_injector(), ClipboardInjector)


def test_wayland_without_ydotoold_falls_back_to_wtype(monkeypatch):
    # ydotool installed but no daemon socket → must NOT pick ydotool (it would
    # fail at runtime); fall back to wtype. This is the GNOME-Wayland fix.
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    with patch("yazses.inject.auto.shutil.which", side_effect=_which(["ydotool", "wtype"])), \
         patch("yazses.inject.auto.os.path.exists", return_value=False):
        assert isinstance(get_injector(), WtypeInjector)


def test_wayland_falls_back_to_wtype(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    with patch("yazses.inject.auto.shutil.which", side_effect=_which(["wtype"])):
        assert isinstance(get_injector(), WtypeInjector)


def test_no_tools_falls_back_to_clipboard(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    with patch("yazses.inject.auto.shutil.which", return_value=None):
        assert isinstance(get_injector(), ClipboardInjector)


def test_x11_no_xdotool_falls_back_to_clipboard(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    with patch("yazses.inject.auto.shutil.which", return_value=None):
        assert isinstance(get_injector(), ClipboardInjector)


def test_ydotool_type_timeout_scales_with_length():
    # Long text must get a proportionally longer timeout so `ydotool type` never
    # times out mid-type — a timeout triggers the clipboard fallback and the text
    # is injected twice (the "typed twice" bug).
    from unittest.mock import MagicMock
    short, long = "hi", "x" * 2000
    timeouts = {}
    def fake_run(cmd, *a, **kw):
        if cmd[:2] == ["ydotool", "type"]:
            timeouts[len(cmd[-1])] = kw.get("timeout")
        return MagicMock(returncode=0)
    with patch("yazses.inject.ydotool.subprocess.run", side_effect=fake_run):
        YdotoolInjector().inject(short)
        YdotoolInjector().inject(long)
    assert timeouts[len(long)] > timeouts[len(short)]
    assert timeouts[len(long)] >= 10 + 2000 * 0.03


def test_ydotool_type_uses_speed_flags():
    from unittest.mock import MagicMock
    seen = {}
    def fake_run(cmd, *a, **kw):
        if cmd[:2] == ["ydotool", "type"]:
            seen["cmd"] = cmd
        return MagicMock(returncode=0)
    with patch("yazses.inject.ydotool.subprocess.run", side_effect=fake_run):
        YdotoolInjector().inject("hello")
    assert "-d" in seen["cmd"] and "-H" in seen["cmd"]


def test_flood_guard_releases_right_side_modifiers():
    # The post-type flood guard must release right_alt (100), the default
    # hold-to-talk hotkey — otherwise a dropped key-up leaves Alt logically held,
    # turning the next Space into Alt+Space (the GNOME window menu / screenshot)
    # and mangling typed characters. left_alt/left_ctrl/shifts are in 2..57;
    # right_ctrl(97)/right_alt(100)/meta(125,126) are the ones that were missing.
    from unittest.mock import MagicMock
    key_cmds = []
    def fake_run(cmd, *a, **kw):
        if cmd[:2] == ["ydotool", "key"]:
            key_cmds.append(cmd[2:])
        return MagicMock(returncode=0)
    with patch("yazses.inject.ydotool.subprocess.run", side_effect=fake_run):
        YdotoolInjector().inject("hello")
    released = set().union(*key_cmds) if key_cmds else set()
    for code in (97, 100, 125, 126):   # right_ctrl, right_alt, left_meta, right_meta
        assert f"{code}:0" in released, f"flood guard did not release keycode {code}"
    # and the original character-row releases are still there
    assert "56:0" in released and "57:0" in released
