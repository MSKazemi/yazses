#!/usr/bin/env python3
"""Generate the paper-v2 manuscript tables and figure data from the archived result files.

Issue #508 (PAPER2-FIG-001). The second paper's headline numbers used to be copied by hand
from `paper/results/` into `design/publication/paper-v2/manuscript/sections/*.tex`. This
script reads ONLY the committed result artifacts under `paper/results/` and writes the
LaTeX tables and pgfplots-ready CSV files the manuscript `\\input`s into
`design/publication/paper-v2/manuscript/generated/`:

    uv run python scripts/gen-paper-v2-tables.py            # write
    uv run python scripts/gen-paper-v2-tables.py --check    # exit 1 if a committed output is stale

Properties, each enforced by `tests/test_gen_paper_v2_tables.py`:

* **No typed numbers.** Every number is read from an artifact or computed from one. The only
  literals in this file are labels, column names and prose.
* **Provenance in every output.** Each file starts with a comment block naming the source
  artifacts and the sha256 of each (computed over LF-normalised bytes, so a Windows checkout
  with CRLF hashes the same). Table captions name their sources as well.
* **Deterministic.** Pure stdlib, no clock, no environment, no network, no random numbers;
  the same artifact bytes give byte-identical output.
* **Contradictory runs are shown, never chosen between.** Where the archive holds two runs of
  one measurement (the two clean engine matrices, the two `test-other` matrix runs, the
  `large-v3` repeats) every run appears. Where two artifacts disagree on a point they both
  claim (a threshold swept twice), the generator stops rather than pick one.
* **The caveat travels with the number.** Sample sizes, host load, non-paired comparisons,
  multiplicity corrections and each artifact's own caveat text are carried into the table
  notes, derived from the artifacts rather than retyped.

It does not claim a table is *frozen*: #495 will replace the clean matrix with a frozen
artifact, and the generator will then be pointed at it.

Exit codes: 0 written / current; 1 a rule was violated or `--check` found drift;
2 an input could not be read or parsed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT_REL = "design/publication/paper-v2/manuscript/generated"
GENERATOR = "scripts/gen-paper-v2-tables.py"
RES = "paper/results"

# --- source artifacts (relative to the repository root) ---------------------------------
CLEAN_A = f"{RES}/probes/wer-matrix.json"  # first clean matrix
CLEAN_B = f"{RES}/probes/wer-vm-clean.json"  # second clean matrix (the one the draft headlines)
HARD_JSON = f"{RES}/wer-test-other.json"  # hard matrix, run 2 (overwrote run 1)
HARD_LOG = f"{RES}/probes/logs/x86b-other_wer.log"  # hard matrix, run 1 survives only as a log
LV3_OTHER = f"{RES}/probes/largev3-instability-test-other.json"
LV3_CLEAN = f"{RES}/probes/largev3-instability-test-clean.json"
LV3_DET = f"{RES}/probes/decode-determinism-large-v3-test-other.json"
LV3_DET_OFF = f"{RES}/probes/decode-determinism-large-v3-test-other-no_context.json"
LV3_ARMS = f"{RES}/probes/decode-arms-per-utterance-large-v3-test-other.json"
CONDITIONING = (  # (checkpoint, split, artifact)
    ("tiny.en", "test-clean", f"{RES}/probes/decode-determinism-tiny.en-test-clean-baseline.json"),
    ("base.en", "test-clean", f"{RES}/probes/decode-determinism-base.en-test-clean.json"),
    ("base.en", "test-other", f"{RES}/probes/decode-determinism-base.en-test-other.json"),
    (
        "small.en",
        "test-clean",
        f"{RES}/probes/decode-determinism-small.en-test-clean-baseline-no_context.json",
    ),
    (
        "small.en",
        "test-other",
        f"{RES}/probes/decode-determinism-small.en-test-other-baseline-no_context.json",
    ),
    (
        "medium.en",
        "test-clean",
        f"{RES}/probes/decode-determinism-medium.en-test-clean-baseline-no_context.json",
    ),
    (
        "medium.en",
        "test-other",
        f"{RES}/probes/decode-determinism-medium.en-test-other-baseline-no_context.json",
    ),
    ("large-v3", "test-other", LV3_DET),
)
ONSET = f"{RES}/onset.json"
ONSET_SIG = f"{RES}/onset-significance.json"
STREAMING = f"{RES}/streaming.json"
AMI_SHIPPED = f"{RES}/probes/ami16-shipped.json"  # threshold 0.5, no cap
AMI_CAP_05 = f"{RES}/probes/ami16-maxspk.json"  # threshold 0.5, max_speakers 4
AMI_12 = f"{RES}/diarization-ami16_corpus-der.json"  # threshold 1.2, no cap
AMI_CAP_12 = f"{RES}/diarization-ami16_corpus-maxspk4.json"  # threshold 1.2, max_speakers 4
AMI_PAIRED = f"{RES}/diarization-ami16_corpus-maxspk4-vs-der-significance.json"
SWEEP_SYNTH_1 = f"{RES}/probes/sweep.json"
SWEEP_SYNTH_2 = f"{RES}/probes/synth-sweep-wide.json"
SWEEP_AMI4 = f"{RES}/probes/ami-sweep2.json"
SWEEP_AMI1 = f"{RES}/probes/ami-one-sweep.json"
SWEEP_VOX_GATE = f"{RES}/probes/vox-gate.json"
SWEEP_VOX_LOG = f"{RES}/probes/logs/x86-vox_optimum.log"
PLATFORMS_DIR = f"{RES}/platforms"

LABELS = {
    "tiny.en": r"Whisper \texttt{tiny.en}",
    "base.en": r"Whisper \texttt{base.en}",
    "small.en": r"Whisper \texttt{small.en}",
    "medium.en": r"Whisper \texttt{medium.en}",
    "large-v3": r"Whisper \texttt{large-v3}",
    "parakeet-tdt-0.6b-v2": "Parakeet TDT 0.6B v2",
    "moonshine/tiny": "Moonshine tiny",
    "moonshine/base": "Moonshine base",
}


class GenError(Exception):
    """An input parsed but breaks a rule the tables depend on (exit 1)."""


# --- reading ----------------------------------------------------------------------------


class Reader:
    """Reads artifacts and remembers the sha256 of every file it touched."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.sources: dict[str, str] = {}

    def _raw(self, rel: str) -> bytes:
        raw = (self.root / rel).read_bytes().replace(b"\r\n", b"\n")
        self.sources[rel] = hashlib.sha256(raw).hexdigest()
        return raw

    def json(self, rel: str) -> Any:
        return json.loads(self._raw(rel).decode("utf-8"))

    def text(self, rel: str) -> str:
        return self._raw(rel).decode("utf-8")

    def listdir(self, rel: str) -> list[str]:
        return sorted(p.name for p in (self.root / rel).iterdir() if p.is_dir())


# --- formatting -------------------------------------------------------------------------

