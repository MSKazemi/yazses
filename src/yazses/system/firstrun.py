"""First-run config seeding.

On a fresh install there is no ``config.toml`` and the daemon runs on dataclass
defaults, which keep every optional feature dormant (the "loads with no config =
dormant" contract that the library and tests rely on). That is the right default
for embedding YazSes as a library, but a *user* installing the app should get the
recommended experience — the overlay, voice commands, and the rest of the
"recommended" tier — without having to run ``yazses features enable`` by hand.

``ensure_recommended_config`` bridges the two: the moment a user first starts the
daemon and no config file exists yet, it writes one that enables the
recommended-by-default feature set (derived from the capability registry, the
single source of truth). It never touches an existing config, so a user's own
choices are always respected.
"""
from __future__ import annotations

from pathlib import Path


def default_config_path() -> Path:
    """The config path the daemon loads (mirrors ``config.load_config``'s default)."""
    return Path.home() / ".config" / "yazses" / "config.toml"


def ensure_recommended_config(path: Path | None = None) -> bool:
    """Seed a config enabling the recommended feature set if none exists yet.

    Returns ``True`` when a new config was written (first run), ``False`` when a
    config already existed and was left untouched. Safe to call on every start.
    """
    from yazses.system.configedit import set_config_key
    from yazses.system.features import default_enabled_writes

    p = Path(path) if path is not None else default_config_path()
    if p.exists():
        return False

    p.parent.mkdir(parents=True, exist_ok=True)
    # A header so the generated file reads as intentional, not stray output.
    p.write_text(
        "# YazSes configuration (created on first run).\n"
        "# The recommended feature set is enabled below. Toggle anything with\n"
        "#   yazses features enable <name>   /   yazses features disable <name>\n",
        encoding="utf-8",
    )
    for section, key, value, quote in default_enabled_writes():
        set_config_key(p, section, key, value, quote=quote)
    return True
