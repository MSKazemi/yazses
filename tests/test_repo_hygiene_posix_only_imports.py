"""A POSIX-only import at test-module scope kills the entire Windows run.

Not one red test -- the whole job. `tests/test_setup_probe_survives_a_passwdless_uid.py`
had a bare ``import pwd`` at module scope, and Windows CI reported::

    collecting ... collected 9525 items / 1 error / 8 skipped
    ERROR collecting tests/test_setup_probe_survives_a_passwdless_uid.py
        import pwd
    E   ModuleNotFoundError: No module named 'pwd'
    !!!!!!! Interrupted: 1 error during collection !!!!!!!
    ======== 8 skipped, 1 error in 14.19s ========

pytest aborts the session on a collection error, so **both Windows jobs ran zero
tests** while reporting a failure that looked like one broken file. `main` carried
that for days: the cross-platform matrix existed, and on half of it nothing was
being verified at all.

The fix in that file is `pytest.importorskip`, which turns the same situation into
a skip. This guard is here so the next one cannot repeat it -- and it derives the
module list from `sys.builtin_module_names`-adjacent facts rather than restating a
hand-written set, because a hand-written set is the thing that goes stale.

Scope note: only **module-scope** imports are a collection hazard. An import inside
a function or fixture raises at *call* time, which pytest reports as one failing
test -- bad, but not a dead session -- and is how `src/yazses/system/setup.py`
legitimately uses `pwd`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent

# Stdlib modules that do not exist on Windows. Kept short and factual: each is
# absent from a CPython Windows install, and each has bitten a project somewhere.
# `pytest.importorskip` (or a function-scope import) is the fix for every one.
POSIX_ONLY = frozenset({
    "pwd", "grp", "termios", "tty", "fcntl", "crypt", "posix",
    "resource", "syslog", "pty", "spwd", "nis", "ossaudiodev",
})


def _module_scope_imports(tree: ast.Module) -> set[str]:
    """Top-level `import x` / `from x import ...` only.

    Walks the module body directly rather than `ast.walk`, because a nested import
    is exactly the safe case this guard must not flag. An import inside `if
    sys.platform != "win32":` is also nested and therefore allowed -- that is a
    deliberate, working pattern, not an oversight.
    """
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def _test_files() -> list[Path]:
    return sorted(TESTS.glob("test_*.py"))


def test_the_guard_has_something_to_check() -> None:
    """A guard that iterates is green over an empty collection.

    This suite has thousands of tests; if this ever sees a handful, the glob is
    broken and every assertion below is vacuous.
    """
    assert len(_test_files()) > 50, "the test glob found almost nothing — guard is blind"


@pytest.mark.parametrize("path", _test_files(), ids=lambda p: p.name)
def test_no_test_module_imports_a_posix_only_module_at_module_scope(path: Path) -> None:
    offenders = _module_scope_imports(ast.parse(path.read_text(encoding="utf-8"))) & POSIX_ONLY
    assert not offenders, (
        f"{path.name} imports {sorted(offenders)} at module scope. On Windows that is a "
        "COLLECTION error, which aborts the whole pytest session — every other test in "
        "the suite stops running and the job reports one broken file.\n"
        "Fix: `mod = pytest.importorskip(\"<name>\", reason=\"POSIX-only\")`, or move the "
        "import inside the function or fixture that needs it."
    )


def test_the_guard_actually_catches_the_shape(tmp_path: Path) -> None:
    """Prove the detector, not just its verdict — otherwise a broken parser reads
    as a clean repo."""
    bad = tmp_path / "test_bad.py"
    bad.write_text("import os\nimport pwd\n\ndef test_x():\n    assert pwd\n", encoding="utf-8")
    assert _module_scope_imports(ast.parse(bad.read_text(encoding="utf-8"))) & POSIX_ONLY == {"pwd"}


def test_the_guard_allows_the_two_documented_fixes(tmp_path: Path) -> None:
    """`importorskip` and a function-scope import must both pass, or the guard
    pushes people toward deleting coverage instead of gating it."""
    ok = tmp_path / "test_ok.py"
    ok.write_text(
        "import pytest\n"
        "pwd = pytest.importorskip('pwd')\n\n"
        "def test_y():\n"
        "    import grp\n"
        "    assert grp\n"
    , encoding="utf-8")
    assert not (_module_scope_imports(ast.parse(ok.read_text(encoding="utf-8"))) & POSIX_ONLY)
