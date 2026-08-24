"""`paper/results/README.md` must account for every artifact in that directory.

`MANIFEST.md` beside it is generated and therefore cannot drift. The README's tables
are hand-written, and a hand-written set over a directory that grows is the defect
rather than the documentation: the table had fallen three artifact kinds behind
(`platform-resolution.json` and both families of `*-significance.json`) within a day
of them being committed, while claiming to say what is here.

The check runs in both directions. A file nobody documented reads as a stray; a row
for a file that is gone reads as a measurement that still exists. Neither is visible
by reading the page, which is the whole reason it drifted.

Patterns are globs because several artifacts are per-split (`beam-test-clean.json`,
`beam-test-other.json`) and a table with one row per split would be the same
hand-maintained set one level down.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "paper" / "results"
README = RESULTS / "README.md"

#: First cell of a markdown table row, when it is a backticked `*.json` name or glob.
_ROW = re.compile(r"^\|\s*`([A-Za-z0-9_.*-]+\.json)`\s*\|")


def _documented() -> list[str]:
    return sorted({
        m.group(1)
        for line in README.read_text(encoding="utf-8").splitlines()
        if (m := _ROW.match(line))
    })


def _artifacts() -> list[str]:
    """Top level only. `probes/` is a separate archive with its own README, and its
    files are deliberately not enumerated -- they are exploratory and numerous."""
    return sorted(p.name for p in RESULTS.glob("*.json"))


def test_both_sides_of_this_check_are_non_empty() -> None:
    """Guard the guard. An unparseable README or an empty directory makes every
    parametrized case below collect nothing and the file passes green."""
    assert README.is_file()
    assert len(_artifacts()) >= 10, f"only found {_artifacts()}"
    assert len(_documented()) >= 8, (
        f"parsed only {_documented()} out of the README -- if the table format "
        "changed, this check stopped reading it rather than started failing."
    )


@pytest.mark.parametrize("artifact", _artifacts())
def test_every_archived_artifact_is_documented(artifact: str) -> None:
    patterns = _documented()
    assert any(fnmatch.fnmatch(artifact, p) for p in patterns), (
        f"paper/results/{artifact} is committed and paper/results/README.md never "
        f"mentions it. Add a row saying what it measures and which script wrote it. "
        f"The README documents {patterns}."
    )


@pytest.mark.parametrize("pattern", _documented())
def test_every_documented_pattern_matches_something(pattern: str) -> None:
    files = _artifacts()
    assert any(fnmatch.fnmatch(f, pattern) for f in files), (
        f"paper/results/README.md has a row for `{pattern}` and no file matches it. "
        "A row for an artifact that is gone reads as a measurement you can still go "
        "and check."
    )


def test_a_glob_that_matched_nothing_would_be_caught() -> None:
    """The reverse check is only worth anything if a stale pattern actually fails
    it. Prove the matcher on a name of the shape the table uses."""
    assert not any(fnmatch.fnmatch(f, "wer-test-deleted.json") for f in _artifacts())
