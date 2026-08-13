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

# Stamped into every synthetic event's dwExtraInfo so our own WH_KEYBOARD_LL
# hook can tell the text we type from the keys the user pressed. Any non-zero
# constant works; this one is recognisable in a debugger.
INJECTED_TAG = 0x59415A53  # 'YAZS'


def _user32() -> "ctypes.WinDLL":  # type: ignore[name-defined]  # Windows-only in typeshed
    """user32 with working error reporting.

    ``ctypes.windll.user32`` is cached without ``use_last_error``, so
    ``get_last_error()`` against it returns an unrelated value — a SendInput
    failure would be reported with a meaningless error code.
    """
    lib = ctypes.WinDLL("user32", use_last_error=True)
    lib.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
    lib.SendInput.restype = wintypes.UINT
    return lib


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
                dwExtraInfo=INJECTED_TAG,
            )
            up = inputs[i * 2 + 1]
            up.type = INPUT_KEYBOARD
            up.ki = _KEYBDINPUT(
                wVk=0,
                wScan=unit,
                dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=INJECTED_TAG,
            )
        sent = _user32().SendInput(
            len(inputs), ctypes.byref(inputs), ctypes.sizeof(_INPUT)
        )
        if sent != len(inputs):
            err = ctypes.get_last_error()
            log.warning("SendInput sent %d/%d events (lastError=%d)", sent, len(inputs), err)

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        inputs = (_INPUT * (count * 2))()
        for i in range(count):
            down = inputs[i * 2]
            down.type = INPUT_KEYBOARD
            down.ki = _KEYBDINPUT(
                wVk=VK_BACK, wScan=0, dwFlags=0, time=0, dwExtraInfo=INJECTED_TAG
            )
            up = inputs[i * 2 + 1]
            up.type = INPUT_KEYBOARD
            up.ki = _KEYBDINPUT(
                wVk=VK_BACK,
                wScan=0,
                dwFlags=KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=INJECTED_TAG,
            )
        _user32().SendInput(len(inputs), ctypes.byref(inputs), ctypes.sizeof(_INPUT))

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        # Windows VK codes for common keys.
        _VK: dict[str, int] = {
            "Return": 0x0D, "Left": 0x25, "Right": 0x27, "Up": 0x26, "Down": 0x28,
            "BackSpace": 0x08, "Tab": 0x09, "Escape": 0x1B, "slash": 0xBF,
            **{str(i): (0x30 + i) for i in range(10)},
            **{c: (0x41 + i) for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")},
        }
        _MOD_VK: dict[str, int] = {
            "ctrl": 0xA2,   # VK_LCONTROL
            "shift": 0xA0,  # VK_LSHIFT
            "alt": 0xA4,    # VK_LMENU
            "meta": 0x5B,   # VK_LWIN
        }
        def _make_vk_event(vk: int, flags: int) -> _INPUT:
            inp = _INPUT()
            inp.type = INPUT_KEYBOARD
            inp.ki = _KEYBDINPUT(
                wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=INJECTED_TAG
            )
            return inp

        all_inputs: list[_INPUT] = []
        for combo in keys:
            parts = combo.split("+")
            key_name = parts[-1].lower()
            mods = [p.lower() for p in parts[:-1]]
            vk = _VK.get(key_name, 0)
            mod_vks = [_MOD_VK[m] for m in mods if m in _MOD_VK]
            for mod_vk in mod_vks:
                all_inputs.append(_make_vk_event(mod_vk, 0))
            all_inputs.append(_make_vk_event(vk, 0))
            all_inputs.append(_make_vk_event(vk, KEYEVENTF_KEYUP))
            for mod_vk in reversed(mod_vks):
                all_inputs.append(_make_vk_event(mod_vk, KEYEVENTF_KEYUP))

        if not all_inputs:
            return
        arr = (_INPUT * len(all_inputs))(*all_inputs)
        _user32().SendInput(len(arr), ctypes.byref(arr), ctypes.sizeof(_INPUT))
