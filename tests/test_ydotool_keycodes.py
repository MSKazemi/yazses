"""`ydotool key` must work on a platform that cannot install evdev.

`ydotool_key_args` used to read its keycodes from `evdev.ecodes` at call time, under a
comment saying "the function only ever runs on Linux". It does not. `platform/bsd/`
composes itself from `LinuxInjector`, and `inject/auto.py` picks ydotool on **any**
Wayland session where the binary and ydotoold's socket exist -- it never asks which OS
it is on. FreeBSD has ydotool in ports and runs Wayland compositors; it cannot have
python-evdev, which pyproject.toml marks `sys_platform == "linux"` because it is a C
extension against `<linux/input.h>`.

So on a FreeBSD Wayland desktop, dictation typed fine and every spoken *command* --
Enter, Tab, an arrow key, Ctrl+V, and every backspace, including the clipboard
injector's paste -- raised `ModuleNotFoundError: evdev` from inside the injector.

The numbers themselves were never the Linux-only part: they are `input-event-codes.h`,
a frozen kernel ABI that FreeBSD's own evdev implements identically, and this file
already hardcoded a dozen of them (2..57, 97, 100, 125, 126). So they are committed in
`inject/keycodes.py` -- and, because a hand-written set is its own defect, verified
here against evdev wherever evdev exists.
"""

from __future__ import annotations

import builtins

import pytest

from yazses.inject.keycodes import KEYCODES
from yazses.inject.ydotool import ydotool_key_args

#: Every code a keyboard emits. Above this, names stay behind the evdev fallback.
KEYBOARD_RANGE = 255


def _evdev_keycodes() -> dict[str, int]:
    ecodes = pytest.importorskip(
        "evdev.ecodes", reason="evdev is Linux-only; the table is the answer elsewhere"
    )
    return {
        name: value
        for name in dir(ecodes)
        if name.startswith("KEY_")
        and isinstance(value := getattr(ecodes, name), int)
        and value <= KEYBOARD_RANGE
    }


def test_every_committed_code_matches_evdev() -> None:
    """A wrong number here presses the wrong key, silently."""
    expected = _evdev_keycodes()
    wrong = {n: (v, expected[n]) for n, v in KEYCODES.items()
             if n in expected and v != expected[n]}
    assert not wrong, f"committed keycodes disagree with evdev (name: got, want): {wrong}"


def test_the_table_is_complete_for_the_keyboard_range() -> None:
    """A guard that only checks the entries it finds passes trivially on a short
    table -- which is exactly how a generated set rots. Check for omissions too."""
    expected = _evdev_keycodes()
    missing = sorted(set(expected) - set(KEYCODES))
    assert not missing, (
        f"{len(missing)} KEY_* names in the keyboard range are absent from "
        f"inject/keycodes.py: {missing[:10]}... Regenerate it."
    )
    extra = sorted(set(KEYCODES) - set(expected))
    assert not extra, f"inject/keycodes.py invents names evdev does not have: {extra}"


def test_the_keys_the_product_actually_presses_resolve_without_evdev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real regression test: with evdev unimportable, every combo the injector
    and the command grammar send must still produce tokens."""
    real_import = builtins.__import__

    def _no_evdev(name, *args, **kwargs):
        if name == "evdev" or name.startswith("evdev."):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_evdev)

    # Ctrl+V is the clipboard injector's paste; backspace is correction-on-commit;
    # the rest are what `commands/dispatch.py` sends for a spoken command.
    for combo in ("ctrl+v", "KEY_BACKSPACE", "Return", "Tab", "shift+Left", "Home",
                  "End", "Page_Up", "Page_Down", "escape", "space", "alt+F4",
                  "ctrl+shift+z", "super+d", "a", "7", "F11", "delete"):
        tokens = ydotool_key_args(combo)
        assert tokens, f"{combo!r} produced no tokens without evdev"
        assert all(":" in t for t in tokens), f"{combo!r} produced {tokens!r}"


def test_ctrl_v_is_still_the_exact_sequence_it_was(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one combo whose numbers were verified against a real ydotoold device."""
    real_import = builtins.__import__

    def _no_evdev(name, *args, **kwargs):
        if name == "evdev" or name.startswith("evdev."):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_evdev)
    assert ydotool_key_args("ctrl+v") == ["29:1", "47:1", "47:0", "29:0"]


def test_an_unknown_key_still_raises_rather_than_pressing_something_else() -> None:
    with pytest.raises(ValueError, match="unknown key"):
        ydotool_key_args("KEY_DEFINITELY_NOT_A_KEY")
