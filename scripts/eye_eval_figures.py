#!/usr/bin/env python3
"""Deterministic tables and figures from an eye-control analysis report (#426).

    uv run python scripts/analyze_eye_eval.py --unit participant --links links.json \\
        --format json --out report.json results/
    uv run python scripts/eye_eval_figures.py report.json --out paper-eye/

`scripts/analyze_eye_eval.py` produces the provisional, descriptive report (JSON) and its
Markdown tables. This script is the second half of #426's "generates tables/figures from
inputs deterministically": it turns that JSON report -- never raw result files, never a
spreadsheet -- into

* ``tables/counts.csv``            participants, sessions, runs, trials, distinct hosts,
                                   loaded vs analysed, each in its own column;
* ``tables/outcomes.csv``          one row per stratum x unit x outcome category;
* ``tables/false_activations.csv`` events / scored exposure hours per unit;
* ``tables/latency.csv``           per-run p50 latency, one stratum (host + config) per row;
* ``tables/session_retest.csv``    within-participant per-session primary rate and spread;
* ``tables/exclusions.csv``        every exclusion with category, reason, predefined flag;
* ``tables/missing_data.csv``      every missing metric family with its reason;
* ``figures/outcomes_<stratum>.svg`` and ``figures/latency_<stratum>.svg``, one per stratum;
* ``manifest.json``                 every file above with its sha256, the sha256 of the report
                                   it came from, and the report's claim IDs / source runs
                                   that each file carries (the claim-to-table/figure manifest).

What it holds to (each one is a #426 acceptance or analysis-integrity line):

* **It refuses, rather than repairs.** An unknown ``analysis_version`` major, a report not
  marked provisional, a stratum ID that is not a plain token, a duplicate stratum, or a
  rate/interval that is not a number in [0, 1] stops everything; nothing is written.
* **``insufficient data`` never becomes 0.** Such a cell is empty in the CSV, with the status
  column saying why, and the figure prints the words instead of drawing a mark at zero.
* **Wrong target, fallback and lost tracking stay separate rows**, each with its own colour.
  No combined "error" is computed here either.
* **Latency is never pooled.** One latency figure per stratum; the CSV keeps the stratum's
  host and config hash on every row.
* **The figures are descriptions, not inference.** Whiskers are the report's per-unit 95%
  Wilson intervals (that unit's own trials); every figure title says PROVISIONAL and n.
* **Deterministic.** Stdlib only, no plotting library, no clock, no locale, no random, sorted
  everywhere, fixed number formatting and ``\\n`` line endings: the same report gives
  byte-identical files on every machine, so a figure can be diffed in review.

It does not read result files, so it cannot see a participant; the report it reads already
carries only pseudonymous IDs. Point it at reports kept outside the repository.

Exit codes: 0 files written; 1 report refused; 2 usage error.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

FIGURES_VERSION = "1.0"
SUPPORTED_ANALYSIS_MAJOR = "1"
INSUFFICIENT = "insufficient data"  # the exact words `yazses.eyeeval.analysis` prints

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

#: Fixed colours per outcome category (colour-blind-distinguishable Okabe-Ito set). A
#: category not listed falls back to grey and is still drawn as its own row.
_COLOURS = {
    "correct_target": "#009E73", "hit": "#009E73", "detected": "#009E73",
    "wrong_target": "#D55E00", "miss": "#D55E00", "missed": "#D55E00",
    "fallback_no_route": "#0072B2", "abandoned": "#0072B2",
    "invalid_tracking": "#CC79A7", "tracking_lost": "#CC79A7",
}
_GREY = "#555555"


class FiguresError(Exception):
    """The report cannot be turned into tables/figures; ``problems`` lists every reason."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


# --- validation --------------------------------------------------------------------------


def _is_unit_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= float(value) <= 1.0


