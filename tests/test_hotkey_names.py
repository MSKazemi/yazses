"""The keys a user is offered must be keys the daemon can actually bind.

Four copies of this list existed: a private `_KEY_MAP` in each platform hotkey
backend, and `_HOTKEYS` in `cli.py` under the comment "mirror
platform/linux/hotkey.py keymap". It had already drifted — every platform binds
`right_option` and `left_option`, and the CLI refused both:

    $ yazses hotkey set right_option
    Unknown key 'right_option'. Choose one of: right_alt, left_alt, ...

Which is the worse direction of the two possible failures. Offering a key nothing
can bind leaves the user unable to dictate; refusing a key that works just makes
the tool look wrong — but it refused the *macOS* spelling, which the Linux backend
carries on purpose so one config file works everywhere.

The platform maps are read as text rather than imported: `platform/macos/hotkey.py`
and `platform/windows/hotkey.py` import libraries that do not exist on a Linux CI
runner, and this must hold for every platform regardless of where it runs.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from yazses.hotkeys.names import ALIASES, SUPPORTED_HOTKEYS, canonical

ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = ("linux", "macos", "windows")


def _key_map_names(platform: str) -> set[str]:
    """The names in one backend's `_KEY_MAP`, parsed from the source."""
    text = (ROOT / "src" / "yazses" / "platform" / platform / "hotkey.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r"_KEY_MAP[^=]*=\s*\{(.*?)\n\}", text, re.S)
    assert match, f"{platform}/hotkey.py no longer declares a _KEY_MAP"
    return set(re.findall(r'"([a-z_]+)":', match.group(1)))


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_platform_can_bind_every_offered_key(platform: str) -> None:
    """The offered list must never promise what a backend cannot deliver."""
    missing = set(SUPPORTED_HOTKEYS) - _key_map_names(platform)
    assert not missing, (
        f"{platform} cannot bind {sorted(missing)}, but they are offered to users. "
        f"Either add them to that backend's _KEY_MAP or drop them from SUPPORTED_HOTKEYS"
    )


def test_the_cli_offers_exactly_the_shared_list() -> None:
    """`yazses hotkey set` and the settings window must not disagree."""
    from yazses.cli import _HOTKEYS

    assert set(_HOTKEYS) == set(SUPPORTED_HOTKEYS)


def test_the_macos_spellings_resolve_to_the_keys_they_alias() -> None:
    assert canonical("right_option") == "right_alt"
    assert canonical("LEFT_OPTION") == "left_alt"
    assert canonical(" space ") == "space"


def test_a_plain_key_is_returned_unchanged() -> None:
    assert canonical("right_ctrl") == "right_ctrl"


def test_every_alias_points_at_something_offered() -> None:
    """An alias resolving to a key nobody offers would be a dead entry."""
    for name, target in ALIASES.items():
        assert name in SUPPORTED_HOTKEYS, f"{name} is aliased but never offered"
        assert target in SUPPORTED_HOTKEYS, f"{name} aliases {target}, which is not offered"
