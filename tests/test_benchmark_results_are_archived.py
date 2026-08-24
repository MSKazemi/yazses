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
import sys
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


# --------------------------------------------------------------------------------
# 5. Every new result records the command line that produced it.
# --------------------------------------------------------------------------------
#
# The archive opened on the claim that a figure can be re-derived from the harness,
# and recorded, for all eighty-three files, the *script* and never its arguments. The
# arguments are the measurement: `bench_wer.py` writes `wer.json` for `200 test-clean`
# and `500 test-other` alike, `bench_beam.py` writes `beam-test-clean.json` for the
# `base.en` grid and for the `tiny.en` grid whose disagreement decided ADR-v2-073, and
# `bench_diarization.py` writes one filename with and without `--max-speakers 4` -- the
# difference the AMI table turns on. "Reproduce it from the harness" was an instruction
# that could not be followed.
#
# Guarded in three parts, because each fails differently: the chokepoint stamps it, it
# stamps it on the sweep path too, and what it stamps carries no home directory.

#: Results taken before this predate the field and are exempt. A single constant with
#: a stated meaning, and one that self-heals: re-running any of those benchmarks fills
#: the field in and moves the artifact across the line. Not a hand-written list of the
#: eighty-three exempt files -- a list is only complete on the day it is written, and
#: its omissions are invisible, which is the failure this whole module exists to catch.
ARGV_STAMPED_FROM = "2026-08-24T04:00:00Z"


@pytest.fixture(scope="module")
def common():
    from tests.benchmark_deps import load

    return load("_common", "_common.py")


