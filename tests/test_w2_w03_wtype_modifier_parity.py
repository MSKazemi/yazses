"""wtype key combos speak the same modifier vocabulary as the X11 and ydotool paths.

wtype's `-M`/`-m` accept only shift, capslock, ctrl, logo, win, alt, altgr and
mod1..mod4 (upstream main.c `mod_names[]`, https://github.com/atx/wtype, read
2026-11-06) and exit 1 on anything else; `-k` goes through
xkb_keysym_from_name and exits 1 on an unknown keysym. `meta+k`, `super+k`,
`cmd+z` and `control+a` -- all of which xdotool.py and ydotool.py resolve to
Super / Ctrl -- were passed to wtype verbatim, so every one was refused and the
command did nothing, on WtypeInjector and on the clipboard fallback's wtype path.

Pure argv tests: subprocess.run is captured, nothing is executed.
"""

from __future__ import annotations

import subprocess

import pytest

from yazses.inject import clipboard as clipboard_mod
from yazses.inject.clipboard import ClipboardInjector
from yazses.inject.wtype import WtypeInjector

# The full set wtype accepts for -M/-m (strcasecmp), per upstream main.c.
_WTYPE_MODIFIER_NAMES = {
    "shift", "capslock", "ctrl", "logo", "win", "alt", "altgr",
    "mod1", "mod2", "mod3", "mod4",
}


def _capture(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(argv, *args, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _modifiers(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, tok in enumerate(argv) if tok in ("-M", "-m")]


def _keys(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, tok in enumerate(argv) if tok == "-k"]


@pytest.mark.parametrize("mod", ["meta", "super", "cmd", "win"])
def test_super_aliases_become_wtype_logo(monkeypatch, mod):
    calls = _capture(monkeypatch)
    WtypeInjector().inject_key_sequence([f"{mod}+k"])
    assert calls == [["wtype", "-M", "logo", "-k", "k", "-m", "logo"]]


def test_control_alias_becomes_ctrl(monkeypatch):
    calls = _capture(monkeypatch)
    WtypeInjector().inject_key_sequence(["control+a"])
    assert calls == [["wtype", "-M", "ctrl", "-k", "a", "-m", "ctrl"]]


@pytest.mark.parametrize(
    "combo",
    ["meta+k", "super+Left", "cmd+shift+Down", "control+v", "Ctrl+Shift+o", "alt+BackSpace"],
)
def test_every_modifier_sent_is_one_wtype_accepts(monkeypatch, combo):
    calls = _capture(monkeypatch)
    WtypeInjector().inject_key_sequence([combo])
    (argv,) = calls
    mods = _modifiers(argv)
    assert mods, argv
    assert all(m.lower() in _WTYPE_MODIFIER_NAMES for m in mods), argv


@pytest.mark.parametrize("alias, keysym", [("enter", "Return"), ("esc", "Escape"), ("del", "Delete")])
def test_short_key_aliases_become_keysym_names(monkeypatch, alias, keysym):
    """`enter`/`esc`/`del` are ydotool aliases but not xkb keysym names."""
    calls = _capture(monkeypatch)
    WtypeInjector().inject_key_sequence([alias, f"ctrl+{alias}"])
    (argv,) = calls
    assert _keys(argv) == [keysym, keysym]


def test_multi_modifier_chord_releases_in_reverse(monkeypatch):
    calls = _capture(monkeypatch)
    WtypeInjector().inject_key_sequence(["ctrl+shift+k"])
    assert calls == [["wtype", "-M", "ctrl", "-M", "shift", "-k", "k", "-m", "shift", "-m", "ctrl"]]


def test_plain_keys_are_unchanged(monkeypatch):
    calls = _capture(monkeypatch)
    WtypeInjector().inject_key_sequence(["shift+Left", "Return", "BackSpace"])
    assert calls == [[
        "wtype", "-M", "shift", "-k", "Left", "-m", "shift", "-k", "Return", "-k", "BackSpace",
    ]]


def test_clipboard_fallback_wtype_path_maps_the_same(monkeypatch):
    """The clipboard backend's Wayland key path without ydotool shells out to wtype too."""
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(clipboard_mod, "_ydotool_ready", lambda: False)
    monkeypatch.setattr(
        clipboard_mod.shutil, "which", lambda name: "/usr/bin/wtype" if name == "wtype" else None
    )
    calls = _capture(monkeypatch)
    ClipboardInjector().inject_key_sequence(["meta+k", "control+v"])
    assert calls == [[
        "wtype", "-M", "logo", "-k", "k", "-m", "logo", "-M", "ctrl", "-k", "v", "-m", "ctrl",
    ]]
