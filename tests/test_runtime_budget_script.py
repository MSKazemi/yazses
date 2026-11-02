"""The nightly runtime-budget gate (`scripts/check_runtime_budget.py`, ADR-029 section 4).

The script decides whether the nightly job passed, so its failure modes are the contract:
a run that measured nothing must fail, a skipped unit must be named, and a malformed file
must exit 2 with a message rather than a traceback. Each test runs `main()` in-process over
files in `tmp_path`; one subprocess test checks the entry point a human actually types.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from yazses.system import residency

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_runtime_budget.py"
COMMITTED = ROOT / "scripts" / "runtime_budget.json"


@pytest.fixture(scope="module")
def crb():
    spec = importlib.util.spec_from_file_location("check_runtime_budget", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _budget_file(tmp_path: Path, ceilings: dict[str, float | None] | None = None) -> Path:
    """A budget covering every policy unit; *ceilings* overrides the given units only."""
    rows = {unit: None for unit in residency.DEFAULT_POLICY.units()}
    rows.update(ceilings or {})
    path = tmp_path / "budget.json"
    path.write_text(
        json.dumps({u: {"peak_rss_mb": v, "idle_cpu_s_per_min": None} for u, v in rows.items()}),
        encoding="utf-8",
    )
    return path


def _measured_file(tmp_path: Path, body: object, name: str = "measured.json") -> Path:
    path = tmp_path / name
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return path


def _run(crb, tmp_path: Path, measured: object, ceilings=None) -> int:
    return crb.main([
        "--budget", str(_budget_file(tmp_path, ceilings)),
        "--measured", str(_measured_file(tmp_path, measured)),
    ])


ALL_UNITS = sorted(residency.DEFAULT_POLICY.units())


def _every_unit_at(value: float) -> dict[str, float]:
    return {unit: value for unit in ALL_UNITS}


# ---- verdicts ------------------------------------------------------------------


def test_a_run_within_every_ceiling_passes(crb, tmp_path, capsys) -> None:
    ceilings = {"stt": 343.0, "latency": 116.0}
    assert _run(crb, tmp_path, _every_unit_at(10.0), ceilings) == 0
    assert "OK:" in capsys.readouterr().out


def test_a_peak_over_the_tolerance_is_a_breach_named_with_the_amount(crb, tmp_path, capsys) -> None:
    measured = _every_unit_at(10.0) | {"stt": 500.0}
    assert _run(crb, tmp_path, measured, {"stt": 343.0, "latency": 116.0}) == 1
    out = capsys.readouterr().out
    breach_lines = [line for line in out.splitlines() if line.startswith("BREACH")]
    assert breach_lines == [
        "BREACH " + residency.Breach("stt", 500.0, 343.0).describe(),
    ]


def test_a_peak_within_the_tolerance_is_not_a_breach(crb, tmp_path) -> None:
    """Tolerance is the ADR's 1.2: 343 x 1.2 = 411.6, so 411 passes and 412 breaches."""
    ceilings = {"stt": 343.0, "latency": 116.0}
    assert _run(crb, tmp_path, _every_unit_at(10.0) | {"stt": 411.0}, ceilings) == 0
    assert _run(crb, tmp_path, _every_unit_at(10.0) | {"stt": 412.0}, ceilings) == 1


def test_an_unmeasured_budgeted_unit_fails_and_is_named(crb, tmp_path, capsys) -> None:
    assert _run(crb, tmp_path, {"stt": 100.0}, {"stt": 343.0, "latency": 116.0}) == 1
    out = capsys.readouterr().out
    assert "UNMEASURED latency" in out
    assert "UNMEASURED diarize" in out
    assert "UNMEASURED stt" not in out


def test_an_empty_measurement_fails_and_is_not_a_pass(crb, tmp_path, capsys) -> None:
    assert _run(crb, tmp_path, {}) == 1
    err = capsys.readouterr().err
    assert "measured nothing" in err


def test_the_emit_template_skeleton_is_all_unmeasured_so_it_cannot_pass(crb, tmp_path) -> None:
    template = tmp_path / "template.json"
    template.write_text(crb.emit_template(sorted(crb.load_budget(COMMITTED))), encoding="utf-8")
    assert crb.main(["--measured", str(template)]) == 1


def test_an_unbudgeted_unit_with_no_ceiling_is_not_a_breach(crb, tmp_path, capsys) -> None:
    """A unit with a null ceiling is reported as a note, never as a breach."""
    assert _run(crb, tmp_path, _every_unit_at(10.0) | {"diarize": 9999.0},
                {"stt": 343.0, "latency": 116.0}) == 0
    assert "NOTE diarize" in capsys.readouterr().out


# ---- malformed input -> exit 2, no traceback ---------------------------------------


def test_malformed_json_exits_two_with_a_message_not_a_traceback(crb, tmp_path, capsys) -> None:
    assert _run(crb, tmp_path, "{not json") == 2
    captured = capsys.readouterr()
    assert "not valid JSON" in captured.err
    assert "Traceback" not in captured.err


