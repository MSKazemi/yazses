"""A macOS build must not import the Linux backend to answer a question about names.

`system/doctor.py` imported `BSD_PREFIXES` — a four-string tuple — from
`yazses.platform.bsd`. That module imports the Linux backend at module scope, because
BSD reuses it wholesale. So one tuple of strings dragged the whole Linux platform
package into `doctor` on *every* OS.

From source that is invisible: a wheel carries every backend, so the import resolves
and nothing looks wrong. Inside a PyInstaller macOS bundle, which correctly ships no
Linux backend, `yazses doctor` died with `No module named 'yazses.platform.linux'` —
a released .app crashing on a documented command. Nothing but the bundle smoke test
could see it, and a smoke test runs only on a tag, after the release is under way.

The rule these tests hold is narrow and mechanical: **outside the platform package,
no module may name an OS backend in a module-scope import**. Inside a function is
fine — that is what `platform/factory.py` does, and the import is then reached only
on the OS it belongs to. What must not happen is a backend arriving as a side effect
of importing something that merely wanted a constant.
"""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "yazses"
PLATFORM = SRC / "platform"


def _os_backends() -> frozenset[str]:
    """The backends `platform/factory.py` dispatches to by `sys.platform`.

    Read out of the factory rather than listed here, because a listed set is only
    ever as current as the day it was written — and `platform/` also holds `emg/`,
    which is an activation source, not an OS backend, and which any module may
    legitimately import. Deriving the set keeps that distinction correct for free
    when a platform is added.
    """
    text = (PLATFORM / "factory.py").read_text(encoding="utf-8")
    named = set(re.findall(r"from yazses\.platform\.(\w+) import", text))
    # A backend is a *package* (`platform/<os>/__init__.py`); `platform.base` is a
    # module and is exactly what everything is supposed to import instead. Filtering
    # on that structural difference rather than on a name list keeps the two apart
    # without anything to remember.
    found = {name for name in named if (PLATFORM / name).is_dir()}
    assert found, "no backend packages imported by platform/factory.py -- has it moved?"
    return frozenset(found)


def _module_scope_imports(path: pathlib.Path) -> list[tuple[int, str]]:
    """(lineno, module) for every import written at module scope in *path*."""
    out = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            out.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.lineno, node.module))
    return out


def test_the_backend_set_is_derived_and_non_empty():
    backends = _os_backends()
    assert {"linux", "macos", "windows", "bsd"} <= backends, backends
    assert "base" not in backends, (
        "platform.base is a module of names, not an OS backend -- it is what modules "
        "are supposed to import instead of a backend"
    )
    assert "emg" not in backends, (
        "emg is an activation source, not an OS backend -- it is platform-independent "
        "and importing it says nothing about which OS a bundle is for"
    )


def test_no_module_outside_the_platform_package_imports_a_backend_at_module_scope():
    backends = _os_backends()
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path.is_relative_to(PLATFORM):
            continue
        for lineno, module in _module_scope_imports(path):
            parts = module.split(".")
            if parts[:2] == ["yazses", "platform"] and len(parts) >= 3 and parts[2] in backends:
                offenders.append(f"{path.relative_to(ROOT)}:{lineno} imports {module}")
    assert not offenders, (
        "these reach an OS backend at import time, so every OS pays for it and a "
        "bundle that ships only its own backend crashes:\n  " + "\n  ".join(offenders)
        + "\nMove the import inside the function that needs it, or move the thing "
        "being imported to `platform/base.py` if it is only a name."
    )


@pytest.mark.parametrize("module", ["yazses.system.doctor", "yazses.config"])
def test_importing_it_pulls_in_no_backend_at_all(module):
    """The source rule, checked at runtime — a re-export could satisfy one and not the other.

    Run in a subprocess: this test session has already imported half the tree, so
    inspecting `sys.modules` in-process would report whatever ran before it.
    """
    code = (
        f"import {module}, sys\n"
        "print('\\n'.join(sorted(m for m in sys.modules "
        "if m.startswith('yazses.platform.'))))"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    loaded = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    backends = _os_backends()
    leaked = {m for m in loaded if m.split(".")[2] in backends}
    assert not leaked, (
        f"importing {module} loaded {sorted(leaked)}. On this OS the import resolves; "
        f"in a bundle built for a different one it does not exist."
    )
