"""The bundled `.exe`/`.app` must enter the CLI the way the console script does.

`pyproject.toml` binds `yazses` to `yazses.cli:main`, and `main` does three things
before handing over to Typer. `src/yazses/__main__.py` -- the PyInstaller entry point
for every Windows and macOS bundle -- called `cli.app()` directly, so a bundled user
got none of them:

* `ensure_printable_streams()`. A redirected stdout on Windows is cp1252, which cannot
  encode the arrow, the warning sign or the box rule this CLI prints everywhere.
  Reproduced on the Scoop-installed v2.32.0 binary on a real Windows host:

      yazses doctor  ->  UnicodeEncodeError: 'charmap' codec can't encode
                         character '✗' in position 0

  after most of the report had already printed, so the diagnostic command aborts
  precisely when somebody is redirecting it into an issue.
* `escape_help_sections(app)`. Rich parses `[meeting]` in a help string as a style tag
  and drops it, so twelve commands named a config key without naming its section.
* the `UnsupportedPlatformError` handler, which turns "no backend for this OS" into a
  sentence rather than a traceback.

The shape of the bug is what makes it worth a test: two entry points into one CLI, one
of which is only reachable from a build artifact that no test suite imports. Nothing
about `app()` is wrong to call -- it just is not the entry the project ships.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_MAIN = Path(__file__).resolve().parents[1] / "src" / "yazses" / "__main__.py"


def _run_cli_body() -> ast.FunctionDef:
    tree = ast.parse(_MAIN.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_run_cli":
            return node
    raise AssertionError("__main__.py no longer defines _run_cli")


def _imported_names(fn: ast.FunctionDef) -> set[tuple[str, str]]:
    """(module, imported name) for every `from x import y` inside the function."""
    return {
        (node.module or "", alias.name)
        for node in ast.walk(fn)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def test_the_bundle_enters_through_cli_main() -> None:
    assert ("yazses.cli", "main") in _imported_names(_run_cli_body()), (
        "the bundled CLI must go through yazses.cli:main -- the same entry "
        "pyproject.toml binds the `yazses` console script to"
    )


def test_the_bundle_does_not_call_the_typer_app_directly() -> None:
    """The precise regression: `from yazses.cli import app` inside `_run_cli`.

    It reads as equivalent and skips every fix `main` applies first.
    """
    assert ("yazses.cli", "app") not in _imported_names(_run_cli_body()), (
        "calling cli.app() skips ensure_printable_streams, the Rich help-tag "
        "escaping and the UnsupportedPlatformError handler"
    )


def test_the_console_script_still_points_at_main() -> None:
    """Anchors the other half of the pair -- if `yazses` stopped being `cli:main`,
    the test above would be enforcing agreement with the wrong thing."""
    import tomllib

    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["yazses"] == "yazses.cli:main"


def test_main_is_still_the_one_that_fixes_the_streams() -> None:
    """Guards the guard: routing through `main` is only a fix while `main` does this.

    Read from the source rather than by calling it, because `ensure_printable_streams`
    only changes anything on a stream whose encoding cannot carry the characters --
    which is not the stream a test on Linux has.
    """
    import inspect

    from yazses import cli

    source = inspect.getsource(cli.main)
    for needed in (
        "ensure_printable_streams()",
        "escape_help_sections(app)",
        "UnsupportedPlatformError",
    ):
        assert needed in source, f"cli.main no longer does: {needed}"


def test_streams_are_still_ensured_before_anything_prints() -> None:
    """`ensure_streams()` answers a different question and must not be dropped.

    It is "is there a stream at all" -- the windowed binary has no stdout, and
    `sys.stdout.isatty()` on `None` raises before any encoding matters.
    """
    assert ("yazses.system.wincon", "ensure_streams") in _imported_names(_run_cli_body())


@pytest.mark.parametrize("mode", ["--cli", None])
def test_every_cli_route_goes_through_the_same_helper(mode: str | None) -> None:
    """Both ways into the CLI -- the explicit `--cli` flag and the bare default --
    must land in `_run_cli`, or fixing one leaves the other broken."""
    tree = ast.parse(_MAIN.read_text(encoding="utf-8"))
    main_fn = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    calls = [
        n.func.id
        for n in ast.walk(main_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert calls.count("_run_cli") == 2, (
        f"expected both CLI routes to call _run_cli, found {calls.count('_run_cli')}"
    )
