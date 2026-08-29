import subprocess

from yazses.inject.keycodes import KEYCODES


def _keycode_from_evdev(name: str) -> int | None:
    """Resolve a ``KEY_*`` name outside the keyboard range (code > 255).

    The committed table covers 1-255, which is every key a keyboard emits. The rest
    -- media, brightness, vendor keys -- stay behind evdev rather than being frozen
    into a table nothing verifies, so anything that resolved on Linux before still
    resolves. evdev is Linux-only (`sys_platform == "linux"` in pyproject.toml, and
    it does not build on the BSDs), so its absence is an ordinary answer of "no",
    never an error: on those platforms the table above is the whole answer.
    """
    try:
        from evdev import ecodes
    except ImportError:
        return None
    code = getattr(ecodes, name, None)
    return code if isinstance(code, int) else None


def ydotool_key_args(combo: str) -> list[str]:
    """Convert a key combo into ydotool 1.x ``key`` tokens.

    ydotool's ``key`` command takes **numeric** ``<keycode>:<state>`` tokens and
    *silently ignores* symbolic names — ``ydotool key ctrl+v`` and even
    ``ydotool key KEY_LEFTCTRL+KEY_V`` emit no events at all (verified against
    ydotoold's virtual input device). Only ``29:1 47:1 47:0 29:0`` works.

    Given a combo like ``"ctrl+v"``, ``"shift+Left"`` or ``"KEY_BACKSPACE"``,
    return the press-in-order / release-in-reverse keycode tokens, e.g.
    ``["29:1", "47:1", "47:0", "29:0"]`` for Ctrl+V.
    """
    aliases = {
        "ctrl": "KEY_LEFTCTRL", "control": "KEY_LEFTCTRL",
        "shift": "KEY_LEFTSHIFT", "alt": "KEY_LEFTALT",
        "meta": "KEY_LEFTMETA", "super": "KEY_LEFTMETA", "win": "KEY_LEFTMETA",
        "return": "KEY_ENTER", "enter": "KEY_ENTER", "backspace": "KEY_BACKSPACE",
        "tab": "KEY_TAB", "escape": "KEY_ESC", "esc": "KEY_ESC",
        "left": "KEY_LEFT", "right": "KEY_RIGHT", "up": "KEY_UP", "down": "KEY_DOWN",
        "home": "KEY_HOME", "end": "KEY_END",
        "page_up": "KEY_PAGEUP", "page_down": "KEY_PAGEDOWN",
        "delete": "KEY_DELETE", "del": "KEY_DELETE", "space": "KEY_SPACE",
    }
    codes: list[int] = []
    for part in (p for p in combo.split("+") if p):
        low = part.lower()
        if low in aliases:
            name = aliases[low]
        elif part.upper().startswith("KEY_"):
            name = part.upper()
        else:
            name = f"KEY_{part.upper()}"
        code = KEYCODES.get(name)
        if code is None:
            code = _keycode_from_evdev(name)
        if code is None:
            raise ValueError(f"ydotool: unknown key {part!r} (resolved to {name})")
        codes.append(code)
    return [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]


# Every keycode `ydotool type` can press: the number row through space, plus both
# shifts (Linux input-event-codes 2..57). After typing we send a key-up for all of
# them so that if the compositor dropped the real final key-up (Ubuntu 26+ mutter
# does this intermittently with synthetic input), no character can stay "held" and
# auto-repeat into a flood (`mmmm…`). A key-up for a key that isn't down is a
# harmless no-op, so this is safe and layout-independent.
#
# We ALSO release the right-side modifier/meta keycodes that fall *outside* 2..57
# and are common hold-to-talk hotkeys: right_ctrl=97, right_alt=100, left_meta=125,
# right_meta=126. (left_ctrl/left_alt/both shifts are already inside 2..57.) If the
# hotkey is one of these and mutter drops its key-up, the modifier stays logically
# held — which turns the next Space into Alt+Space (the GNOME window menu, whose
# first item is "Take Screenshot") and mangles typed letters via the AltGr layer.
# Injection only runs after hold-end (the key is physically released), so releasing
# it here is safe. See the stuck-right_alt report.
_HOTKEY_MODIFIER_KEYCODES = (97, 100, 125, 126)
_RELEASE_ALL_TYPED_KEYS = [f"{code}:0" for code in range(2, 58)] + [
    f"{code}:0" for code in _HOTKEY_MODIFIER_KEYCODES
]


class YdotoolInjector:
    # ~12 ms/char (6 ms between events + 6 ms hold): faster than ydotool's 20/20
    # default so long dictations don't crawl, but slow enough that the compositor
    # doesn't drop characters mid-string.
    _KEY_DELAY_MS = 6
    _KEY_HOLD_MS = 6

    def inject(self, text: str) -> None:
        if not text:
            return
        # Scale the timeout with length so a long dictation never times out. A
        # timeout looks like a failure to LinuxInjector and triggers the clipboard
        # fallback, which re-injects the WHOLE text — the "typed twice" bug. Budget
        # 30 ms/char (~2.5x the real ~12 ms) plus a base.
        timeout = 10.0 + len(text) * 0.03
        subprocess.run(
            ["ydotool", "type", "-d", str(self._KEY_DELAY_MS),
             "-H", str(self._KEY_HOLD_MS), "--", text],
            check=True,
            timeout=timeout,
        )
        # Flood guard — release any key the compositor failed to release.
        subprocess.run(
            ["ydotool", "key"] + _RELEASE_ALL_TYPED_KEYS,
            check=False,
            timeout=5,
        )

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        subprocess.run(
            ["ydotool", "key"] + ydotool_key_args("KEY_BACKSPACE") * count,
            check=True,
            timeout=10,
        )

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        args: list[str] = []
        for combo in keys:
            args += ydotool_key_args(combo)
        subprocess.run(["ydotool", "key"] + args, check=True, timeout=10)
