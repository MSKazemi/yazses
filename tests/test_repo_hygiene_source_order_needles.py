"""A source-order assertion must search for something that occurs once.

Several guards in this suite assert that one thing happens before another by comparing
positions in `inspect.getsource(...)`:

    source = inspect.getsource(Daemon._on_hold_end)
    assert source.index(A) < source.index(B)

`str.index` returns the **first** match. If A or B also appears somewhere earlier — an
import line, a comment, a docstring — the comparison measures that instead, and the guard
passes regardless of the order it claims to check.

This is not hypothetical. On 2026-08-19 it happened three times in one day, all caught by
sabotaging the source and watching the test stay green:

* `test_meeting_notes_reason` compared `index("notes_unavailable_reason")` against the
  echo. The name is also in the function's import block, above the echo in *either*
  order, so the assertion could never fail. Reordering the body left it green.
* Anchoring on the call fixed that, and it then failed while the code was **correct**:
  the explanatory comment written beside the change contains the phrase "Generating
  minutes locally", and `index` found the comment.
* `test_miclevel_cannot_hear_whether_you_spoke` compared
  `index("update_threshold_in_config")`, which is also in that function's import block.

The rule is mechanical now rather than remembered, in the same spirit as
`test_repo_hygiene_vacuous_guards.py`: bind the position to something that appears once.

## What counts as acceptable

A needle that occurs exactly once in the source it searches. A needle that occurs more than
once is allowed only when the call passes an explicit `start` offset — `source.index(x,
start)` is a deliberate "the next one after here", which is how
`test_device_heal_daemon._empty_discard_branch` correctly finds the `return` that ends a
branch out of the thirty in that function.

## Deliberately dynamic

The needle's ambiguity cannot be seen statically: it depends on the *target's* source. So
this resolves each site's `getsource(...)` argument in the test module's own namespace and
counts. Modules that will not import cheaply are skipped, and a floor on the number of
resolved sites keeps that from quietly becoming zero coverage.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent

#: Below this many resolved sites, the scan has broken rather than the repo improved.
MIN_SITES = 12


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"_srcorder_{path.stem}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None  # Qt, a missing extra, an env assumption — not our business here
    return module


def _sites():
    """`(file, lineno, needle, haystack)` for every resolvable source-order needle."""
    out = []
    for path in sorted(TESTS.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if "getsource" not in text or (".index(" not in text and ".find(" not in text):
            continue
        tree = ast.parse(text)
        module = None
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            targets = {
                n.targets[0].id: n.value.args[0]
                for n in ast.walk(fn)
                if isinstance(n, ast.Assign)
                and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Attribute)
                and n.value.func.attr == "getsource"
                and n.value.args
            }
            if not targets:
                continue
            for call in ast.walk(fn):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in ("index", "find")
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in targets
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)
                ):
                    continue
                if len(call.args) > 1:
                    continue  # an explicit start offset is a deliberate "the next one"
                if module is None:
                    module = _load(path)
                    if module is None:
                        break
                # Most of these tests import their target INSIDE the test function, so it
                # is not in module globals. Replaying the function's own imports is what
                # took coverage from 5 sites to most of them; without it the guard would
                # have silently watched a third of the suite.
                scope = dict(vars(module))
                for stmt in ast.walk(fn):
                    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                        try:
                            exec(ast.unparse(stmt), scope)  # noqa: S102 — this repo's tests
                        except Exception:
                            pass
                try:
                    target = eval(  # noqa: S307 — a literal from this repo's own tests
                        ast.unparse(targets[call.func.value.id]), scope
                    )
                    haystack = inspect.getsource(target)
                except Exception:
                    continue
                out.append((path.name, call.lineno, call.args[0].value, haystack))
    return out


SITES = _sites()


def test_the_scan_resolved_enough_sites() -> None:
    """Guard the guard: an empty scan would read as a clean bill of health."""
    assert len(SITES) >= MIN_SITES, (
        f"only {len(SITES)} source-order needles resolved — the scan is broken, not the "
        f"suite. Check that test modules still import and that the getsource idiom is "
        f"unchanged."
    )


@pytest.mark.parametrize(
    "where,needle,haystack",
    [(f"{f}:{ln}", needle, hay) for f, ln, needle, hay in SITES],
    ids=[f"{f}:{ln}" for f, ln, _n, _h in SITES],
)
def test_each_needle_occurs_exactly_once(where: str, needle: str, haystack: str) -> None:
    count = haystack.count(needle)
    assert count == 1, (
        f"{where}: {needle!r} occurs {count}x in the source it searches, so `.index` "
        f"measures the first one — which may be an import, a comment or a docstring "
        f"rather than the statement this guard is about. Use a longer, statement-shaped "
        f"needle, or pass an explicit start offset if you mean 'the next one after here'."
    )
