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

import ast
import ctypes
import ctypes.util
import json
import logging
import os
import shutil
import struct
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from yazses.inject.keycodes import KEYCODES

log = logging.getLogger(__name__)

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

# Give compositors time to propagate uinput modifier state before subsequent key events.
_MODIFIER_SETTLE_SECONDS = 0.020
_INTER_CHARACTER_GAP_SECONDS = 0.020


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


# --------------------------------------------------------------- layout detection
#
# uinput sends KEYCODES, and the compositor turns them into characters with ITS active
# layout. So the layout resolved here has to be the one the session is actually using,
# or the injector types the wrong letters. Nothing below can prove the compositor agrees
# with it; the probes only read what the session reports, and every answer is labelled
# with the source it came from.

#: Read-only local probes. Each is independently time-limited; none is a network call.
_PROBE_TIMEOUT_SECONDS = 0.8

#: Sway reports layout *descriptions* (``"Persian"``), not XKB codes. Only these map;
#: an unmapped description is treated as no answer, never guessed. Descriptions are the
#: ones in xkeyboard-config's ``rules/base.lst``.
_SWAY_LAYOUT_CODES = {
    "Arabic": "ara",
    "English (UK)": "gb",
    "English (US)": "us",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Persian": "ir",
    "Portuguese": "pt",
    "Spanish": "es",
    "Swedish": "se",
}

#: The layout keys are resolved against when nothing says otherwise: the historical
#: default, and the one an English machine uses.
_DEFAULT_LAYOUT = "us"

#: The guess from LANG when nothing else answers (the behaviour before layout probing).
_LANG_LAYOUTS = (
    ("sv", "se"),
    ("de", "de"),
    ("fr", "fr"),
    ("es", "es"),
    ("it", "it"),
    ("pt", "pt"),
    ("en_gb", "gb"),
)

#: Persian (and Arabic-script) letters only exist on these XKB layouts.
PERSIAN_LAYOUT = "ir"

ProbeRunner = Callable[[list[str]], str | None]


@dataclass(frozen=True)
class LayoutDetection:
    """The XKB layout keys are resolved against, where it came from, and what else is listed.

    ``active`` is the single layout used to resolve characters. ``listed`` is every
    layout the session reports, in order, so a caller can explain a Persian layout that
    is present but is not the one in use. ``source`` names the probe that answered.
    """

    active: str
    listed: tuple[str, ...]
    source: str


def _split_layouts(value: str) -> tuple[str, ...]:
    """``"us,ir"`` -> ``("us", "ir")``. A variant (``"ir+pes"``) is dropped; ``"(unset)"`` is none."""
    value = value.strip()
    if not value or value.startswith("("):
        return ()
    codes: list[str] = []
    for part in value.split(","):
        code = part.strip().split("+", 1)[0].strip().lower()
        if code:
            codes.append(code)
    return tuple(codes)


def parse_localectl_layouts(text: str) -> tuple[str, ...]:
    """The ``X11 Layout`` of ``localectl status``. Pure; ``()`` when absent or unset.

    Real output on a machine with a set layout::

        System Locale: LANG=en_US.UTF-8
            VC Keymap: (unset)
           X11 Layout: us
            X11 Model: pc105
    """
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == "X11 Layout":
            return _split_layouts(value)
    return ()


def parse_gsettings_sources(text: str) -> tuple[str, ...]:
    """The ``xkb`` layouts in a ``gsettings get org.gnome.desktop.input-sources`` value.

    Pure and total. The value is a GVariant text of ``(type, id)`` pairs, e.g.
    ``"[('xkb', 'us'), ('xkb', 'ir'), ('ibus', 'anthy')]"``; only ``xkb`` entries are
    keyboard layouts. An empty array prints as ``"@a(ss) []"``. Parsed with
    ``ast.literal_eval``, which accepts literals only, so nothing in the output runs.
    """
    body = text.strip()
    if body.startswith("@"):
        body = body.split(" ", 1)[1] if " " in body else ""
    if not body:
        return ()
    try:
        pairs = ast.literal_eval(body)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return ()
    if not isinstance(pairs, (list, tuple)):
        return ()
    codes: list[str] = []
    for pair in pairs:
        if (
            isinstance(pair, tuple)
            and len(pair) == 2
            and pair[0] == "xkb"
            and isinstance(pair[1], str)
        ):
            codes.extend(_split_layouts(pair[1]))
    return tuple(codes)


