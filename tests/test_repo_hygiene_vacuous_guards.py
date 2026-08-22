"""A guard that iterates a glob must pin that the glob found something.

`for path in SOMEWHERE.glob("*"): assert <property>(path)` is green in exactly two
situations: every file satisfies the property, and *there are no files*. The second
is indistinguishable from the first in the output, and it is the state a rename, a
moved directory or a changed suffix produces — which is to say, precisely when the
guard was most needed.

This is not hypothetical, and it is not rare. On 2026-08-15 it was found three
separate times in one day:

- Four checks globbed `README.*.md` at the repo root — `check-translations.py`,
  `gen-readme-translation.py`, `test_contributors_wall.py` and
  `test_citation_metadata.py`. The translations moved to `docs/<lang>/index.md` and
  all four went quietly green while checking zero files. The contributor wall, the
  citation identifier and the translation drift check were all unguarded, and the
  suite said everything was fine.
- `test_cli_reference_covers_every_command.py` read only the top level of the Click
  tree, so the ~50 subcommands behind 15 groups were never looked at, and two had
  drifted out of the reference.
- The three fixed alongside this file: two `packaging/` manifest guards and the
  winget locale guard, the last of which protects against a defect that has already
  shipped once.

So the rule is mechanical now rather than remembered. The fix is one line — bind the
glob to a name and assert it is non-empty first — and the repo already had the idiom
before this file existed, in `test_docs_current_version_claims.py`:

    assert versions, "no softwareVersion in the home page JSON-LD -- guard is blind"

The check is deliberately narrow: it fires only on a `for` loop whose iterator is a
literal `.glob(...)`/`.rglob(...)` call *and* whose body asserts something, and it
accepts any assertion in the enclosing function that could pin a size — a bare name,
or a comparison with `==`, `>` or `>=`. A comprehension that filters the glob before
asserting is fine, because the assertion then sits outside the loop.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def _pins_non_emptiness(fn: ast.FunctionDef) -> bool:
    """Does *fn* assert, anywhere, that some collection is non-empty or sized?"""
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assert):
            continue
        if isinstance(node.test, ast.Name):  # assert manifests, "..."
            return True
        if isinstance(node.test, ast.Compare) and any(
            isinstance(op, (ast.Gt, ast.GtE, ast.Eq)) for op in node.test.ops
        ):
            return True
    return False


def _vacuous_loops(source: str) -> list[str]:
    offenders: list[str] = []
    tree = ast.parse(source)
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        if _pins_non_emptiness(fn):
            continue
        for node in ast.walk(fn):
            if not (isinstance(node, ast.For) and isinstance(node.iter, ast.Call)):
                continue
            func = node.iter.func
            if not (isinstance(func, ast.Attribute) and func.attr in {"glob", "rglob"}):
                continue
            if any(isinstance(inner, ast.Assert) for inner in ast.walk(node)):
                offenders.append(f"{fn.name} (line {node.lineno})")
    return offenders


def test_no_guard_asserts_over_a_glob_it_never_proved_non_empty() -> None:
    offenders: list[str] = []
    for path in sorted(TESTS.glob("test_*.py")):
        for name in _vacuous_loops(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.name}::{name}")

    assert not offenders, (
        "These loop over a glob and assert on each hit, but nothing pins that the "
        f"glob matched anything — so they pass on an empty set: {offenders}. Bind "
        "the glob to a name and assert it is non-empty before the loop."
    )


def test_the_check_catches_the_shape_it_exists_for() -> None:
    """A detector for a silent failure must not fail silently itself.

    The suite is expected to be clean, so the assertion above passes whether the
    detector works or is broken — the same vacuity, one level up.
    """
    vacuous = '''
def test_thing():
    for p in ROOT.glob("*.yaml"):
        assert "bad" not in p.read_text(encoding="utf-8")
'''
    guarded = '''
def test_thing():
    paths = list(ROOT.glob("*.yaml"))
    assert paths, "guard is blind"
    for p in paths:
        assert "bad" not in p.read_text(encoding="utf-8")
'''
    no_assert = '''
def test_thing():
    for p in ROOT.glob("*.yaml"):
        print(p)
'''
    assert _vacuous_loops(vacuous) == ["test_thing (line 3)"]
    assert _vacuous_loops(guarded) == []
    assert _vacuous_loops(no_assert) == []


def test_the_repo_actually_contains_tests_to_scan() -> None:
    """The scanner globs too, so it can be blinded in exactly the same way."""
    assert len(list(TESTS.glob("test_*.py"))) > 100
