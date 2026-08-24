"""`paper/results/MANIFEST.md` must describe every archived artifact, and only those.

The archive is forty-odd JSON files written across two months, three machines and two
dozen scripts. A reader checking a figure on `docs/benchmarks.md` needs to know which
file backs it and whether two numbers were taken on the same machine; both are in the
files and neither is findable without opening them all.

Two checks, and the second is the one that matters. Re-running the generator and
diffing catches a manifest that was edited by hand or left stale -- but it is computed
by the same code that wrote the file, so it agrees with itself by construction and
would pass a generator that silently skipped an entire subtree. So the file names are
also checked against the **directory**, in both directions. That is the shape of the
mistake this repository has hit before: an in-sync check on a generated file cannot
notice an omission, because it compares the file to its own generator.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.benchmark_deps import load

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "paper" / "results"
MANIFEST = RESULTS / "MANIFEST.md"


@pytest.fixture(scope="module")
def gen():
    return load("make_results_index", "make_results_index.py")


def _archived() -> list[str]:
    return sorted(p.relative_to(RESULTS).as_posix() for p in RESULTS.rglob("*.json"))


def test_the_archive_and_the_manifest_both_exist() -> None:
    """Guard the guard: an empty archive makes every check below vacuous."""
    assert MANIFEST.is_file(), "paper/results/MANIFEST.md is missing; regenerate it"
    assert len(_archived()) >= 10, f"only {len(_archived())} archived results found"


@pytest.mark.parametrize("name", _archived())
def test_every_archived_result_is_in_the_manifest(name: str) -> None:
    """Read from the directory, not from the generator.

    This is what a re-run-and-diff cannot do. `make_results_index.py` buckets files by
    their top-level directory; a new subtree that matched no bucket would be dropped
    from the table, and the generated file would still equal what the generator
    produces.
    """
    assert f"`{name}`" in MANIFEST.read_text(encoding="utf-8"), (
        f"{name} is archived under paper/results/ and MANIFEST.md never names it. "
        "Regenerate with `uv run python paper/benchmark/make_results_index.py`; if it "
        "is still absent afterwards, the generator has a bucket that does not cover it."
    )


def test_the_manifest_names_no_result_that_is_gone() -> None:
    """The other direction. A row for a deleted artifact reads as a citable file."""
    import re

    named = set(re.findall(r"`([A-Za-z0-9_./-]+\.json)`", MANIFEST.read_text(encoding="utf-8")))
    missing = sorted(named - set(_archived()))
    assert not missing, f"MANIFEST.md names results that are not in paper/results/: {missing}"


def test_the_manifest_is_not_stale(gen) -> None:
    """Regenerating must be a no-op. Catches a hand edit and a forgotten re-run."""
    assert MANIFEST.read_text(encoding="utf-8") == gen.render(gen.rows()), (
        "paper/results/MANIFEST.md is out of date. Run "
        "`uv run python paper/benchmark/make_results_index.py`."
    )


def test_every_row_names_the_machine_or_the_script(gen) -> None:
    """A row with neither is a filename in a table, which is what the archive already
    was. Probe rows carry the producing script; harness rows carry the machine."""
    thin = [r["path"] for r in gen.rows() if not r["machine"].strip("? ") and not r["produced_by"]]
    assert not thin, f"these artifacts describe neither their machine nor their script: {thin}"


def test_a_cpu_name_is_not_mangled(gen) -> None:
    """`.title()` on a name that was not shouting turns `13th Gen` into `13Th Gen`.
    Cosmetic, but the manifest exists to be read, and a reader who spots one mangled
    field stops trusting the rest of the table."""
    machines = {r["machine"] for r in gen.rows()}
    assert not [m for m in machines if "Th Gen" in m or "(R)" in m or "(TM)" in m], machines
