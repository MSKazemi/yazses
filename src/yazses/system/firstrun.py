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

``migrate_legacy_config`` repairs the collateral of the bug fixed in #330: the
config seam used to resolve to the POSIX path on every OS, so first-run seeding
wrote configs there even on Windows and macOS, where the daemon (reading the
platform location all along via the CLI's resolver) never saw them. The moment
the daemon *does* start reading the platform file, such a stranded config would
silently stop applying — so startup carries it over once, before seeding. The
file is moved intact with a rename (comments arrive byte-for-byte), and on
Linux the legacy path *is* the platform path, so the migration is a no-op there
by construction — the configuration that was never broken is never touched.
"""
from __future__ import annotations

from pathlib import Path


def default_config_path() -> Path:
    """The config path the daemon loads.

    Delegates to ``config.default_config_path`` rather than restating it: seeding a
    file the loader does not read is a first run that appears to do nothing.
    """
    from yazses.config import default_config_path as _loader_default

    return _loader_default()


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


def migrate_legacy_config(
    legacy_path: Path | None = None, target_path: Path | None = None
) -> bool:
    """Carry a stranded pre-#330 config to the location the daemon now reads.

    Before #330, ``config.default_config_path()`` returned the POSIX path on
    every OS, so first-run seeding wrote configs there even on Windows and
    macOS. Once the daemon reads the platform file, such a stranded config
    would silently stop applying — so the daemon's startup runs this before
    seeding: if the legacy file exists and the platform file does not, the
    legacy file is moved intact and the caller reports True.

    The move is a rename (comments arrive byte-for-byte), with a copy fallback
    for a legacy home on a different volume than the platform dir. Deliberate
    no-ops, each pinned by a test: on Linux the legacy path *is* the platform
    path (the resolver agrees with the old literal), so nothing there was ever
    stranded and nothing is touched; when both files exist the platform config
    already wins and the legacy copy is left exactly where it is rather than
    merged or deleted; and no legacy file means nothing to do. Errors raise
    into the daemon's swallow-and-log startup guard, same as seeding: config
    housekeeping must never block startup.
    """
    from yazses.config import default_config_path, legacy_default_config_path

    legacy = (
        Path(legacy_path) if legacy_path is not None else legacy_default_config_path()
    )
    target = (
        Path(target_path) if target_path is not None else default_config_path()
    )
    if legacy == target or not legacy.is_file():
        return False
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        legacy.rename(target)
    except OSError:
        import shutil

        shutil.copy2(legacy, target)
        legacy.unlink()
    return True
