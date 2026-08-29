"""Code that nothing imports, hiding inside features the registry calls wired.

`test_feature_wiring_honesty.py` is the existing guard and it works — but it
measures reachability at **top-level package** granularity (`tops()`, which does
`m.split(".")[1]`). One live import of one module therefore marks the whole
package wired, and everything else in it can be dead without the registry
noticing.

`windowctl` is the clearest case. `system/doctor.py` imports `windowctl.focus` for
a Wayland-limitation string, so the package is reachable and the feature reports
`wired=True` — while `windowctl/commands.py`, the entire spoken window grammar, is
imported by nothing. `yazses features enable windowctl` succeeds and "move window
left half" does nothing at all. A toggle that lies is worse than a missing one.

This module closes that gap at *module* granularity. It is deliberately a **ledger,
not a gate**: the nine known orphans are listed below with why each is dead, so
the suite passes today and fails the moment a tenth appears — or when one is
finally wired and its entry goes stale. Silently tolerating a growing pile is the
thing being prevented; demanding nine fixes in one commit would just get the test
deleted.

Feature packages already declared in `_UNWIRED` are excluded — they are honestly
registered as not-yet-wired and the existing test owns them.
"""
from __future__ import annotations

import ast
from pathlib import Path

import yazses
from yazses.system.features import _UNWIRED, feature_packages

SRC = Path(yazses.__file__).parent
_PREFIX = len("yazses.")

#: Modules that are entry points by definition — something outside the package
#: runs them, so no in-tree importer is expected.
ENTRY_MODULES = {
    "__main__", "main", "cli", "core.daemon",
    "tray.app", "overlay.app", "remote.agent",
}

#: The known orphans, each with what is missing. An entry here is a debt that has
#: been *looked at and written down*, not one that is hidden.
KNOWN_ORPHANS = {
    "commands.slm_router":
        "Tier-2 SLM intent fallback. commands/grammar.py takes an `slm_router` "
        "parameter and nothing ever constructs one — a plumbed seam never filled.",
    "commands.profiles":
        "Per-editor grammar config. commands/dispatch.py has a comment pointing at "
        "this module and still never imports it; load_profiles would return an "
        "empty registry anyway.",
    "activation.pipeline":
        "Its own docstring says the daemon wires the real classify/dispatch/confirm "
        "into it. The daemon does not.",
    "gaze.implicit":
        "gaze is wired through targeter/route/zones; this module is not on that path.",
    "personalize.adapter_gate":
        "personalize is wired through prompt_builder; the P2 LoRA gate is not.",
    "platform.emg.ble_backend":
        "The BLE transport for the EMG armband. _build_activation_sources constructs "
        "the serial backend only.",
    "platform.emg.brainflow_source":
        "A second EMG source, tested but never constructed by the factory.",
}


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SRC).with_suffix("").parts)


def _imported_names() -> set[str]:
    """Every `yazses.*` module named by an import anywhere in the package.

    Counts in-function imports, which this codebase uses heavily to keep startup
    cheap — a scan that only read module-level imports would call most of the tree
    dead.
    """
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        here = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("yazses."):
                        found.add(alias.name[_PREFIX:])
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative
                    base = (
                        here.rsplit(".", node.level)[0]
                        if node.level <= here.count(".") + 1 else ""
                    )
                    module = f"{base}.{node.module}" if node.module and base else (node.module or base)
                else:
                    module = node.module or ""
                    if not module.startswith("yazses"):
                        continue
                    module = module[_PREFIX:] if module != "yazses" else ""
                if module:
                    found.add(module)
                # `from yazses.pkg import mod` names the module in the alias.
                for alias in node.names:
                    found.add(f"{module}.{alias.name}" if module else alias.name)
    return found


def orphan_modules() -> set[str]:
    """Modules with no importer, excluding entry points and declared-unwired features."""
    unwired_packages = {pkg for slug in _UNWIRED for pkg in feature_packages(slug)}
    imported = _imported_names()
    return {
        name
        for path in SRC.rglob("*.py")
        if (name := _module_name(path))
        and not name.endswith("__init__")
        and name not in imported
        and name not in ENTRY_MODULES
        and name.split(".")[0] not in unwired_packages
    }


def test_the_scan_finds_the_package_at_all() -> None:
    """Guard the guard: a broken path or a bad prefix length would report zero
    orphans and pass. (The first draft of this scan sliced 8 characters off
    'yazses.' instead of 7 and called 267 live modules dead.)"""
    assert len(list(SRC.rglob("*.py"))) > 100
    assert "system.doctor" in _imported_names(), "a plainly-imported module reads as dead"


def test_no_new_orphan_module_appears() -> None:
    """Something written, tested, and connected to nothing is this project's most
    frequent defect. The ledger stops the pile growing quietly."""
    new = orphan_modules() - set(KNOWN_ORPHANS)
    assert not new, (
        "these modules are imported by nothing in src/ — they cannot run:\n  "
        + "\n  ".join(sorted(new))
        + "\n\nWire it (usually a call site in core/daemon.py or cli.py), or add it "
        "to KNOWN_ORPHANS with what is missing."
    )


def test_the_ledger_has_no_stale_entries() -> None:
    """A fixed orphan must leave the list, or the list stops meaning anything."""
    fixed = set(KNOWN_ORPHANS) - orphan_modules()
    assert not fixed, (
        "these are listed as orphans but now have importers — delete their entries:\n  "
        + "\n  ".join(sorted(fixed))
    )


def test_every_ledger_entry_says_what_is_missing() -> None:
    """An entry without a reason is a silenced test, not a recorded debt."""
    thin = {name for name, why in KNOWN_ORPHANS.items() if len(why) < 60}
    assert not thin, f"these entries need a real explanation: {sorted(thin)}"


def test_the_ledger_does_not_grow_unnoticed() -> None:
    """A ceiling on the debt itself. Raising it is a deliberate edit with a diff,
    which is the point — it makes 'we added another orphan' visible in review."""
    assert len(KNOWN_ORPHANS) <= 8, (
        f"{len(KNOWN_ORPHANS)} known orphans. Wire one before adding another."
    )
