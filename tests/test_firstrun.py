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
    cfg_path.write_text("[overlay]\nenabled = false\n", encoding="utf-8")
    assert firstrun.ensure_recommended_config(cfg_path) is False
    # Untouched: the user's explicit choice survives.
    assert "enabled = false" in cfg_path.read_text(encoding="utf-8")
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


def test_overlay_stays_off_after_seed(tmp_path):
    cfg_path = tmp_path / "config.toml"
    firstrun.ensure_recommended_config(cfg_path)
    assert load_config(cfg_path).overlay.enabled is False


# ── #330: the stranded pre-fix config is carried over, not ignored ────────────


def test_stranded_legacy_config_is_moved_to_the_platform_path(tmp_path):
    """A Windows/macOS user's seeded config must not silently stop applying.

    The old seam wrote the POSIX literal on every OS; the fix reads the
    platform file. Migration runs first, so the user's choices arrive intact.
    """
    legacy = tmp_path / "legacy" / "config.toml"
    legacy.parent.mkdir()
    legacy.write_text(
        "# my hand-written notes\n[hotkey]\nkey = \"left_ctrl\"\n", encoding="utf-8"
    )
    target = tmp_path / "platform" / "config.toml"

    assert firstrun.migrate_legacy_config(legacy, target) is True
    assert not legacy.exists()
    # A rename: comments and formatting arrive byte-for-byte, not reparsed.
    assert target.read_text(encoding="utf-8") == (
        "# my hand-written notes\n[hotkey]\nkey = \"left_ctrl\"\n"
    )
    assert load_config(target).hotkey.key == "left_ctrl"


def test_migrate_is_a_noop_when_paths_coincide(tmp_path):
    """Linux: the legacy path *is* the platform path; nothing is stranded.

    The migration must not so much as rewrite its own config — the file that
    was never broken must never be touched.
    """
    cfg = tmp_path / "config.toml"
    cfg.write_text("[hotkey]\nkey = \"left_ctrl\"\n", encoding="utf-8")

    assert firstrun.migrate_legacy_config(cfg, cfg) is False
    assert cfg.read_text(encoding="utf-8") == "[hotkey]\nkey = \"left_ctrl\"\n"


def test_platform_config_wins_when_both_exist(tmp_path, caplog):
    """Both files present: the platform file already wins; no merge, no delete.

    Guessing between two configs risks destroying one; leaving the legacy copy
    in place keeps the decision reversible and the user's data readable.
    """
    legacy = tmp_path / "legacy.toml"
    legacy.write_text("[hotkey]\nkey = \"left_ctrl\"\n", encoding="utf-8")
    target = tmp_path / "target.toml"
    target.write_text("[hotkey]\nkey = \"right_ctrl\"\n", encoding="utf-8")

    with caplog.at_level("WARNING", logger="yazses.system.firstrun"):
        assert firstrun.migrate_legacy_config(legacy, target) is False
    assert legacy.exists()
    assert load_config(target).hotkey.key == "right_ctrl"
    # Settings that lived only in the legacy file stop applying: that must be said.
    assert str(legacy) in caplog.text and str(target) in caplog.text


def test_coinciding_paths_stay_silent(tmp_path, caplog):
    """Linux: the legacy path is the platform path, so there is nothing to warn about."""
    same = tmp_path / "config.toml"
    same.write_text("[hotkey]\nkey = \"left_ctrl\"\n", encoding="utf-8")

    with caplog.at_level("WARNING", logger="yazses.system.firstrun"):
        assert firstrun.migrate_legacy_config(same, same) is False
    assert caplog.text == ""


def test_no_legacy_file_means_nothing_to_do(tmp_path):
    assert (
        firstrun.migrate_legacy_config(tmp_path / "absent.toml", tmp_path / "new.toml")
        is False
    )
    assert not (tmp_path / "new.toml").exists()


def test_migration_runs_before_seeding_on_startup():
    """Ordering: migrate first, seed second.

    Reversed, a stranded user's platform dir would get seeded with defaults and
    the stranded file would then hit the `target exists` no-op — their choices
    silently replaced by the recommended set, the exact harm the migration
    exists to prevent. Checked structurally on `daemon.run`'s source: driving
    the real entry point would start a daemon.
    """
    import ast
    import inspect

    from yazses.core import daemon

    tree = ast.parse(inspect.getsource(daemon.run))
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "migrate_legacy_config" in calls and "ensure_recommended_config" in calls
    assert calls.index("migrate_legacy_config") < calls.index(
        "ensure_recommended_config"
    )


def test_tiers_constants_present():
    # Guard against a registry refactor silently dropping the tiers we seed.
    assert DEFAULT_ON and RECOMMENDED
