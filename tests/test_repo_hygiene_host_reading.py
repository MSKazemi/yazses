"""No test may derive an expected value from the machine it runs on.

**This cost a release.** `test_the_account_name_is_still_scrubbed_from_ordinary_strings`
called `getpass.getuser()`, built a string containing the result, and asserted
`redact_config` removed it — guarding only against a name shorter than three
characters. A GitHub runner's account is `runner`: six characters, and listed in
`report.py`'s own `_GENERIC_ACCOUNTS`, because a machine called "runner" is not
identified by the word. The module therefore *deliberately* does not redact it.

Green on the author's laptop, red on every CI leg. It was the sole failure in
`release.yml`'s `test` job, which gates `publish-pypi`, `build-deb` and
`release-linux` — all three ran 0 s. v2.28.0 shipped as a half-release: `.exe` and
`.dmg` published, PyPI and `.deb` never.

It is the fourth occurrence of this shape in this repo, so it stops being a lesson
and becomes a check.

## The rule

Host facts are inputs to **patch**, never values to **assert against**. Patch
`getpass.getuser` to a fixed name and the test means the same thing everywhere — and
it *runs* everywhere, which a `skip` guard does not: a test that skips on CI protects
nothing on CI, which is the machine you least control.

## What is allowed

A call inside a `monkeypatch.setattr(...)` line is the fix, not the fault. So is
`os.environ.setdefault(...)`, which *sets* the environment rather than reading it —
`QT_QPA_PLATFORM=offscreen` is how the Qt tests run headless.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent

#: Calls whose value is a property of the machine, not of the code under test.
#: `sys.platform` is deliberately absent: a test that branches on the OS is normal
#: and correct here, since the package has per-OS backends.
_HOST_CALLS = {
    "getuser": "getpass.getuser() — the CI account is `runner`, and it is a GENERIC name the code deliberately leaves alone",
    "gethostname": "socket.gethostname() — differs on every runner",
    "getlogin": "os.getlogin() — fails outright on a runner with no controlling tty",
}

#: This file names the calls in its own prose and allow-list; scanning it would be
#: a guard reporting itself.
_SELF = Path(__file__).name


def _offending_calls(tree: ast.AST, source: str) -> list[str]:
    """Host-reading calls that are not part of a patch. Returns their descriptions."""
    lines = source.splitlines()
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _HOST_CALLS:
            continue
        # A call on a `monkeypatch.setattr(...)`/`mocker.patch(...)` line is the fix.
        # Checked by line text because the call sits inside the patch's arguments,
        # and walking outward from an arbitrary node is more fragile than reading
        # the statement it lives on.
        row = (node.lineno or 1) - 1
        context = "\n".join(lines[max(0, row - 1): row + 2])
        if "setattr" in context or "patch" in context or "monkeypatch" in context:
            continue
        found.append(f"line {node.lineno}: {_HOST_CALLS[name]}")
    return found


def test_the_scan_sees_the_test_suite() -> None:
    """A guard that scans an empty set passes on everything — a shape this repo has
    been bitten by three times in one day."""
    assert len(list(TESTS.glob("test_*.py"))) > 100


def test_no_test_asserts_against_a_value_read_from_the_host() -> None:
    bad: dict[str, list[str]] = {}
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == _SELF:
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:  # pragma: no cover - fails loudly elsewhere
            continue
        if hits := _offending_calls(tree, source):
            bad[path.name] = hits
    assert not bad, (
        "these read the machine instead of patching it, which is green locally and "
        "red on CI:\n"
        + "\n".join(f"  {f}\n    " + "\n    ".join(v) for f, v in sorted(bad.items()))
        + "\n\nPatch the value (monkeypatch.setattr(getpass, 'getuser', lambda: 'ada')) "
        "so the test means the same thing everywhere — and still runs on CI, which a "
        "skip guard does not."
    )


@pytest.mark.parametrize(
    "snippet,expected",
    [
        ("import getpass\ndef test_x():\n    assert getpass.getuser() in s\n", 1),
        ("def test_x(monkeypatch):\n    monkeypatch.setattr(getpass, 'getuser', lambda: 'ada')\n", 0),
        ("def test_x(mocker):\n    mocker.patch('getpass.getuser', return_value='ada')\n", 0),
        ("import socket\ndef test_x():\n    assert socket.gethostname() == 'x'\n", 1),
        ("def test_x():\n    assert 1 == 1\n", 0),
    ],
)
def test_the_check_catches_the_shape_and_allows_the_fix(snippet: str, expected: int) -> None:
    """Only worth having if it can fail — and only keepable if it does not cry wolf."""
    assert len(_offending_calls(ast.parse(snippet), snippet)) == expected
