"""Feature-wiring honesty guard: the registry must never advertise a dead toggle.

`yazses features enable <slug>` writes a config key. That is only honest when some
runtime path — the daemon pipeline, a CLI command, or the tray/overlay/agent entry
points — actually reads that feature's code. This test computes the transitive
import closure of ``yazses.*`` top-level subpackages reachable from the real entry
points (static AST analysis, covers lazy in-function imports) and asserts that
``features._UNWIRED`` — the set of slugs `features enable` refuses as
"designed but not yet wired" — EXACTLY matches the computed unreachable set:

* Wire a feature (import its package from the daemon/CLI) without removing it
  from ``_UNWIRED`` → this test fails (stale flag).
* Add a stub registry entry whose package nothing imports, without flagging it
  → this test fails (a lying toggle).

Slugs whose implementation lives in a shared package under a different name are
mapped in ``features._SLUG_PACKAGES`` (e.g. ``undo`` → ``commands``, where
``commands/revise.py`` lives).
"""
from __future__ import annotations

import ast
from pathlib import Path

import yazses
from yazses.system.features import (
    _SLUG_PACKAGES,
    _UNWIRED,
    _registry,
    default_enabled_slugs,
    feature_packages,
    feature_status,
)
from yazses.config import Config

SRC = Path(yazses.__file__).parent

# The runtime entry points (pyproject console scripts + the daemon orchestrator).
# If one of these moves, update it here — the assert below catches a rename.
ENTRY_MODULES = (
    "yazses.core.daemon",   # yazses-daemon orchestrator
    "yazses.cli",           # yazses <command>
    "yazses.main",          # yazses-daemon entry
    "yazses.__main__",      # python -m yazses
    "yazses.tray.app",      # yazses-tray
    "yazses.overlay.app",   # yazses-overlay
    "yazses.remote.agent",  # yazses-agent
)


def _module_name(path: Path) -> str:
    rel = path.relative_to(SRC.parent)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _all_modules() -> dict[str, Path]:
    return {
        _module_name(p): p
        for p in SRC.rglob("*.py")
        if "__pycache__" not in p.parts
    }


