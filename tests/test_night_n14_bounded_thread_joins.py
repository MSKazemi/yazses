"""Every ``join`` in the test suite is bounded.

An unbounded ``Thread.join()`` turns a deadlock into a 300 s pytest-timeout kill
(and, on Windows, a dead worker or a stopped serial run) that names no thread.
``join(timeout=N)`` followed by ``assert not t.is_alive()`` fails in seconds and
says which thread hung. This guard keeps new unbounded joins out of ``tests/``.

A zero-argument ``.join()`` call is never ``str.join`` (that takes one
argument), so the check needs no type inference. ``.join(None)`` and
``.join(timeout=None)`` are unbounded too and are flagged the same way.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent

# Files whose unbounded join is fixed on another, unmerged branch. Each entry is
# temporary: remove it when that branch lands, and this guard then covers it.
PENDING_ELSEWHERE: dict[str, str] = {}


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _unbounded_joins(source: str, filename: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "join":
            continue
        args, kwargs = node.args, node.keywords
        if not args and not kwargs:
            lines.append(node.lineno)
        elif len(args) == 1 and not kwargs and _is_none(args[0]):
            lines.append(node.lineno)
        elif not args and len(kwargs) == 1 and kwargs[0].arg == "timeout" and _is_none(kwargs[0].value):
            lines.append(node.lineno)
    return lines


def test_the_detector_flags_unbounded_and_passes_bounded_joins():
    src = (
        "t.join()\n"
        "t.join(None)\n"
        "t.join(timeout=None)\n"
        "t.join(timeout=5.0)\n"
        "t.join(5)\n"
        "', '.join(parts)\n"
    )
    assert _unbounded_joins(src, "<probe>") == [1, 2, 3]


def test_no_test_file_joins_a_thread_without_a_timeout():
    offenders: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        if path.name in PENDING_ELSEWHERE:
            continue
        source = path.read_text(encoding="utf-8")
        if ".join(" not in source:
            continue
        for lineno in _unbounded_joins(source, str(path)):
            offenders.append(f"{path.relative_to(TESTS)}:{lineno}")
    assert offenders == [], (
        "unbounded .join() in tests; use join(timeout=N) then "
        "assert not t.is_alive(): " + ", ".join(offenders)
    )


def test_every_pending_exemption_still_names_a_real_file():
    # A stale entry would silently exempt a file that no longer exists or was renamed.
    missing = [name for name in PENDING_ELSEWHERE if not (TESTS / name).is_file()]
    assert missing == []
