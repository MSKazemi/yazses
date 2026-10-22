"""No autouse fixture in `tests/conftest.py` may make a numbered temp directory per test.

`tmp_path_factory.mktemp()` picks its number by listing the whole session basetemp
(`make_numbered_dir` scans it on every call), and `tmp_path` goes through the same
call. Two autouse fixtures here once did that for every one of ~30,000 tests. Each
test added two entries to basetemp, so each later call listed more of them. The cost
grew with the square of the suite: about 18 ms of setup per test by the end, and most
of a 40-minute run. `--durations` never showed it, because it was spread across
thousands of setups rather than sitting in one slow test.

The fix was a session-scoped `_fresh_dir`, which makes one parent directory once and
then numbers children with a counter. This guard keeps the next autouse fixture from
reintroducing the per-test call. It follows fixture dependencies within the conftest,
so an autouse fixture that requests a per-test helper which requests `tmp_path` is
caught too. A session- or module-scoped fixture may call `mktemp`, since that runs
once per scope rather than once per test.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFTEST = ROOT / "tests" / "conftest.py"

#: Built-in fixtures that create a numbered directory for every test that requests them.
_PER_TEST_TEMP = {"tmp_path", "tmpdir"}


def _fixture_kwargs(func: ast.FunctionDef) -> dict[str, ast.expr] | None:
    """The keyword arguments of `@pytest.fixture(...)`, or None if it is not a fixture."""
    for deco in func.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None)
        if name == "fixture":
            if isinstance(deco, ast.Call):
                return {kw.arg: kw.value for kw in deco.keywords if kw.arg}
            return {}
    return None


def _is_true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _scope(kwargs: dict[str, ast.expr]) -> str:
    node = kwargs.get("scope")
    return node.value if isinstance(node, ast.Constant) else "function"


def _calls_mktemp(func: ast.FunctionDef) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "mktemp"
        for node in ast.walk(func)
    )


def per_test_temp_dirs(source: str) -> dict[str, list[str]]:
    """Map each function-scoped autouse fixture to the chain that makes a temp dir."""
    fixtures: dict[str, tuple[ast.FunctionDef, dict[str, ast.expr]]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef):
            kwargs = _fixture_kwargs(node)
            if kwargs is not None:
                fixtures[node.name] = (node, kwargs)

    def chain(name: str, seen: frozenset[str]) -> list[str] | None:
        func, kwargs = fixtures[name]
        if _scope(kwargs) != "function":
            return None
        if _calls_mktemp(func):
            return [name, "mktemp()"]
        for arg in func.args.args:
            if arg.arg in _PER_TEST_TEMP:
                return [name, arg.arg]
            if arg.arg in fixtures and arg.arg not in seen:
                rest = chain(arg.arg, seen | {arg.arg})
                if rest:
                    return [name, *rest]
        return None

    found = {}
    for name, (_, kwargs) in fixtures.items():
        if _is_true(kwargs.get("autouse")):
            path = chain(name, frozenset({name}))
            if path:
                found[name] = path
    return found


def test_no_autouse_fixture_makes_a_temp_dir_per_test() -> None:
    offenders = per_test_temp_dirs(CONFTEST.read_text(encoding="utf-8"))
    assert not offenders, (
        "These autouse fixtures make a numbered temp dir for every test, which makes "
        "the whole suite's setup cost grow with the square of its size: "
        + "; ".join(" -> ".join(path) for path in offenders.values())
        + ". Use the session-scoped `_fresh_dir(prefix)` instead."
    )


def test_the_conftest_still_has_autouse_fixtures_to_check() -> None:
    source = CONFTEST.read_text(encoding="utf-8")
    autouse = [
        node.name
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef)
        and _is_true((_fixture_kwargs(node) or {}).get("autouse"))
    ]
    assert len(autouse) >= 5, autouse


def test_the_detector_fires_on_each_way_in() -> None:
    planted = '''
import pytest

@pytest.fixture(autouse=True)
def direct(tmp_path):
    pass

@pytest.fixture(autouse=True)
def calls(tmp_path_factory):
    tmp_path_factory.mktemp("x")

@pytest.fixture
def helper(tmpdir):
    pass

@pytest.fixture(autouse=True)
def indirect(monkeypatch, helper):
    pass

@pytest.fixture(scope="session")
def once(tmp_path_factory):
    return tmp_path_factory.mktemp("once")

@pytest.fixture(autouse=True)
def fine(once, monkeypatch):
    pass

@pytest.fixture
def not_autouse(tmp_path):
    pass
'''
    assert per_test_temp_dirs(planted) == {
        "direct": ["direct", "tmp_path"],
        "calls": ["calls", "mktemp()"],
        "indirect": ["indirect", "helper", "tmpdir"],
    }
