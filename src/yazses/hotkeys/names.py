"""The hold-to-talk keys YazSes accepts, in one place.

There were four lists of this: a private ``_KEY_MAP`` in each of the three
platform hotkey backends, plus ``_HOTKEYS`` in ``cli.py`` carrying the comment
"mirror platform/linux/hotkey.py keymap". A hand-copied mirror drifts, and this
one had: every platform binds ``right_option``/``left_option``, and the CLI
refused them — so ``yazses hotkey set right_option`` failed on a key the daemon
would have bound perfectly well, using the name a Mac user would reach for first.

The option aliases exist deliberately. Linux maps them onto the alt key codes so
one config file behaves the same on all three systems; dropping them from the
offered set defeated the point of having them.

This module is names only — no key codes, no imports. The codes stay in the
platform backends, which are the only things that can know them, and this list is
what the *user-facing* surfaces (the CLI and the settings window) offer. A test
pins that every platform can bind everything named here, so the list cannot
promise a key the daemon would reject.
"""

from __future__ import annotations

#: Ordered for display: the modifiers people actually hold, then space.
#: `right_alt` leads because it is the default on Linux and Windows.
SUPPORTED_HOTKEYS: tuple[str, ...] = (
    "right_alt",
    "left_alt",
    "right_option",
    "left_option",
    "right_ctrl",
    "left_ctrl",
    "right_shift",
    "left_shift",
    "right_meta",
    "left_meta",
    "space",
)

#: The default, and a real setting rather than an absence: the daemon resolves it
#: to `platform.default_hotkey` at start, which differs per OS. It is deliberately
#: **not** in `SUPPORTED_HOTKEYS` — no backend has a key code for it, and the test
#: that proves every offered key is bindable would rightly fail on it.
AUTO = "auto"

#: What a user may choose. `SUPPORTED_HOTKEYS` is what a backend can *bind*; this
#: is what may be *written* to `[hotkey] key`. Without the distinction, picking any
#: key was a one-way door — nothing offered `auto`, so there was no way back to the
#: default short of editing TOML by hand.
SETTABLE_HOTKEYS: tuple[str, ...] = (AUTO, *SUPPORTED_HOTKEYS)

#: `right_option` is macOS's name for the key evdev calls `right_alt`; both are
#: accepted and mean the same physical key. Kept here so a UI can say so rather
#: than offering two entries that look like different choices.
ALIASES: dict[str, str] = {
    "right_option": "right_alt",
    "left_option": "left_alt",
}


def canonical(name: str) -> str:
    """The evdev-style name for *name*, resolving the macOS spellings."""
    cleaned = (name or "").strip().lower()
    return ALIASES.get(cleaned, cleaned)
