"""Unicode-capable keyboard injection through XKB and Linux uinput.

The ordinary ``ydotool type`` path accepts UTF-8 text but turns it into keycodes
using the active keyboard layout; characters that layout cannot produce are
silently discarded. This opt-in backend resolves each character with
``libxkbcommon`` and sends the resulting key/modifier events through a private
uinput keyboard.

Nothing native is loaded at import time. ``evdev`` is Linux-only,
``/dev/uinput`` is not present on every Linux installation, and
``libxkbcommon`` is a system library, so importing YazSes remains safe without
any of them.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import struct
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass

from yazses.inject.keycodes import KEYCODES

_EV_SYN = 0
_EV_KEY = 1
_SYN_REPORT = 0
_KEY_PRESS = 1
_KEY_RELEASE = 0
_KEY_LEFTSHIFT = 42
_KEY_RIGHTALT = 100
_KEY_BACKSPACE = 14

_UINPUT_DEVICE = "/dev/uinput"
_UINPUT_USER_DEV_SIZE = 1116

# Linux uinput ioctl values. Keeping these constants here avoids making this
# optional backend depend on evdev just to create a virtual keyboard.
_UI_SET_EVBIT = 0x40045564
_UI_SET_KEYBIT = 0x40045565
_UI_DEV_CREATE = 0x5501
_UI_DEV_DESTROY = 0x5502


class UnicodeInjectorError(RuntimeError):
    """The Unicode injector cannot be used on this machine or for this text."""


class _XkbRuleNames(ctypes.Structure):
    _fields_ = [
        ("rules", ctypes.c_char_p),
        ("model", ctypes.c_char_p),
        ("layout", ctypes.c_char_p),
        ("variant", ctypes.c_char_p),
        ("options", ctypes.c_char_p),
    ]


def _layout_name() -> str:
    """Return the layout hint exposed by common Wayland/XKB environments."""
    for variable in ("XKB_DEFAULT_LAYOUT", "XKB_LAYOUT"):
        value = os.environ.get(variable, "").strip()
        if value:
            return value.split(",", 1)[0]

    language = os.environ.get("LANG", "").lower()
    language_layouts = (
        ("sv", "se"),
        ("de", "de"),
        ("fr", "fr"),
        ("es", "es"),
        ("it", "it"),
        ("pt", "pt"),
        ("en_gb", "gb"),
    )
    for prefix, layout in language_layouts:
        if language.startswith(prefix):
            return layout
    return "us"


def _xkb_library_name_candidates() -> Iterable[str]:
    found = ctypes.util.find_library("xkbcommon")
    if found:
        yield found
    # find_library may return None on a minimal Linux image even when the SONAME
    # is loadable directly.
    yield "libxkbcommon.so.0"
    yield "libxkbcommon.so"


def _load_xkb_library() -> ctypes.CDLL:
    errors: list[str] = []
    seen: set[str] = set()
    for name in _xkb_library_name_candidates():
        if name in seen:
            continue
        seen.add(name)
        try:
            return ctypes.CDLL(name)
        except OSError as exc:
            errors.append(f"{name}: {exc}")
    raise UnicodeInjectorError(
        "libxkbcommon is unavailable; install the system libxkbcommon package "
        f"({'; '.join(errors)})"
    )


def _configure_xkb(lib: ctypes.CDLL) -> None:
    pointer = ctypes.c_void_p
    lib.xkb_context_new.argtypes = [ctypes.c_int]
    lib.xkb_context_new.restype = pointer
    lib.xkb_context_unref.argtypes = [pointer]
    lib.xkb_context_unref.restype = None
    lib.xkb_keymap_new_from_names.argtypes = [
        pointer,
        ctypes.POINTER(_XkbRuleNames),
        ctypes.c_int,
    ]
    lib.xkb_keymap_new_from_names.restype = pointer
    lib.xkb_keymap_unref.argtypes = [pointer]
    lib.xkb_keymap_unref.restype = None
    lib.xkb_state_new.argtypes = [pointer]
    lib.xkb_state_new.restype = pointer
    lib.xkb_state_unref.argtypes = [pointer]
    lib.xkb_state_unref.restype = None
    lib.xkb_state_update_key.argtypes = [pointer, ctypes.c_uint32, ctypes.c_int]
    lib.xkb_state_update_key.restype = ctypes.c_int
    lib.xkb_state_key_get_utf8.argtypes = [
        pointer,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    lib.xkb_state_key_get_utf8.restype = ctypes.c_int


@dataclass
class _XkbSession:
    """Small lifetime wrapper for the opaque XKB objects."""

    lib: ctypes.CDLL
    context: ctypes.c_void_p
    keymap: ctypes.c_void_p
    state: ctypes.c_void_p

    @classmethod
    def create(cls) -> _XkbSession:
        if not sys.platform.startswith("linux"):
            raise UnicodeInjectorError("the Unicode injector requires Linux")

        lib = _load_xkb_library()
        _configure_xkb(lib)
        context = lib.xkb_context_new(0)
        if not context:
            raise UnicodeInjectorError("libxkbcommon could not create an XKB context")

        layout = _layout_name()
        names = _XkbRuleNames(
            rules=b"evdev",
            model=b"pc105",
            layout=layout.encode("ascii"),
            variant=None,
            options=None,
        )
        keymap = lib.xkb_keymap_new_from_names(context, ctypes.byref(names), 0)
        if not keymap:
            lib.xkb_context_unref(context)
            raise UnicodeInjectorError(
                f"libxkbcommon could not create a keymap for layout {layout!r}"
            )

        state = lib.xkb_state_new(keymap)
        if not state:
            lib.xkb_keymap_unref(keymap)
            lib.xkb_context_unref(context)
            raise UnicodeInjectorError("libxkbcommon could not create XKB state")
        return cls(lib, context, keymap, state)

    def key_text(self, keycode: int) -> str:
        buffer = ctypes.create_string_buffer(32)
        length = self.lib.xkb_state_key_get_utf8(
            self.state,
            keycode + 8,  # XKB keycodes are Linux evdev codes plus eight.
            buffer,
            len(buffer),
        )
        return buffer.raw[:length].decode("utf-8", errors="replace") if length > 0 else ""

    def update(self, keycode: int, direction: int) -> None:
        self.lib.xkb_state_update_key(self.state, keycode + 8, direction)

    def close(self) -> None:
        if self.state:
            self.lib.xkb_state_unref(self.state)
            self.state = ctypes.c_void_p()
        if self.keymap:
            self.lib.xkb_keymap_unref(self.keymap)
            self.keymap = ctypes.c_void_p()
        if self.context:
            self.lib.xkb_context_unref(self.context)
            self.context = ctypes.c_void_p()

    def __enter__(self) -> _XkbSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _find_key_for_character(
    xkb: _XkbSession, character: str
) -> tuple[int, tuple[int, ...]] | None:
    """Find an evdev key and modifiers that produce exactly *character*."""
    modifier_sets = (
        (),
        (_KEY_LEFTSHIFT,),
        (_KEY_RIGHTALT,),
        (_KEY_LEFTSHIFT, _KEY_RIGHTALT),
    )
    for modifiers in modifier_sets:
        for modifier in modifiers:
            xkb.update(modifier, _KEY_PRESS)
        try:
            for keycode in range(1, 256):
                if xkb.key_text(keycode) == character:
                    return keycode, modifiers
        finally:
            for modifier in reversed(modifiers):
                xkb.update(modifier, _KEY_RELEASE)
    return None


def _ioctl(fd: int, request: int, value: int | None = None) -> None:
    import fcntl

    ioctl = getattr(fcntl, "ioctl")
    if value is None:
        ioctl(fd, request)
    else:
        ioctl(fd, request, value)


class _UinputKeyboard:
    """Minimal uinput keyboard writer with no evdev dependency."""

    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._created = False

    @classmethod
    def create(cls, path: str = _UINPUT_DEVICE) -> _UinputKeyboard:
        if not sys.platform.startswith("linux"):
            raise UnicodeInjectorError("the Unicode injector requires Linux")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as exc:
            raise UnicodeInjectorError(
                f"cannot open {path}: {exc}; ensure /dev/uinput exists and is accessible"
            ) from exc

        keyboard = cls(fd)
        try:
            _ioctl(fd, _UI_SET_EVBIT, _EV_KEY)
            for keycode in range(1, 256):
                _ioctl(fd, _UI_SET_KEYBIT, keycode)
            device = bytearray(_UINPUT_USER_DEV_SIZE)
            device[: len(b"yazses-unicode") + 1] = b"yazses-unicode\0"
            struct.pack_into("<HHHHI", device, 80, 0x03, 0x01, 0x01, 0x01, 0)
            _write_all(fd, device)
            _ioctl(fd, _UI_DEV_CREATE)
            keyboard._created = True
            time.sleep(0.05)
            return keyboard
        except Exception:
            keyboard.close()
            raise

    def _event(self, event_type: int, code: int, value: int) -> None:
        now = time.time()
        seconds = int(now)
        micros = int((now - seconds) * 1_000_000)
        _write_all(self._fd, struct.pack("llHHi", seconds, micros, event_type, code, value))

    def key(self, keycode: int, value: int) -> None:
        self._event(_EV_KEY, keycode, value)
        self._event(_EV_SYN, _SYN_REPORT, 0)

    def tap(self, keycode: int, modifiers: Iterable[int] = ()) -> None:
        modifiers = tuple(modifiers)
        for modifier in modifiers:
            self.key(modifier, _KEY_PRESS)
        self.key(keycode, _KEY_PRESS)
        self.key(keycode, _KEY_RELEASE)
        for modifier in reversed(modifiers):
            self.key(modifier, _KEY_RELEASE)

    def close(self) -> None:
        if getattr(self, "_fd", None) is None:
            return
        try:
            if self._created:
                _ioctl(self._fd, _UI_DEV_DESTROY)
        finally:
            os.close(self._fd)
            self._fd = None  # type: ignore[assignment]
            self._created = False

    def __enter__(self) -> _UinputKeyboard:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _write_all(fd: int, data: bytes | bytearray) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _keycode_for_name(name: str) -> int:
    aliases = {
        "ctrl": "KEY_LEFTCTRL",
        "control": "KEY_LEFTCTRL",
        "shift": "KEY_LEFTSHIFT",
        "alt": "KEY_LEFTALT",
        "meta": "KEY_LEFTMETA",
        "super": "KEY_LEFTMETA",
        "win": "KEY_LEFTMETA",
        "return": "KEY_ENTER",
        "enter": "KEY_ENTER",
        "backspace": "KEY_BACKSPACE",
        "tab": "KEY_TAB",
        "escape": "KEY_ESC",
        "esc": "KEY_ESC",
        "left": "KEY_LEFT",
        "right": "KEY_RIGHT",
        "up": "KEY_UP",
        "down": "KEY_DOWN",
        "home": "KEY_HOME",
        "end": "KEY_END",
        "space": "KEY_SPACE",
    }
    key_name = aliases.get(name.lower(), name.upper())
    if not key_name.startswith("KEY_"):
        key_name = f"KEY_{key_name}"
    try:
        return KEYCODES[key_name]
    except KeyError as exc:
        raise UnicodeInjectorError(f"unknown key {name!r}") from exc


def _tap_combo(keyboard: _UinputKeyboard, combo: str) -> None:
    parts = [part for part in combo.split("+") if part]
    if not parts:
        return
    keycodes = [_keycode_for_name(part) for part in parts]
    keyboard.tap(keycodes[-1], keycodes[:-1])


def runtime_availability() -> tuple[str, str] | None:
    """Return ``(reason, remedy)`` when this backend cannot run, else ``None``."""
    if not sys.platform.startswith("linux"):
        return (
            "the 'unicode' backend requires Linux",
            "select `auto`, `type`, `clipboard`, or `wtype` on this platform",
        )
    if not os.path.exists(_UINPUT_DEVICE):
        return (
            "the 'unicode' backend needs /dev/uinput",
            "load the uinput kernel module and grant the current user access",
        )
    try:
        _load_xkb_library()
    except UnicodeInjectorError:
        return (
            "the 'unicode' backend needs libxkbcommon",
            "install the system libxkbcommon package (for example `libxkbcommon0`)",
        )
    return None


class UnicodeInjector:
    """Opt-in injector that preserves non-ASCII characters on Linux layouts."""

    def __init__(self, *, device_path: str = _UINPUT_DEVICE) -> None:
        self._device_path = device_path
        self._xkb: _XkbSession | None = None
        self._keyboard: _UinputKeyboard | None = None

    def _ready(self) -> tuple[_XkbSession, _UinputKeyboard]:
        if self._xkb is None:
            self._xkb = _XkbSession.create()
        if self._keyboard is None:
            try:
                self._keyboard = _UinputKeyboard.create(self._device_path)
            except Exception:
                self._xkb.close()
                self._xkb = None
                raise
        return self._xkb, self._keyboard

    def inject(self, text: str) -> None:
        if not text:
            return
        xkb, keyboard = self._ready()
        for character in text:
            result = _find_key_for_character(xkb, character)
            if result is None:
                raise UnicodeInjectorError(
                    f"the active XKB layout cannot produce {character!r}; "
                    "switch to a layout containing it or use clipboard injection"
                )
            keycode, modifiers = result
            keyboard.tap(keycode, modifiers)

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        _, keyboard = self._ready()
        for _ in range(count):
            keyboard.tap(_KEY_BACKSPACE)

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        _, keyboard = self._ready()
        for combo in keys:
            _tap_combo(keyboard, combo)

    def close(self) -> None:
        if self._keyboard is not None:
            self._keyboard.close()
            self._keyboard = None
        if self._xkb is not None:
            self._xkb.close()
            self._xkb = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
