"""The changelog must survive concurrent sessions merging into it.

Two sessions each added entries under their own `## [Unreleased]` heading, and the
merge kept **both** — leaving the file with two Unreleased sections about 170 lines
apart. Nothing caught it: there is no changelog test, and no script renames
`[Unreleased]` at release time, so the rename is a manual step that would have
retitled the first heading and left ~100 lines of shipped entries sitting under a
stray "Unreleased" heading *inside* a released changelog.

These are cheap structural checks. They deliberately say nothing about whether an
entry is good — that is a human judgement and stays one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"

#: `## [1.2.3] - 2026-08-13` or `## [Unreleased]`
VERSION_HEADING = re.compile(r"^## \[([^\]]+)\](?:\s+-\s+(\S+))?\s*$", re.M)


@pytest.fixture(scope="module")
def text() -> str:
    return CHANGELOG.read_text(encoding="utf-8")


def test_exactly_one_unreleased_section(text: str) -> None:
    """The regression this file was written for."""
    count = len(re.findall(r"^## \[Unreleased\]\s*$", text, re.M))
    assert count == 1, (
        f"found {count} '## [Unreleased]' headings; a merge probably kept both sides. "
        "Release renames the first one and orphans everything under the others."
    )


def test_unreleased_comes_first(text: str) -> None:
    """Newest first — an Unreleased section below a version is unreachable by a reader."""
    headings = [m.group(1) for m in VERSION_HEADING.finditer(text)]
    assert headings, "no version headings at all"
    assert headings[0] == "Unreleased", (
        f"first section is {headings[0]!r}; Unreleased must lead the file"
    )
    assert "Unreleased" not in headings[1:], "an Unreleased section appears below a release"


def test_released_versions_are_unique_and_dated(text: str) -> None:
    """A duplicated or undated release heading is the same merge accident, one level down."""
    releases = [(m.group(1), m.group(2)) for m in VERSION_HEADING.finditer(text)]
    versions = [v for v, _ in releases if v != "Unreleased"]

    duplicates = {v for v in versions if versions.count(v) > 1}
    assert not duplicates, f"duplicated release headings: {sorted(duplicates)}"

    undated = [v for v, date in releases if v != "Unreleased" and not date]
    assert not undated, f"release headings with no date: {undated}"


def test_every_entry_sits_under_a_version(text: str) -> None:
    """An `###` entry above the first `##` belongs to no release and ships nowhere."""
    first_version = VERSION_HEADING.search(text)
    assert first_version is not None
    preamble = text[: first_version.start()]
    orphans = re.findall(r"^### .*$", preamble, re.M)
    assert not orphans, f"entries above the first version heading: {orphans}"
