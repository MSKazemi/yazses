"""#426: deterministic tables/figures from the eye-control analysis report.

`scripts/eye_eval_figures.py` turns the JSON report of `scripts/analyze_eye_eval.py` into
CSV tables, one SVG figure per stratum, and a claim-to-table/figure manifest. Every input
here is SYNTHETIC: hand-built report dicts, or the committed de-identified fixtures under
`tests/fixtures/eye_eval/` run through `yazses.eyeeval.analysis.analyze`. They prove the
plumbing, not how well eye control works; no test asserts that a rate is good.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from yazses.eyeeval.analysis import INSUFFICIENT, analyze, dump_report

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "eye_eval_figures.py"
FIXTURES = Path(__file__).parent / "fixtures" / "eye_eval"


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("eye_eval_figures_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


F = _load_script()


def _share(k: int, n: int, lo: float, hi: float) -> dict[str, Any]:
    return {"k": k, "n": n, "provisional": True, "rate": round(k / n, 4), "ci95_wilson": [lo, hi]}


def _stratum(sid: str, host: str, latencies: list[float]) -> dict[str, Any]:
    return {
        "stratum_id": sid,
        "stratum": {"task": "gaze_routing_4_pane", "host": host, "config_hash": f"cfg-{sid}"},
        "unit": "participant",
        "primary_outcome": "correct_target",
        "units": [
            {"unit": "P01", "runs": 2, "source_runs": ["a"], "outcomes": {
                "correct_target": _share(30, 40, 0.6, 0.86),
                "wrong_target": _share(4, 40, 0.04, 0.23),
                "fallback_no_route": _share(5, 40, 0.05, 0.26),
                "invalid_tracking": _share(1, 40, 0.0, 0.13),
            }},
            {"unit": "P02", "runs": 1, "source_runs": ["b"], "outcomes": {
                "correct_target": {"n": 3, "provisional": True, "rate": INSUFFICIENT, "minimum_n": 20},
                "wrong_target": {"n": 3, "provisional": True, "rate": INSUFFICIENT, "minimum_n": 20},
                "fallback_no_route": {"n": 3, "provisional": True, "rate": INSUFFICIENT, "minimum_n": 20},
                "invalid_tracking": {"n": 3, "provisional": True, "rate": INSUFFICIENT, "minimum_n": 20},
            }},
        ],
        "latency": {"metric": "trial_time_ms_p50", "runs_with_value": len(latencies),
                    "per_run_p50": latencies, "missing_by_reason": {"not_measured": 1},
                    "pooling": "never pooled"},
        "session_retest": {"outcome": "correct_target", "rows": [
            {"participant": "P01", "spread": 0.1, "sessions": [
                {"session": "S0", "n": 20, "rate": 0.7}, {"session": "S1", "n": 20, "rate": 0.8}]}]},
    }


def report() -> dict[str, Any]:
    strata = [_stratum("bbbb", "host-B", [900.0, 650.5]), _stratum("aaaa", "host-A", [120.0])]
    claims = []
    for s in strata:
        sid = s["stratum_id"]
        claims += [
            {"claim_id": f"{sid}/outcomes/P01", "stratum_id": sid, "table": "outcomes", "row": "P01", "source_runs": ["a"]},
            {"claim_id": f"{sid}/outcomes/P02", "stratum_id": sid, "table": "outcomes", "row": "P02", "source_runs": ["b"]},
            {"claim_id": f"{sid}/latency/trial_time_ms_p50", "stratum_id": sid, "table": "latency",
             "row": "trial_time_ms_p50", "source_runs": ["a"]},
            {"claim_id": f"{sid}/session_retest/P01", "stratum_id": sid, "table": "session_retest",
             "row": "P01", "source_runs": ["a"]},
        ]
    return {
        "analysis_version": "1.0", "provisional": True, "study_mode": "research",
        "aggregation_unit": "participant",
        "counts": {
            "loaded": {"runs": 4, "participants": 2, "sessions": 3, "trials_by_task": {"gaze_routing_4_pane": 83},
                       "distinct_hosts": 2, "host_identity": ["links file host_id"]},
            "analysed": {"runs": 3, "participants": 2, "sessions": 3, "trials_by_task": {"gaze_routing_4_pane": 83},
                         "distinct_hosts": 2, "host_identity": ["links file host_id"]},
        },
        "exclusions": [{"run": "p", "category": "pilot", "reason": "pilot", "predefined": True, "rule": "x"}],
        "missing_data": [{"run": "c", "family": "latency", "reason": "not_measured"}],
        "strata": strata,
        "claim_manifest": sorted(claims, key=lambda c: c["claim_id"]),
    }


def build(rep: dict[str, Any]) -> dict[str, bytes]:
    raw = json.dumps(rep, sort_keys=True).encode("utf-8")
    return F.build_outputs(rep, raw)


def rows(files: dict[str, bytes], name: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(files[name].decode("utf-8"))))


# --- refusals ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda r: r.__setitem__("analysis_version", "2.0"), "analysis_version"),
        (lambda r: r.__setitem__("provisional", False), "provisional"),
        (lambda r: r["strata"][0].__setitem__("stratum_id", "../evil"), "plain token"),
        (lambda r: r["strata"][1].__setitem__("stratum_id", "bbbb"), "repeats"),
        (lambda r: r["strata"][0]["units"][0]["outcomes"]["correct_target"].__setitem__("rate", 1.5), r"\[0, 1\]"),
        (lambda r: r["strata"][0]["units"][0]["outcomes"]["correct_target"].__setitem__("ci95_wilson", [0.9, 0.95]),
         "lo <= rate <= hi"),
        (lambda r: r.pop("claim_manifest"), "claim_manifest"),
        (lambda r: r.pop("aggregation_unit"), "aggregation_unit"),
    ],
)
def test_a_bad_report_is_refused_and_nothing_is_built(mutate: Any, match: str) -> None:
    rep = report()
    mutate(rep)
    with pytest.raises(F.FiguresError, match=match):
        build(rep)


def test_a_non_object_report_is_refused() -> None:
    assert F.check_report([1, 2]) and "JSON object" in F.check_report([1, 2])[0]


# --- integrity ----------------------------------------------------------------------------


def test_insufficient_data_is_never_written_as_zero() -> None:
    files = build(report())
    p02 = [r for r in rows(files, "tables/outcomes.csv") if r["unit"] == "P02"]
    assert p02 and all(r["rate"] == "" and r["ci95_lo"] == "" and r["k"] == "" for r in p02)
    assert all(r["status"].startswith(INSUFFICIENT) and r["n"] == "3" for r in p02)
    svg = files["figures/outcomes_bbbb.svg"].decode("utf-8")
    assert "P02 / correct_target" in svg and INSUFFICIENT in svg
    # P01 has 4 categories drawn as dots; P02 has none.
    assert svg.count("<circle") == 4


def test_wrong_target_fallback_and_lost_tracking_stay_separate_rows() -> None:
    cats = {r["category"] for r in rows(build(report()), "tables/outcomes.csv")}
    assert {"wrong_target", "fallback_no_route", "invalid_tracking", "correct_target"} <= cats
    assert not any("error" in c for c in cats)


def test_latency_is_one_figure_per_stratum_and_never_pooled() -> None:
    files = build(report())
    assert {"figures/latency_aaaa.svg", "figures/latency_bbbb.svg"} <= set(files)
    lat = rows(files, "tables/latency.csv")
    assert {(r["stratum_id"], r["host"]) for r in lat} == {("aaaa", "host-A"), ("bbbb", "host-B")}
    assert sorted(r["p50_ms"] for r in lat if r["stratum_id"] == "bbbb") == ["650.5000", "900.0000"]
    a_svg = files["figures/latency_aaaa.svg"].decode("utf-8")
    assert a_svg.count("<circle") == 1 and "host=host-A" in a_svg and "not_measured=1" in a_svg


def test_counts_keep_participants_sessions_runs_and_hosts_apart() -> None:
    got = {r["scope"]: r for r in rows(build(report()), "tables/counts.csv")}
    assert got["analysed"]["participants"] == "2" and got["analysed"]["sessions"] == "3"
    assert got["analysed"]["runs"] == "3" and got["analysed"]["distinct_hosts"] == "2"
    assert got["loaded"]["runs"] == "4"


def test_exclusions_and_missing_data_are_tabled_with_reasons() -> None:
    files = build(report())
    ex = rows(files, "tables/exclusions.csv")
    assert ex == [{"run": "p", "category": "pilot", "reason": "pilot", "predefined": "true", "detail": '{"rule":"x"}'}]
    assert rows(files, "tables/missing_data.csv") == [{"run": "c", "family": "latency", "reason": "not_measured"}]


def test_the_manifest_places_every_claim_and_hashes_every_file() -> None:
    rep = report()
    raw = json.dumps(rep, sort_keys=True).encode("utf-8")
    files = F.build_outputs(rep, raw)
    manifest = json.loads(files["manifest.json"])
    assert manifest["source_report_sha256"] == hashlib.sha256(raw).hexdigest()
    listed = {e["path"]: e for e in manifest["files"]}
    assert set(listed) == set(files) - {"manifest.json"}
    for path, entry in listed.items():
        assert entry["sha256"] == hashlib.sha256(files[path]).hexdigest()
    placed = {c["claim_id"] for e in manifest["files"] for c in e["claims"]}
    assert placed == {c["claim_id"] for c in rep["claim_manifest"]}
    assert manifest["claims_without_a_file"] == []
    fig = {c["claim_id"] for c in listed["figures/outcomes_aaaa.svg"]["claims"]}
    assert fig == {"aaaa/outcomes/P01", "aaaa/outcomes/P02"}


def test_output_is_byte_identical_regardless_of_input_order() -> None:
    a = report()
    b = copy.deepcopy(a)
    b["strata"].reverse()
    b["claim_manifest"].reverse()
    fa, fb = build(a), build(b)
    assert {k: v for k, v in fa.items() if k != "manifest.json"} == {k: v for k, v in fb.items() if k != "manifest.json"}
    ma, mb = json.loads(fa["manifest.json"]), json.loads(fb["manifest.json"])
    assert ma["files"] == mb["files"]
    assert build(a) == fa  # same input, same bytes


def test_text_is_escaped_in_svg() -> None:
    rep = report()
    rep["strata"][0]["stratum"]["task"] = "a<b&c"
    svg = build(rep)["figures/outcomes_bbbb.svg"].decode("utf-8")
    assert "a&lt;b&amp;c" in svg and "a<b&c" not in svg


# --- end to end against the committed synthetic fixtures ----------------------------------


def _fixture_report() -> tuple[dict[str, Any], bytes]:
    names = ["gaze_community_qa.json", "head_pointer_community_qa.json"]
    inputs = [(n, (FIXTURES / n).read_bytes()) for n in names]
    rep = analyze(inputs, unit="run", study_mode="community_qa", min_trials=1, min_units=1)
    text = dump_report(rep).encode("utf-8")
    return json.loads(text), text


def test_committed_fixtures_flow_through_analysis_into_tables_and_figures() -> None:
    rep, raw = _fixture_report()
    files = F.build_outputs(rep, raw)
    sids = sorted(s["stratum_id"] for s in rep["strata"])
    # Only the gaze fixture carries outcome counts the 1.0 analysis reads; the head-pointer
    # fixture has none of hit/miss/abandoned/tracking_lost, so it is EXCLUDED with a reason,
    # and that exclusion must reach the table rather than vanish.
    assert len(sids) == 1
    for sid in sids:
        assert f"figures/outcomes_{sid}.svg" in files and f"figures/latency_{sid}.svg" in files
    ex = rows(files, "tables/exclusions.csv")
    assert len(ex) == 1 and ex[0]["reason"] == "not_measured" and ex[0]["predefined"] == "true"
    counts = {r["scope"]: r for r in rows(files, "tables/counts.csv")}
    assert counts["loaded"]["runs"] == "2" and counts["analysed"]["runs"] == "1"
    assert counts["analysed"]["participants"] == "not available (no links file)"
    gaze = [r for r in rows(files, "tables/outcomes.csv") if r["task"] == "gaze_routing_4_pane"]
    by_cat = {r["category"]: r for r in gaze}
    # The fixture's own counts: 35 / 2 / 3 / 0 of 40.
    assert by_cat["correct_target"]["k"] == "35" and by_cat["correct_target"]["n"] == "40"
    assert by_cat["wrong_target"]["k"] == "2" and by_cat["fallback_no_route"]["k"] == "3"
    manifest = json.loads(files["manifest.json"])
    placed = {c["claim_id"] for e in manifest["files"] for c in e["claims"]}
    assert placed | set(manifest["claims_without_a_file"]) == {c["claim_id"] for c in rep["claim_manifest"]}


def test_cli_writes_the_same_bytes_as_build_outputs(tmp_path: Path) -> None:
    rep, raw = _fixture_report()
    src = tmp_path / "report.json"
    src.write_bytes(raw)
    out = tmp_path / "out"
    assert F.main([str(src), "--out", str(out)]) == 0
    expected = F.build_outputs(rep, raw)
    written = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    assert written == expected


def test_cli_refuses_a_bad_report_and_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "report.json"
    src.write_text(json.dumps({"analysis_version": "9.0"}), encoding="utf-8")
    out = tmp_path / "out"
    assert F.main([str(src), "--out", str(out)]) == 1
    assert not out.exists()


def test_cli_requires_an_output_directory(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as info:
        F.main([str(tmp_path / "report.json")])
    assert info.value.code == 2


# --- QA follow-ups ------------------------------------------------------------------------


def test_long_run_unit_labels_are_not_clipped_off_the_left_edge() -> None:
    # `--unit run` names each row "<file>@<hash> / <category>" (~55 characters); with a fixed
    # 260 px label column the right-anchored labels started off-canvas and were cut off.
    import re

    rep, raw = _fixture_report()
    files = F.build_outputs(rep, raw)
    (sid,) = [s["stratum_id"] for s in rep["strata"]]
    svg = files[f"figures/outcomes_{sid}.svg"].decode("utf-8")
    width = float(re.search(r'<svg [^>]*width="([0-9.]+)"', svg).group(1))  # type: ignore[union-attr]
    labels = re.findall(r'<text x="([0-9.]+)" y="[0-9.]+" text-anchor="end">([^<]+)</text>', svg)
    assert labels and all(len(t) > 40 for _, t in labels)
    for x, text in labels:
        assert float(x) - F._CHAR * len(text) >= 0, text
    title = re.search(r'<text x="12" y="22" font-size="14" font-weight="bold">([^<]+)</text>', svg)
    subtitle = re.search(r'<text x="12" y="42" fill="#333333">([^<]+)</text>', svg)
    assert title and subtitle
    assert 12 + F._TITLE_CHAR * len(title.group(1)) <= width
    assert 12 + F._CHAR * len(subtitle.group(1)) <= width


def test_whole_number_latency_and_exposure_keep_the_fixed_number_format() -> None:
    # analysis `_tidy()` writes 900.0 as the int 900; the column must still read 900.0000.
    rep = report()
    rep["strata"][0]["latency"]["per_run_p50"] = [900, 650.5]
    rep["strata"][0]["units"][0]["false_activations"] = {
        "events": 2, "exposure_s": 3600, "per_hour": 2.0, "provisional": True}
    files = build(rep)
    assert sorted(r["p50_ms"] for r in rows(files, "tables/latency.csv") if r["stratum_id"] == "bbbb") == [
        "650.5000", "900.0000"]
    (fa,) = rows(files, "tables/false_activations.csv")
    assert fa["exposure_s"] == "3600.0000" and fa["per_hour"] == "2.0000" and fa["events"] == "2"
