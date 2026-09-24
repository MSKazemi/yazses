import itertools
import subprocess
from collections.abc import Iterable, Sequence

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


# --- Two incompatible ydotool CLIs --------------------------------------------
#
# ydotool 1.x and ydotool 0.1.x are different command-line tools wearing the same
# name, and Debian/Ubuntu ship the old one (0.1.8 on Ubuntu 24.04 through 26.04).
# Everything below existed for 1.x and was silently a no-op on 0.1.8:
#
#   ydotool type -d 6 -H 6 -- text   ->  "type: error: unrecognised option '-d'"
#   ydotool key 29:1 47:1 47:0 29:0  ->  types "2", not Ctrl+V
#
# and -- the reason this could be lost rather than reported -- **0.1.8 exits 0 on a
# parse error**. `check=True` never raised, so LinuxInjector's clipboard fallback
# never fired, nothing reached the log, and `doctor` said the backend was fine while
# every dictation went nowhere. So: detect the dialect, and never trust the exit code.
DIALECT_V1 = "v1"
DIALECT_V0 = "v0"

_dialect_cache: str | None = None


class YdotoolCliError(RuntimeError):
    """ydotool did not do what it was asked -- whatever its exit code says."""


class YdotoolOptionError(YdotoolCliError):
    """ydotool refused the command line itself, so it typed nothing.

    Separate from the base class on purpose: this is the only failure after which
    re-running the command in the other dialect cannot double-type, because a
    refused command line emitted no events at all.
    """


_OPTION_ERROR_MARKERS = ("unrecognised option", "unrecognized option", "invalid option")


def _classify(stderr: str, returncode: int) -> type[YdotoolCliError] | None:
    """The exception for this result, or None when it succeeded.

    0.1.8 writes ordinary progress to stderr ("notice: Using ydotoold backend",
    "Key delay was set to 6 milliseconds."), so only an explicit error is an error.
    """
    low = stderr.lower()
    if any(marker in low for marker in _OPTION_ERROR_MARKERS):
        return YdotoolOptionError
    if ": error:" in low or returncode != 0:
        return YdotoolCliError
    return None


def run_ydotool(args: Sequence[str], timeout: float, check: bool = True) -> None:
    """Run ydotool and raise on failure, including the failures it exits 0 for."""
    argv = list(args)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:  # pragma: no cover - `which` gates selection
        raise YdotoolCliError("ydotool is not installed") from exc
    failure = _classify(proc.stderr or "", proc.returncode)
    if failure is not None and check:
        raise failure(f"{' '.join(argv)} -> exit {proc.returncode}: {(proc.stderr or '').strip()}")