_TEX = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def esc(text: str) -> str:
    return "".join(_TEX.get(c, c) for c in text)


def tt(path: str) -> str:
    """A path in monospace, with break points after separators."""
    body = esc(path).replace("/", "/\\allowbreak{}").replace("-", "-\\allowbreak{}")
    return f"\\texttt{{{body}}}"


def f2(x: float) -> str:
    return f"{x:.2f}"


def sg(x: float, nd: int = 2) -> str:
    """Signed number with a typeset minus."""
    s = f"{x:+.{nd}f}"
    return "$-$" + s[1:] if s.startswith("-") else s


def rng(lo: float, hi: float, nd: int = 2) -> str:
    return f"{lo:.{nd}f}" if f"{lo:.{nd}f}" == f"{hi:.{nd}f}" else f"{lo:.{nd}f}--{hi:.{nd}f}"


def ci(pair: list[float], nd: int = 2) -> str:
    return f"{pair[0]:.{nd}f}--{pair[1]:.{nd}f}"


def need(cond: bool, message: str) -> None:
    if not cond:
        raise GenError(message)


def header(kind: str, sources: dict[str, str]) -> str:
    mark = "%" if kind == "tex" else "#"
    lines = [
        f"{mark} GENERATED by {GENERATOR} -- DO NOT EDIT. Issue #508.",
        f"{mark} Regenerate: uv run python {GENERATOR}   (check: add --check)",
        f"{mark} Source artifacts, with sha256 of the LF-normalised file:",
    ]
    lines += [f"{mark}   {rel}  sha256:{sha}" for rel, sha in sorted(sources.items())]
    if kind == "csv":
        lines.append("# Read with comment char '#'; empty cell = not recorded in the artifact.")
    return "\n".join(lines) + "\n"


def tex_table(
    *,
    label: str,
    caption: str,
    colspec: str,
    head: list[str],
    rows: list[list[str]],
    notes: list[str],
) -> str:
    out = [
        "\\begin{table}[ht]",
        "\\centering",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        # Measure first; shrink to the text width only if the natural width overflows it.
        f"\\sbox0{{\\begin{{tabular}}{{{colspec}}}",
        "\\toprule",
        " & ".join(head) + " \\\\",
        "\\midrule",
    ]
    out += [" & ".join(r) + " \\\\" for r in rows]
    out += [
        "\\bottomrule",
        "\\end{tabular}}%",
        "\\ifdim\\wd0>\\linewidth\\resizebox{\\linewidth}{!}{\\usebox0}\\else\\usebox0\\fi",
    ]
    if notes:
        out.append("\\par\\smallskip")
        out.append("\\begin{minipage}{0.96\\linewidth}\\footnotesize")
        out.append("\n\\par ".join(notes))
        out.append("\\end{minipage}")
    out.append("\\end{table}")
    return "\n".join(out) + "\n"


