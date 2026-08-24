"""Every published benchmark number must trace to a stored, provenanced artifact.

`docs/benchmarks.md` opens on the claim that its numbers can be reproduced, and
`paper/benchmark/README.md` documents the commands. Until now the *results* those
commands produce were gitignored, so the artifact behind a published figure lived on
one laptop and nowhere else: no reader could check a per-row number that did not fit
on the page, and no future run could be compared against the one that was published.

Four things are guarded here, each because it has already gone wrong somewhere:

1. **Every archived result carries provenance.** Two did not. `run_all.py` attaches a
   shared block, but a single bench run from the command line -- the documented way to
   re-measure one thing -- wrote through `write_result` without one and overwrote the
   good file. A benchmark with no record of the CPU, the OS and the library versions is
   a number, not a measurement, and latency and RTF are properties of the machine.

2. **No result names a person or a path.** These files are published. The provenance
   block is deliberately machine-descriptive (CPU model, OS, kernel, versions) and must
   stay that way; a home directory or a login name in an artifact is a privacy leak
   that no amount of later editing takes back out of git history.

3. **Every bench script is either archived or listed with a reason.** An unwritten
   judgement is indistinguishable from an oversight. `bench_diarization.py` needs a
   corpus that cannot be committed; that is a decision, and it is recorded here rather
   than shown as an absence.

4. **The subtree is checked, not just the top level.** `paper/results/probes/` holds
   the one-off measurements made on the rented Azure boxes, and the logs those runs
   printed. Those files are the ones most likely to carry a login name, because they
   were written on a machine where the home directory was in every path -- so the
   privacy and provenance checks recurse, and only the *script coverage* check stays
   at the top level, where the harness writes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "paper" / "results"
HARNESS = ROOT / "paper" / "benchmark"

#: Bench scripts with no archived result, and why. A script may only appear here for a
#: reason that a re-run cannot fix -- "we have not run it yet" is not one.
NO_ARCHIVED_RESULT = {
    "bench_throughput.py": (
        "needs a human at the keyboard -- it times a person dictating and the same "
        "person typing the same prompts. There is no result to archive until a study "
        "is run, and a synthetic stand-in would be the guess the instrument exists to "
        "avoid."
    ),
}

#: The provenance keys that make a result a measurement rather than a number.
REQUIRED_PROVENANCE = ("timestamp", "cpu_model", "os", "python", "yazses")

#: Patterns that would mean a person, a home directory or a login leaked into a
#: published artifact.
IDENTIFIERS = (
    re.compile(r"/home/[A-Za-z0-9_.-]+"),
    re.compile(r"/Users/[A-Za-z0-9_.-]+"),
    re.compile(r"[Cc]:\\+Users", re.IGNORECASE),
    re.compile(r"\bmohsen\b", re.IGNORECASE),
    re.compile(r"\bazureuser\b", re.IGNORECASE),
)


def _results() -> list[Path]:
    """Every archived result, including the probe subtree."""
    return sorted(RESULTS.rglob("*.json"))


def _harness_results() -> list[Path]:
    """Only what the committed harness writes.

    The script-coverage check reads these. A probe artifact must not be able to
    satisfy it: `probes/beam-probe.json` would answer for `bench_beam.py` on a stem
    match while proving only that somebody once measured the thing by hand.
    """
    return sorted(RESULTS.glob("*.json"))


def _published_text() -> list[Path]:
    """Every published file a person could read a name out of.

    Two trees, not one. `paper/results/` holds the artifacts and the run logs;
    `paper/benchmark/probes/drivers/` holds the forty-nine shell scripts recovered
    from the rented boxes before they were released. Both were written on a machine
    where the home directory was in every path, both are committed, and git history
    does not forget -- so the same redaction rule has to reach both. Scoping this to
    the results directory was correct right up until the drivers were archived
    beside it, which is the point at which a check stops covering what it claims to.
    """
    trees = (RESULTS, HARNESS / "probes" / "drivers")
    return sorted(
        p for tree in trees for p in tree.rglob("*")
        if p.is_file() and p.suffix in {".json", ".log", ".md", ".txt", ".sh"}
    )


def test_the_archive_is_not_empty() -> None:
    """Guard the guard: every check below iterates, and an empty directory passes
    all of them while proving nothing."""
    found = _results()
    assert len(found) >= 5, f"paper/results/ holds {len(found)} result files: {found}"
    texts = _published_text()
    assert len(texts) > len(found), (
        "the run logs are part of the record and none is archived; "
        f"only {len(texts)} readable files found"
    )


@pytest.mark.parametrize("path", _results(), ids=lambda p: p.name)
def test_every_archived_result_parses(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", _results(), ids=lambda p: p.name)
def test_every_archived_result_names_the_machine_it_came_from(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    prov = data.get("provenance")
    assert isinstance(prov, dict), (
        f"{path.name} has no provenance block. `_common.write_result` stamps one when "
        "the caller does not, so a file without it was written by something that "
        "bypassed the chokepoint -- fix that, do not hand-edit the artifact."
    )
    missing = [k for k in REQUIRED_PROVENANCE if not prov.get(k)]
    assert not missing, f"{path.name} provenance is missing {missing}"


@pytest.mark.parametrize("path", _published_text(), ids=lambda p: p.name)
def test_no_archived_result_names_a_person_or_a_path(path: Path) -> None:
    blob = path.read_text(encoding="utf-8")
    hits = [m.group(0) for pat in IDENTIFIERS for m in [pat.search(blob)] if m]
    # `$HOME` is what the redaction leaves behind and is not an identifier.
    assert not hits, (
        f"{path.name} contains {hits}. These files are published; a login name or a "
        "home directory cannot be taken back out of git history once pushed."
    )


def _norm(name: str) -> str:
    """Fold the two separators apart, so a script name can match its result name.

    Scripts are `snake_case` because they are Python modules; results are `kebab-case`
    because every other one in the archive is (`wer-test-other`, `plausibility-ami-1.2`).
    For a single-word name the two coincide and nothing noticed -- but
    `bench_platform_resolution.py` could never match `platform-resolution.json`, so the
    first multi-word bench script to be added would have been reported as unarchived no
    matter how faithfully its result was committed, and the obvious way out is to rename
    the *result* into an inconsistency.
    """
    return name.replace("_", "-")


def test_every_bench_script_is_archived_or_explained() -> None:
    scripts = {p.name for p in HARNESS.glob("bench_*.py")}
    assert scripts, "no bench_*.py found -- the matcher is broken"
    stems = {_norm(p.stem) for p in _harness_results()}

    unexplained = []
    for script in sorted(scripts):
        if script in NO_ARCHIVED_RESULT:
            continue
        key = _norm(script[len("bench_"):-len(".py")])
        # Results are named after their script, optionally with a variant suffix:
        # `beam-test-other`, `throughput_dictation`, `plausibility-ami-1.2`.
        if not any(s == key or s.startswith(f"{key}-") for s in stems):
            unexplained.append(script)

    assert not unexplained, (
        "these bench scripts have no archived result and no recorded reason: "
        f"{unexplained}. Either run them and commit the result, or add an entry to "
        "NO_ARCHIVED_RESULT saying what a re-run cannot fix."
    )


def test_the_exemption_list_does_not_outlive_its_scripts() -> None:
    """A reason recorded for a script that no longer exists is stale documentation
    that reads as a live decision."""
    scripts = {p.name for p in HARNESS.glob("bench_*.py")}
    stale = sorted(set(NO_ARCHIVED_RESULT) - scripts)
    assert not stale, f"NO_ARCHIVED_RESULT names scripts that are gone: {stale}"


def test_a_multi_word_script_name_matches_its_hyphenated_result() -> None:
    """The bridge itself, asserted rather than left implicit in a passing suite.

    Both spellings must reach the same key, and a *different* script must still not --
    otherwise folding the separators would make the guard match everything.
    """
    assert _norm("platform_resolution") == _norm("platform-resolution")
    assert _norm("platform_resolution") != _norm("plausibility")


def test_the_separator_fold_does_not_merge_two_real_scripts() -> None:
    """If two bench scripts ever collided under the fold, one could satisfy the other's
    archive requirement and a missing result would go unreported."""
    keys = [_norm(p.name[len("bench_"):-len(".py")]) for p in HARNESS.glob("bench_*.py")]
    assert len(keys) == len(set(keys)), f"two bench scripts fold to one key: {sorted(keys)}"
