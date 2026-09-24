"""The opt-in Unicode injector stays lazy and preserves the existing path.

These tests exercise the backend boundary without a Linux desktop. Real Wayland
acceptance still needs a machine with the target keyboard layout and uinput access.
"""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from yazses.inject.auto import describe_injector, get_injector
from yazses.inject.unicode import UnicodeInjector, UnicodeInjectorError
from yazses.inject.ydotool import YdotoolInjector
from yazses.system.backends import probe_backend


def test_import_is_safe_without_linux_runtime_facilities():
    proc = subprocess.run(
        [sys.executable, "-c", "import yazses.inject.unicode; print('ok')"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_unicode_is_opt_in_and_auto_still_prefers_ydotool(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr("yazses.inject.auto.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("yazses.inject.auto.ydotool_ready", lambda: True)

    assert isinstance(get_injector("unicode"), UnicodeInjector)
    assert type(get_injector("auto")).__name__ == "YdotoolInjector"


def test_describe_names_the_selected_backend():
    assert describe_injector(UnicodeInjector()) == "UnicodeInjector"


def test_probe_backend_reports_a_native_runtime_failure():
    status = probe_backend(
        "unicode",
        adapter="yazses.inject.unicode",
        requires=(),
        runtime=lambda: (
            "the 'unicode' backend needs /dev/uinput",
            "load the uinput kernel module and grant the current user access",
        ),
    )
    assert not status.available
    assert status.implemented
    assert "/dev/uinput" in status.message


def test_doctor_uses_the_native_probe_for_the_forced_backend(monkeypatch):
    import yazses.inject.unicode as unicode_mod
    from yazses.system.doctor import _injection_readiness

    monkeypatch.setattr(unicode_mod, "runtime_availability", lambda: None)
    checks = _injection_readiness(False, False, "unicode")

    assert checks == [
        ("Injection", "OK", "unicode — forced by `[injection] backend = unicode`")
    ]


class _FakeXkb:
    def __init__(self):
        self.modifiers: set[int] = set()

    def update(self, keycode: int, direction: int) -> None:
        if direction:
            self.modifiers.add(keycode)
        else:
            self.modifiers.discard(keycode)

    def key_text(self, keycode: int) -> str:
        if keycode == 30 and not self.modifiers:
            return "a"
        if keycode == 31 and 42 in self.modifiers:
            return "Å"
        return ""

    def close(self) -> None:
        pass


class _FakeKeyboard:
    def __init__(self):
        self.taps: list[tuple[int, tuple[int, ...]]] = []

    def tap(self, keycode: int, modifiers=()) -> None:
        self.taps.append((keycode, tuple(modifiers)))

    def close(self) -> None:
        pass


def test_ascii_and_unicode_text_use_xkb_key_and_modifier_events(monkeypatch):
    import yazses.inject.unicode as unicode_mod

    xkb = _FakeXkb()
    keyboard = _FakeKeyboard()
    monkeypatch.setattr(unicode_mod._XkbSession, "create", lambda: xkb)
    monkeypatch.setattr(unicode_mod._UinputKeyboard, "create", lambda path: keyboard)

    injector = UnicodeInjector()
    injector.inject("aÅ")

    assert keyboard.taps == [(30, ()), (31, (42,))]


def test_backspaces_and_key_sequences_use_the_same_uinput_device(monkeypatch):
    import yazses.inject.unicode as unicode_mod

    xkb = _FakeXkb()
    keyboard = _FakeKeyboard()
    monkeypatch.setattr(unicode_mod._XkbSession, "create", lambda: xkb)
    monkeypatch.setattr(unicode_mod._UinputKeyboard, "create", lambda path: keyboard)

    injector = UnicodeInjector()
    injector.inject_backspaces(2)
    injector.inject_key_sequence(["ctrl+v"])

    assert keyboard.taps[:2] == [(14, ()), (14, ())]
    assert keyboard.taps[2][1] == (29,)
    assert keyboard.taps[2][0] == 47


def test_unmapped_character_fails_loudly_instead_of_dropping_text(monkeypatch):
    import yazses.inject.unicode as unicode_mod

    xkb = _FakeXkb()
    keyboard = _FakeKeyboard()
    monkeypatch.setattr(unicode_mod._XkbSession, "create", lambda: xkb)
    monkeypatch.setattr(unicode_mod._UinputKeyboard, "create", lambda path: keyboard)

    with pytest.raises(UnicodeInjectorError, match="cannot produce"):
        UnicodeInjector().inject("a🙂")


class _FakeXkbMap:
    """Fake XKB session backed by an explicit character -> keycode map, no modifiers."""

    def __init__(self, mapping: dict[str, int]):
        self._reverse = {code: char for char, code in mapping.items()}

    def update(self, keycode: int, direction: int) -> None:
        pass

    def key_text(self, keycode: int) -> str:
        return self._reverse.get(keycode, "")

    def close(self) -> None:
        pass


class _RecordingKeyboard:
    """Fake uinput keyboard that records the character each tap would produce."""

    def __init__(self, reverse_map: dict[int, str]):
        self._reverse_map = reverse_map
        self.produced: list[str] = []

    def tap(self, keycode: int, modifiers=()) -> None:
        self.produced.append(self._reverse_map.get(keycode, "?"))

    def close(self) -> None:
        pass


def test_ascii_only_text_still_uses_a_single_ydotool_type_call(monkeypatch):
    """#329 must not change existing ASCII behaviour: same single `type` call."""
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        if argv[1] == "type":
            calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("yazses.inject.ydotool.subprocess.run", side_effect=fake_run):
        YdotoolInjector().inject("hello world")

    assert len(calls) == 1
    assert calls[0][-1] == "hello world"


def test_ydotool_inject_no_longer_drops_non_ascii_runs(monkeypatch):
    """Regression test for #329.

    Before the fix, `YdotoolInjector.inject` handed the whole string to one
    `ydotool type` call. `fake_run` below models what the *real* ydotool binary
    does when a character has no keycode on the active XKB layout: it presses
    nothing for that character and still exits 0 (see the issue — "nothing
    errors"). Against the unfixed code this test fails, because the whole mixed
    string reached `ydotool type` and the mock silently stripped the "Å".

    After the fix, only the ASCII runs ("A", "B") reach `ydotool type` — so the
    real binary would have nothing to drop — and "Å" is produced through the
    Unicode injector's XKB/uinput boundary (mocked here exactly as elsewhere in
    this file) instead of being discarded.
    """
    import yazses.inject.unicode as unicode_mod

    typed: list[str] = []

    def fake_run(argv, **_kwargs):
        if argv[1] == "type":
            typed.append("".join(char for char in argv[-1] if char.isascii()))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    xkb = _FakeXkb()
    keyboard = _FakeKeyboard()
    monkeypatch.setattr(unicode_mod._XkbSession, "create", lambda: xkb)
    monkeypatch.setattr(unicode_mod._UinputKeyboard, "create", lambda path: keyboard)

    with patch("yazses.inject.ydotool.subprocess.run", side_effect=fake_run):
        YdotoolInjector().inject("AÅB")

    assert typed == ["A", "B"]            # ASCII runs: unchanged ydotool-type path
    assert (31, (42,)) in keyboard.taps   # Å: produced via uinput, not dropped


@pytest.mark.parametrize("text", ["åäö", "éèê", "öüß"])
def test_ydotool_inject_preserves_the_329_acceptance_strings(monkeypatch, text):
    """Acceptance criteria from #329: dictating åäö / éèê / öüß on Wayland via the
    ydotool path must produce those exact characters."""
    import yazses.inject.unicode as unicode_mod

    mapping = {char: 40 + i for i, char in enumerate(dict.fromkeys(text))}
    xkb = _FakeXkbMap(mapping)
    keyboard = _RecordingKeyboard({code: char for char, code in mapping.items()})
    monkeypatch.setattr(unicode_mod._XkbSession, "create", lambda: xkb)
    monkeypatch.setattr(unicode_mod._UinputKeyboard, "create", lambda path: keyboard)

    type_calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        if argv[1] == "type":
            type_calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("yazses.inject.ydotool.subprocess.run", side_effect=fake_run):
        YdotoolInjector().inject(text)

    assert "".join(keyboard.produced) == text
    assert type_calls == []  # nothing ASCII in these strings; ydotool type unused
