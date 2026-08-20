"""Turning a capability off must undo turning it on.

`yazses features enable <slug>` and `disable <slug>` write `(section, key, value)` tuples
from the registry, and nothing checked that the second list reverses the first. On
2026-08-20 one of the 147 features did not: `read-back` enabled **two** keys and disabled
**one**.

    enable read-back  -> [tts] enabled = true, [accessibility] read_back = "final"
    disable read-back -> [accessibility] read_back = "off"          <- [tts] stays true

`yazses features` reported the capability as off, because its status reads
`c.tts.enabled and c.accessibility.read_back != "off"` and the second half had flipped.
Meanwhile `build_tts` branches on `[tts] enabled` alone and kept returning a live backend
-- so the daemon went on constructing a TTS engine for a feature the user had switched
off, and on a machine with the `tts` extra that means loading Kokoro and, per
`tts/download.py`, fetching **~340 MB** the first time. The probe that found this printed
the evidence itself: *"TTS engine 'kokoro' unavailable ... Read-back will be silent"*,
emitted after the disable.

Two properties, because they fail differently. The key-set check localises the bug to one
registry row; the behavioural round-trip is what a user would actually notice, and it
would also catch a disable that writes the right key with a wrong value.
"""

from __future__ import annotations

import dataclasses
import pathlib
import tempfile

import pytest

from yazses.config import load_config
from yazses.system import features
from yazses.system.configedit import set_config_key

REGISTRY = features._registry()
TOGGLEABLE = [d for d in REGISTRY if d.on_writes and d.off_writes]


def _keys(writes) -> set[tuple[str, str]]:
    return {(section, key) for section, key, *_ in writes}


def _apply(path: pathlib.Path, writes) -> None:
    for section, key, value, quote in writes:
        set_config_key(path, section, key, value, quote=quote)


def _config_after(*write_lists) -> dict:
    """The loaded config as a plain dict, after applying each write list in order."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="yazses-toggle-"))
    path = tmp / "config.toml"
    path.write_text("", encoding="utf-8")
    for writes in write_lists:
        _apply(path, writes)
    return dataclasses.asdict(load_config(path))


def test_there_are_features_to_check():
    """A guard that iterates is green on an empty collection."""
    assert len(TOGGLEABLE) > 100, f"only {len(TOGGLEABLE)} toggleable features found"
    assert any(d.slug == "read-back" for d in TOGGLEABLE)


@pytest.mark.parametrize("feature", TOGGLEABLE, ids=lambda d: d.slug)
def test_disable_touches_every_key_enable_touches(feature):
    """Any key enable writes and disable does not is residue the user cannot see.

    Deliberately strict, with no exception list. A capability that must leave a shared
    prerequisite switched on is a real possibility, but there is no such case today, and
    an exception mechanism written before it is needed is one nobody has to justify.
    """
    on, off = _keys(feature.on_writes), _keys(feature.off_writes)
    assert on == off, (
        f"`features enable {feature.slug}` writes "
        f"{sorted('.'.join(k) for k in on - off)} which `disable` never clears"
        if on - off
        else f"`features disable {feature.slug}` writes "
             f"{sorted('.'.join(k) for k in off - on)} which `enable` never set"
    )


@pytest.mark.parametrize("feature", TOGGLEABLE, ids=lambda d: d.slug)
def test_enabling_then_disabling_leaves_no_trace(feature):
    """The end state must not depend on the capability ever having been on.

    Compared against `disable` alone rather than against the shipped defaults, so a
    feature whose off-value is not its dataclass default is still checked honestly.
    """
    assert _config_after(feature.on_writes, feature.off_writes) == _config_after(
        feature.off_writes
    ), f"disabling {feature.slug} did not undo enabling it"


@pytest.mark.parametrize("feature", TOGGLEABLE, ids=lambda d: d.slug)
def test_the_writes_actually_move_the_switch(feature):
    """The round-trip above proves the two lists agree; this proves they *mean* it.

    `enable -> disable == disable` is an idempotence property, and a `disable` that
    wrote `true` would satisfy it trivially -- both sides would write `true` and compare
    equal. A mutation that inverted every `_bool` off-value sailed through for exactly
    that reason. The registry's own `status` predicate is what `yazses features` prints,
    so hold the writes to it.
    """
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="yazses-switch-"))
    path = tmp / "config.toml"
    path.write_text("", encoding="utf-8")

    _apply(path, feature.on_writes)
    assert feature.status(load_config(path)) is True, (
        f"`features enable {feature.slug}` does not make it report as on"
    )
    _apply(path, feature.off_writes)
    assert feature.status(load_config(path)) is False, (
        f"`features disable {feature.slug}` does not make it report as off"
    )


def test_the_read_back_regression_specifically():
    """The case that motivated the file, pinned end to end through the real builder."""
    from yazses.tts.factory import build_tts

    feature = next(d for d in TOGGLEABLE if d.slug == "read-back")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="yazses-readback-"))
    path = tmp / "config.toml"
    path.write_text("", encoding="utf-8")

    _apply(path, feature.on_writes)
    assert load_config(path).tts.enabled is True, "enable should switch TTS on"

    _apply(path, feature.off_writes)
    config = load_config(path)
    assert config.tts.enabled is False, "[tts] enabled survived `features disable`"
    assert build_tts(config.tts) is None, (
        "the daemon still builds a TTS backend for a disabled capability -- with the "
        "`tts` extra installed that loads Kokoro and can fetch ~340 MB"
    )
    assert features.find_feature(config, "read-back").on is False
