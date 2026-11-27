"""Linux hotkey backend — wraps EvdevHoldListener with key-id resolution."""

from __future__ import annotations

from collections.abc import Callable

import evdev
from evdev import ecodes

from yazses.hotkeys.evdev_hold import (
    EvdevHoldListener,
    _is_virtual_device,
    _looks_like_keyboard,
)

# key_id strings → evdev key codes. Used by the cross-platform abstraction so
# the same config value resolves correctly across Linux/Mac/Win.
_KEY_MAP: dict[str, int] = {
    "space": ecodes.KEY_SPACE,
    "right_ctrl": ecodes.KEY_RIGHTCTRL,
    "left_ctrl": ecodes.KEY_LEFTCTRL,
    "right_alt": ecodes.KEY_RIGHTALT,
    "left_alt": ecodes.KEY_LEFTALT,
    "right_meta": ecodes.KEY_RIGHTMETA,
    "left_meta": ecodes.KEY_LEFTMETA,
    "right_shift": ecodes.KEY_RIGHTSHIFT,
    "left_shift": ecodes.KEY_LEFTSHIFT,
    # macOS naming compatibility — "right_option" maps to evdev's right alt
    # key code so a shared config file behaves sensibly across platforms.
    "right_option": ecodes.KEY_RIGHTALT,
    "left_option": ecodes.KEY_LEFTALT,
}

# Keys whose press produces a printable character that needs cleanup via
# backspace when used as a hold-to-talk hotkey. Modifier-only keys don't.
_CHARACTER_KEYS: frozenset[str] = frozenset({"space"})


def resolve_key_id(key_id: str, default: str = "right_alt") -> tuple[str, int]:
    """Return (canonical_key_id, evdev_key_code). 'auto' resolves to default."""
    name = key_id.lower()
    if name == "auto":
        name = default
    if name not in _KEY_MAP:
        raise ValueError(
            f"Unknown hotkey {key_id!r}. Supported: {sorted(_KEY_MAP)} or 'auto'."
        )
    return name, _KEY_MAP[name]


def can_read_keyboard(key_id: str) -> bool:
    """Whether a real keyboard carrying *key_id* can actually be opened. Never raises.

    Opens the nodes rather than asking about permission bits: `os.access` does not see
    a confinement profile, so inside a snap without `raw-input` it can say yes to a
    node that every open then refuses.
    """
    try:
        _, code = resolve_key_id(key_id)
        paths = evdev.list_devices()
    except Exception:
        return False
    for path in paths:
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        try:
            if (
                not _is_virtual_device(dev)
                and _looks_like_keyboard(dev)
                and code in dev.capabilities().get(ecodes.EV_KEY, ())
            ):
                return True
        except OSError:
            continue
        finally:
            dev.close()
    return False


class LinuxHotkey:
    """HotkeyBackend implementation for Linux via evdev."""

    def __init__(
        self,
        key_id: str,
        threshold_ms: int,
        on_hold_start: Callable[[int], None],
        on_hold_end: Callable[[], None],
    ) -> None:
        self._key_id, key_code = resolve_key_id(key_id)
        self._produces_char = self._key_id in _CHARACTER_KEYS

        # Suppress leaked-character count for non-character keys (Right Ctrl
        # etc.) — there's nothing to backspace.
        def _wrapped_start(leaked: int) -> None:
            on_hold_start(leaked if self._produces_char else 0)

        self._listener = EvdevHoldListener(
            threshold_ms=threshold_ms,
            on_hold_start=_wrapped_start,
            on_hold_end=on_hold_end,
            key_code=key_code,
            produces_char=self._produces_char,
        )

    def run(self) -> None:
        self._listener.run()

    def stop(self) -> None:
        self._listener.stop()

    @property
    def key_id(self) -> str:
        return self._key_id
