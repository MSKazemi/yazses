"""A test that never runs here still has to be *correct* here.

`tests/test_macos_input_monitoring_on_hardware.py` is `skipif`-ed off darwin, so
on Linux pytest never imports its bodies -- and one of them did
``from yazses.platform.factory import build_platform``, a name that does not
exist. Every Linux run was green. It failed the moment it first reached a real
Mac, which is the one place it was supposed to be *proving* something rather than
discovering its own typo.

That is the general shape: a platform-gated module is dead code on every other
platform, so its imports are unchecked by the machines that run most often. The
cost is paid at the worst moment -- in the rare, slow, cross-platform job, where
a broken test looks exactly like a broken product.

So: on any host, resolve the names those modules import from `yazses`.

What this deliberately does NOT do is execute them. `import`-ability is the part
that is platform-independent; behaviour is not. A module that genuinely cannot be
imported off its platform is skipped with a reason rather than failed -- but a
module that imports fine and simply lacks the *attribute* is a hard failure,
because that is a typo, not a platform difference.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent

#: Modules whose import is genuinely platform-conditional. Anything else that
#: fails to import is a real defect and must not be swallowed.
_PLATFORM_ONLY_PREFIXES = ("yazses.platform.macos", "yazses.platform.windows")


def _is_platform_gated(tree: ast.Module) -> bool:
    """True when the module builds a platform skip at module scope.

    Any module-level assignment of a `skipif` that mentions `sys.platform` counts,
    not only one named `pytestmark`. `tests/test_ipc_protocol.py` calls its mark
    `pytestmark_unix` and applies it per test -- so a detector keyed to the magic
    name saw an unguarded file, which is the same class of miss this whole module
    exists to prevent.
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        src = ast.dump(node.value)
        if "skipif" in src and "platform" in src:
            return True
    return False


def _yazses_imports(tree: ast.Module) -> list[tuple[str, str]]:
    """Every ``from yazses... import name``, at any nesting depth.

    Nesting is the point: these live inside test function bodies, which is exactly
    why nothing resolved them.
    """
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == "yazses" or node.module.startswith("yazses."):
                out.extend((node.module, alias.name) for alias in node.names)
    return out


def _gated_modules() -> list[Path]:
    return sorted(
        p
        for p in TESTS.glob("test_*.py")
        if _is_platform_gated(ast.parse(p.read_text(encoding="utf-8")))
    )


def test_the_guard_has_something_to_check() -> None:
    """A guard that iterates is green over an empty list. If the detection breaks,
    every check below passes while checking nothing."""
    gated = _gated_modules()
    assert gated, "no platform-gated test modules found -- the detector is broken"
    names = {p.name for p in gated}
    assert "test_macos_input_monitoring_on_hardware.py" in names, (
        f"the module this guard was written for is not being detected: {sorted(names)}"
    )


@pytest.mark.parametrize("path", _gated_modules(), ids=lambda p: p.name)
def test_every_name_a_platform_gated_test_imports_actually_exists(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # A gated module need not import from `yazses` at all -- one of them drives the
    # CLI through a subprocess. Non-vacuity is held by
    # `test_the_guard_has_something_to_check`, not by demanding every module here
    # have imports to check.
    for module_name, attr in _yazses_imports(tree):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            if module_name.startswith(_PLATFORM_ONLY_PREFIXES):
                pytest.skip(f"{module_name} is not importable on this platform")
            raise
        if hasattr(module, attr):
            continue
        # `from pkg import submodule` binds a module, and `hasattr(pkg, sub)` is
        # False until something imports it. Resolving it as a module is the whole
        # difference between this guard and a false alarm on every package import.
        try:
            importlib.import_module(f"{module_name}.{attr}")
        except ImportError:
            pytest.fail(
                f"{path.name} imports {attr!r} from {module_name}, which has no "
                f"such name and no such submodule. This module is skipped on this "
                f"platform, so nothing else would notice until the test reached "
                f"the one machine it exists to run on."
            )