def check_report(report: Any) -> list[str]:
    """Every reason *report* must be refused; empty when it is usable."""
    if not isinstance(report, dict):
        return ["report: expected a JSON object (the output of analyze_eye_eval.py --format json)."]
    problems: list[str] = []
    version = report.get("analysis_version")
    if not isinstance(version, str) or version.split(".", 1)[0] != SUPPORTED_ANALYSIS_MAJOR:
        problems.append(
            f"analysis_version: {version!r} is not a {SUPPORTED_ANALYSIS_MAJOR}.x report; "
            "an unknown layout is refused rather than guessed."
        )
    if report.get("provisional") is not True:
        problems.append("provisional: the report must be marked provisional (the #425 plan is not frozen).")
    for key in ("aggregation_unit", "study_mode"):
        if not isinstance(report.get(key), str):
            problems.append(f"{key}: missing; a table without its unit / study mode is refused.")
    strata = report.get("strata")
    if not isinstance(strata, list):
        problems.append("strata: expected a list.")
        return problems
    seen: set[str] = set()
    for i, s in enumerate(strata):
        where = f"strata[{i}]"
        if not isinstance(s, dict):
            problems.append(f"{where}: expected an object.")
            continue
        sid = s.get("stratum_id")
        if not isinstance(sid, str) or not _TOKEN.fullmatch(sid):
            problems.append(f"{where}.stratum_id: {sid!r} is not a plain token; it names output files.")
        elif sid in seen:
            problems.append(f"{where}.stratum_id: {sid!r} repeats; two strata would share one figure.")
        else:
            seen.add(sid)
        if not isinstance(s.get("stratum"), dict):
            problems.append(f"{where}.stratum: expected an object (task, host, config_hash, ...).")
        for j, unit in enumerate(s.get("units") or []):
            for cat, entry in sorted((unit.get("outcomes") or {}).items()):
                at = f"{where}.units[{j}].outcomes.{cat}"
                if not isinstance(entry, dict) or "rate" not in entry or "n" not in entry:
                    problems.append(f"{at}: expected rate and n.")
                    continue
                if entry["rate"] == INSUFFICIENT:
                    continue
                ci = entry.get("ci95_wilson")
                if not _is_unit_number(entry["rate"]) or not (
                    isinstance(ci, list) and len(ci) == 2 and all(_is_unit_number(x) for x in ci)
                    and ci[0] <= entry["rate"] <= ci[1]
                ):
                    problems.append(f"{at}: rate / interval are not numbers in [0, 1] with lo <= rate <= hi.")
    claims = report.get("claim_manifest")
    if not isinstance(claims, list) or not all(isinstance(c, dict) and "claim_id" in c for c in claims):
        problems.append("claim_manifest: expected a list of claims; without it no figure can name its sources.")
    return problems


# --- tables ------------------------------------------------------------------------------


