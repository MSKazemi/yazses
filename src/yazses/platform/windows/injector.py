"""Windows injector — SendInput with KEYEVENTF_UNICODE.

Each printable code unit goes out as one down event and one up event. Non-BMP
characters (e.g. emoji) encode as a UTF-16 surrogate pair — two pairs of
events, four total per character. This avoids any layout / IME translation
that scancode-based injection would suffer.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger(__name__)


# WinAPI constants for SendInput.
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_BACK = 0x08


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUT_UNION),
    ]


def _utf16_units(text: str) -> list[int]:
    """Encode *text* to UTF-16-LE and return code units as ints."""
    encoded = text.encode("utf-16-le")
    return [int.from_bytes(encoded[i : i + 2], "little") for i in range(0, len(encoded), 2)]


def _load_user32():
    """user32 with `use_last_error` so SendInput failures report a real code.

    ``ctypes.get_last_error()`` reads a per-library copy that is only populated
    when the library was opened with ``use_last_error=True``; off a bare
    ``ctypes.windll`` it returns 0 no matter what actually failed.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.restype = wintypes.UINT
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    return user32


# Virtual-key codes for the key *names* the command dispatcher emits. Those
# names are X11-style and capitalised ("Return", "BackSpace", "Page_Down"), so
# every lookup is done lower-cased and this table is keyed lower-case to match.
#
# Getting that wrong is not a graceful degradation: an unresolved name used to
# fall back to `vk=0`, and SendInput happily delivers a keystroke for virtual
# key 0 — a no-op the caller cannot distinguish from success. Every named key
# the dispatcher uses (Return/Tab/Escape/BackSpace/arrows/Home/End/Page_*) went
# out as vk=0, so "press enter", "go to line", "select to end" and the arrow
# commands did nothing at all on Windows.
_VK_NAMED: dict[str, int] = {
    "return": 0x0D, "enter": 0x0D, "kp_enter": 0x0D,
    "tab": 0x09,
    "escape": 0x1B, "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E, "insert": 0x2D,
    "space": 0x20,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "home": 0x24, "end": 0x23,
    "page_up": 0x21, "prior": 0x21,
    "page_down": 0x22, "next": 0x22,
    # OEM punctuation (US layout). SendInput with a VK is layout-dependent;
    # these match what the dispatcher's editor bindings expect.
    "slash": 0xBF, "backslash": 0xDC, "period": 0xBE, "comma": 0xBC,
    "minus": 0xBD, "equal": 0xBB, "semicolon": 0xBA, "apostrophe": 0xDE,
    "bracketleft": 0xDB, "bracketright": 0xDD, "grave": 0xC0,
    **{str(i): (0x30 + i) for i in range(10)},
    **{c: (0x41 + i) for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")},
    **{f"f{i}": (0x70 + i - 1) for i in range(1, 13)},
}

_MOD_VK: dict[str, int] = {
    "ctrl": 0xA2,     # VK_LCONTROL
    "control": 0xA2,
    "shift": 0xA0,    # VK_LSHIFT
    "alt": 0xA4,      # VK_LMENU
    "meta": 0x5B,     # VK_LWIN
    "super": 0x5B,
    "win": 0x5B,
    # macOS-style names appear in shared command tables.
    "cmd": 0x5B,
    "command": 0x5B,
    "option": 0xA4,
}


def resolve_key_combo(combo: str) -> tuple[list[int], int] | None:
    """Resolve ``"ctrl+shift+End"`` to ``([VK_LCONTROL, VK_LSHIFT], VK_END)``.

    Returns ``None`` when the key name is unknown, so the caller can skip and
    say so rather than injecting a meaningless ``vk=0`` keystroke.
    """
    parts = [p for p in combo.split("+") if p]
    if not parts:
        return None
    key_name = parts[-1].lower()
    vk = _VK_NAMED.get(key_name)
    if vk is None:
        return None
    mod_vks: list[int] = []
    for raw in parts[:-1]:
        mod = _MOD_VK.get(raw.lower())
        if mod is None:
            return None
        if mod not in mod_vks:
            mod_vks.append(mod)
    return mod_vks, vk


class WindowsInjector:
    """InjectorBackend for Windows."""

    def inject(self, text: str) -> None:
        if not text:
            return
        units = _utf16_units(text)
        if not units:
            return
        inputs = (_INPUT * (len(units) * 2))()
        for i, unit in enumerate(units):
            down = inputs[i * 2]
            down.type = INPUT_KEYBOARD
            down.ki = _KEYBDINPUT(
                wVk=0,
                wScan=unit,
                dwFlags=KEYEVENTF_UNICODE,
                time=0,
                dwExtraInfo=None,
            )
            up = inputs[i * 2 + 1]
            up.type = INPUT_KEYBOARD
            up.ki = _KEYBDINPUT(
                wVk=0,
                wScan=unit,
                dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=None,
            )
        sent = _load_user32().SendInput(len(inputs), inputs, ctypes.sizeof(_INPUT))
        if sent != len(inputs):
            err = ctypes.get_last_error()
            log.warning(
                "SendInput sent %d/%d events (lastError=%d). Error 5 (ACCESS_DENIED) "
                "means the focused window runs elevated and UIPI blocks input from "
                "this process -- run YazSes as administrator to type into it.",
                sent, len(inputs), err,
            )

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        inputs = (_INPUT * (count * 2))()
        for i in range(count):
            down = inputs[i * 2]
            down.type = INPUT_KEYBOARD
            down.ki = _KEYBDINPUT(
                wVk=VK_BACK, wScan=0, dwFlags=0, time=0, dwExtraInfo=None
            )
            up = inputs[i * 2 + 1]
            up.type = INPUT_KEYBOARD
            up.ki = _KEYBDINPUT(
                wVk=VK_BACK, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None
            )
        sent = _load_user32().SendInput(len(inputs), inputs, ctypes.sizeof(_INPUT))
        if sent != len(inputs):
            log.warning(
                "SendInput sent %d/%d backspace events (lastError=%d)",
                sent, len(inputs), ctypes.get_last_error(),
            )

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return

        def _make_vk_event(vk: int, flags: int) -> _INPUT:
            inp = _INPUT()
            inp.type = INPUT_KEYBOARD
            inp.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None)
            return inp

        all_inputs: list[_INPUT] = []
        for combo in keys:
            resolved = resolve_key_combo(combo)
            if resolved is None:
                # Skip loudly. Injecting vk=0 would look like success while
                # doing nothing, which is how this failure hid for so long.
                log.warning(
                    "Unsupported key combo %r for Windows injection -- skipping. "
                    "Supported names: %s",
                    combo, ", ".join(sorted(_VK_NAMED)),
                )
                continue
            mod_vks, vk = resolved
            for mod_vk in mod_vks:
                all_inputs.append(_make_vk_event(mod_vk, 0))
            all_inputs.append(_make_vk_event(vk, 0))
            all_inputs.append(_make_vk_event(vk, KEYEVENTF_KEYUP))
            for mod_vk in reversed(mod_vks):
                all_inputs.append(_make_vk_event(mod_vk, KEYEVENTF_KEYUP))

        if not all_inputs:
            return
        arr = (_INPUT * len(all_inputs))(*all_inputs)
        sent = _load_user32().SendInput(len(arr), arr, ctypes.sizeof(_INPUT))
        if sent != len(arr):
            log.warning(
                "SendInput sent %d/%d key events (lastError=%d)",
                sent, len(arr), ctypes.get_last_error(),
            )
