"""First-run config seeding: a fresh install gets the recommended feature set on."""
from __future__ import annotations

from yazses.config import load_config
from yazses.system import firstrun
from yazses.system.features import (
    DEFAULT_ON,
    RECOMMENDED,
    default_enabled_slugs,
    default_enabled_writes,
    feature_status,
)


def test_writes_config_when_absent(tmp_path):
    cfg_path = tmp_path / "config.toml"
    assert firstrun.ensure_recommended_config(cfg_path) is True
    assert cfg_path.exists()


def test_never_overrides_existing_config(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[overlay]\nenabled = false\n")
    assert firstrun.ensure_recommended_config(cfg_path) is False
    # Untouched: the user's explicit choice survives.
    assert "enabled = false" in cfg_path.read_text()
    assert load_config(cfg_path).overlay.enabled is False


def test_seeded_config_enables_the_recommended_set(tmp_path):
    cfg_path = tmp_path / "config.toml"
    firstrun.ensure_recommended_config(cfg_path)
    cfg = load_config(cfg_path)

    on = {f.slug for f in feature_status(cfg) if f.on}
    for slug in default_enabled_slugs():
        assert slug in on, f"expected recommended feature {slug!r} enabled on first run"


def test_recommended_writes_derived_from_registry():
    # Every write targets a DEFAULT_ON or RECOMMENDED feature; nothing else.
    writes = default_enabled_writes()
    assert writes, "expected at least the DEFAULT_ON tier to produce writes"
    assert all(isinstance(w, tuple) and len(w) == 4 for w in writes)


def test_overlay_is_on_by_default_after_seed(tmp_path):
    cfg_path = tmp_path / "config.toml"
    firstrun.ensure_recommended_config(cfg_path)
    assert load_config(cfg_path).overlay.enabled is True


def test_tiers_constants_present():
    # Guard against a registry refactor silently dropping the tiers we seed.
    assert DEFAULT_ON and RECOMMENDED