def test_the_chokepoint_stamps_the_command(common, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(common, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["paper/benchmark/bench_beam.py", "--grid=tiny.en:1,2,5"])
    path = common.write_result("argv-probe", {"result": {}})
    prov = json.loads(path.read_text(encoding="utf-8"))["provenance"]
    assert prov["argv"] == "paper/benchmark/bench_beam.py --grid=tiny.en:1,2,5"


def test_the_sweep_path_is_stamped_too(common, tmp_path, monkeypatch) -> None:
    """`run_all.py` attaches a shared provenance block, and the early return that
    honoured it skipped the one field that is *not* shared across a sweep. Stamping
    only the branch that builds a block would have left every sweep-written artifact
    -- which is most of the archive -- without the field, and passed the test above."""
    monkeypatch.setattr(common, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["paper/benchmark/run_all.py"])
    shared = {"timestamp": "2026-08-24T05:00:00Z", "cpu_model": "x", "os": "y",
              "python": "3.12.0", "yazses": "2.29.0"}
    path = common.write_result("argv-sweep", {"provenance": dict(shared), "result": {}})
    prov = json.loads(path.read_text(encoding="utf-8"))["provenance"]
    assert prov["argv"] == "paper/benchmark/run_all.py"
    # and the shared half is untouched -- the block says which machine, and this must
    # not become a second thing that overwrites it.
    assert prov["timestamp"] == shared["timestamp"]


def test_a_caller_that_recorded_its_own_command_keeps_it(common, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(common, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["paper/benchmark/run_all.py"])
    prov_in = {"timestamp": "t", "argv": "something more precise"}
    path = common.write_result("argv-keep", {"provenance": prov_in, "result": {}})
    prov = json.loads(path.read_text(encoding="utf-8"))["provenance"]
    assert prov["argv"] == "something more precise"


@pytest.mark.parametrize(
    "raw",
    [
        "bench_diarization.py /home/azureuser/ami16_corpus out.json",
        "bench_wer.py /Users/mohsen/data 200",
    ],
)
def test_the_recorded_command_carries_no_home_directory(common, raw: str) -> None:
    """The argv is the one field written from a *path the operator typed*, so it is the
    likeliest new source of the leak check 2 above exists to catch -- and it would have
    arrived through a door that check watches but this module's authors had not yet
    pointed anything at."""
    out = common._redact(raw)
    hits = [m.group(0) for pat in IDENTIFIERS for m in [pat.search(out)] if m]
    assert not hits, f"_redact left {hits} in {out!r}"
    assert "$HOME" in out, f"the path was dropped rather than redacted: {out!r}"


@pytest.mark.parametrize("path", _results(), ids=lambda p: p.name)
def test_every_result_taken_since_the_cutover_records_its_command(path: Path) -> None:
    prov = json.loads(path.read_text(encoding="utf-8")).get("provenance") or {}
    when = prov.get("timestamp", "")
    if not when or when < ARGV_STAMPED_FROM:
        pytest.skip(f"taken {when or 'at an unrecorded time'}; predates the field")
    assert prov.get("argv"), (
        f"{path.name} was written after the command line became part of provenance and "
        "carries none. It was produced by something that bypassed "
        "`_common.write_result`, which is the only place that stamps it."
    )


# --------------------------------------------------------------------------------
# 6. Which utterances were scored, not merely how many.
# --------------------------------------------------------------------------------
#
# Every artifact recorded `n_utterances: 200` and nothing identifying the 200.
# `librispeech_subset` is deterministic given the corpus, but `_entry` returns `None`
# for an utterance whose `.flac` is absent and the round-robin simply carries on --
# so a host with a partially extracted corpus scores a *different* set and still
# reports 200. These numbers were taken on a laptop, two rented x86 boxes and three CI
# runners, and "WER is reproducible across CPUs" was concluded from exactly that kind
# of cross-host comparison.
#
# It is now checkable, and was checked: all three Linux hosts return
# `08c500680ad493e4` for 200 stratified `test-clean` utterances, with the same first
# and last id, so that conclusion stands. `test-other` exists on only one of them,
# which is why every `test-other` number in the archive comes from one box.

#: Deliberately later than the field's own commit. A measurement already running on a
#: rented box had imported `_common` hours earlier, so it writes through the version of
#: the module that was loaded then and cannot stamp a field added after it started —
#: copying the new file onto that host mid-run changes nothing, because the import has
#: happened. An artifact that genuinely predates the code must skip this guard rather
#: than be back-filled by hand: a hand-edited provenance block is worth less than an
#: absent one, because it cannot be told apart from a measured one.
CORPUS_STAMPED_FROM = "2026-08-25T00:00:00Z"

#: The digest all three hosts agreed on. Pinned so that a change to the *selection*
#: -- a different stratification, a different sort, a silently truncated corpus --
#: fails here rather than quietly renumbering every WER in `docs/benchmarks.md`.
TEST_CLEAN_200_SHA16 = "08c500680ad493e4"


def test_the_digest_is_order_sensitive(common) -> None:
    """Two runs that score the same utterances in a different order are not the same
    measurement: the subset order is the decode order, and `condition_on_previous_text`
    makes the decode of one utterance depend on what came before it."""
    a = common.subset_digest(["1-1-0001", "1-1-0002"])
    b = common.subset_digest(["1-1-0002", "1-1-0001"])
    assert a != b
    assert a == common.subset_digest(["1-1-0001", "1-1-0002"]), "not stable"


def test_a_dropped_utterance_is_counted_rather_than_hidden(common) -> None:
    """`tried` exceeding the kept count is the signature of an incomplete corpus."""
    entries = [("1-1-0001", None, "a", 1.0), ("1-1-0002", None, "b", 1.0)]
    common._record_subset(entries, 5, "test-clean", stratified=True, tried=4)
    rec = common._LAST_SUBSET
    assert rec["n"] == 2 and rec["requested_n"] == 5
    assert rec["n_missing"] == 2, "two `.flac` files were absent and nothing said so"


def test_a_complete_subset_reports_nothing_missing(common) -> None:
    entries = [("1-1-0001", None, "a", 1.0)]
    common._record_subset(entries, 1, "test-clean", stratified=True, tried=1)
    assert common._LAST_SUBSET["n_missing"] == 0


def test_an_empty_subset_does_not_raise(common) -> None:
    """A missing corpus must fail with `FileNotFoundError` upstream, not an IndexError
    inside the bookkeeping."""
    common._record_subset([], 10, "test-other", stratified=False, tried=0)
    assert common._LAST_SUBSET["n"] == 0
    assert common._LAST_SUBSET["first"] == ""


def test_the_chokepoint_stamps_the_corpus(common, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(common, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(
        common, "_LAST_SUBSET",
        {"dataset": "LibriSpeech test-clean", "n": 200, "sha256_16": "deadbeefdeadbeef"},
    )
    path = common.write_result("x", {"config": {}})
    prov = json.loads(path.read_text(encoding="utf-8"))["provenance"]
    assert prov["corpus"]["sha256_16"] == "deadbeefdeadbeef"


def test_the_sweep_path_is_stamped_with_the_corpus_too(common, tmp_path, monkeypatch) -> None:
    """`run_all.py` attaches a shared provenance block; the corpus is not shared in the
    same way, and stamping only the other branch would leave every sweep-written
    artifact without the one field that says what was scored."""
    monkeypatch.setattr(common, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(common, "_LAST_SUBSET", {"n": 200, "sha256_16": "abc123abc123abc1"})
    path = common.write_result("y", {"provenance": {"timestamp": "z", "argv": "kept"}})
    prov = json.loads(path.read_text(encoding="utf-8"))["provenance"]
    assert prov["corpus"]["sha256_16"] == "abc123abc123abc1"
    assert prov["argv"] == "kept", "filling one field must not overwrite another"


def test_a_caller_that_recorded_its_own_corpus_keeps_it(common, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(common, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(common, "_LAST_SUBSET", {"sha256_16": "new"})
    path = common.write_result("z", {"provenance": {"timestamp": "t", "corpus": {"sha256_16": "old"}}})
    prov = json.loads(path.read_text(encoding="utf-8"))["provenance"]
    assert prov["corpus"]["sha256_16"] == "old"


def test_the_pinned_test_clean_digest_still_describes_the_corpus(common) -> None:
    """Skips where LibriSpeech is absent; fails where it is present and disagrees."""
    try:
        subset = common.librispeech_subset(200, stratified=True, split="test-clean")
    except FileNotFoundError as exc:
        pytest.skip(str(exc).split(".")[0])
    digest = common.subset_digest([e[0] for e in subset])
    assert digest == TEST_CLEAN_200_SHA16, (
        f"200 stratified test-clean utterances now digest to {digest}, not "
        f"{TEST_CLEAN_200_SHA16}. Either the corpus on this host is incomplete or the "
        "selection changed — in both cases every WER in docs/benchmarks.md was measured "
        "on a different set than a fresh run would use."
    )
    assert common._LAST_SUBSET["n_missing"] == 0


@pytest.mark.parametrize("path", _results(), ids=lambda p: p.name)
def test_every_result_taken_since_the_cutover_records_its_corpus(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    prov = payload.get("provenance") or {}
    when = prov.get("timestamp", "")
    if not when or when < CORPUS_STAMPED_FROM:
        pytest.skip(f"taken {when or 'at an unrecorded time'}; predates the field")
    dataset = str((payload.get("config") or {}).get("dataset", ""))
    if "LibriSpeech" not in dataset:
        pytest.skip(f"not a LibriSpeech measurement ({dataset or 'no dataset'})")
    assert (prov.get("corpus") or {}).get("sha256_16"), (
        f"{path.name} scores LibriSpeech and does not say which utterances. It was "
        "produced by something that bypassed `_common.librispeech_subset`, which is "
        "the only place that records them."
    )
