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


# --------------------------------------------------------------------------------
# An analysis is not a measurement, and the manifest must not say it is.
# --------------------------------------------------------------------------------
#
# `_describe` matched by *prefix* over `MEASURES`, so every `*-significance*.json` --
# seven of the twenty-five harness artifacts -- was described as the grid it re-reads:
# "WER and RTF across `[stt] beam_size`". A reader counting rows would have concluded
# the beam grid was measured three times per split when it was measured once and
# bootstrapped twice, and `paper/results/README.md` already carries a paragraph warning
# about this exact confusion, written after it happened once by hand.
#
# Derived from the directory, not from a list of the seven: the next analysis suffix
# added is covered the day the file lands.


def _analysis_artifacts() -> list[str]:
    return sorted(
        p.name for p in RESULTS.glob("*.json")
        if any(f"-{a}" in p.stem for a in ("significance",))
    )


def test_there_are_analysis_artifacts_to_check() -> None:
    """Guard the guard: the check below iterates and passes on an empty archive."""
    found = _analysis_artifacts()
    assert len(found) >= 5, f"only {len(found)} analysis artifacts found: {found}"


@pytest.mark.parametrize("name", _analysis_artifacts())
def test_an_analysis_is_not_described_as_a_measurement(gen, name: str) -> None:
    described = gen._describe(name)
    assert "bootstrap" in described, (
        f"{name} is a significance analysis of another file, and the manifest "
        f"describes it as {described!r} -- the description of the grid it re-reads. "
        "Two different files claiming the same measurement is how a reader "
        "double-counts the evidence."
    )


def test_a_measurement_is_still_described_as_one(gen) -> None:
    """The other direction: the analysis rule must not swallow the grid itself.

    `beam-test-clean.json` and `beam-test-clean-significance.json` differ by a suffix,
    and a substring test written slightly wrong labels both as bootstraps -- which
    would lose the measurement rather than the analysis, the worse of the two.
    """
    assert "bootstrap" not in gen._describe("beam-test-clean.json")
    assert "beam_size" in gen._describe("beam-test-clean.json")


def test_every_harness_row_carries_a_description(gen) -> None:
    """A blank `Measures` cell is an unlabelled number.

    `platform-resolution.json` had one for as long as it existed: `MEASURES` is keyed
    on the script stem and nobody added `platform` when the bench was written, so the
    manifest listed the artifact and said nothing about it.
    """
    blank = [
        p.name for p in RESULTS.glob("*.json") if not gen._describe(p.name)
    ]
    assert not blank, (
        f"{blank} appear in MANIFEST.md with an empty Measures column. Add the script "
        "stem to make_results_index.MEASURES; listing a number without saying what it "
        "measures is the omission the manifest exists to close."
    )