def parse_sway_inputs(text: str) -> tuple[str, ...]:
    """The active keyboard layout first, then the others, from ``swaymsg -t get_inputs``.

    Pure and total. Returns ``()`` unless the *active* layout's description is one this
    module can map: a list whose active entry is unknown has no reliable first element,
    and guessing one would resolve every key against the wrong layout.
    """
    try:
        data = json.loads(text)
    except ValueError:
        return ()
    if not isinstance(data, list):
        return ()
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "keyboard":
            continue
        names = item.get("xkb_layout_names")
        index = item.get("xkb_active_layout_index")
        if not isinstance(names, list) or not isinstance(index, int):
            continue
        if not 0 <= index < len(names) or names[index] not in _SWAY_LAYOUT_CODES:
            continue
        ordered = [names[index]] + [name for i, name in enumerate(names) if i != index]
        return tuple(
            _SWAY_LAYOUT_CODES[name]
            for name in ordered
            if isinstance(name, str) and name in _SWAY_LAYOUT_CODES
        )
    return ()


def _run_probe(argv: list[str]) -> str | None:
    """Run one read-only local command. Its stdout, or ``None``. Never raises.

    ``None`` covers absent, failed, slow and unparseable alike: a probe that did not
    answer is no evidence, so the next source is asked instead.
    """
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except Exception:  # noqa: BLE001 - absent, timed out, or undecodable: no answer
        return None
    return done.stdout if done.returncode == 0 else None


def detect_layout(
    *,
    environ: Mapping[str, str] | None = None,
    run: ProbeRunner = _run_probe,
    which: Callable[[str], str | None] = shutil.which,
) -> LayoutDetection:
    """The layout keys are resolved against, from the first source that answers.

    Order: ``XKB_DEFAULT_LAYOUT`` / ``XKB_LAYOUT`` (as before), then sway's active
    layout, then GNOME's ``mru-sources`` (the layout in use is listed first) and
    ``sources``, then ``localectl``'s system default, then ``us``. The session's own
    state beats the system default: on a machine installed as ``us`` where the user
    switched to Persian, ``localectl`` says ``us`` and the session says ``ir``. Each
    probe runs only when its tool is on ``PATH`` and is skipped on any failure.
    """
    env = os.environ if environ is None else environ
    for variable in ("XKB_DEFAULT_LAYOUT", "XKB_LAYOUT"):
        layouts = _split_layouts(env.get(variable, ""))
        if layouts:
            return LayoutDetection(layouts[0], layouts, variable)

    if which("swaymsg"):
        layouts = parse_sway_inputs(run(["swaymsg", "-t", "get_inputs", "--raw"]) or "")
        if layouts:
            return LayoutDetection(layouts[0], layouts, "sway")

    if which("gsettings"):
        # `mru-sources` names the layout in use first, but can list fewer layouts than
        # `sources` does (here: only "us" while "ir" is configured). The listed set is
        # the union, so "the session also lists ir" is said whenever ir is configured.
        mru = parse_gsettings_sources(
            run(["gsettings", "get", "org.gnome.desktop.input-sources", "mru-sources"]) or ""
        )
        configured = parse_gsettings_sources(
            run(["gsettings", "get", "org.gnome.desktop.input-sources", "sources"]) or ""
        )
        if mru:
            return LayoutDetection(
                mru[0], tuple(dict.fromkeys((*configured, *mru))), "gsettings mru-sources"
            )
        if configured:
            return LayoutDetection(configured[0], configured, "gsettings sources")

    if which("localectl"):
        layouts = parse_localectl_layouts(run(["localectl", "status"]) or "")
        if layouts:
            return LayoutDetection(layouts[0], layouts, "localectl")

    # Last resort before "us", kept from the original guess: the language of the session
    # for a handful of European layouts. A session that reports nothing (no env var, no
    # gsettings, no sway, an unset localectl) used to get these and must still.
    language = env.get("LANG", "").lower()
    for prefix, layout in _LANG_LAYOUTS:
        if language.startswith(prefix):
            return LayoutDetection(layout, (layout,), f"LANG={env.get('LANG', '')}")

    return LayoutDetection(_DEFAULT_LAYOUT, (), "default")


