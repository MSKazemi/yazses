"""Load a `paper/benchmark/` module, or skip when its optional deps are absent.

The benchmark harness is maintainer tooling. Its dependencies live in the
`benchmark` dependency *group*, which `uv sync` does not install — so every CI job
that runs the suite with a plain `uv sync` imports these modules without `psutil`,
`jiwer` or `whisper_normalizer` present.

That is not hypothetical: it turned `main` red and skipped the `publish-pypi` step of
a tagged release. Seven tests raised `ModuleNotFoundError` at import time. Three of
them sat in a file that already called `pytest.importorskip` for `scipy`, `jiwer` and
`whisper_normalizer` — the mechanism was right there and the list was simply short of
the dependency that mattered. A hand-written list of what to skip on is the defect;
it is only ever as complete as the day it was written.

So the set is **derived from `pyproject.toml`'s own `benchmark` group** instead. If a
bench module fails to import because a distribution declared there is missing, that is
an uninstalled optional dependency and the test skips. If it fails to import for any
other reason — a typo, a real broken import, a module nobody declared — the error is
raised, because that is a bug and skipping it would hide exactly what the tests exist
to catch.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import tomllib
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "paper" / "benchmark"


@lru_cache(maxsize=1)
def optional_modules() -> frozenset[str]:
    """Import names of every distribution in the `benchmark` dependency group.

    PEP 503 normalisation in reverse: a distribution is named with hyphens on PyPI and
    imported with underscores (`whisper-normalizer` -> `whisper_normalizer`). That
    rule holds for all five here; a future member for which it does not would simply
    not be recognised as optional, and would fail loudly rather than skip silently —
    the safe direction.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    group = data.get("dependency-groups", {}).get("benchmark", [])
    names = set()
    for req in group:
        dist = req.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip()
        names.add(dist.replace("-", "_").lower())
    return frozenset(names)


def _imports(path: Path) -> set[str]:
    """Every top-level module name imported anywhere in *path*, nesting included.

    `ast.walk` rather than a scan of module-level statements, because the imports that
    actually broke this were **inside functions**: `_common.provenance()` imports
    `psutil` when called, so the module loads cleanly and the failure lands at call
    time, several tests later. A check that only looked at import time would have
    reported the file fine and let every caller fail.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _needed(filename: str) -> set[str]:
    """Optional deps of *filename* and of the bench modules it pulls in transitively.

    The bench scripts import each other by bare name (`from _common import ...`), so a
    test that loads `bench_wer` reaches `_common`'s dependencies too. Closed over the
    benchmark directory only — nothing outside it is followed.
    """
    seen: set[str] = set()
    pending = [filename]
    found: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen or not (BENCH / current).exists():
            continue
        seen.add(current)
        for name in _imports(BENCH / current):
            if (BENCH / f"{name}.py").exists():
                pending.append(f"{name}.py")
            elif name in optional_modules():
                found.add(name)
    return found


def load(name: str, filename: str):
    """Exec `paper/benchmark/<filename>` as *name*, or skip on a missing bench dep."""
    for dep in sorted(_needed(filename)):
        pytest.importorskip(
            dep,
            reason=f"`{filename}` needs `{dep}`, in the optional `benchmark` "
                   f"dependency group: `uv sync --group benchmark`",
        )
    if str(BENCH) not in sys.path:
        sys.path.insert(0, str(BENCH))
    spec = importlib.util.spec_from_file_location(name, BENCH / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:
        missing = (exc.name or "").split(".")[0]
        if missing in optional_modules():
            del sys.modules[name]
            pytest.skip(
                f"`{filename}` needs `{missing}`, in the optional `benchmark` "
                f"dependency group: `uv sync --group benchmark`"
            )
        raise
    return module
