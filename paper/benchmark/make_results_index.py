"""Write `../results/MANIFEST.md`: what every archived artifact is, and where it came from.

`paper/results/` now holds forty-odd JSON files written across two months, three
machines and two dozen scripts, plus a subtree of one-off probes and their logs. Each
one carries its own provenance block, which is what makes it a measurement -- but a
reader who wants to check a figure on `docs/benchmarks.md` has to open files until they
find the right one, and a reader who wants to know whether two numbers are comparable
has to compare two provenance blocks by hand. Both questions are answerable from the
files themselves, so this answers them once, in a table.

**Generated, and derived from the directory rather than from a list.** A hand-written
inventory of a directory is the defect: it is only ever as complete as the day it was
written, and its omissions are invisible. The companion guard
(`tests/test_results_manifest_is_current.py`) checks both directions -- every file on
disk appears, and every file named exists -- because an "is it in sync?" test that only
re-runs the generator and diffs cannot notice that the generator skips a whole subtree.

    uv run python paper/benchmark/make_results_index.py
"""
from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "results"

#: What each harness result answers, keyed by the script stem its filename starts with.
#: Only used for the prose column; a file whose stem is unknown is still listed, with
#: an empty description, because dropping it would be the omission this exists to
#: prevent.
MEASURES = {
    # Keys are tried longest-first, so a full stem names exactly one file. This one is
    # here because it was produced before `decode_determinism.py` learned to describe
    # itself: the run had already imported the module when the `probe` block was added,
    # so re-generating the description would mean re-decoding 200 utterances on
    # `large-v3` five times. Every other decode-determinism artifact carries its own
    # block and is deliberately left to it -- a generic `decode-determinism` key would
    # match them all and replace four specific descriptions with one vague one.
    "decode-determinism-large-v3-test-other-no_context": (
        "the fourth decode arm on its own -- conditioning off, temperature fallback "
        "left on, five decodes -- which is the setting a large-model user would ship "
        "and the only arm whose reproducibility was genuinely open"
    ),
    # `_describe` truncates the stem at the first dot, so `base.en-test-clean` and
    # `base.en-test-other` both reduce to this one key -- which is right here, since
    # they are the same 2x2 on the same checkpoint over the two splits. Both were
    # produced while the probe block still named `large-v3` (the question it was first
    # asked about), and re-running the model the default install actually uses is
    # exactly what they are.
    "decode-determinism-base": (
        "the decode 2x2 -- temperature fallback x conditioning on previous text, five "
        "decodes per arm -- on `base.en`, the checkpoint a default install runs, to "
        "test whether the `large-v3` result generalises to the shipped model"
    ),
    # Keyed on the two-word prefix, not `centroid`, so a future centroid measurement
    # of something else cannot inherit this description by accident.
    "centroid-merge": (
        "whether cluster-centroid cosine separates two clusters of one speaker from "
        "two real speakers -- the merge-shaped diarization error ADR-v2-133 could not see"
    ),
    "beam": "WER and RTF across `[stt] beam_size`",
    "commands": "command-grammar accuracy and false-positive rate",
    "diarization": "diarization DER, miss, false alarm, confusion",
    "index": "roll-up written by `run_all.py` (a snapshot, superseded by the per-bench files)",
    "latency": "decode P50/P95, cold start, RSS, per-stage timings",
    "meta": "dysfluency gate, model footprint, engineering scale",
    "onset": "first-word accuracy against the silence lead-in",
    "platform": "which install targets resolve, per OS and instruction set",
    "plausibility": "how often the implausible-attribution warning fires",
    "streaming": "partial-hypothesis latency and rewrite rate",
    "vad": "speech detection and silence rejection at the default threshold",
    "wer": "WER and RTF per engine and checkpoint",
}


