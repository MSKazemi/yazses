"""`[handsfree_safety] stale_after_ms = 0` was REPORTED as 0 and APPLIED as 500.

The loader refused a negative window (``negative_is_impossible``: the shipped default is >= 0)
but waved a ZERO through, because 0 is a legitimate value for many magnitudes. So::

    [handsfree_safety]
    stale_after_ms = 0

loaded with no problem and ``Config`` said 0, while ``SafetyLimits.window_ms()`` silently
substituted 500. Two numbers for one setting: whatever surface shows the config (settings
window, ``doctor``, a user reading their own file) disagrees with what the watchdog does.

The rule is that the value ``Config`` reports must be the value the guard applies. A window of
zero cannot express a freshness judgement, so the loader now repairs it exactly as it repairs
a negative: say so, and use the shipped default. Declared as dataclass *field metadata*
(``min_exclusive`` / ``max``) rather than a list in ``configcheck`` -- a hand-written set of
"settings where zero is impossible" would be right today and stale after the next feature.
"""
from __future__ import annotations

import dataclasses

import pytest

from yazses.config import Config, HandsfreeSafetyConfig, load_config_checked
from yazses.configcheck import ConfigProblem
from yazses.handsfree.safety import DEFAULT_STALE_AFTER_MS, SafetyLimits, gate_from_config

DEFAULT = int(DEFAULT_STALE_AFTER_MS)


def _load(tmp_path, literal: str):
    path = tmp_path / "config.toml"
    path.write_text(
        f"[handsfree_safety]\nenabled = true\nstale_after_ms = {literal}\n", encoding="utf-8"
    )
    return load_config_checked(path)


def _applied(config: Config) -> float:
    """The window the watchdog really uses, read back from the gate the config builds."""
    gate = gate_from_config(config, ("headpointer",))
    assert gate is not None
    return gate._limits.window_ms()  # noqa: SLF001 - the one number under test


@pytest.mark.parametrize(
    "literal",
    [
        "0",
        "0.0",
        '"0"',
        "-1",
        "-5000",
        "nan",
        "inf",
        "-inf",
        "1e999",
        '"abc"',
        '""',
        "true",
    ],
)
def test_a_hostile_window_is_repaired_to_the_default_and_reported_as_it(tmp_path, literal):
    loaded = _load(tmp_path, literal)

    reported = loaded.config.handsfree_safety.stale_after_ms
    assert reported == DEFAULT, (literal, reported)
    assert reported == _applied(loaded.config), "Config shows one number, the guard uses another"
    assert any(
        isinstance(p, ConfigProblem) and p.key == "stale_after_ms" for p in loaded.problems
    ), "a repaired window must be reported, not silent"


def test_zero_is_named_as_zero_not_as_a_type_error(tmp_path):
    """The user wrote a perfectly well-typed 0; tell them what is wrong with it."""
    loaded = _load(tmp_path, "0")
    message = " ".join(str(p) for p in loaded.problems)
    assert "stale_after_ms" in message and "greater than 0" in message, message
    assert "using the default instead" in message


@pytest.mark.parametrize("literal", ["99999999999999999999999999999999", str(10**400), "60001"])
def test_an_absurdly_large_window_is_repaired_and_cannot_crash_the_gate(tmp_path, literal):
    """`float(10**400)` raises OverflowError inside `gate_from_config` -- at daemon start-up.
    A window that long also means "never stale": the guard is silently off."""
    loaded = _load(tmp_path, literal)

    assert loaded.config.handsfree_safety.stale_after_ms == DEFAULT
    assert _applied(loaded.config) == DEFAULT
    assert any(p.key == "stale_after_ms" for p in loaded.problems)


@pytest.mark.parametrize("literal", ["1", "120", "500", "60000"])
def test_a_sensible_window_passes_through_unchanged_and_unreported(tmp_path, literal):
    loaded = _load(tmp_path, literal)

    assert loaded.config.handsfree_safety.stale_after_ms == int(literal)
    assert _applied(loaded.config) == float(literal)
    assert not [p for p in loaded.problems if p.key == "stale_after_ms"]


def test_the_shipped_default_is_inside_its_own_bounds():
    """A bound the default violates would reject every fresh install."""
    meta = {f.name: f.metadata for f in dataclasses.fields(HandsfreeSafetyConfig)}[
        "stale_after_ms"
    ]
    assert meta["min_exclusive"] < HandsfreeSafetyConfig().stale_after_ms <= meta["max"]


def test_the_loader_and_the_guard_agree_on_what_nonsense_is():
    """`SafetyLimits.window_ms()` repairs the same non-positive values the loader now repairs,
    to the same number -- the two layers cannot drift into two defaults."""
    assert Config().handsfree_safety.stale_after_ms == DEFAULT
    for bad in (0.0, -1.0, float("nan")):
        assert SafetyLimits(stale_after_ms=bad).window_ms() == DEFAULT_STALE_AFTER_MS
