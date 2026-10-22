"""Every third-party package `src/` imports is declared — in the base install or an extra.

The feature contract runs registry → extra → installer, and the earlier guards close
it from the extra end: an extra no feature installs fails
(`test_every_extra_has_an_install_path.py`), a feature pin below its extra fails
(`test_feature_pins_match_the_extras.py`), a module-scope import of an extra fails
(`test_no_module_imports_an_extra_at_module_scope.py`).

All of those start from `pyproject.toml`. None can see a library that was never
written there. A new feature whose module does `import torch` inside a function, with
torch declared nowhere, passes every one of them, installs nothing when enabled, and
fails on the first user's machine with an ImportError the developer never saw —
because the developer had torch installed for something else. That is the "added a
feature without declaring its requirements" case, and this test is its gate.

So every import in `src/yazses/` (any scope — a lazy import is still a requirement)
must resolve to one of:

* the standard library, or YazSes itself;
* a distribution declared in `[project.dependencies]` or an extra — found from the
  installed metadata, or, for one not installed here, from its PEP 503 name;
* an extra's module (`scripts/check_dependency_budget.py::EXTRA_MODULES`);
* one of the three hand-kept maps below, each entry with a reason, each checked for
  staleness.
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "yazses"

#: Import names a declared *base* dependency provides under a name that is not its
#: distribution's, for platforms where it is not installed (so the metadata cannot say).
PLATFORM_BASE: dict[str, str] = {
    "Xlib": "python-xlib",
    "PIL": "pillow",
    "Quartz": "pyobjc-framework-quartz",
    "AppKit": "pyobjc-framework-cocoa",
    "CoreFoundation": "pyobjc-framework-cocoa",
    "ApplicationServices": "pyobjc-framework-applicationservices",
    "AVFoundation": "pyobjc-framework-avfoundation",
    "pywintypes": "pywin32",
    "win32file": "pywin32",
    "win32pipe": "pywin32",
}

#: Imported directly, provided by a declared dependency's own requirements. Each names
#: the declared parent; relying on a transitive is a choice, and this is where it is
#: written down.
PROVIDED_BY: dict[str, tuple[str, str]] = {
    "ctranslate2": ("faster-whisper", "the decoder faster-whisper runs on"),
    "huggingface_hub": ("faster-whisper", "faster-whisper's model downloader"),
    "rich": ("typer", "typer's terminal renderer"),
    "packaging": ("faster-whisper", "via huggingface-hub; version parsing only"),
    "torch": ("speechbrain", "speechbrain (voiceprint) and pyannote.audio pull it in; "
                             "imported only inside those backends"),
}

#: Imported, deliberately not installable from this project's metadata. A feature that
#: needs one of these cannot be turned on by `features enable` alone, and says so.
NOT_DECLARED: dict[str, str] = {
    "pyatspi": "the AT-SPI bindings come from the OS package manager (python3-pyatspi), "
               "never PyPI; every import is guarded and the caller falls back",
    "l2cs": "the opt-in L2CS-Net gaze backend is manual-install by design: it pins an "
            "older torch that conflicts with the base install (see gaze/factory.py)",
}


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(spec: str) -> str:
    return _canonical(re.split(r"[\[<>=!~; @]", spec.strip(), maxsplit=1)[0])


def _declared() -> tuple[set[str], set[str]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    base = {_requirement_name(s) for s in data["dependencies"]}
    extras = {_requirement_name(s) for g in data["optional-dependencies"].values() for s in g}
    return base, extras


@functools.cache
def _extra_modules() -> frozenset[str]:
    spec = importlib.util.spec_from_file_location(
        "check_dependency_budget", ROOT / "scripts" / "check_dependency_budget.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return frozenset(m.split(".")[0] for m in mod.OPTIONAL_IMPORT_MODULES)


def _imports() -> dict[str, set[str]]:
    """top-level import name -> the src files importing it (absolute imports only)."""
    found: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module]
            else:
                continue
            for name in names:
                found.setdefault(name.split(".")[0], set()).add(
                    path.relative_to(SRC.parent).as_posix()
                )
    return found


@functools.cache
def _distributions() -> dict[str, list[str]]:
    return dict(packages_distributions())


IMPORTS = _imports()
BASE, EXTRAS = _declared()


def _allowed(top: str) -> bool:
    if top in sys.stdlib_module_names or top in {"yazses", "__future__"}:
        return True
    if top in _extra_modules() or top in PLATFORM_BASE or top in PROVIDED_BY:
        return True
    if top in NOT_DECLARED:
        return True
    providers = {_canonical(d) for d in _distributions().get(top, [])}
    if providers & (BASE | EXTRAS):
        return True
    # Not installed here (another platform's dependency, or the FreeBSD leg without
    # faster-whisper): fall back to the PEP 503 name, which is the import name for
    # every declared dependency the maps above do not list.
    return _canonical(top) in BASE | EXTRAS


def test_the_scan_sees_imports_of_every_kind():
    assert {"numpy", "typer", "PySide6", "sherpa_onnx", "evdev"} <= set(IMPORTS)


def test_the_check_rejects_an_undeclared_library():
    """A check that allows everything is worse than none."""
    assert not _allowed("definitely_not_declared_anywhere_xyz")
    assert _allowed("numpy") and _allowed("os") and _allowed("PySide6")


@pytest.mark.parametrize("top", sorted(IMPORTS))
def test_every_import_is_declared_somewhere(top):
    assert _allowed(top), (
        f"`{top}` is imported by {sorted(IMPORTS[top])} but no dependency in "
        "pyproject.toml provides it. On a user's machine that import fails, and "
        "`yazses features enable` cannot fix it because nothing says what to install. "
        "Declare it: in an extra (and the feature's `_FEATURE_DEPS` entry in "
        "system/features.py) if it is optional, in [project.dependencies] if not — "
        "or add it to a map in this file with the reason it cannot be declared."
    )


@pytest.mark.parametrize("top", sorted({*PLATFORM_BASE, *PROVIDED_BY, *NOT_DECLARED}))
def test_every_hand_kept_entry_is_still_imported(top):
    assert top in IMPORTS, f"`{top}` is no longer imported by src/; drop its entry"


@pytest.mark.parametrize("top, dist", sorted(PLATFORM_BASE.items()))
def test_every_platform_entry_names_a_declared_base_dependency(top, dist):
    assert dist in BASE, f"{top} -> {dist}, which [project.dependencies] does not declare"


@pytest.mark.parametrize("top, parent", sorted((t, p) for t, (p, _w) in PROVIDED_BY.items()))
def test_every_transitive_names_a_declared_parent(top, parent):
    assert parent in BASE | EXTRAS, f"{top} is said to come with {parent}, which is undeclared"
    assert top not in _extra_modules(), f"{top} is an extra's module now; drop it here"


@pytest.mark.parametrize("top", sorted(NOT_DECLARED))
def test_an_undeclared_entry_really_is_undeclared(top):
    assert _canonical(top) not in BASE | EXTRAS, f"{top} is declared now; drop its entry"
    assert len(NOT_DECLARED[top]) > 30, "an exemption needs its reason"