def test_a_file_that_is_not_utf8_exits_two_not_a_traceback(crb, tmp_path, capsys) -> None:
    path = tmp_path / "binary.json"
    path.write_bytes(b"\xff\xfe{")
    rc = crb.main(["--budget", str(_budget_file(tmp_path)), "--measured", str(path)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "not UTF-8" in captured.err
    assert "Traceback" not in captured.err


def test_a_missing_measured_file_exits_two(crb, tmp_path, capsys) -> None:
    rc = crb.main(["--budget", str(_budget_file(tmp_path)),
                   "--measured", str(tmp_path / "absent.json")])
    assert rc == 2
    assert "cannot read" in capsys.readouterr().err


def test_a_measured_file_that_is_not_an_object_exits_two(crb, tmp_path) -> None:
    assert _run(crb, tmp_path, [1, 2, 3]) == 2


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", '"big"', "true"])
def test_a_nan_negative_or_non_numeric_figure_exits_two(crb, tmp_path, bad: str) -> None:
    assert _run(crb, tmp_path, '{"stt": %s}' % bad) == 2


def test_an_unknown_unit_in_the_measured_file_exits_two_and_is_named(crb, tmp_path, capsys) -> None:
    """A misspelt unit must not quietly leave its real unit unmeasured."""
    assert _run(crb, tmp_path, {"sst": 100.0}) == 2
    assert "'sst'" in capsys.readouterr().err


def test_a_budget_missing_a_policy_unit_exits_two(crb, tmp_path, capsys) -> None:
    budget = _budget_file(tmp_path)
    data = json.loads(budget.read_text(encoding="utf-8"))
    del data["tts"]
    budget.write_text(json.dumps(data), encoding="utf-8")
    rc = crb.main(["--budget", str(budget), "--measured", str(_measured_file(tmp_path, {}))])
    assert rc == 2
    assert "tts" in capsys.readouterr().err


def test_a_budget_with_an_unknown_unit_exits_two(crb, tmp_path) -> None:
    budget = _budget_file(tmp_path)
    data = json.loads(budget.read_text(encoding="utf-8"))
    data["gazee"] = {"peak_rss_mb": 1.0}
    budget.write_text(json.dumps(data), encoding="utf-8")
    rc = crb.main(["--budget", str(budget), "--measured", str(_measured_file(tmp_path, {}))])
    assert rc == 2


@pytest.mark.parametrize("bad", [-5.0, "NaN", "huge"])
def test_a_budget_ceiling_that_is_negative_nan_or_not_a_number_exits_two(
    crb, tmp_path, bad,
) -> None:
    budget = _budget_file(tmp_path)
    data = json.loads(budget.read_text(encoding="utf-8"))
    data["stt"]["peak_rss_mb"] = bad
    budget.write_text(json.dumps(data), encoding="utf-8")
    rc = crb.main(["--budget", str(budget), "--measured", str(_measured_file(tmp_path, {}))])
    assert rc == 2


def test_measured_is_required_unless_emitting_a_template(crb, tmp_path) -> None:
    with pytest.raises(SystemExit) as exc:
        crb.main(["--budget", str(_budget_file(tmp_path))])
    assert exc.value.code == 2


# ---- the committed budget and the template -------------------------------------


def test_the_committed_budget_parses_and_covers_exactly_the_policy_units(crb) -> None:
    rows = crb.load_budget(COMMITTED)
    assert set(rows) == set(residency.DEFAULT_POLICY.units())


def test_the_committed_ceilings_are_only_the_adr_stated_figures(crb) -> None:
    """Every stated figure is pinned; every other unit is an honest null, not a guess."""
    rows = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert rows["stt"]["peak_rss_mb"] == residency.MEASURED_FA058766_MB["stt.base.en.load_peak"]
    assert rows["latency"]["peak_rss_mb"] == residency.MEASURED_FA058766_MB["latency.tiny.en"]
    for unit in set(residency.DEFAULT_POLICY.units()) - {"stt", "latency"}:
        assert rows[unit]["peak_rss_mb"] is None, unit
        assert rows[unit]["status"] == "proposal", unit
        assert rows[unit]["note"], unit


def test_every_committed_row_carries_its_status_and_a_note(crb) -> None:
    rows = json.loads(COMMITTED.read_text(encoding="utf-8"))
    for unit, row in rows.items():
        if unit.startswith("_"):
            continue
        assert row["status"] in {"baseline", "proposal"}, unit
        assert row["note"].strip(), unit
        assert row["idle_cpu_s_per_min"] is None, unit


def test_the_committed_budget_has_a_comment_saying_it_is_to_be_replaced() -> None:
    comment = json.loads(COMMITTED.read_text(encoding="utf-8"))["_comment"]
    assert "replaced" in comment and "nightly" in comment


def test_the_template_names_every_budgeted_unit_with_null(crb, tmp_path) -> None:
    template = json.loads(crb.emit_template(ALL_UNITS))
    assert set(template) == set(ALL_UNITS)
    assert all(value is None for value in template.values())


def test_the_entry_point_emits_the_template_and_exits_zero() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--emit-template"],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert set(json.loads(proc.stdout)) == set(residency.DEFAULT_POLICY.units())
