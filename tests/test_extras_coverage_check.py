"""The two-environment coverage check for the heavy extras.

`tests/test_shipped_backends.py` cannot be exercised by one environment. Two of its
tests are exact opposites -- one skips unless `import resemblyzer` works (which needs
`setuptools<81`), the other skips unless it fails -- so `heavy-extras.yml` runs the
file twice and asserts nothing was skipped in *both*. The old gate asserted nothing
was skipped at all, which no run could satisfy; it went unnoticed for three releases
because the job died two steps earlier for an unrelated reason.

`scripts/check_extras_coverage.py` is that comparison. It is a script rather than
shell inside the workflow for the reason this module exists: it can be run here,
against reports built in the test, instead of once a week on a runner.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_extras_coverage.py"

_spec = importlib.util.spec_from_file_location("check_extras_coverage", SCRIPT)
assert _spec and _spec.loader
coverage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(coverage)


def _report(path: pathlib.Path, cases: dict[str, bool], *, classname: str = "t") -> pathlib.Path:
    """Write a pytest-shaped JUnit report. ``cases`` maps test name -> was it skipped."""
    body = "".join(
        f'<testcase classname="{classname}" name="{name}">'
        + ('<skipped type="pytest.skip" message="x"/>' if skipped else "")
        + "</testcase>"
        for name, skipped in cases.items()
    )
    path.write_text(
        f'<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" '
        f'tests="{len(cases)}">{body}</testsuite></testsuites>',
        encoding="utf-8",
    )
    return path


def _pair(tmp_path: pathlib.Path, first: dict[str, bool], second: dict[str, bool]):
    a = coverage.read_report(_report(tmp_path / "a.xml", first))
    b = coverage.read_report(_report(tmp_path / "b.xml", second))
    return [("a.xml", *a), ("b.xml", *b)]


def _many(skip: str | None = None, count: int = 30) -> dict[str, bool]:
    return {f"test_{i}": (f"test_{i}" == skip) for i in range(count)}


def test_opposite_skips_are_exactly_what_is_allowed(tmp_path: pathlib.Path) -> None:
    """The real shape: each environment skips the test written for the other one.

    This is the case the old gate rejected, and it is not a defect -- it is the
    design of the file being tested.
    """
    assert coverage.check(_pair(tmp_path, _many(skip="test_1"), _many(skip="test_2"))) == []


def test_a_test_skipped_in_both_environments_is_reported(tmp_path: pathlib.Path) -> None:
    problems = coverage.check(_pair(tmp_path, _many(skip="test_1"), _many(skip="test_1")))
    assert problems, "a test that ran nowhere was accepted"
    assert "test_1" in problems[0]


def test_neither_run_skipping_anything_is_fine(tmp_path: pathlib.Path) -> None:
    assert coverage.check(_pair(tmp_path, _many(), _many())) == []


def test_a_near_empty_report_fails_rather_than_comparing_nothing(
    tmp_path: pathlib.Path,
) -> None:
    """Two empty sets have an empty intersection, so without this the check passes
    most loudly exactly when it has learnt the least."""
    problems = coverage.check(_pair(tmp_path, {"test_only": False}, _many()))
    assert problems and "only 1 tests" in problems[0]


def test_runs_that_collected_different_tests_are_refused(tmp_path: pathlib.Path) -> None:
    """If the two runs did not collect the same file, 'skipped in both' compares two
    unrelated populations and the answer means nothing."""
    first = _many()
    second = dict(_many())
    second.pop("test_5")
    second["test_new"] = False
    problems = coverage.check(_pair(tmp_path, first, second))
    assert problems and "different tests" in problems[0]
    assert "test_5" in problems[0] and "test_new" in problems[0]


def test_a_parametrised_id_containing_spaces_survives(tmp_path: pathlib.Path) -> None:
    """The regression this file was written for.

    The first version of this check scanned pytest's terminal output with
    ``awk '$2 == "SKIPPED"'``. Four real tests in `test_shipped_backends.py` are
    parametrised on `huggingface_hub` error messages, whose ids contain spaces and
    full stops, so the verdict was not the second field and they were dropped without
    a word: 32 of 36 counted, and a green result. Reading the XML attribute means
    there is nothing to tokenise.
    """
    spacey = "test_a_raised_access_failure[GatedRepoError-403 Client Error. Access denied.]"
    cases = _many()
    cases[spacey] = True
    every, skipped = coverage.read_report(_report(tmp_path / "s.xml", cases))
    assert f"t::{spacey}" in every
    assert f"t::{spacey}" in skipped


def test_the_same_report_twice_fails_instead_of_crashing(tmp_path: pathlib.Path) -> None:
    """Found by controlling the script against itself: the reports were held in a dict
    keyed by filename, so a repeated path collapsed to one entry and the comparison
    raised IndexError instead of answering."""
    path = _report(tmp_path / "same.xml", _many(skip="test_3"))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path), str(path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "::error::" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("argv", [[], ["one.xml"], ["a.xml", "b.xml", "c.xml"]])
def test_the_wrong_number_of_reports_is_refused(argv: list[str], tmp_path: pathlib.Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, cwd=tmp_path
    )
    assert result.returncode == 2


def test_the_workflow_calls_this_script(tmp_path: pathlib.Path) -> None:
    """The vacuity anchor. A checker nothing runs is not a gate."""
    workflow = (ROOT / ".github/workflows/heavy-extras.yml").read_text(encoding="utf-8")
    assert "scripts/check_extras_coverage.py" in workflow, (
        "heavy-extras.yml no longer runs the coverage check, so this module is "
        "testing a script with no caller"
    )
    assert workflow.count("--junit-xml") == 2, (
        "the check compares two JUnit reports; the workflow must produce exactly two"
    )


def test_the_message_explains_itself() -> None:
    """The failure lands in a weekly run nobody was watching, so it has to say what to
    do without the reader opening this file."""
    text = textwrap.dedent(coverage.__doc__ or "")
    assert "skipped in *both*" in text
    assert "setuptools<81" in text
