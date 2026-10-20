"""No module a base install can import pulls in an optional extra at module scope.

AGENTS.md rule 3: heavy dependencies are optional extras, imported lazily inside the
function that needs them, so a fresh install with no extras imports and runs.
`scripts/check_dependency_budget.py` enforces that for one entry point — it imports
`yazses.core.daemon` and inspects `sys.modules`. Everything the daemon does not
import at start was enforced by nothing: `yazses transcribe`, `meeting`, the tray,
the settings window, every module reached only from a CLI command. A top-level
`import sherpa_onnx` in one of those would pass every check and turn the command
into an ImportError traceback on a base install.

This scans the source statically, so it covers every module and needs no extra
installed. The set of optional modules is **derived** from the budget script's
`EXTRA_MODULES` — which that script already forces to cover every extra in
`pyproject.toml` — so a new extra is covered here the moment it is declared.

Module scope includes `if`/`try`/`with`/class bodies (they run at import);
`if TYPE_CHECKING:` does not. A module that imports an extra at module scope is a
*Qt-only leaf* or an *adapter* and must be listed in `ALLOWED_LEAVES` with a reason;
the closure check then proves no other module imports it at module scope, so it
stays reachable only lazily.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

#: Modules allowed to import an extra at module scope, and why. Each must be imported
#: by every other module only inside a function — the closure test proves it.
ALLOWED_LEAVES: dict[str, str] = {
    "yazses.overlay.widget": "the Qt widget itself; overlay/app.py imports it lazily",
    "yazses.platform.emg.backend": "try/except-guarded pyserial; built lazily by the daemon",
    "yazses.platform.emg.ble_backend": "try/except-guarded bleak; built lazily by the daemon",
}


def _budget_script():
    spec = importlib.util.spec_from_file_location(
        "check_dependency_budget", ROOT / "scripts" / "check_dependency_budget.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


OPTIONAL = frozenset(_budget_script().OPTIONAL_IMPORT_MODULES)


def _owned(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in OPTIONAL)


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _module_scope_imports(path: Path, package: str) -> set[str]:
    """Every absolute module name imported when *path* is imported."""
    found: set[str] = set()

    def visit(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(node, ast.If) and _is_type_checking(node.test):
                visit(node.orelse)
                continue
            if isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")
                    base = base[: len(base) - node.level + 1]
                    mod = ".".join([*base, node.module] if node.module else base)
                else:
                    mod = node.module or ""
                found.add(mod)
                found.update(f"{mod}.{a.name}" for a in node.names)
            for field in ("body", "orelse", "finalbody", "handlers"):
                sub = getattr(node, field, None)
                if isinstance(sub, list):
                    visit(sub)

    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return found


def _scan() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(module -> extras it imports at scope, module -> yazses modules it imports)."""
    direct: dict[str, set[str]] = {}
    internal: dict[str, set[str]] = {}
    for path in sorted((SRC / "yazses").rglob("*.py")):
        name = _module_name(path)
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        imports = _module_scope_imports(path, package)
        direct[name] = {i for i in imports if _owned(i)}
        internal[name] = {i for i in imports if i.split(".")[0] == "yazses"}
    return direct, internal


DIRECT, INTERNAL = _scan()


def _heavy_closure() -> dict[str, str]:
    """module -> the reason it pulls an extra in at import (directly or transitively)."""
    heavy = {m: f"imports {', '.join(sorted(x))}" for m, x in DIRECT.items() if x}
    changed = True
    while changed:
        changed = False
        for mod, deps in INTERNAL.items():
            if mod in heavy:
                continue
            hit = next((d for d in sorted(deps) if d in heavy), None)
            if hit is not None:
                heavy[mod] = f"imports {hit} at module scope"
                changed = True
    return heavy


def test_the_optional_module_set_is_derived_and_non_empty():
    assert {"PySide6", "mediapipe", "onnx_asr", "sherpa_onnx", "speechbrain"} <= OPTIONAL


def test_the_scanner_sees_a_known_module_scope_import():
    """A scanner that finds nothing would pass everything."""
    assert DIRECT["yazses.overlay.widget"], "the scan cannot see PySide6 in overlay/widget.py"


def test_the_scanner_ignores_function_scope_and_type_checking(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    import mediapipe\n"
        "def f():\n    import sherpa_onnx\n"
        "try:\n    import PySide6\nexcept ImportError:\n    PySide6 = None\n",
        encoding="utf-8",
    )
    found = {i for i in _module_scope_imports(probe, "x") if _owned(i)}
    assert found == {"PySide6"}


def test_no_module_outside_the_allowed_leaves_imports_an_extra_at_module_scope():
    offenders = {m: why for m, why in _heavy_closure().items() if m not in ALLOWED_LEAVES}
    assert not offenders, (
        "These modules import an optional extra when they are imported, so a base "
        "install (no extras) gets an ImportError — or a slow import — from them. Move "
        "the import inside the function that needs it (AGENTS.md rule 3):\n"
        + "\n".join(f"  {m}: {why}" for m, why in sorted(offenders.items()))
    )


@pytest.mark.parametrize("leaf", sorted(ALLOWED_LEAVES))
def test_every_allowed_leaf_still_exists_and_still_needs_the_exemption(leaf):
    assert leaf in DIRECT, f"{leaf} no longer exists; drop it from ALLOWED_LEAVES"
    assert DIRECT[leaf], f"{leaf} no longer imports an extra; drop it from ALLOWED_LEAVES"