def _probe_dialect() -> str:
    """Which ydotool is installed, asked once and cached.

    `type --help` is the probe because it is the one question both CLIs answer
    without emitting a keystroke. 1.x documents ``-d, --key-delay`` **and**
    ``-H, --key-hold`` (verified against upstream v1.0.4 `Client/tool_type.c`);
    0.1.x documents `--key-delay` and has no hold time at all.

    **Only a positive 0.1.x signature returns v0, and everything else returns v1**
    -- including an unreadable answer or a future ydotool whose help we do not
    recognise. The asymmetry is deliberate, because only one of the two mistakes
    can correct itself: guessing v1 on a 0.1.x machine produces
    `unrecognised option`, which `inject` catches and downgrades. Guessing v0 on a
    1.x machine produces *silence* -- 1.x's `key` ignores symbolic names without
    an error and emits no events -- so there is nothing to catch.
    """
    try:
        proc = subprocess.run(
            ["ydotool", "type", "--help"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - defensive
        return DIALECT_V1
    help_text = f"{proc.stdout}{proc.stderr}".lower()
    looks_like_v0 = "key-delay" in help_text and "key-hold" not in help_text
    return DIALECT_V0 if looks_like_v0 else DIALECT_V1


def ydotool_dialect() -> str:
    """``DIALECT_V1`` or ``DIALECT_V0`` for the installed ydotool."""
    global _dialect_cache
    if _dialect_cache is None:
        _dialect_cache = _probe_dialect()
    return _dialect_cache


def set_ydotool_dialect(dialect: str | None) -> None:
    """Pin the dialect (``None`` re-probes). Used by the downgrade path and tests."""
    global _dialect_cache
    _dialect_cache = dialect


def ydotool_key_names(combo: str) -> list[str]:
    """Canonical evdev ``KEY_*`` names for *combo*, in press order.

    ``"ctrl+shift+v"`` -> ``["KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_V"]``.
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
    names: list[str] = []
    for part in (p for p in combo.split("+") if p):
        low = part.lower()
        if low in aliases:
            names.append(aliases[low])
        elif part.upper().startswith("KEY_"):
            names.append(part.upper())
        else:
            names.append(f"KEY_{part.upper()}")
    return names


def ydotool_key_args(combo: str) -> list[str]:
    """Convert a key combo into ydotool 1.x ``key`` tokens.

    ydotool 1.x's ``key`` command takes **numeric** ``<keycode>:<state>`` tokens and
    *silently ignores* symbolic names -- ``ydotool key ctrl+v`` and even
    ``ydotool key KEY_LEFTCTRL+KEY_V`` emit no events at all (verified against
    ydotoold's virtual input device). Only ``29:1 47:1 47:0 29:0`` works.

    0.1.x is the exact opposite and wants the symbolic form; see
    `ydotool_key_args_v0`.

    Given a combo like ``"ctrl+v"``, ``"shift+Left"`` or ``"KEY_BACKSPACE"``,
    return the press-in-order / release-in-reverse keycode tokens, e.g.
    ``["29:1", "47:1", "47:0", "29:0"]`` for Ctrl+V.
    """
    codes: list[int] = []
    for name in ydotool_key_names(combo):
        code = KEYCODES.get(name)
        if code is None:
            code = _keycode_from_evdev(name)
        if code is None:
            raise ValueError(f"ydotool: unknown key (resolved to {name})")
        codes.append(code)
    return [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]


# Every key 0.1.8's `key` actually resolves, measured on Ubuntu by grabbing the
# ydotoold virtual device and reading the events it emitted (EVIOCGRAB, so the
# probe typed into nothing). The table matters more than it looks: 0.1.8 has **no
# error path** for a name it does not know -- it types that name's first letter and
# exits 0. Measured: `Return` -> `r`, `Escape` -> `e`, `space` -> `s`,
# `Page_Up` -> `p`, `KEY_BACKSPACE` -> `k`, `rightctrl` -> `r`, `zzznotakey` -> `z`.
# `Return` is what commands/dispatch.py sends for "new line", so on an unmapped
# pass-through, saying "new line" typed the letter r.
#
# Anything absent here raises, which routes the keystroke to the clipboard fallback
# instead of quietly typing a wrong character. Names are matched case-insensitively
# by 0.1.8; they are written lowercase here.
_V0_KEY_TOKENS: dict[str, str] = {
    **{
        "KEY_ENTER": "enter",
        "KEY_ESC": "esc",
        "KEY_TAB": "tab",
        "KEY_BACKSPACE": "backspace",
        "KEY_DELETE": "delete",
        "KEY_INSERT": "insert",
        "KEY_HOME": "home",
        "KEY_END": "end",
        "KEY_PAGEUP": "pageup",
        "KEY_PAGEDOWN": "pagedown",
        "KEY_UP": "up",
        "KEY_DOWN": "down",
        "KEY_LEFT": "left",
        "KEY_RIGHT": "right",
        "KEY_CAPSLOCK": "capslock",
        "KEY_NUMLOCK": "numlock",
        "KEY_SYSRQ": "sysrq",
        "KEY_LEFTCTRL": "ctrl",
        "KEY_LEFTSHIFT": "shift",
        "KEY_LEFTALT": "alt",
        "KEY_LEFTMETA": "super",
    },
    **{f"KEY_F{n}": f"f{n}" for n in range(1, 13)},
    **{f"KEY_{c}": c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    **{f"KEY_{d}": d for d in "0123456789"},
}


def ydotool_key_args_v0(combo: str) -> list[str]:
    """Convert a key combo into a ydotool 0.1.x ``key`` token, e.g. ``["ctrl+v"]``."""
    tokens: list[str] = []
    for name in ydotool_key_names(combo):
        token = _V0_KEY_TOKENS.get(name)
        if token is None:
            raise ValueError(
                f"ydotool 0.1.x cannot express {name}: its `key` has no error path and "
                f"would type the first letter of the name instead"
            )
        tokens.append(token)
    return ["+".join(tokens)]


def ydotool_key_argv(
    combos: Sequence[str],
    dialect: str | None = None,
    key_delay_ms: int | None = None,
) -> list[str]:
    """Full argv for `ydotool key` covering *combos*, in the installed dialect."""
    dialect = dialect or ydotool_dialect()
    argv = ["ydotool", "key"]
    if key_delay_ms is not None:
        # 0.1.x spells it --key-delay and rejects -d (for `key` as well as `type`).
        argv += (
            ["--key-delay", str(key_delay_ms)]
            if dialect == DIALECT_V0
            else ["-d", str(key_delay_ms)]
        )
    for combo in combos:
        argv += (
            ydotool_key_args_v0(combo) if dialect == DIALECT_V0 else ydotool_key_args(combo)
        )
    return argv


def run_ydotool_keys(
    combos: Sequence[str],
    timeout: float = 10.0,
    key_delay_ms: int | None = None,
    check: bool = True,
) -> None:
    """Send *combos*, downgrading to the 0.1.x dialect if 1.x's is refused."""
    dialect = ydotool_dialect()
    try:
        run_ydotool(ydotool_key_argv(combos, dialect, key_delay_ms), timeout=timeout, check=check)
    except YdotoolOptionError:
        if dialect != DIALECT_V1:
            raise
        set_ydotool_dialect(DIALECT_V0)
        run_ydotool(
            ydotool_key_argv(combos, DIALECT_V0, key_delay_ms), timeout=timeout, check=check
        )


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
#
# 1.x only: the guard is a list of bare key-*ups*, which the 0.1.x `key` grammar
# (press-and-release sequences of names) cannot express at all. Skipping it there
# costs nothing that machine had -- 0.1.8 predates the compositor behaviour it
# guards against, and every 0.1.x keystroke is a matched press/release by
# construction.
_HOTKEY_MODIFIER_KEYCODES = (97, 100, 125, 126)
_RELEASE_ALL_TYPED_KEYS = [f"{code}:0" for code in range(2, 58)] + [
    f"{code}:0" for code in _HOTKEY_MODIFIER_KEYCODES
]


def _ascii_runs(text: str) -> list[tuple[bool, str]]:
    """Split *text* into consecutive ASCII / non-ASCII runs, in order.

    ``ydotool type`` presses keycodes against the active XKB layout, so a
    character that layout has no keycode for produces nothing — see issue #329
    (Wayland dictation of Swedish/French/German/etc. text silently loses every
    accented or non-Latin character, with no error). Splitting into runs lets
    the caller keep sending the ASCII stretches through ``ydotool type``
    unchanged and route only the non-ASCII stretches through a layout-independent
    path.
    """
    return [
        (is_ascii, "".join(chars))
        for is_ascii, chars in itertools.groupby(text, key=str.isascii)
    ]


def release_keycodes(codes: Iterable[int], timeout: float = 3.0) -> None:
    """Send a bare key-up for each keycode. A no-op on 0.1.x, which has no such thing.

    0.1.x's `key` grammar is press-and-release sequences of *names*, and it has no
    error path: handed the 1.x token ``97:0`` it types the digit **9** (measured --
    it falls back to the first character of a token it does not recognise). The
    daemon runs this on every hold-end, so on Debian and Ubuntu the stuck-modifier
    guard was itself typing a stray digit into the user's document.
    """
    codes = sorted(codes)
    if not codes:
        return
    if ydotool_dialect() == DIALECT_V0:
        return
    run_ydotool(
        ["ydotool", "key", *[f"{code}:0" for code in codes]],
        timeout=timeout,
        check=False,
    )


class YdotoolInjector:
    # ~12 ms/char (6 ms between events + 6 ms hold): faster than ydotool's 20/20
    # default so long dictations don't crawl, but slow enough that the compositor
    # doesn't drop characters mid-string.
    _KEY_DELAY_MS = 6
    _KEY_HOLD_MS = 6

    def _type_argv(self, text: str, dialect: str) -> list[str]:
        if dialect == DIALECT_V0:
            # 0.1.x has --key-delay and no hold time; -d and -H are both refused.
            return ["ydotool", "type", "--key-delay", str(self._KEY_DELAY_MS), "--", text]
        return [
            "ydotool", "type", "-d", str(self._KEY_DELAY_MS),
            "-H", str(self._KEY_HOLD_MS), "--", text,
        ]

    def _type_ascii_run(self, run: str) -> None:
        """Type one ASCII run with whichever ydotool command line is installed."""
        # Scale the timeout with length so a long dictation never times out. A
        # timeout looks like a failure to LinuxInjector and triggers the clipboard
        # fallback, which re-injects the WHOLE text — the "typed twice" bug. Budget
        # 30 ms/char (~2.5x the real ~12 ms) plus a base.
        timeout = 10.0 + len(run) * 0.03
        dialect = ydotool_dialect()
        try:
            run_ydotool(self._type_argv(run, dialect), timeout=timeout)
        except YdotoolOptionError:
            # A refused command line typed nothing, so retrying cannot double-type.
            if dialect != DIALECT_V1:
                raise
            set_ydotool_dialect(DIALECT_V0)
            run_ydotool(self._type_argv(run, DIALECT_V0), timeout=timeout)

    def inject(self, text: str) -> None:
        if not text:
            return
        if text.isascii():
            # The overwhelmingly common case (and everything this backend could
            # handle before #329): one `ydotool type` call, exactly as before.
            self._type_ascii_run(text)
        else:
            self._inject_mixed(text)
        # Flood guard — release any key the compositor failed to release. Read the
        # dialect AFTER typing: a run may have downgraded it. 0.1.x cannot express a
        # bare key-up at all, so there the guard is a no-op by construction.
        if ydotool_dialect() == DIALECT_V1:
            run_ydotool(["ydotool", "key", *_RELEASE_ALL_TYPED_KEYS], timeout=5, check=False)

    def _inject_mixed(self, text: str) -> None:
        """Type ASCII runs via ``ydotool type``; route non-ASCII runs around it.

        The layout-independent replacement already exists: `inject/unicode.py`'s
        `UnicodeInjector` resolves a character through ``libxkbcommon`` and presses
        it via a private ``/dev/uinput`` keyboard, so it does not depend on the
        active layout having a keycode for it. It shipped opt-in (#364) behind
        ``[injection] backend = "unicode"`` because it was not yet known to be safe
        as everyone's default. It is safe as *this* backend's fallback: any machine
        where `YdotoolInjector` is even selected already has a working ydotoold
        talking to `/dev/uinput`, and `yazses setup`'s udev rule
        (``GROUP="input", MODE="0660"``) grants that same access to the invoking
        user's own process — the same `input`-group membership
        `own_ydotoold_can_reach_uinput` already requires before `auto` will pick
        ydotool at all. So this introduces no new permission the user didn't
        already need.

        A single `UnicodeInjector` is reused across every non-ASCII run in this
        call so it opens `/dev/uinput` and builds the XKB keymap at most once, and
        it is always closed — success or failure — instead of leaking the uinput
        device.

        Note this path is layout-independent and therefore also **dialect**-
        independent: it never shells out to ydotool, so ydotool 0.1.x vs 1.x does
        not enter into it.
        """
        from yazses.inject.unicode import UnicodeInjector

        unicode_injector: UnicodeInjector | None = None
        try:
            for is_ascii, run in _ascii_runs(text):
                if not run:
                    continue
                if is_ascii:
                    self._type_ascii_run(run)
                else:
                    if unicode_injector is None:
                        unicode_injector = UnicodeInjector()
                    unicode_injector.inject(run)
        finally:
            if unicode_injector is not None:
                unicode_injector.close()

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        run_ydotool_keys(["KEY_BACKSPACE"] * count, timeout=10)

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        run_ydotool_keys(keys, timeout=10)
