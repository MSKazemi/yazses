"""The Persian candidates that were *not* measured stay on the record (#514).

FA-05's acceptance list says "failures/unsupported combinations are recorded, not
omitted". A skip that happens before conversion leaves no result file, so every
guard that walks `paper/results/*.json` is structurally blind to it: drop the row
from the page and the manifest and nothing that reads the archive notices. These
checks read the hand-written `NOT_MEASURED` list instead, and hold the page and the
manifest to it in both places.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.benchmark_deps import load

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "benchmarks.md"
MANIFEST = ROOT / "paper" / "results" / "MANIFEST.md"

COMMENT_URL = re.compile(
    r"^https://github\.com/MSKazemi/yazses/issues/514#issuecomment-\d+$"
)


@pytest.fixture(scope="module")
def gen():
    return load("make_results_index", "make_results_index.py")


def test_the_list_is_not_empty(gen) -> None:
    """Guard the guard: every check below iterates and passes on an empty list."""
    assert len(gen.NOT_MEASURED) >= 3


def test_every_entry_cites_the_comment_its_numbers_come_from(gen) -> None:
    """No artifact backs these rows, so the issue comment is the only citation."""
    bad = [n["candidate"] for n in gen.NOT_MEASURED if not COMMENT_URL.match(n["source"])]
    assert not bad, f"these entries cite no #514 comment: {bad}"


def test_the_memory_gated_skip_keeps_its_numbers(gen) -> None:
    """The skip is evidence only with the footprint and the host limit attached."""
    skip = next(n for n in gen.NOT_MEASURED if "nezamisafa" in n["candidate"])
    assert "SKIP" in skip["disposition"]
    for figure in ("6.17 GB", "6.2 GB", "4.80", "5.15"):
        assert figure in skip["reason"], f"the nezamisafa skip lost {figure!r}"


def test_the_manifest_renders_the_section(gen) -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    assert "## Recorded without an artifact" in text
    for n in gen.NOT_MEASURED:
        assert n["source"] in text, f"MANIFEST.md omits {n['candidate']}"


def test_the_benchmarks_page_records_the_same_candidates(gen) -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "Recorded, not measured" in text
    for n in gen.NOT_MEASURED:
        assert n["source"] in text, (
            f"docs/benchmarks.md no longer records {n['candidate']}; #514 asks for "
            "skips and exclusions to be recorded, not omitted"
        )
    for figure in ("6.17 GB", "6.2 GB", "4.80–5.15 GB"):
        assert figure in text, f"the page's nezamisafa row lost {figure!r}"
