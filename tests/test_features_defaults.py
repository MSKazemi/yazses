"""What "restore defaults" means, at the registry — the one definition.

Both the settings window's Restore-defaults button and `yazses features reset`
read `default_state()`, so a drift here is a drift in both. These tests pin the
properties that make a reset safe to press: it never enables something the
project does not advise, it agrees with what a fresh install is actually seeded
with, and it never claims to reset a switch that does nothing.
"""

import pytest

from yazses.config import Config
from yazses.system.features import (
    EXPERIMENTAL,
    default_drift,
    default_enabled_slugs,
    default_state,
    feature_status,
    find_feature,
    unwired_slugs,
)


def test_defaults_cover_exactly_the_toggleable_wired_capabilities():
    defaults = default_state()
    expected = {
        f.slug for f in feature_status(Config())
        if f.toggleable and f.wired
    }
    assert set(defaults) == expected


def test_the_default_on_set_is_the_same_set_a_fresh_install_is_seeded_with():
    """`firstrun` seeds `default_enabled_slugs()`; a reset must target the same set."""
    assert {slug for slug, on in default_state().items() if on} == set(default_enabled_slugs())


def test_no_experimental_capability_is_ever_on_by_default():
    """So a reset can only ever switch an experimental feature OFF."""
    cfg = Config()
    for slug, on in default_state().items():
        if on:
            feat = find_feature(cfg, slug)
            assert feat is not None and feat.tier != EXPERIMENTAL, slug


def test_unwired_capabilities_are_excluded():
    """Resetting one would write a config key no runtime path reads."""
    assert not set(default_state()) & set(unwired_slugs())


def test_drift_lists_every_off_default_row_and_nothing_else():
    cfg = Config()
    drifting = {f.slug for f, _ in default_drift(cfg)}
    defaults = default_state()
    for feat in feature_status(cfg):
        if feat.slug in defaults and feat.slug not in drifting:
            assert feat.on == defaults[feat.slug], feat.slug


def test_drift_reports_the_direction_each_row_must_move():
    cfg = Config()
    for feat, desired in default_drift(cfg):
        assert desired is default_state()[feat.slug]
        assert bool(feat.on) is not desired


def test_a_bare_config_drifts_only_by_the_recommended_tier():
    """The dataclass defaults are not the shipped state — first-run seeds the rest.

    If this ever comes back empty, `firstrun` has stopped having anything to do
    and the two notions of "default" have silently merged.
    """
    drift = default_drift(Config())
    assert drift, "a bare config should still be missing the recommended tier"
    assert all(desired for _feat, desired in drift), (
        "nothing in a bare config should need turning OFF to reach the defaults"
    )


@pytest.mark.parametrize("slug", ["commands", "tray", "target-guard"])
def test_shipped_on_capabilities_default_to_on(slug):
    assert default_state()[slug] is True


@pytest.mark.parametrize("slug", ["streaming", "learning", "cocktail", "gaze"])
def test_opt_in_capabilities_default_to_off(slug):
    assert default_state()[slug] is False
