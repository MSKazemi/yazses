"""Han text through every injection backend's character path (#501).

What this file can prove without a desktop: how each backend turns a Han or astral
character into the thing it sends (a keysym, a UTF-16 unit, a keycode), and that a
backend which *cannot* produce Han fails before it types anything, so the clipboard
fallback does not type half the burst twice.

What it cannot prove, and does not claim: that a real compositor, X server or Windows
application accepts those events. That is COMP-06..09 and needs a human on each
platform (the #501 checklist, COMP-06..09).
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

import yazses.inject.unicode as unicode_mod
from yazses.inject import ydotool as yd
from yazses.inject.keysyms import char_to_keysym
from yazses.inject.unicode import UnicodeInjector, UnicodeInjectorError
from yazses.platform.macos.injector import _utf16_chunks
from yazses.platform.windows.injector import _utf16_units

#: The three strings #501 names, plus an astral ideograph (U+20BB7) in a name.
ISSUE_STRINGS = [
    "你好，世界。今天测试 YazSes 123。",
    "你好，世界。今天測試 YazSes 123。",
    "版本 v2.0，文件 test.py，编号 12345。",
    "\U00020bb7野家的牛肉饭很好吃。",
]


# --- per-character encodings ---------------------------------------------------------------


@pytest.mark.parametrize("text", ISSUE_STRINGS)
def test_portal_keysyms_are_one_per_code_point_and_reversible(text):
    # The RemoteDesktop portal path sends one keysym per *code point*; the Unicode
    # keysym range is codepoint | 0x01000000 (X11 keysymdef.h), astral planes included.
    syms = [char_to_keysym(ch) for ch in text]
    assert len(syms) == len(text)
    decoded = "".join(
        chr(s & 0x00FF_FFFF) if s & 0x0100_0000 else chr(s) for s in syms
    )
    assert decoded == text


def test_portal_keysym_for_han_and_an_astral_ideograph():
    assert char_to_keysym("你") == 0x0100_4F60
    assert char_to_keysym("，") == 0x0100_FF0C
    assert char_to_keysym("\U00020bb7") == 0x0102_0BB7


@pytest.mark.parametrize("text", ISSUE_STRINGS)
def test_windows_sendinput_units_round_trip(text):
    units = _utf16_units(text)
    raw = b"".join(u.to_bytes(2, "little") for u in units)
    assert raw.decode("utf-16-le") == text


def test_windows_sends_an_astral_ideograph_as_a_surrogate_pair():
    assert _utf16_units("\U00020bb7") == [0xD842, 0xDFB7]


def test_macos_chunks_never_split_an_astral_ideograph():
    # Put U+20BB7 exactly across the 20-unit chunk boundary.
    text = "你" * 19 + "\U00020bb7" + "野家"
    chunks = _utf16_chunks(text)
    for chunk in chunks:
        assert not (0xD800 <= chunk[-1] <= 0xDBFF), "a high surrogate ended a chunk"
    raw = b"".join(u.to_bytes(2, "little") for c in chunks for u in c)
    assert raw.decode("utf-16-le") == text


# --- the XKB/uinput path fails before typing, not half-way ------------------------------------


class _LatinXkb:
    """A Latin layout: a, v, space and digits have keys; Han does not."""

    _KEYS = {30: "a", 47: "v", 57: " ", 2: "1", 3: "2", 52: "."}

    def update(self, keycode, direction):
        pass

    def key_text(self, keycode):
        return self._KEYS.get(keycode, "")

    def close(self):
        pass


class _Keyboard:
    def __init__(self):
        self.taps = []

    def tap(self, keycode, modifiers=()):
        self.taps.append(keycode)

    def close(self):
        pass


@pytest.fixture
def latin_layout(monkeypatch):
    # The ydotool dialect is a module-level cache; pin it for this test and put the
    # previous value back, so no other test inherits it.
    monkeypatch.setattr(yd, "_dialect_cache", yd.DIALECT_V1)
    keyboard = _Keyboard()
    monkeypatch.setattr(unicode_mod._XkbSession, "create", lambda: _LatinXkb())
    monkeypatch.setattr(unicode_mod._UinputKeyboard, "create", lambda path: keyboard)
    monkeypatch.setattr(unicode_mod.time, "sleep", lambda s: None)
    return keyboard


def test_unicode_injector_types_nothing_when_a_han_character_is_unavailable(latin_layout):
    # Before #501 this tapped "a", "v", " " and only then raised on 版 -- and the
    # clipboard fallback pasted the whole burst after the typed prefix.
    with pytest.raises(UnicodeInjectorError, match="cannot produce '版'"):
        UnicodeInjector().inject("av 版本")
    assert latin_layout.taps == []


def test_ensure_producible_types_nothing(latin_layout):
    injector = UnicodeInjector()
    injector.ensure_producible("av 12")
    with pytest.raises(UnicodeInjectorError):
        injector.ensure_producible("版")
    assert latin_layout.taps == []


def test_ydotool_mixed_path_fails_before_its_first_ascii_run(latin_layout, monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess, "run",
        lambda argv, **kw: calls.append(list(argv)) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    with pytest.raises(UnicodeInjectorError):
        yd.YdotoolInjector().inject("YazSes 版本 v2.0")
    assert not [c for c in calls if c[1] == "type"], "an ASCII run was typed before the failure"
    assert latin_layout.taps == []


def test_linux_fallback_types_a_mixed_han_burst_exactly_once(latin_layout, monkeypatch):
    """The user-visible consequence: the clipboard carries the burst, once."""
    from yazses.platform.linux.injector import LinuxInjector

    typed = []
    monkeypatch.setattr(
        subprocess, "run",
        lambda argv, **kw: (typed.append(argv[-1]) if argv[1] == "type" else None)
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    class _Clipboard:
        def inject(self, text):
            typed.append(text)

    inj = LinuxInjector.__new__(LinuxInjector)
    inj._primary = yd.YdotoolInjector()
    inj._fallback = _Clipboard()
    inj.inject("YazSes 版本 v2.0")
    assert typed == ["YazSes 版本 v2.0"]
