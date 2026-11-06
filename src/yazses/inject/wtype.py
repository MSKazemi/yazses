import subprocess

from yazses.inject.payload import hide_payload

# wtype resolves `-M`/`-m` against a fixed table and exits 1 on anything else
# ("Invalid modifier name"). Its accepted names, from upstream main.c `mod_names[]`
# (https://github.com/atx/wtype, read 2026-11-06): shift, capslock, ctrl, logo, win,
# alt, altgr, mod1..mod4 -- matched with strcasecmp. The combos YazSes sends speak
# the same vocabulary as the X11 and ydotool backends, where `meta`, `super` and
# `cmd` all mean the Windows/Super key (xdotool.py `_xdotool_combo`, ydotool.py
# `ydotool_key_names`) and `control` means Ctrl. None of those four is in wtype's
# table, so on wtype every such combo was refused outright and the voice command
# did nothing -- and the clipboard fallback, which sends keys through the very same
# wtype argv on a session without ydotool, failed the same way.
_WTYPE_MODIFIERS: dict[str, str] = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "altgr": "altgr",
    "meta": "logo",
    "super": "logo",
    "cmd": "logo",
    "win": "logo",
    "logo": "logo",
}

# `-k` goes through xkb_keysym_from_name(..., XKB_KEYSYM_CASE_INSENSITIVE) and wtype
# exits 1 on NoSymbol ("Unknown key"). Case is therefore free ("left", "page_up",
# "backspace" all resolve), but the short aliases ydotool.py accepts are not keysym
# names at all. Only those are mapped here.
_WTYPE_KEYS: dict[str, str] = {
    "enter": "Return",
    "esc": "Escape",
    "del": "Delete",
}


def wtype_combo_args(combo: str) -> list[str]:
    """wtype argv tokens for one combo: ``"meta+k"`` -> ``-M logo -k k -m logo``.

    Modifiers are pressed in order and released in reverse, so a two-modifier
    chord unwinds symmetrically. A modifier wtype does not know is passed through
    lowercased: wtype itself is the authority on its table and refuses it with a
    non-zero exit, which ``check=True`` turns into the error the caller needs.
    """
    parts = combo.split("+")
    modifiers = [_WTYPE_MODIFIERS.get(m.lower(), m.lower()) for m in parts[:-1]]
    key_name = parts[-1]
    key_name = _WTYPE_KEYS.get(key_name.lower(), key_name)
    args: list[str] = []
    for mod in modifiers:
        args += ["-M", mod]
    args += ["-k", key_name]
    for mod in reversed(modifiers):
        args += ["-m", mod]
    return args


def wtype_key_argv(keys: list[str]) -> list[str]:
    """Full ``wtype`` argv sending every combo in *keys*, in order."""
    args: list[str] = ["wtype"]
    for key in keys:
        args += wtype_combo_args(key)
    return args


class WtypeInjector:
    def inject(self, text: str) -> None:
        with hide_payload():
            subprocess.run(["wtype", "--", text], check=True, timeout=10)

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        args: list[str] = []
        for _ in range(count):
            args += ["-k", "BackSpace"]
        subprocess.run(["wtype"] + args, check=True, timeout=10)

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        subprocess.run(wtype_key_argv(keys), check=True, timeout=10)