def _csv(header: Sequence[str], rows: list[list[Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if v is None else _fmt(v) for v in row])
    return buf.getvalue().encode("utf-8")


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _stratum_cols(s: dict[str, Any]) -> list[Any]:
    st = s["stratum"]
    return [s["stratum_id"], st.get("task"), st.get("host"), st.get("config_hash")]


def _outcome_rows(s: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for unit in s.get("units") or []:
        for cat, e in sorted((unit.get("outcomes") or {}).items()):
            if e["rate"] == INSUFFICIENT:
                rows.append([*_stratum_cols(s), unit["unit"], cat, None, e["n"], None, None, None,
                             f"{INSUFFICIENT} (minimum n {e.get('minimum_n')})"])
            else:
                lo, hi = e["ci95_wilson"]
                rows.append([*_stratum_cols(s), unit["unit"], cat, e.get("k"), e["n"],
                             float(e["rate"]), float(lo), float(hi), "ok"])
    return rows


def build_tables(report: dict[str, Any]) -> dict[str, bytes]:
    strata = sorted(report["strata"], key=lambda s: s["stratum_id"])
    head = ["stratum_id", "task", "host", "config_hash"]
    out: dict[str, bytes] = {}

    count_rows = []
    for scope in ("loaded", "analysed"):
        c = (report.get("counts") or {}).get(scope) or {}
        count_rows.append([scope, c.get("participants"), c.get("sessions"), c.get("runs"),
                           c.get("trials_by_task"), c.get("distinct_hosts"), c.get("host_identity")])
    out["tables/counts.csv"] = _csv(
        ["scope", "participants", "sessions", "runs", "trials_by_task", "distinct_hosts", "host_identity"],
        count_rows)

    out["tables/outcomes.csv"] = _csv(
        [*head, "unit", "category", "k", "n", "rate", "ci95_lo", "ci95_hi", "status"],
        [r for s in strata for r in _outcome_rows(s)])

    fa_rows = []
    for s in strata:
        for unit in s.get("units") or []:
            fa = unit.get("false_activations")
            if not isinstance(fa, dict):
                continue
            ok = fa.get("per_hour") != INSUFFICIENT
            fa_rows.append([*_stratum_cols(s), unit["unit"], fa.get("events") if ok else None,
                            fa.get("exposure_s"), fa.get("per_hour") if ok else None,
                            "ok" if ok else f"{INSUFFICIENT} (minimum exposure {fa.get('minimum_exposure_s')} s)"])
    out["tables/false_activations.csv"] = _csv(
        [*head, "unit", "events", "exposure_s", "per_hour", "status"], fa_rows)

    lat_rows = []
    for s in strata:
        lat = s.get("latency") or {}
        for i, value in enumerate(lat.get("per_run_p50") or []):
            lat_rows.append([*_stratum_cols(s), lat.get("metric"), i, value])
    out["tables/latency.csv"] = _csv([*head, "metric", "run_index", "p50_ms"], lat_rows)

    retest_rows = []
    for s in strata:
        rt = s.get("session_retest") or {}
        for row in rt.get("rows") or []:
            for sess in row.get("sessions") or []:
                retest_rows.append([*_stratum_cols(s), rt.get("outcome"), row.get("participant"),
                                    sess.get("session"), sess.get("n"), sess.get("rate"), row.get("spread")])
    out["tables/session_retest.csv"] = _csv(
        [*head, "outcome", "participant", "session", "n", "rate", "participant_spread"], retest_rows)

    out["tables/exclusions.csv"] = _csv(
        ["run", "category", "reason", "predefined", "detail"],
        [[e.get("run"), e.get("category"), e.get("reason"), e.get("predefined"),
          {k: v for k, v in sorted(e.items()) if k not in {"run", "category", "reason", "predefined"}} or None]
         for e in sorted(report.get("exclusions") or [], key=lambda e: str(e.get("run")))])
    out["tables/missing_data.csv"] = _csv(
        ["run", "family", "reason"],
        [[m.get("run"), m.get("family"), m.get("reason")]
         for m in sorted(report.get("missing_data") or [], key=lambda m: (str(m.get("run")), str(m.get("family"))))])
    return out


# --- figures -----------------------------------------------------------------------------

_W = 720
_LEFT = 260
_RIGHT = 40
_ROW = 22
_TOP = 64


def _x(value: float, lo: float, hi: float) -> float:
    span = (hi - lo) or 1.0
    return _LEFT + (value - lo) / span * (_W - _LEFT - _RIGHT)


def _n(value: float) -> str:
    return f"{value:.2f}"


def _svg(height: float, body: list[str], title: str, subtitle: str) -> bytes:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{_n(height)}" '
        f'viewBox="0 0 {_W} {_n(height)}" font-family="sans-serif" font-size="12">',
        f'<rect x="0" y="0" width="{_W}" height="{_n(height)}" fill="#ffffff"/>',
        f'<text x="12" y="22" font-size="14" font-weight="bold">{escape(title)}</text>',
        f'<text x="12" y="42" fill="#333333">{escape(subtitle)}</text>',
        *body,
        "</svg>",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _axis(y: float, lo: float, hi: float, ticks: list[float], fmt: str) -> list[str]:
    out = [f'<line x1="{_n(_x(lo, lo, hi))}" y1="{_n(y)}" x2="{_n(_x(hi, lo, hi))}" y2="{_n(y)}" stroke="#000000"/>']
    for t in ticks:
        x = _n(_x(t, lo, hi))
        out.append(f'<line x1="{x}" y1="{_n(y)}" x2="{x}" y2="{_n(y + 4)}" stroke="#000000"/>')
        out.append(f'<text x="{x}" y="{_n(y + 16)}" text-anchor="middle">{escape(format(t, fmt))}</text>')
    return out


def outcomes_svg(report: dict[str, Any], s: dict[str, Any]) -> bytes:
    """Dot-and-whisker of every unit x category share in one stratum; never a bar at 0 for missing."""
    body: list[str] = []
    y = float(_TOP)
    units = s.get("units") or []
    for unit in units:
        for cat, e in sorted((unit.get("outcomes") or {}).items()):
            cy = y + _ROW / 2
            label = f"{unit['unit']} / {cat}"
            body.append(f'<text x="{_LEFT - 8}" y="{_n(cy + 4)}" text-anchor="end">{escape(label)}</text>')
            if e["rate"] == INSUFFICIENT:
                words = f"{INSUFFICIENT} (n={e['n']}, minimum {e.get('minimum_n')})"
                body.append(f'<text x="{_LEFT}" y="{_n(cy + 4)}" fill="{_GREY}" font-style="italic">'
                            f"{escape(words)}</text>")
            else:
                colour = _COLOURS.get(cat, _GREY)
                lo, hi = e["ci95_wilson"]
                body.append(f'<line x1="{_n(_x(lo, 0, 1))}" y1="{_n(cy)}" x2="{_n(_x(hi, 0, 1))}" '
                            f'y2="{_n(cy)}" stroke="{colour}" stroke-width="2"/>')
                rate = float(e["rate"])
                tip = f"{label}: {rate:.4f} [{lo:.4f}, {hi:.4f}] n={e['n']}"
                body.append(f'<circle cx="{_n(_x(rate, 0, 1))}" cy="{_n(cy)}" r="4" fill="{colour}">'
                            f"<title>{escape(tip)}</title></circle>")
            y += _ROW
    if not body:
        body.append(f'<text x="12" y="{_n(y + 14)}">no unit in this stratum has outcome counts</text>')
        y += _ROW
    body += _axis(y + 6, 0.0, 1.0, [0.0, 0.25, 0.5, 0.75, 1.0], ".2f")
    st = s["stratum"]
    title = f"PROVISIONAL -- {st.get('task')} outcome shares, stratum {s['stratum_id']}"
    subtitle = (f"unit={report['aggregation_unit']}, units={len(units)}, mode={report['study_mode']}; "
                "dot = share, whisker = 95% Wilson interval of that unit's own trials")
    return _svg(y + 40, body, title, subtitle)


def latency_svg(report: dict[str, Any], s: dict[str, Any]) -> bytes:
    """Per-run p50 latency strip for ONE stratum (one host + config); never pooled across strata."""
    lat = s.get("latency") or {}
    values = [float(v) for v in lat.get("per_run_p50") or []]
    body: list[str] = []
    y = float(_TOP)
    if values:
        hi = max(values) * 1.1 or 1.0
        cy = y + _ROW / 2
        body.append(f'<text x="{_LEFT - 8}" y="{_n(cy + 4)}" text-anchor="end">'
                    f'{escape(str(lat.get("metric")))} (per run)</text>')
        for i, v in enumerate(values):
            body.append(f'<circle cx="{_n(_x(v, 0, hi))}" cy="{_n(cy)}" r="4" fill="#0072B2" fill-opacity="0.6">'
                        f"<title>run {i}: {escape(_fmt(v))} ms</title></circle>")
        y += _ROW
        body += _axis(y + 6, 0.0, hi, [0.0, hi / 2, hi], ".0f")
        y += 24
    else:
        body.append(f'<text x="12" y="{_n(y + 14)}">no run in this stratum has a latency value</text>')
        y += _ROW
    reasons = lat.get("missing_by_reason") or {}
    if reasons:
        listing = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
        body.append(f'<text x="12" y="{_n(y + 20)}" fill="{_GREY}">missing (kept, never zero): {escape(listing)}</text>')
        y += _ROW
    st = s["stratum"]
    title = f"PROVISIONAL -- {st.get('task')} latency, stratum {s['stratum_id']}"
    subtitle = (f"host={st.get('host')}, config={st.get('config_hash')}, runs with a value={len(values)}; "
                "one host and config only, never pooled")
    return _svg(y + 40, body, title, subtitle)


# --- manifest + entry point --------------------------------------------------------------


def build_outputs(report: dict[str, Any], report_bytes: bytes) -> dict[str, bytes]:
    """Every output file (relative path -> bytes) for *report*. Raises `FiguresError`."""
    problems = check_report(report)
    if problems:
        raise FiguresError(problems)
    files = build_tables(report)
    strata = sorted(report["strata"], key=lambda s: s["stratum_id"])
    for s in strata:
        files[f"figures/outcomes_{s['stratum_id']}.svg"] = outcomes_svg(report, s)
        files[f"figures/latency_{s['stratum_id']}.svg"] = latency_svg(report, s)

    claims = sorted(report["claim_manifest"], key=lambda c: str(c["claim_id"]))
    by_table: dict[str, list[dict[str, Any]]] = {}
    for c in claims:
        by_table.setdefault(str(c.get("table")), []).append(c)

    def carried(path: str) -> list[dict[str, Any]]:
        if path == "tables/outcomes.csv":
            picked = by_table.get("outcomes", [])
        elif path == "tables/false_activations.csv":
            picked = by_table.get("false_activations", [])
        elif path == "tables/latency.csv":
            picked = by_table.get("latency", [])
        elif path == "tables/session_retest.csv":
            picked = by_table.get("session_retest", [])
        elif path.startswith("figures/outcomes_"):
            sid = path[len("figures/outcomes_"):-len(".svg")]
            picked = [c for c in by_table.get("outcomes", []) if c.get("stratum_id") == sid]
        elif path.startswith("figures/latency_"):
            sid = path[len("figures/latency_"):-len(".svg")]
            picked = [c for c in by_table.get("latency", []) if c.get("stratum_id") == sid]
        else:
            picked = []
        return [{"claim_id": c["claim_id"], "source_runs": sorted(c.get("source_runs") or [])} for c in picked]

    entries = [{"path": p, "sha256": hashlib.sha256(files[p]).hexdigest(), "claims": carried(p)}
               for p in sorted(files)]
    placed = {c["claim_id"] for e in entries for c in e["claims"]}
    manifest = {
        "figures_version": FIGURES_VERSION,
        "provisional": True,
        "source_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "analysis_version": report["analysis_version"],
        "aggregation_unit": report["aggregation_unit"],
        "study_mode": report["study_mode"],
        "files": entries,
        # A claim the report makes that no file carries (e.g. a session-retest row) is listed,
        # so a paper cannot cite a number that has no table behind it without seeing it here.
        "claims_without_a_file": sorted(str(c["claim_id"]) for c in claims if c["claim_id"] not in placed),
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
    return files


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n", 1)[0])
    parser.add_argument("report", type=Path, help="report JSON from analyze_eye_eval.py --format json")
    parser.add_argument("--out", type=Path, required=True, help="directory to write tables/, figures/, manifest.json")
    args = parser.parse_args(argv)
    try:
        report_bytes = args.report.read_bytes()
        report = json.loads(report_bytes.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"REFUSED: cannot read the report ({exc}).", file=sys.stderr)
        return 1
    try:
        files = build_outputs(report, report_bytes)
    except FiguresError as exc:
        print("REFUSED:", file=sys.stderr)
        print("  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 1
    for rel, data in sorted(files.items()):
        target = args.out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)  # bytes: the same file on every OS
    print(f"wrote {len(files)} files to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