def _layout_name() -> str:
    """The layout keys are resolved against. See :func:`detect_layout`."""
    return detect_layout().active


def _is_arabic_script(character: str) -> bool:
    code = ord(character)
    return 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F or 0xFB50 <= code <= 0xFEFF


def _missing_layout_message(layout: str, character: str) -> str:
    """Why *character* cannot be typed under *layout*, in words a user can act on."""
    message = (
        f"the active XKB layout {layout!r} cannot produce {character!r}; "
        "switch to a layout containing it or use clipboard injection"
    )
    if _is_arabic_script(character):
        message += (
            f" (Persian and Arabic letters need the {PERSIAN_LAYOUT!r} or 'ara' layout "
            "to be the active one in the compositor)"
        )
    return message


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
    #: The XKB layout the keymap was built for. Named in errors, so a failure says which
    #: layout was actually consulted.
    layout: str = ""

    @classmethod
    def create(cls) -> _XkbSession:
        if not sys.platform.startswith("linux"):
            raise UnicodeInjectorError("the Unicode injector requires Linux")

        lib = _load_xkb_library()
        _configure_xkb(lib)
        context = lib.xkb_context_new(0)
        if not context:
            raise UnicodeInjectorError("libxkbcommon could not create an XKB context")

        detection = detect_layout()
        layout = detection.active
        log.info(
            "unicode injector resolves keys against XKB layout %r (from %s; listed: %s)",
            layout,
            detection.source,
            ", ".join(detection.listed) or "none",
        )
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
        return cls(lib, context, keymap, state, layout)

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
        if modifiers:
            time.sleep(_MODIFIER_SETTLE_SECONDS)
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

    def _xkb_ready(self) -> _XkbSession:
        if self._xkb is None:
            self._xkb = _XkbSession.create()
        return self._xkb

    def _ready(self) -> tuple[_XkbSession, _UinputKeyboard]:
        self._xkb_ready()
        assert self._xkb is not None
        if self._keyboard is None:
            try:
                self._keyboard = _UinputKeyboard.create(self._device_path)
            except Exception:
                self._xkb.close()
                self._xkb = None
                raise
        return self._xkb, self._keyboard

    @staticmethod
    def _plan(xkb: _XkbSession, text: str) -> list[tuple[int, tuple[int, ...]]]:
        """The key press for every character of *text*, or raise before any is typed.

        Resolving the whole burst first is what makes a failure clean. Resolving one
        character at a time typed everything up to the first one the layout lacks and
        *then* raised -- and `LinuxInjector` answers a raise by pasting the whole burst
        from the clipboard, so the typed prefix appeared twice. A Mandarin sentence
        is exactly that case: ``"版本 v2.0"`` on a Latin layout has no key for 版 (#501).
        """
        found: dict[str, tuple[int, tuple[int, ...]] | None] = {}
        plan: list[tuple[int, tuple[int, ...]]] = []
        for character in text:
            if character not in found:
                found[character] = _find_key_for_character(xkb, character)
            result = found[character]
            if result is None:
                raise UnicodeInjectorError(
                    _missing_layout_message(getattr(xkb, "layout", "") or "?", character)
                )
            plan.append(result)
        return plan

    def ensure_producible(self, text: str) -> None:
        """Raise :class:`UnicodeInjectorError` if the layout cannot produce all of *text*.

        Types nothing. For a caller that interleaves this injector with another
        backend (``YdotoolInjector``'s mixed path) and must know before it types its
        own part of the burst that this one will not fail half-way.
        """
        if text:
            self._plan(self._xkb_ready(), text)

    def inject(self, text: str) -> None:
        if not text:
            return
        xkb, keyboard = self._ready()
        plan = self._plan(xkb, text)
        for index, (keycode, modifiers) in enumerate(plan):
            keyboard.tap(keycode, modifiers)
            if index < len(plan) - 1:
                time.sleep(_INTER_CHARACTER_GAP_SECONDS)

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