#: Suffixes that mark a file as an *analysis of* a measurement rather than a
#: measurement. Seven of the twenty-five harness artifacts are these, and the prefix
#: match below described every one of them as the grid it re-reads: a paired bootstrap
#: over utterances was listed as "WER and RTF across `[stt] beam_size`", which is what
#: the grid file says, so the manifest asserted that the same thing had been measured
#: twice. `paper/results/README.md` warns about exactly this glob -- the warning was
#: written because the confusion had already happened once, by hand.
ANALYSES = {
    "significance": (
        "paired bootstrap over the same utterances -- an analysis of the grid file of "
        "the same name, not a second measurement"
    ),
}


def _describe(name: str) -> str:
    stem = name.split(".")[0]
    analysis = next(
        (ANALYSES[a] for a in ANALYSES if stem.endswith(f"-{a}") or f"-{a}-" in stem),
        "",
    )
    for key in sorted(MEASURES, key=len, reverse=True):
        if stem == key or stem.startswith(f"{key}-") or stem.startswith(f"{key}_"):
            return f"{analysis} ({MEASURES[key]})" if analysis else MEASURES[key]
    return analysis


def _machine(prov: dict) -> str:
    cpu = prov.get("cpu_model") or "?"
    # Long marketing names make the table unreadable; the full string stays in the
    # artifact, which is the citable thing. Title-casing is applied only to a name
    # that arrived SHOUTING (Azure reports `INTEL(R) XEON(R) PLATINUM 8573C`) --
    # applied unconditionally it turns `13th Gen` into `13Th Gen`.
    if cpu.isupper():
        cpu = cpu.title()
    for noisy in ("(R)", "(r)", "(TM)", "(tm)", "(Tm)", " CPU", " Cpu"):
        cpu = cpu.replace(noisy, "")
    cpu = " ".join(cpu.split())
    n = prov.get("logical_cpus")
    return f"{cpu} ({n} vCPU)" if n else cpu


