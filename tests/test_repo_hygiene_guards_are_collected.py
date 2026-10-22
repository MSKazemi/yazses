"""Every repo-hygiene guard must import on a base install, or it guards nothing.

`test_repo_hygiene_source_order_needles.py` imports other test modules to read their
sources. One of those, `test_bench_diarization_profile.py`, calls `pytest.skip` at import
wherever the optional `benchmark` group is absent. `pytest.skip` raises an exception
derived from BaseException, which the guard's `except Exception` did not catch, so the
guard's whole module was skipped at collection on every default run and in every CI job
that ran it. Its own "guard the guard" floor check was skipped along with it. Serially
this showed only as one extra skip in the summary; under `-n auto`, xdist does not count
a module skipped at collection, so not even that.

A test inside a module cannot notice that its module was skipped, so this check lives
in a module of its own. It imports each `test_repo_hygiene_*.py` the way collection
does and fails if the import skips. These guards read the source tree and need nothing
optional, so none of them has a reason to skip.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
GUARDS = sorted(p for p in TESTS.glob("test_repo_hygiene_*.py") if p.name != Path(__file__).name)


def test_there_are_guards_to_check() -> None:
    assert len(GUARDS) >= 5, [p.name for p in GUARDS]


@pytest.mark.parametrize("path", GUARDS, ids=[p.name for p in GUARDS])
def test_the_guard_module_imports_without_skipping(path: Path) -> None:
    spec = importlib.util.spec_from_file_location(f"_collect_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except pytest.skip.Exception as skip:
        pytest.fail(
            f"{path.name} skips at import, so none of its tests run: {skip.msg}. A "
            "repo-hygiene guard reads the source tree and has no optional dependency; "
            "find what raised the skip during import (a module it loads, a fixture-free "
            "importorskip) and catch it there."
        )
