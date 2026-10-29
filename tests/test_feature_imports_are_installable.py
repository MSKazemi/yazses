"""A feature's own package imports nothing optional that enabling it would not install.

`yazses features enable <slug>` installs `_FEATURE_DEPS[slug]` and the dormancy probe
checks its `check_modules`. Both are hand-written next to the registry, and the code
that actually needs the library is somewhere else. The guards so far compare
`_FEATURE_DEPS` with `pyproject.toml`; none compares it with the *code*. So a new
feature whose package lazily imports an extra's module — `mcp`, `speechbrain`,
`sherpa_onnx` — with no `_FEATURE_DEPS` entry (or one naming the wrong module) ships a
toggle that installs nothing, and a dormancy probe that reports it healthy.

This reads the feature's implementation package (`features.feature_packages(slug)`),
collects every import of an extra's module at any scope, and requires each to be in
that feature's `check_modules` — or listed in `BACKEND_CHOICES`, for a module that is
a *selectable alternative* inside the feature rather than what the feature needs.

Scope, stated rather than implied: only packages owned by exactly one slug are
attributed. A shared package (`postprocess`, `stt`, `commands`) hosts many features
and cannot say which one an import belongs to; those features are covered by
`test_feature_deps_cover_every_probe.py` instead. A new feature gets its own package
by default, which is the case this exists for.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from yazses.system.features import _registry, feature_packages, unwired_slugs

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "yazses"

#: (slug, extra module) -> why the feature does not install it on enable.
BACKEND_CHOICES: dict[tuple[str, str], str] = {
    ("recimport", "pyannote.audio"): "`[recimport] backend = \"pyannote\"`, an alternative "
        "diarizer; its probe names the `diarization-pyannote` extra",
    ("meeting", "llama_cpp"): "the minutes writer runs only when `[meeting] notes_model` "
        "names a local GGUF; it needs the `notes` extra, not Meeting Mode itself",
    ("meeting", "silero_vad"): "`[meeting] vad_backend = \"silero\"`, an alternative VAD "
        "inside Meeting Mode (the `silero` extra)",
    ("cocktail", "resemblyzer"): "`[voiceprint] backend = \"resemblyzer\"`, an alternative "
        "speaker embedder (the `voiceprint-resemblyzer` extra)",
    ("biosignal", "brainflow"): "only a `[biosignal] source = \"brainflow:<id>\"` board needs it; "
        "the synthetic and replay sources need nothing (the `emg-band` extra)",
}


def _optional_modules() -> set[str]:
    spec = importlib.util.spec_from_file_location(
        "check_dependency_budget", ROOT / "scripts" / "check_dependency_budget.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return set(mod.OPTIONAL_IMPORT_MODULES)


OPTIONAL = _optional_modules()


def _owned(name: str) -> str | None:
    return next((m for m in sorted(OPTIONAL) if name == m or name.startswith(m + ".")), None)


def _package_files(package: str) -> list[Path]:
    base = SRC / package
    if base.is_dir():
        return sorted(base.rglob("*.py"))
    single = base.with_suffix(".py")
    return [single] if single.exists() else []


def _optional_imports(package: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in _package_files(package):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module]
            else:
                continue
            for name in names:
                module = _owned(name)
                if module:
                    found.setdefault(module, set()).add(path.relative_to(SRC.parent).as_posix())
    return found


def _attributed() -> dict[str, tuple[tuple[str, ...], dict[str, set[str]]]]:
    """slug -> (check_modules, extra module -> files) for every wired, owned package."""
    defs = _registry()
    owners: dict[str, set[str]] = {}
    for d in defs:
        for package in feature_packages(d.slug):
            owners.setdefault(package, set()).add(d.slug)
    unwired = unwired_slugs()
    out = {}
    for d in defs:
        if d.slug in unwired:
            continue
        found: dict[str, set[str]] = {}
        for package in feature_packages(d.slug):
            if owners[package] != {d.slug}:
                continue
            for module, files in _optional_imports(package).items():
                found.setdefault(module, set()).update(files)
        out[d.slug] = (tuple(d.check_modules), found)
    return out


ATTRIBUTED = _attributed()


def test_the_scan_attributes_known_imports():
    """`gaze` imports mediapipe and cv2 from its own package; a blind scan finds nothing."""
    _mods, found = ATTRIBUTED["gaze"]
    assert {"mediapipe", "cv2"} <= set(found)
    assert any(found for _m, found in ATTRIBUTED.values())


@pytest.mark.parametrize("slug", sorted(ATTRIBUTED))
def test_a_feature_installs_what_its_own_package_imports(slug):
    check_modules, found = ATTRIBUTED[slug]
    missing = {
        module: sorted(files) for module, files in found.items()
        if module not in check_modules and (slug, module) not in BACKEND_CHOICES
    }
    assert not missing, (
        f"`{slug}`'s own package imports {missing}, but its `_FEATURE_DEPS` entry in "
        "system/features.py does not name the module, so `yazses features enable "
        f"{slug}` installs nothing for it and the dormancy probe never notices. Add "
        "the module and its extra's packages to that entry — or, if it is a "
        "selectable alternative backend, to BACKEND_CHOICES here with the reason."
    )


@pytest.mark.parametrize("slug, module", sorted(BACKEND_CHOICES))
def test_every_backend_choice_is_still_imported_and_still_uninstalled(slug, module):
    assert slug in ATTRIBUTED, f"{slug} is no longer a wired, owned feature package"
    check_modules, found = ATTRIBUTED[slug]
    assert module in found, f"{slug} no longer imports {module}; drop the exemption"
    assert module not in check_modules, f"{slug} installs {module} now; drop the exemption"
    assert len(BACKEND_CHOICES[(slug, module)]) > 30, "an exemption needs its reason"