def rows(results: Path = RESULTS) -> list[dict]:
    out = []
    for path in sorted(results.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        prov = data.get("provenance") or {}
        probe = data.get("probe") or {}
        out.append({
            "path": path.relative_to(results).as_posix(),
            "measures": _describe(path.name) or probe.get("measured", ""),
            "machine": _machine(prov),
            "when": prov.get("timestamp", ""),
            "yazses": prov.get("yazses", ""),
            "command": prov.get("argv", ""),
            "produced_by": probe.get("produced_by", "") or _script_from_argv(prov),
            "superseded_by": probe.get("superseded_by", ""),
        })
    return out



def _script_from_argv(prov: dict) -> str:
    """Name the script from the recorded command line when no probe block does.

    `write_result` stamps `probe.produced_by`, but artifacts written before that
    chokepoint existed carry only `provenance.argv` -- and an unattributed row in a
    manifest whose whole purpose is attribution reads as "nobody knows", when the
    command line is sitting right there. Only the first token is taken, and only if
    it looks like a path to a script this repo could hold; a bare interpreter or a
    shell pipeline is left unattributed rather than guessed at.
    """
    argv = prov.get("argv", "")
    if not isinstance(argv, str) or not argv.strip():
        return ""
    first = argv.split()[0]
    if not first.endswith(".py") or first.startswith("-"):
        return ""
    return first


def render(entries: list[dict]) -> str:
    harness = [e for e in entries if "/" not in e["path"]]
    probes = [e for e in entries if e["path"].startswith("probes/")]
    platforms = [e for e in entries if e["path"].startswith("platforms/")]
    history = [e for e in entries if e["path"].startswith("history/")]
    # Anything in no bucket still gets a section. A generator that quietly drops a
    # subtree it was not written for is the omission an in-sync check cannot see.
    known = harness + probes + platforms + history
    other = [e for e in entries if e not in known]

    lines = [
        "<!-- Generated by paper/benchmark/make_results_index.py. Do not edit by hand;",
        "     tests/test_results_manifest_is_current.py fails on drift. -->",
        "# Archived results",
        "",
        "Every measurement behind a published number, with the machine it was taken on.",
        "Regenerate with `uv run python paper/benchmark/make_results_index.py`.",
        "",
        "**Two numbers are comparable only if the `Machine` column matches.** WER on a",
        "fixed subset reproduces bit-for-bit on one machine and moves by up to a third of",
        "a point across two; RTF moves by 3 % between runs on identical instances and by",
        "a quarter when a second job shares the box.",
        "",
        "## Harness results",
        "",
        "Written by a committed `paper/benchmark/bench_*.py` and reproducible by re-running it.",
        "",
        "**The `Command` column is how you re-run one.** A row that shows `\u2014` predates the",
        "field: `_common.write_result` stamps it now, so re-running that benchmark fills it",
        "in. The arguments are not decoration -- `bench_wer.py` writes one filename for",
        "`200 test-clean` and for `500 test-other`, and `bench_beam.py` writes one for the",
        "`base.en` grid and the `tiny.en` grid whose disagreement decided ADR-v2-073.",
        "",
        "| File | Measures | Command | Machine | Taken | YazSes |",
        "|---|---|---|---|---|---|",
    ]
    for e in harness:
        cmd = f"`{e['command']}`" if e["command"] else "\u2014"
        lines.append(
            f"| `{e['path']}` | {e['measures']} | {cmd} | {e['machine']} | {e['when']} | {e['yazses']} |"
        )

    if probes:
        lines += [
            "",
            "## Probes",
            "",
            "One-off measurements made while a question was being scoped, on rented compute.",
            "Kept because a published finding that traces to a deleted script is not",
            "reproducible; the producing script is committed under `paper/benchmark/probes/`.",
            "A `Superseded by` entry means a committed harness script now measures the same",
            "thing, and that its result is the one to cite.",
            "",
            "| File | Measures | Produced by | Taken | Superseded by |",
            "|---|---|---|---|---|",
        ]
        for e in probes:
            sup = f"`{e['superseded_by']}`" if e["superseded_by"] else "—"
            by = f"`{e['produced_by']}`" if e["produced_by"] else "—"
            lines.append(f"| `{e['path']}` | {e['measures']} | {by} | {e['when']} | {sup} |")

    if platforms:
        lines += [
            "",
            "## The same harness on four instruction sets",
            "",
            "Uploaded by `.github/workflows/benchmark.yml`, one directory per runner. The",
            "WER column is comparable across them and the timings are not: the macOS runner",
            "reported a one-minute load average of 30.44 on three logical CPUs, which the",
            "provenance block records and a table of RTFs would have hidden.",
            "",
            "| File | Measures | Machine | Taken |",
            "|---|---|---|---|",
        ]
        for e in platforms:
            lines.append(f"| `{e['path']}` | {e['measures']} | {e['machine']} | {e['when']} |")

    if history:
        lines += [
            "",
            "## Displaced runs",
            "",
            "A benchmark writes to a fixed filename, so re-running one overwrites the",
            "previous measurement. `_common.write_result` copies the old file here first,",
            "named for the instant *it* was measured, and only when the content actually",
            "changed -- a reproducible re-run archives nothing. These exist because the",
            "first `test-other` matrix was lost that way and the two runs disagreed by 2.83",
            "points on `large-v3`, which made the displaced file half the finding rather",
            "than a redundant copy.",
            "",
            "| File | Measures | Machine | Taken |",
            "|---|---|---|---|",
        ]
        for e in history:
            lines.append(f"| `{e['path']}` | {e['measures']} | {e['machine']} | {e['when']} |")

    if other:
        lines += ["", "## Other", "", "| File | Measures | Machine | Taken |", "|---|---|---|---|"]
        for e in other:
            lines.append(f"| `{e['path']}` | {e['measures']} | {e['machine']} | {e['when']} |")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    out = RESULTS / "MANIFEST.md"
    text = render(rows())
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(rows())} artifacts)")


if __name__ == "__main__":
    main()