def csv_text(columns: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return buf.getvalue()


def host_sentence(prov: dict[str, Any]) -> str:
    load = prov.get("load_average_1m")
    tail = f"; 1-min load average {load}" if load is not None else ""
    return (
        f"{esc(prov['cpu_model'])} ({prov['logical_cpus']} logical CPUs, {esc(prov['os'])}{tail})"
    )


# --- 1/2/3: engine matrix (clean + hard) and the robustness plot data -------------------

_LOG_LINE = re.compile(
    r"^\[wer\] (?P<model>\S+): WER=(?P<wer>[\d.]+)% \(95% CI (?P<lo>[\d.]+)-(?P<hi>[\d.]+)\)"
    r"\s+RTF median=(?P<rtf>[\d.]+)",
    re.M,
)


def parse_wer_log(text: str) -> dict[str, dict[str, float]]:
    found = {
        m["model"]: {"wer": float(m["wer"]), "lo": float(m["lo"]), "hi": float(m["hi"])}
        for m in _LOG_LINE.finditer(text)
    }
    need(bool(found), f"{HARD_LOG}: no '[wer] <model>: WER=...' line parsed")
    return found


def _models(doc: dict[str, Any], rel: str) -> dict[str, Any]:
    models = (doc.get("result") or doc)["models"]
    need(bool(models), f"{rel}: empty model matrix")
    return models  # type: ignore[no-any-return]


def build_engine_matrix(rd: Reader) -> dict[str, str]:
    doc_a, doc_b = rd.json(CLEAN_A), rd.json(CLEAN_B)
    ma, mb = _models(doc_a, CLEAN_A), _models(doc_b, CLEAN_B)
    doc_h = rd.json(HARD_JSON)
    h2 = _models(doc_h, HARD_JSON)
    h1 = parse_wer_log(rd.text(HARD_LOG))
    need(set(ma) == set(mb) == set(h2) == set(h1), "engine matrices do not list the same engines")
    cfg_b = doc_b["result"]["config"]
    cfg_h = doc_h["config"]
    prov_a, prov_b, prov_h = doc_a["provenance"], doc_b["provenance"], doc_h["provenance"]
    need(cfg_b["n_utterances"] == cfg_h["n_utterances"], "clean/hard n_utterances differ")

    order = sorted(mb, key=lambda k: (mb[k]["wer"], k))
    best_lo, best_hi = mb[order[0]]["wer_ci95"]

    def overlaps_best(k: str) -> bool:
        lo, hi = mb[k]["wer_ci95"]
        return lo <= best_hi and hi >= best_lo

    differing = [k for k in order if ma[k]["wer"] != mb[k]["wer"]]

    # Table 1: clean matrix, both runs.
    rows = []
    for k in order:
        dag = "" if k == order[0] or not overlaps_best(k) else "$^\\dagger$"
        rows.append(
            [
                LABELS.get(k, esc(k)),
                f2(mb[k]["wer"]) + dag,
                ci(mb[k]["wer_ci95"]),
                f2(ma[k]["wer"]),
                f"{mb[k]['rtf_median']:.3f}",
                f"{ma[k]['rtf_median']:.3f}",
            ]
        )
    disagree = "; ".join(
        f"{LABELS.get(k, esc(k))} {f2(ma[k]['wer'])} (A) vs {f2(mb[k]['wer'])} (B)"
        for k in differing
    )
    clean_tex = tex_table(
        label="tab:clean-asr",
        caption=(
            f"Clean-speech ASR on LibriSpeech \\texttt{{test-clean}} ({cfg_b['n_utterances']} "
            f"utterances, {cfg_b['n_speakers']} speakers, {cfg_b['total_audio_seconds']} s of audio). "
            f"Two archived runs of the same matrix are shown: run A ({tt(CLEAN_A)}, "
            f"{esc(prov_a['timestamp'])}) and run B ({tt(CLEAN_B)}, {esc(prov_b['timestamp'])}); "
            "run B supplies the CI and the ordering."
        ),
        colspec="lrrrrr",
        head=[
            "Engine / checkpoint",
            "WER B (\\%)",
            "95\\% CI (B)",
            "WER A (\\%)",
            "RTF B",
            "RTF A",
        ],
        rows=rows,
        notes=[
            "Runs A and B disagree on WER for: " + (disagree or "no engine") + ". Neither run "
            "is presented as the value; the disagreement is the same repeated-run behaviour "
            "analysed in the reproducibility section.",
            f"$^\\dagger$ 95\\% CI overlaps that of the lowest-WER row ({LABELS.get(order[0], esc(order[0]))}); "
            "the ordering is a point-estimate ordering, not a statistical one.",
            f"Host: {host_sentence(prov_b)} for run B; run A: {host_sentence(prov_a)}. A load "
            "average near or above the logical-CPU count includes the benchmark's own threads, "
            "so it is reported, not interpreted. RTF is specific to this host and not "
            "transportable to another CPU.",
            f"Read audiobook speech, one host, one library version "
            f"(CTranslate2 {esc(prov_b['ctranslate2'])}, int8).",
        ],
    )

    clean_tex = (
        "% Provisional: replace the inputs with the frozen clean matrix when issue #495 delivers it.\n"
        + clean_tex
    )

    # Table 2: clean vs hard, every run of each.
    hard_order = sorted(h2, key=lambda k: (h2[k]["wer"], k))
    rows = []
    csv_rows: list[list[Any]] = []
    for k in hard_order:
        clean_vals = [ma[k]["wer"], mb[k]["wer"]]
        hard_vals = [h1[k]["wer"], h2[k]["wer"]]
        ratios = [h / c for h in hard_vals for c in clean_vals]
        rows.append(
            [
                LABELS.get(k, esc(k)),
                rng(min(clean_vals), max(clean_vals)),
                rng(min(hard_vals), max(hard_vals)),
                (
                    f"{min(ratios):.1f}"
                    if f"{min(ratios):.1f}" == f"{max(ratios):.1f}"
                    else f"{min(ratios):.1f}--{max(ratios):.1f}"
                )
                + "$\\times$",
            ]
        )
    for k in order:
        csv_rows.append(
            [
                k,
                f2(ma[k]["wer"]),
                f2(mb[k]["wer"]),
                f2(mb[k]["wer_ci95"][0]),
                f2(mb[k]["wer_ci95"][1]),
                f2(h1[k]["wer"]),
                f2(h1[k]["lo"]),
                f2(h1[k]["hi"]),
                f2(h2[k]["wer"]),
                f2(h2[k]["wer_ci95"][0]),
                f2(h2[k]["wer_ci95"][1]),
                f"{min(h / c for h in (h1[k]['wer'], h2[k]['wer']) for c in (ma[k]['wer'], mb[k]['wer'])):.2f}",
                f"{max(h / c for h in (h1[k]['wer'], h2[k]['wer']) for c in (ma[k]['wer'], mb[k]['wer'])):.2f}",
            ]
        )
    hard_diff = [k for k in hard_order if h1[k]["wer"] != h2[k]["wer"]]
    hard_tex = tex_table(
        label="tab:hard-asr",
        caption=(
            "Clean-to-hard robustness. Clean: both clean runs "
            f"({tt(CLEAN_A)}, {tt(CLEAN_B)}). Hard: LibriSpeech \\texttt{{test-other}}, both runs of "
            f"the matrix: run 1 survives only as the console log {tt(HARD_LOG)}; run 2 is "
            f"{tt(HARD_JSON)}. A range is the span of the archived runs, not a confidence interval."
        ),
        colspec="lrrr",
        head=["Engine / checkpoint", "Clean WER (\\%)", "Hard WER (\\%)", "Hard/Clean"],
        rows=rows,
        notes=[
            "Hard runs 1 and 2 disagree for: "
            + "; ".join(
                f"{LABELS.get(k, esc(k))} {f2(h1[k]['wer'])} vs {f2(h2[k]['wer'])}"
                for k in hard_diff
            )
            + ". Reporting either alone would hide that disagreement.",
            f"The two splits are different utterance subsets (clean: {cfg_b['n_speakers']} speakers, "
            f"{cfg_b['total_audio_seconds']} s; hard: {cfg_h['n_speakers']} speakers, "
            f"{cfg_h['total_audio_seconds']} s). Hard/Clean is a ratio of corpus-level WERs, not a "
            "paired per-utterance difference; its range spans every clean-run and hard-run pairing "
            "and carries no confidence interval. Both splits are read audiobook speech.",
            f"Hard-matrix host: {host_sentence(prov_h)}.",
        ],
    )
    robustness = csv_text(
        [
            "engine",
            "clean_wer_run_a",
            "clean_wer_run_b",
            "clean_ci_lo_b",
            "clean_ci_hi_b",
            "hard_wer_run_1_log",
            "hard_ci_lo_1",
            "hard_ci_hi_1",
            "hard_wer_run_2",
            "hard_ci_lo_2",
            "hard_ci_hi_2",
            "hard_over_clean_min",
            "hard_over_clean_max",
        ],
        csv_rows,
    )
    return {"clean_asr.tex": clean_tex, "hard_asr.tex": hard_tex, "robustness.csv": robustness}


# --- 4: large-v3 repeat decodes -----------------------------------------------------------


def build_largev3(rd: Reader) -> dict[str, str]:
    series: list[dict[str, Any]] = []

    def add(
        split: str, context: str, run: Any, rec: dict[str, Any], src: str, counts: bool
    ) -> None:
        series.append(
            {
                "split": split,
                "context": context,
                "run": run,
                "wer": rec["wer"],
                "sub": rec.get("substitutions") if counts else None,
                "del": rec.get("deletions") if counts else None,
                "ins": rec.get("insertions") if counts else None,
                "hits": rec.get("hits") if counts else None,
                "source": src,
            }
        )

    ctx_matrix, ctx_probe = "engine matrix", "dedicated repeat probe"
    ctx_det, ctx_arms = "decode-determinism baseline arm", "decoder-arms baseline"
    # test-other
    h1 = parse_wer_log(rd.text(HARD_LOG))["large-v3"]
    add("test-other", ctx_matrix, "1 (log)", h1, HARD_LOG, False)
    add(
        "test-other",
        ctx_matrix,
        "2",
        _models(rd.json(HARD_JSON), HARD_JSON)["large-v3"],
        HARD_JSON,
        True,
    )
    for r in rd.json(LV3_OTHER)["result"]["runs"]:
        add("test-other", ctx_probe, r["run"] + 1, r, LV3_OTHER, True)
    for i, r in enumerate(rd.json(LV3_DET)["arms"]["baseline"]["runs"]):
        add("test-other", ctx_det, i + 1, r, LV3_DET, True)
    for i, w in enumerate(rd.json(LV3_ARMS)["baseline_runs_wer"]):
        add("test-other", ctx_arms, i + 1, {"wer": w}, LV3_ARMS, False)
    # test-clean
    for label, rel in (("A", CLEAN_A), ("B", CLEAN_B)):
        add("test-clean", ctx_matrix, label, _models(rd.json(rel), rel)["large-v3"], rel, True)
    for r in rd.json(LV3_CLEAN)["result"]["runs"]:
        add("test-clean", ctx_probe, r["run"] + 1, r, LV3_CLEAN, True)
    need(len(series) > 10, "large-v3 repeat series unexpectedly short")

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for s in series:
        groups.setdefault((s["split"], s["context"]), []).append(s)

    def span(vals: list[float], nd: int = 2) -> str:
        return "---" if not vals else rng(min(vals), max(vals), nd)

    rows = []
    for (split, context), g in groups.items():
        sub = [s["sub"] for s in g if s["sub"] is not None]
        dele = [s["del"] for s in g if s["del"] is not None]
        ins = [s["ins"] for s in g if s["ins"] is not None]
        if len(sub) < 2:
            flat = "n/a"
        else:
            flat = "yes" if len(set(sub)) == 1 and len(set(dele)) == 1 else "no"
        rows.append(
            [
                f"\\texttt{{{esc(split)}}}",
                esc(context),
                str(len(g)),
                span([s["wer"] for s in g]),
                span(sub, 0),
                span(dele, 0),
                span(ins, 0),
                flat,
            ]
        )
    notes = []
    for split in ("test-other", "test-clean"):
        subs = sorted({s["sub"] for s in series if s["split"] == split and s["sub"] is not None})
        dels = sorted({s["del"] for s in series if s["split"] == split and s["del"] is not None})
        n = sum(1 for s in series if s["split"] == split and s["sub"] is not None)
        notes.append(
            f"\\texttt{{{esc(split)}}}: across the {n} decodes that archive error counts, "
            f"substitutions take the value(s) {', '.join(map(str, subs))} and deletions "
            f"{', '.join(map(str, dels))}; the run-to-run movement is in insertions."
        )
    notes.append(
        "Each row is one measurement context and contexts are not pooled: they differ in "
        "host load, run date and library state. ``---'' = not recorded (a console log keeps only "
        "WER; the decoder-arms file keeps only baseline WERs). ``S/D flat'' needs at least two runs "
        "with archived counts. Same 200 utterances, same configuration (\\texttt{large-v3}, int8, "
        "CPU); no decode setting was changed between runs of a row."
    )
    table = tex_table(
        label="tab:largev3-repeats",
        caption=(
            "Repeated decodes of one nominally fixed \\texttt{large-v3} configuration, by "
            "measurement context. Source artifacts are listed in the note."
        ),
        colspec="llrrrrrr",
        head=["Split", "Context", "Runs", "WER (\\%)", "Subs", "Dels", "Ins", "S/D flat"],
        rows=rows,
        notes=notes
        + [
            "Sources: "
            + ", ".join(
                tt(p)
                for p in (
                    HARD_LOG,
                    HARD_JSON,
                    LV3_OTHER,
                    LV3_DET,
                    LV3_ARMS,
                    LV3_CLEAN,
                    CLEAN_A,
                    CLEAN_B,
                )
            )
            + "."
        ],
    )
    data = csv_text(
        [
            "split",
            "context",
            "run",
            "wer_pct",
            "substitutions",
            "deletions",
            "insertions",
            "hits",
            "source",
        ],
        [
            [
                s["split"],
                s["context"],
                s["run"],
                f2(s["wer"]),
                s["sub"],
                s["del"],
                s["ins"],
                s["hits"],
                s["source"],
            ]
            for s in series
        ],
    )
    return {"largev3_repeats.tex": table, "largev3_repeats.csv": data}


# --- 5: previous-text conditioning by checkpoint ------------------------------------------


def _arm(arm: dict[str, Any]) -> dict[str, Any]:
    wers = [r["wer"] for r in arm["runs"]]
    s = arm["summary"]
    return {
        "n": len(wers),
        "min": min(wers),
        "max": max(wers),
        "mean": sum(wers) / len(wers),
        "distinct": s["distinct_outputs"],
    }


def _cell(a: dict[str, Any]) -> str:
    span = rng(a["min"], a["max"])
    return f"{span} ({a['distinct']}/{a['n']} distinct)"


def build_conditioning(rd: Reader) -> dict[str, str]:
    rows: list[list[str]] = []
    csv_rows: list[list[Any]] = []
    for ckpt, split, rel in CONDITIONING:
        doc = rd.json(rel)
        arms = doc["arms"]
        need(doc["config"]["model"] == ckpt, f"{rel}: model is not {ckpt}")
        need("baseline" in arms, f"{rel}: no baseline arm")
        on = _arm(arms["baseline"])
        if "no_context" in arms:
            off = _arm(arms["no_context"])
        elif ckpt == "large-v3":
            off = _arm(rd.json(LV3_DET_OFF)["arms"]["no_context"])
        else:
            off = None
        if off is None:
            delta, reading = "---", "OFF arm not archived"
        else:
            d = off["mean"] - on["mean"]
            delta = sg(d)
            if f"{d:.2f}" in ("0.00", "-0.00"):
                reading = "equal"
            else:
                disjoint = off["max"] < on["min"] or off["min"] > on["max"]
                reading = ("OFF lower" if d < 0 else "OFF higher") + (
                    " (ranges disjoint)" if disjoint else " (ranges overlap)"
                )
        n_utt = doc["config"]["n_utterances"]
        rows.append(
            [
                f"\\texttt{{{esc(ckpt)}}}",
                f"\\texttt{{{esc(split)}}} ($n$={n_utt})",
                _cell(on),
                _cell(off) if off else "---",
                delta,
                reading,
            ]
        )
        csv_rows.append(
            [
                ckpt,
                split,
                f"{on['mean']:.3f}",
                f2(on["min"]),
                f2(on["max"]),
                on["distinct"],
                on["n"],
                None if off is None else f"{off['mean']:.3f}",
                None if off is None else f2(off["min"]),
                None if off is None else f2(off["max"]),
                None if off is None else off["distinct"],
                None if off is None else off["n"],
            ]
        )
    arms_doc = rd.json(LV3_ARMS)
    cmp_ = arms_doc["comparisons"]["no_context"]
    top3 = cmp_["gain_concentration"]["top_3"]["share_of_gain"]
    notes = [
        "ON = faster-whisper default (condition on previous text); OFF = "
        "\\texttt{condition\\_on\\_previous\\_text=False}, temperature fallback left on in both. "
        "Cells are WER (\\%) over repeated decodes of the same $n$ utterances; "
        "``distinct'' counts distinct hypothesis texts. $\\Delta$ is the OFF mean "
        "minus the ON mean, in WER points. The temperature-0 arms in the same artifacts are not shown.",
        f"\\texttt{{large-v3}}, \\texttt{{test-other}}, paired by utterance against the median ON run "
        f"({tt(LV3_ARMS)}): $\\Delta$ = {sg(cmp_['delta_wer'])} WER points, 95\\% CI "
        f"[{sg(cmp_['delta_wer_ci95'][0])}, {sg(cmp_['delta_wer_ci95'][1])}]; "
        f"{cmp_['utterances_better']} utterances better, {cmp_['utterances_worse']} worse, "
        f"{cmp_['utterances_unchanged']} unchanged; sign test p = {cmp_['sign_test_p']}; the three "
        f"largest-gain clips carry {top3 * 100:.1f}\\% of the aggregate gain; the artifact's own "
        f"verdict is ``{esc(cmp_['verdict'])}''. The ON/OFF difference in the table therefore "
        "does not establish a mean-WER improvement: the gain is concentrated in a few clips.",
        f"The \\texttt{{large-v3}} OFF arm is read from {tt(LV3_DET_OFF)}, a separate run from the "
        "ON arm. All rows are one host, read audiobook speech.",
        "Sources: "
        + ", ".join(
            tt(p) for p in sorted({r for _, _, r in CONDITIONING} | {LV3_DET_OFF, LV3_ARMS})
        )
        + ".",
    ]
    table = tex_table(
        label="tab:conditioning",
        caption=(
            "Effect of conditioning on previous text, by checkpoint and split. Source "
            "artifacts are listed in the note."
        ),
        colspec="llllrl",
        head=["Checkpoint", "Split", "ON", "OFF", "$\\Delta$", "Reading"],
        rows=rows,
        notes=notes,
    )
    data = csv_text(
        [
            "checkpoint",
            "split",
            "on_mean",
            "on_min",
            "on_max",
            "on_distinct",
            "on_runs",
            "off_mean",
            "off_min",
            "off_max",
            "off_distinct",
            "off_runs",
        ],
        csv_rows,
    )
    return {"conditioning.tex": table, "conditioning.csv": data}


# --- 6: cross-platform WER ------------------------------------------------------------------


def build_platform(rd: Reader) -> dict[str, str]:
    runners = rd.listdir(PLATFORMS_DIR)
    docs = {r: rd.json(f"{PLATFORMS_DIR}/{r}/wer.json") for r in runners}
    need(len(docs) >= 2, f"{PLATFORMS_DIR}: fewer than two runner directories with wer.json")
    models = sorted({m for d in docs.values() for m in d["models"]})
    n_set = {d["config"]["n_utterances"] for d in docs.values()}
    ct_set = {d["provenance"]["ctranslate2"] for d in docs.values()}
    need(len(n_set) == 1, f"runners disagree on n_utterances: {sorted(n_set)}")
    order = {"tiny.en": 0, "base.en": 1, "small.en": 2}
    models.sort(key=lambda m: (order.get(m, 99), m))
    rows, csv_rows = [], []
    for m in models:
        cells, wers, cis, counts = [], [], [], []
        for r in runners:
            rec = docs[r]["models"].get(m)
            if rec is None:
                cells.append("---")
                continue
            cells.append(f2(rec["wer"]))
            wers.append(rec["wer"])
            cis.append(rec["wer_ci95"])
            counts.append((rec["substitutions"], rec["deletions"], rec["insertions"], rec["hits"]))
            csv_rows.append(
                [m, r, f2(rec["wer"]), f2(rec["wer_ci95"][0]), f2(rec["wer_ci95"][1]),
                 rec["substitutions"], rec["deletions"], rec["insertions"], rec["hits"],
                 docs[r]["provenance"]["cpu_model"], docs[r]["provenance"]["os"]]
            )  # fmt: skip
        spread = max(wers) - min(wers)
        all_overlap = all(a[0] <= b[1] and b[0] <= a[1] for a in cis for b in cis)
        rows.append(
            [f"\\texttt{{{esc(m)}}}"]
            + cells
            + [
                f2(spread),
                "yes" if all_overlap else "no",
                "yes" if len(set(counts)) == 1 else "no",
            ]
        )
    cpu_note = "; ".join(
        f"\\texttt{{{esc(r)}}}: {esc(docs[r]['provenance']['cpu_model'])}, "
        f"{docs[r]['provenance']['logical_cpus']} logical CPUs, {esc(docs[r]['provenance']['os'])}"
        for r in runners
    )
    loads = "; ".join(
        f"\\texttt{{{esc(r)}}} {docs[r]['provenance']['load_average_1m']}"
        f" ({docs[r]['provenance']['logical_cpus']} CPUs)"
        for r in runners
        if docs[r]["provenance"].get("load_average_1m", -1) >= 0  # -1.0 = not measured (Windows)
    )
    unmeasured = [r for r in runners if docs[r]["provenance"].get("load_average_1m", -1) < 0]
    distinct_cpus = len({docs[r]["provenance"]["cpu_model"] for r in runners}) == len(runners)
    table = tex_table(
        label="tab:platform",
        caption=(
            f"Cross-platform WER on the common {next(iter(n_set))}-utterance "
            "LibriSpeech \\texttt{test-clean} subset, one decode per cell. Sources: "
            + ", ".join(tt(f"{PLATFORMS_DIR}/{r}/wer.json") for r in runners)
            + "."
        ),
        colspec="l" + "r" * len(runners) + "rll",
        head=["Checkpoint"]
        + [f"\\texttt{{{esc(r)}}}" for r in runners]
        + ["Spread", "CIs overlap", "S/D/I/H equal"],
        rows=rows,
        notes=[
            "Spread = highest minus lowest point estimate; it is a range of single runs, not a test. "
            "``CIs overlap'' = every pair of 95\\% bootstrap intervals overlaps; ``S/D/I/H equal'' = "
            "substitution, deletion, insertion and hit counts are identical on every runner (an equal "
            "aggregate WER can hide different error decompositions).",
            "Runners"
            + (
                " (every runner has a different CPU model, so no column pair isolates an OS effect)"
                if distinct_cpus
                else ""
            )
            + f": {cpu_note}.",
            f"1-min load average at run end: {loads}"
            + ("; not measured on " + ", ".join(tt(r) for r in unmeasured) if unmeasured else "")
            + f". Shared CI hardware of unknown neighbours; "
            f"CTranslate2 {', '.join(sorted(ct_set))} on all runners. This is a decode benchmark, "
            "not an end-to-end hotkey-to-injection validation.",
        ],
    )
    data = csv_text(
        ["checkpoint", "runner", "wer_pct", "ci_lo", "ci_hi", "substitutions", "deletions",
         "insertions", "hits", "cpu_model", "os"],
        csv_rows,
    )  # fmt: skip
    return {"platform_wer.tex": table, "platform_wer.csv": data}


# --- 7: onset-padding heatmap -----------------------------------------------------------------

_CELL = re.compile(r"^(intact|clipped) cut=(\d+) lead=(\d+)$")


def build_onset(rd: Reader) -> dict[str, str]:
    on = rd.json(ONSET)
    sig = rd.json(ONSET_SIG)
    cfg = on["config"]
    cells: dict[tuple[int, int], list[float]] = {}
    for r in on["rows"]:
        cells.setdefault((r["cut_ms"], r["lead_ms"]), []).append(
            100.0 * r["first_word_ok"] / r["n"]
        )
    cuts = sorted({c for c, _ in cells})
    leads = sorted({lead for _, lead in cells})
    need(0 in leads, "onset.json has no lead_ms=0 baseline")
    need(len(cells) == len(cuts) * len(leads), "onset grid is not rectangular")
    cmp_: dict[tuple[int, int], dict[str, Any]] = {}
    for d in sig["distinct"]:
        m, b = _CELL.match(d["comparison"]), _CELL.match(d["baseline"])
        need(bool(m and b), f"unparseable comparison {d['comparison']!r}")
        assert m and b
        need(int(b[3]) == 0 and b[2] == m[2], f"baseline of {d['comparison']!r} is not lead=0")
        cmp_[(int(m[2]), int(m[3]))] = d
    bonf = sig["bonferroni_alpha"]
    alpha = sig["alpha"]

    def mean(v: list[float]) -> float:
        return sum(v) / len(v)

    rows, csv_rows = [], []
    flagged = harmful = bonf_sig = 0
    for cut in cuts:
        row = [("intact" if cut == 0 else f"{cut} ms")]
        base = mean(cells[(cut, 0)])
        for lead in leads:
            v = cells[(cut, lead)]
            c = cmp_.get((cut, lead))
            text = f"{mean(v):.1f}"
            delta = p = None
            sig_runs = 0
            if lead != 0:
                need(c is not None, f"no significance record for cut={cut} lead={lead}")
                assert c is not None
                delta = mean(v) - base
                p = c["p_max"]
                sig_runs = c["significant_runs"]
                text += f" ({sg(delta, 1)})"
                if sig_runs == c["runs"]:
                    flagged += 1
                    text += "$^\\dagger$"
                    harmful += delta < 0
                bonf_sig += p < bonf
            row.append(text)
            csv_rows.append(
                [cut, lead, f"{mean(v):.2f}", f"{min(v):.2f}", f"{max(v):.2f}", len(v),
                 None if delta is None else f"{delta:.2f}", p,
                 None if c is None else c["significant_runs"], None if c is None else c["runs"],
                 None if c is None else "|".join(map(str, c["baseline_wins_per_run"])),
                 None if c is None else "|".join(map(str, c["cell_wins_per_run"])),
                 None if c is None else str(p < bonf)]
            )  # fmt: skip
        rows.append(row)
    table = tex_table(
        label="tab:onset",
        caption=(
            "First-word correctness (\\%) after clipping real speech (rows) and prepending synthetic "
            f"silence (columns, ms), \\texttt{{{esc(cfg['model'])}}} on {cfg['n']} "
            f"\\texttt{{test-clean}} utterances, mean of {cfg['repeat']} runs; in brackets the change "
            f"from the lead-in-0 cell of the same row, in points. Sources: {tt(ONSET)}, {tt(ONSET_SIG)}."
        ),
        colspec="l" + "r" * len(leads),
        head=["Clipped"] + [f"lead {x}" for x in leads],
        rows=rows,
        notes=[
            f"$^\\dagger$ uncorrected paired p $<$ {alpha} in every run of that cell "
            f"({flagged} of {len(cmp_)} lead-in comparisons; {harmful} of them in the direction "
            "of fewer first words correct). This is a flag, not a finding: the artifact applies "
            f"a Bonferroni threshold of {bonf} over {sig['n_distinct']} distinct comparisons, and "
            f"{bonf_sig} of {len(cmp_)} clear it.",
            f"Natural lead-in was trimmed first (median {cfg['median_trimmed_ms']} ms trimmed, "
            f"maximum {cfg['max_trimmed_ms']} ms). One checkpoint, read speech, one host, "
            f"{cfg['n']} utterances: cells differ by a few utterances.",
        ],
    )
    data = csv_text(
        ["clipped_ms", "lead_ms", "first_word_pct_mean", "first_word_pct_min", "first_word_pct_max",
         "runs", "delta_vs_lead0_pts", "p_max_vs_lead0", "runs_uncorrected_significant",
         "runs_compared", "baseline_only_wins_per_run", "cell_only_wins_per_run",
         "survives_bonferroni"],
        csv_rows,
    )  # fmt: skip
    return {"onset_heatmap.tex": table, "onset_heatmap.csv": data}


# --- 8: streaming vs batch --------------------------------------------------------------------


def build_streaming(rd: Reader) -> dict[str, str]:
    doc = rd.json(STREAMING)
    cfg, prov = doc["config"], doc["provenance"]
    rows, csv_rows = [], []
    for name, m in doc["models"].items():
        b, s, vis = (
            m["batch_speech_end_to_text_s"],
            m["streaming_speech_end_to_final_s"],
            m["streaming_visible_at_release_pct"],
        )
        rows.append(
            [
                f"\\texttt{{{esc(name)}}}",
                f"{b['median']:.3f} ({b['p95']:.3f})",
                f"{s['median']:.3f} ({s['p95']:.3f})",
                f"{s['median'] / b['median']:.2f}$\\times$",
                f"{vis['median']:.1f}",
                f"{m['utterances_with_no_partial_before_release']}/{s['n']}",
            ]
        )
        csv_rows.append(
            [name, b["median"], b["p95"], s["median"], s["p95"], f"{s['median'] / b['median']:.3f}",
             vis["median"], m["utterances_with_no_partial_before_release"], s["n"]]
        )  # fmt: skip
    over = prov.get("load_average_1m")
    contention = (
        f" The 1-min load average at run end ({over}) exceeds the logical-CPU count "
        f"({prov['logical_cpus']}), so absolute times may be inflated by a contended host."
        if over is not None and over > prov["logical_cpus"]
        else ""
    )
    table = tex_table(
        label="tab:streaming",
        caption=(
            "Batch versus streaming dictation on CPU, median (95th percentile) seconds from "
            f"speech end. Source: {tt(STREAMING)}."
        ),
        colspec="lrrrrr",
        head=[
            "Checkpoint",
            "Batch: end$\\to$text (s)",
            "Streaming: end$\\to$final (s)",
            "Stream/batch",
            "Visible at release (\\%)",
            "No partial before release",
        ],
        rows=rows,
        notes=[
            f"n = {cfg['n_utterances']} utterances (median duration {cfg['audio_duration_median_s']} s), "
            f"audio fed in real time in {cfg['chunk_ms']} ms chunks, partial decode every "
            f"{cfg['partial_interval_ms']} ms; one machine ({host_sentence(prov)}). ``Visible at release'' "
            "is the median share of the final text already shown when the key is released."
            + contention,
            "With n = 15 the 95th percentile is the near-maximum observation, not a stable estimate. "
            "The ratio compares medians of two paths on the same utterances; no paired test is "
            "archived.",
        ],
    )
    data = csv_text(
        ["checkpoint", "batch_median_s", "batch_p95_s", "streaming_final_median_s",
         "streaming_final_p95_s", "streaming_over_batch_median", "visible_at_release_median_pct",
         "no_partial_before_release", "n"],
        csv_rows,
    )  # fmt: skip
    return {"streaming.tex": table, "streaming.csv": data}


# --- 9: AMI diarization conditions, and the threshold/domain data ----------------------------


def build_ami(rd: Reader) -> dict[str, str]:
    conds = (AMI_SHIPPED, AMI_CAP_05, AMI_12, AMI_CAP_12)
    loaded = []
    for rel in conds:
        d = rd.json(rel)
        r = d.get("result", d)
        c = r["config"]
        label = f"Threshold {c['cluster_threshold']}, " + (
            "unrestricted"
            if not c["max_speakers"]
            else f"\\texttt{{max\\_speakers={c['max_speakers']}}}"
        )
        meet = r["meetings"]
        exact = sum(
            1 for m in meet if m["strict"]["n_ref_speakers"] == m["strict"]["n_hyp_speakers"]
        )
        loaded.append((label, rel, r, exact))
    cfg = loaded[2][2]["config"]
    for _, rel, r, _ in loaded:
        need(r["config"]["n_meetings"] == cfg["n_meetings"], f"{rel}: n_meetings differs")
    rows = []
    for label, _, r, exact in loaded:
        s = r["summary"]
        tw = s.get("der_strict_time_weighted")
        rows.append(
            [
                label,
                f"{s['der_strict']:.2f}",
                "---" if tw is None else f"{tw:.2f}",
                f"{s['der_collar250ms']:.2f}",
                sg(s["mean_speaker_count_error"]),
                f"{exact}/{len(r['meetings'])}",
            ]
        )
    need(
        [x[2]["config"]["max_speakers"] > 0 for x in loaded] == [False, True, False, True],
        "AMI artifacts are not (uncapped, capped, uncapped, capped)",
    )
    cap05, cap12 = loaded[1][2]["meetings"], loaded[3][2]["meetings"]
    d_hi = loaded[2][2]["summary"]["der_strict"]
    lo_thr, hi_thr = loaded[0][2]["config"]["cluster_threshold"], cfg["cluster_threshold"]
    cap_n = loaded[3][2]["config"]["max_speakers"]
    cap_der = loaded[3][2]["summary"]["der_strict"]
    by_id = {m["id"]: m["strict"]["der"] for m in cap05}
    same = sum(1 for m in cap12 if by_id.get(m["id"]) == m["strict"]["der"])
    meet12 = loaded[2][2]["meetings"]
    minutes = sum(m["duration_s"] for m in meet12) / 60
    four = sum(1 for m in meet12 if m["true_speakers"] == 4)
    table = tex_table(
        label="tab:ami",
        caption=(
            f"AMI test-split diarization ({cfg['n_meetings']} recordings, {minutes:.1f} min, "
            f"{four} with four reference speakers), four archived clustering conditions. DER in "
            "\\%, mean over recordings unless stated; count error is the mean signed "
            "hypothesis-minus-reference speaker count. Sources: "
            + ", ".join(tt(rel) for _, rel, _, _ in loaded)
            + "."
        ),
        colspec="lrrrrr",
        head=[
            "Configuration",
            "Mean DER",
            "Time-weighted DER",
            "Mean DER, 250 ms collar",
            "Count error",
            "Exact count",
        ],
        rows=rows,
        notes=[
            f"``---'' = not recorded: the two threshold-{lo_thr} rows are exploratory-probe artifacts "
            f"with no time-weighted aggregate; the threshold-{hi_thr} rows are harness outputs. The rows "
            f"are four separate runs, not one controlled sweep. The two capped rows have identical "
            f"per-recording strict DER in {same} of {len(cap12)} recordings (the cap, not the "
            "threshold, fixes the final cluster count once it binds). Use the time-weighted figure "
            "when comparing with published diarization work.",
            "Corpus note from the artifact: " + esc(cfg["caveat"]),
            f"Backend: {esc(cfg['backend'])}; scoring: {esc(cfg['scoring'])}.",
        ],
    )
    pdoc = rd.json(AMI_PAIRED)["result"]
    prow = []
    for key, name in (("strict", "strict"), ("collar250ms", "250 ms collar")):
        p = pdoc[key]
        prow.append(
            [
                name,
                sg(p["mean_delta"])
                + f" [{sg(p['mean_delta_ci95'][0])}, {sg(p['mean_delta_ci95'][1])}]",
                sg(p["time_weighted_delta"])
                + f" [{sg(p['time_weighted_delta_ci95'][0])}, {sg(p['time_weighted_delta_ci95'][1])}]",
                f"{p['b_better_on']}/{p['b_worse_on']}/{p['unchanged_on']}",
                f"{p['sign_test_p']}",
                esc(p["verdict"]),
            ]
        )
    paired = tex_table(
        label="tab:ami-paired",
        caption=(
            f"Paired effect of \\texttt{{max\\_speakers={cap_n}}} at threshold {hi_thr} (capped minus "
            f"unrestricted), per recording. Source: {tt(AMI_PAIRED)}."
        ),
        colspec="lllrrl",
        head=[
            "Scoring",
            "Mean $\\Delta$DER [95\\% CI]",
            "Time-weighted $\\Delta$DER [95\\% CI]",
            "Better/worse/same",
            "Sign-test p",
            "Artifact verdict",
        ],
        rows=prow,
        notes=[
            f"Bootstrap over recordings ({pdoc['strict']['n_bootstrap']} resamples, "
            f"{pdoc['strict']['n_recordings']} recordings). A positive $\\Delta$ means the capped run "
            f"has the higher DER. The {d_hi:.2f}\\% (unrestricted) versus {cap_der:.2f}\\% (capped) comparison across rows of the table "
            "above is not this paired comparison and must not be read as one: only this table "
            "holds the threshold fixed."
        ],
    )
    return {"ami_diarization.tex": table, "ami_paired.tex": paired}


_SWEEP_LOG = re.compile(
    r"^\[sweep\] threshold=(?P<t>[\d.]+)\s+DER=(?P<der>[\d.]+)%\s+count_err=(?P<ce>[+-][\d.]+)"
    r"\s+exact=(?P<ex>\d+)/(?P<n>\d+)",
    re.M,
)


def build_threshold(rd: Reader) -> dict[str, str]:
    # series -> {threshold: (der, count_err, exact, n_meetings, source, kind)}
    series: dict[str, dict[float, tuple[Any, ...]]] = {}

    def put(name: str, thr: float, rec: tuple[Any, ...]) -> None:
        cur = series.setdefault(name, {})
        if thr in cur:
            need(
                cur[thr][:3] == rec[:3],
                f"{name} threshold {thr}: {cur[thr][4]} and {rec[4]} disagree "
                f"({cur[thr][:3]} vs {rec[:3]}); refusing to pick one",
            )
            return
        cur[thr] = rec

    synth, ami4, ami1 = "synthetic TTS meetings", "AMI, 4 meetings", "AMI, 1 meeting"
    for rel in (SWEEP_SYNTH_1, SWEEP_SYNTH_2, SWEEP_AMI4, SWEEP_AMI1):
        r = rd.json(rel)["result"]
        for p in r["sweep"] if isinstance(r, dict) else r:
            name = {SWEEP_SYNTH_1: synth, SWEEP_SYNTH_2: synth, SWEEP_AMI4: ami4, SWEEP_AMI1: ami1}[
                rel
            ]
            put(
                name,
                p.get("cluster_threshold", p.get("threshold")),
                (p["der"], p["mean_speaker_count_error"],
                 p.get("meetings_with_exact_count", p.get("exact_count_meetings")),
                 p.get("n_meetings"), rel, "result JSON"),
            )  # fmt: skip
    ami16 = "AMI, 16 meetings"
    for rel in (AMI_SHIPPED, AMI_12):
        d = rd.json(rel)
        r = d.get("result", d)
        put(
            ami16,
            r["config"]["cluster_threshold"],
            (r["summary"]["der_strict"], r["summary"]["mean_speaker_count_error"],
             sum(1 for m in r["meetings"] if m["strict"]["n_ref_speakers"] == m["strict"]["n_hyp_speakers"]),
             r["config"]["n_meetings"], rel, "result JSON"),
        )  # fmt: skip
    vox = "VoxConverse"
    for p in rd.json(SWEEP_VOX_GATE)["result"]["sweep"]:
        put(vox, p["cluster_threshold"], (p["der"], p["mean_speaker_count_error"],
            p["meetings_with_exact_count"], p["n_meetings"], SWEEP_VOX_GATE, "result JSON"))  # fmt: skip
    for m in _SWEEP_LOG.finditer(rd.text(SWEEP_VOX_LOG)):
        put(vox, float(m["t"]), (float(m["der"]), float(m["ce"]), int(m["ex"]), int(m["n"]),
            SWEEP_VOX_LOG, "console log of a terminated run"))  # fmt: skip
    need(len(series) == 5 and all(series.values()), "threshold series incomplete")
    n_vox_log = sum(1 for v in series[vox].values() if v[5].startswith("console"))
    n_vox_json = len(series[vox]) - n_vox_log

    ref_thr = rd.json(AMI_12)["config"]["cluster_threshold"]  # the shipped meeting threshold
    csv_rows, rows = [], []
    for name, pts in series.items():
        thrs = sorted(pts)
        for t in thrs:
            der, ce, ex, n, src, kind = pts[t]
            csv_rows.append([name, t, f2(der), ce, ex, n, src, kind])
        best = min(thrs, key=lambda t: (pts[t][0], t))
        interior = thrs[0] < best < thrs[-1]
        at_ref = pts.get(ref_thr)
        ns = sorted({pts[t][3] for t in thrs if pts[t][3] is not None})
        rows.append(
            [
                esc(name),
                ", ".join(map(str, ns)) or "---",
                f"{len(thrs)} ({thrs[0]}--{thrs[-1]})",
                f"{best} ({f2(pts[best][0])})" + ("" if interior else " edge"),
                "---" if at_ref is None else f2(at_ref[0]),
                "sparse" if len(thrs) < 5 else "",
            ]
        )
    table = tex_table(
        label="tab:threshold-domain",
        caption=(
            "Where the lowest-DER clustering threshold sits in each corpus, among the thresholds "
            "actually measured. Source artifacts are listed in the note."
        ),
        colspec="llllrl",
        head=[
            "Corpus",
            "Meetings",
            "Thresholds measured",
            "Lowest-DER threshold (DER \\%)",
            f"DER at {ref_thr}",
            "Grid",
        ],
        rows=rows,
        notes=[
            "DER levels are not comparable across corpora (different audio, annotation and, for the "
            "synthetic set, text-to-speech voices); the comparable observation is only where each "
            "corpus's own minimum lies on the grid that was measured. ``edge'' = the minimum is at "
            "the end of the measured grid, so the true optimum may lie outside it. ``sparse'' = fewer "
            "than five thresholds. The AMI 16-meeting series has "
            f"{len(series[ami16])} thresholds ({', '.join(map(str, sorted(series[ami16])))}).",
            f"VoxConverse: {n_vox_json} threshold(s) come from a result file and {n_vox_log} from the "
            "console log of a sweep that was terminated before finishing; no archived result file "
            "records a VoxConverse optimum beyond those points. Where two artifacts swept the same "
            "threshold they agree exactly (the generator stops otherwise).",
            "Sources: "
            + ", ".join(tt(p) for p in sorted({v[4] for s in series.values() for v in s.values()}))
            + ".",
        ],
    )
    data = csv_text(
        ["corpus", "cluster_threshold", "der_pct", "mean_speaker_count_error", "exact_count_meetings",
         "n_meetings", "source", "source_kind"],
        csv_rows,
    )  # fmt: skip
    return {"threshold_domain.tex": table, "threshold_domain.csv": data}


# --- driver -------------------------------------------------------------------------------------

BUILDERS: tuple[Callable[[Reader], dict[str, str]], ...] = (
    build_engine_matrix,
    build_largev3,
    build_conditioning,
    build_platform,
    build_onset,
    build_streaming,
    build_ami,
    build_threshold,
)


def build_all(root: Path = ROOT) -> dict[str, str]:
    """Return {filename: full text} for every generated file. Pure function of the artifacts."""
    out: dict[str, str] = {}
    for builder in BUILDERS:
        rd = Reader(root)
        files = builder(rd)
        for name, body in files.items():
            need(name not in out, f"two builders produce {name}")
            out[name] = header("csv" if name.endswith(".csv") else "tex", rd.sources) + body
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this repo)")
    ap.add_argument("--out-dir", type=Path, default=None, help=f"default: <root>/{OUT_REL}")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 on stale output")
    args = ap.parse_args(argv)
    out_dir = args.out_dir or args.root / OUT_REL

    try:
        outputs = build_all(args.root)
    except GenError as exc:
        print(f"paper-v2 tables not generated: {exc}", file=sys.stderr)
        return 1
    except (OSError, KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        print(
            f"paper-v2 input could not be read or parsed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    if args.check:
        stale = [
            n
            for n, body in sorted(outputs.items())
            if not (out_dir / n).is_file() or (out_dir / n).read_bytes() != body.encode("utf-8")
        ]
        extra = (
            sorted(p.name for p in out_dir.iterdir() if p.is_file() and p.name not in outputs)
            if out_dir.is_dir()
            else []
        )
        if stale or extra:
            for n in stale:
                print(f"{OUT_REL}/{n} is missing or stale", file=sys.stderr)
            for n in extra:
                print(f"{OUT_REL}/{n} is not produced by the generator", file=sys.stderr)
            print(f"run `uv run python {GENERATOR}` and commit.", file=sys.stderr)
            return 1
        print(f"{OUT_REL}: {len(outputs)} files current.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    for n, body in sorted(outputs.items()):
        (out_dir / n).write_bytes(body.encode("utf-8"))
    print(f"wrote {len(outputs)} files to {OUT_REL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
