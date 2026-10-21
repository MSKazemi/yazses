"""A deeply nested TOML value must not crash the loaders that promise they are total.

`load_config_checked` says there is no input that makes it raise (issue #52, restated as
the oracle of `fuzz/fuzz_config.py`). It catches `TOMLDecodeError`, `OSError` and
`ValueError` from `tomlio.read` -- and `tomllib` has a fourth way out. Its parser is
recursive descent with no depth limit, so a value nested past the interpreter's
recursion limit raises `RecursionError`, which is a `RuntimeError` and none of the three:

    x = [[[[ ... 5,000 levels ... ]]]]

was enough to take `load_config_checked` down on CPython 3.14.7. A file like that is
not something anyone types, but the contract is about every file, and an editor
plugin or a script that loops while appending brackets can produce one. The macros
and style-rules loaders catch `TOMLDecodeError` too and had the same hole.

`yazses.tomlio` now reports nesting it cannot parse as a `TOMLDecodeError`, the error
every caller already handles, so the file is "could not be read; using defaults" like
any other unparseable one. These tests hold the loaders, not `tomlio`, because the
contract belongs to them.
"""

from __future__ import annotations

import pathlib
import tomllib

import pytest

from yazses import tomlio
from yazses.commands.macros import load_macros
from yazses.config import load_config_checked
from yazses.styleguard.loader import load_rules_file

#: Far past the default recursion limit (1000), so the input reaches the limit on any
#: interpreter rather than only on one with a small stack.
DEPTH = 5000

NESTED = {
    "array": "x = " + "[" * DEPTH + "]" * DEPTH + "\n",
    "inline-table": "x = " + "{a = " * DEPTH + "1" + "}" * DEPTH + "\n",
}


@pytest.mark.parametrize("shape", sorted(NESTED))
def test_the_config_loader_reports_deep_nesting_instead_of_raising(
    shape: str, tmp_path: pathlib.Path
) -> None:
    path = tmp_path / "config.toml"
    # A real setting before the bad line: the whole document is unparseable, so it is
    # lost too, and the loader must say so rather than pretend the file was empty.
    path.write_text("[stt]\nmodel = 'small.en'\n" + NESTED[shape], encoding="utf-8")

    loaded = load_config_checked(path)

    assert loaded.problems, "an unparseable file was loaded without a problem"
    assert "could not be read" in str(loaded.problems[0])
    assert loaded.config.stt.model != "small.en"


@pytest.mark.parametrize("shape", sorted(NESTED))
def test_the_macros_loader_reports_deep_nesting_instead_of_raising(
    shape: str, tmp_path: pathlib.Path
) -> None:
    path = tmp_path / "macros.toml"
    path.write_text(NESTED[shape], encoding="utf-8")
    assert len(load_macros(path)) == 0


@pytest.mark.parametrize("shape", sorted(NESTED))
def test_the_style_rules_loader_reports_deep_nesting_instead_of_raising(
    shape: str, tmp_path: pathlib.Path
) -> None:
    path = tmp_path / "rules.toml"
    path.write_text(NESTED[shape], encoding="utf-8")
    assert load_rules_file(path) == []


@pytest.mark.parametrize("shape", sorted(NESTED))
def test_tomlio_raises_the_error_its_callers_catch(shape: str, tmp_path: pathlib.Path) -> None:
    """The mechanism, pinned so a later refactor of `tomlio` cannot reopen the hole for
    the callers that catch only `TOMLDecodeError` (the macros loader does)."""
    with pytest.raises(tomllib.TOMLDecodeError, match="nested too deeply"):
        tomlio.loads(NESTED[shape])
    path = tmp_path / "x.toml"
    path.write_text(NESTED[shape], encoding="utf-8")
    with pytest.raises(tomllib.TOMLDecodeError, match="nested too deeply"):
        tomlio.read(path)


def test_ordinary_nesting_still_parses() -> None:
    """Non-vacuity: the fix must refuse only what `tomllib` cannot parse. Twenty levels
    is deeper than any real config and must come back as data."""
    data = tomlio.loads("x = " + "[" * 20 + "1" + "]" * 20 + "\n")
    value = data["x"]
    for _ in range(19):
        value = value[0]
    assert value == [1]