def _internal_imports(path: Path, mod: str) -> set[str]:
    """Every ``yazses.*`` dotted name imported by *path* (absolute + relative,
    module-level and inside functions)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pkg_parts = mod.split(".")
    if path.name != "__init__.py":
        pkg_parts = pkg_parts[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "yazses" or alias.name.startswith("yazses."):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                stem = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                base = ".".join(stem)
                if node.module:
                    base = f"{base}.{node.module}"
            if base == "yazses" or base.startswith("yazses."):
                found.add(base)
                for alias in node.names:
                    found.add(f"{base}.{alias.name}")
    return found


def reachable_packages() -> tuple[set[str], set[str]]:
    """(reachable, all) top-level ``yazses.*`` subpackage/module names, computed
    as the transitive import closure from :data:`ENTRY_MODULES`."""
    files = _all_modules()
    for entry in ENTRY_MODULES:
        assert entry in files, f"entry module {entry!r} not found — update ENTRY_MODULES"

    def resolve(name: str) -> str | None:
        while name:
            if name in files:
                return name
            if "." not in name:
                return None
            name = name.rsplit(".", 1)[0]
        return None

    seen: set[str] = set()
    stack = list(ENTRY_MODULES)
    while stack:
        mod = stack.pop()
        if mod in seen:
            continue
        seen.add(mod)
        parts = mod.split(".")
        # Importing a submodule executes every parent package __init__.
        for i in range(1, len(parts)):
            parent = ".".join(parts[:i])
            if parent in files and parent not in seen:
                stack.append(parent)
        for imp in _internal_imports(files[mod], mod):
            hit = resolve(imp)
            if hit is not None and hit not in seen:
                stack.append(hit)

    def tops(mods) -> set[str]:
        return {m.split(".")[1] for m in mods if "." in m}

    return tops(seen), tops(files)


def test_unwired_set_exactly_matches_reachability() -> None:
    reachable, _all_tops = reachable_packages()
    computed_unwired = {
        d.slug
        for d in _registry()
        if not any(pkg in reachable for pkg in feature_packages(d.slug))
    }

    stale = sorted(_UNWIRED - computed_unwired)
    assert not stale, (
        "These slugs are flagged _UNWIRED in features.py but their package IS now "
        f"reachable from an entry point — remove them from _UNWIRED: {stale}"
    )
    lying = sorted(computed_unwired - _UNWIRED)
    assert not lying, (
        "These registry slugs have NO runtime consumer (their package is "
        "unreachable from every entry point) but are not flagged — add them to "
        f"_UNWIRED in features.py so `features enable` stops lying: {lying}"
    )


def test_wired_slugs_map_to_existing_packages() -> None:
    """A typo in _SLUG_PACKAGES for a wired feature would silently mark it
    unreachable; require every wired slug's packages to exist on disk.
    (Unwired slugs MAY name a planned package that doesn't exist yet.)"""
    _reachable, all_tops = reachable_packages()
    for d in _registry():
        if d.slug in _UNWIRED:
            continue
        pkgs = feature_packages(d.slug)
        assert pkgs, f"{d.slug!r} maps to no package"
        missing = [p for p in pkgs if p not in all_tops]
        assert not missing, (
            f"wired feature {d.slug!r} maps to nonexistent package(s) {missing} "
            "— fix _SLUG_PACKAGES in features.py"
        )


def test_unwired_slugs_are_registry_slugs() -> None:
    slugs = {d.slug for d in _registry()}
    unknown = sorted(_UNWIRED - slugs)
    assert not unknown, f"_UNWIRED names unknown slugs: {unknown}"


def test_feature_status_carries_wired_flag() -> None:
    feats = {f.slug: f for f in feature_status(Config())}
    for slug in _UNWIRED:
        assert feats[slug].wired is False
        assert "not yet wired" in feats[slug].tier_label
    # spot-check genuinely wired ones keep their advice tier
    for slug in ("dictation", "commands", "meeting", "verbatim", "compute"):
        assert feats[slug].wired is True
        assert "not yet wired" not in feats[slug].tier_label


def test_default_seed_never_enables_unwired_features() -> None:
    overlap = sorted(set(default_enabled_slugs()) & _UNWIRED)
    assert not overlap, (
        f"first-run seeding would enable unwired features {overlap} — a fresh "
        "install would show them ON while the daemon ignores them"
    )


# --------------------------------------------------------------------------- #
# CLI behavior: enable refuses, disable cleans up, list marks them.
# --------------------------------------------------------------------------- #
def _fake_platform(tmp_path: Path):
    from types import SimpleNamespace

    return SimpleNamespace(
        paths=SimpleNamespace(config_file=tmp_path / "config.toml", data_dir=tmp_path)
    )


def _combined_output(result) -> str:
    try:
        return result.output + result.stderr
    except ValueError:  # older click mixes stderr into output
        return result.output


def test_cli_enable_refuses_unwired(monkeypatch, tmp_path) -> None:
    from typer.testing import CliRunner

    import yazses.cli as cli

    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = CliRunner().invoke(cli.app, ["features", "enable", "wakeword"])
    assert result.exit_code == 1
    out = _combined_output(result)
    assert "not yet wired" in out
    assert "design/adr/" in out
    # Nothing was written: the refusal happens before any config edit.
    assert not (tmp_path / "config.toml").exists()


def test_cli_disable_unwired_cleans_stale_config(monkeypatch, tmp_path) -> None:
    from typer.testing import CliRunner

    import yazses.cli as cli

    cfg = tmp_path / "config.toml"
    cfg.write_text("[wakeword]\nenabled = true\n")
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = CliRunner().invoke(cli.app, ["features", "disable", "wakeword"])
    assert result.exit_code == 0, _combined_output(result)
    assert "never wired" in _combined_output(result)
    assert "enabled = false" in cfg.read_text()


def test_cli_list_marks_unwired_as_planned(monkeypatch, tmp_path) -> None:
    from typer.testing import CliRunner

    import yazses.cli as cli

    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = CliRunner().invoke(cli.app, ["features"])
    assert result.exit_code == 0
    assert "not yet wired" in result.output
