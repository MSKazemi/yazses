"""The generated eye/camera validation coverage dashboard.

`design/eye-control/generated/validation-coverage.md` is generated from the slot registry
by `scripts/gen-eye-validation-dashboard.py`. This file gates three failure shapes this
repository has shipped before, and then the acceptance criteria of the dashboard itself.

**An "is it in sync?" test cannot notice an omission.** Regenerating and comparing only
proves the file matches its generator, so a generator that silently drops a cell agrees
with its own output and the drift test stays green. Completeness is therefore asserted
against the *registry*, by id and by row count, and the drop is simulated here so the
assertion is known to fire.

**A check that cannot parse its input must fail loudly.** A missing, unreadable or
non-JSON registry exits 2 and produces no page. It never degrades into a short page that
reads as coverage.

**A guard that only iterates is green on an empty collection.** A registry with zero slots
is an error, not a blank dashboard.

The acceptance criteria from the issue are tested as behaviour: one complete A/B cell, one
PLANNED cell, one FAIL cell and one test/retest cell -- and, above all, that a FAIL is
never counted as missing evidence and that one person's three sessions are never rendered
as three independent hosts.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / "scripts" / "gen-eye-validation-dashboard.py"
REGISTRY_PATH = ROOT / "design" / "eye-control" / "validation-slots.json"
PAGE_PATH = ROOT / "design" / "eye-control" / "generated" / "validation-coverage.md"


def _load_generator():
    """Load the hyphenated script as a module.

    It is registered in ``sys.modules`` *before* execution, not after: a frozen
    ``@dataclass`` at module scope resolves its own module out of ``sys.modules`` while the
    decorator runs, and an unregistered module makes that lookup return ``None``.
    """
    name = "gen_eye_validation_dashboard"
    spec = importlib.util.spec_from_file_location(name, GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _page() -> str:
    return PAGE_PATH.read_text(encoding="utf-8")


def _slot(**overrides: Any) -> dict[str, Any]:
    """A minimal valid PLANNED cell, so each test varies exactly one thing."""
    slot: dict[str, Any] = {
        "id": "T0-WIN-A",
        "pack": "T0",
        "environment": "WIN",
        "session": "Windows 11",
        "slot": "A",
        "state": "planned",
        "issue": 428,
        "blocked_by": [423],
        "additional_blockers": None,
        "sessions": 1,
        "time_estimate_minutes": {"min": 15, "max": 20},
        "hardware_required": True,
        "beginner_safe": True,
        "cloud_agent_ready": False,
        "public": True,
        "evidence_mode": "community_qa",
        "requirement": "first independent Windows host",
    }
    slot.update(overrides)
    return slot


def _ready(**overrides: Any) -> dict[str, Any]:
    """A cell that has actually become runnable, for the reported-outcome cases."""
    return _slot(state="ready", blocked_by=[], additional_blockers=None, **overrides)


def _doc(*slots: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_from": ["design/eye-control/VALIDATION_MATRIX.md"],
        "slots": list(slots),
    }


def _write(tmp_path: Path, document: Any, name: str = "registry.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


#: The heading above the one-row-per-cell table. Rows are selected from inside this
#: section rather than by prefix: cell ids start table rows in the blocker tables too, and
#: a prefix match counted those as detail rows.
_DETAIL_HEADING = "## Every registered cell"


def _section(page: str, heading: str) -> list[str]:
    """The lines under ``heading``, up to the next top-level heading."""
    lines = page.splitlines()
    assert heading in lines, f"the page has no {heading!r} section"
    out: list[str] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("## "):
            break
        out.append(line)
    return out


def _detail_rows(page: str) -> list[str]:
    return [line for line in _section(page, _DETAIL_HEADING) if line.startswith("| `")]


def _row(page: str, cell_id: str) -> str:
    """The detail-table row for one cell, so a test can assert about that row only."""
    matches = [line for line in _detail_rows(page) if line.startswith(f"| `{cell_id}` |")]
    assert len(matches) == 1, f"expected exactly one detail row for {cell_id}, got {len(matches)}"
    return matches[0]


# --------------------------------------------------------------------------- baseline


def test_the_committed_page_exists():
    assert PAGE_PATH.is_file(), (
        "design/eye-control/generated/validation-coverage.md is missing — regenerate it with "
        "`uv run python scripts/gen-eye-validation-dashboard.py` and commit."
    )


def test_the_committed_page_is_in_sync_with_the_generator():
    assert gen.generate(REGISTRY_PATH) == _page(), (
        "design/eye-control/generated/validation-coverage.md is stale — run "
        "`uv run python scripts/gen-eye-validation-dashboard.py` and commit."
    )


def test_the_check_mode_agrees_that_the_committed_page_is_current():
    assert gen.main(["--check"]) == 0


def test_check_mode_fails_on_a_stale_page(tmp_path):
    stale = tmp_path / "validation-coverage.md"
    stale.write_text("# not the dashboard\n", encoding="utf-8")
    assert gen.main(["--check", "--output", str(stale)]) == 1


def test_the_synthetic_baseline_cell_renders(tmp_path):
    """Guard the guard: if this fails, every negative test below proves nothing."""
    page = gen.generate(_write(tmp_path, _doc(_slot())))
    assert "T0-WIN-A" in page


# ------------------------------------------- an omission a sync test cannot see (trap 3)


def test_every_registered_cell_appears_in_the_committed_page_by_id():
    """By id, against the registry — not by regenerating, which cannot see a drop."""
    assert gen.missing_cells(_page(), _registry()) == []


def test_the_committed_page_has_exactly_one_detail_row_per_registered_cell():
    """By count as well as by id, so a duplicated or invented row also fails."""
    assert len(_detail_rows(_page())) == len(_registry()["slots"])


def test_the_completeness_check_names_a_cell_the_page_dropped():
    """The simulated drop: a page rendered from 15 of 16 cells must be reported short."""
    registry = _registry()
    short = copy.deepcopy(registry)
    dropped = short["slots"].pop()
    page = gen.render(gen.build_coverage(short))
    assert gen.missing_cells(page, registry) == [dropped["id"]]


def test_a_generator_that_silently_drops_a_cell_refuses_to_write(monkeypatch, tmp_path):
    """The same failure end to end: rendering loses a cell, so no page is produced.

    A regenerate-and-compare test would be green here, because the generator and its own
    output would agree. `generate` re-checks the rendered page against the registry.
    """
    full = gen.render

    def dropping_render(coverage):
        return full(gen.Coverage(schema_version=coverage.schema_version,
                                 cells=coverage.cells[:-1]))

    monkeypatch.setattr(gen, "render", dropping_render)
    with pytest.raises(gen.DashboardError) as excinfo:
        gen.generate(REGISTRY_PATH)
    assert "missing registered cell" in str(excinfo.value)
    assert gen.main(["--output", str(tmp_path / "out.md")]) == 1


# --------------------------------------------- input it cannot parse must fail (trap 2)


def test_a_missing_registry_raises_rather_than_rendering_an_empty_page(tmp_path):
    with pytest.raises(gen.RegistryError):
        gen.generate(tmp_path / "nope.json")


@pytest.mark.parametrize("payload", ["", "{", "null", "[]", "not json at all"])
def test_the_cli_exits_two_on_a_registry_it_cannot_parse(tmp_path, payload):
    path = tmp_path / "registry.json"
    path.write_text(payload, encoding="utf-8")
    assert gen.main(["--registry", str(path), "--output", str(tmp_path / "out.md")]) == 2


def test_the_cli_exits_two_on_an_outcome_file_it_cannot_parse(tmp_path):
    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text("{", encoding="utf-8")
    assert (
        gen.main(
            [
                "--outcomes", str(outcomes),
                "--output", str(tmp_path / "out.md"),
            ]
        )
        == 2
    )


def test_an_unreadable_outcome_file_says_which_input_failed(tmp_path):
    """Both inputs share one loader, so the message has to name the one that broke."""
    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text("nope", encoding="utf-8")
    with pytest.raises(gen.RegistryError) as excinfo:
        gen.generate(REGISTRY_PATH, outcomes)
    assert "reported-outcome document" in str(excinfo.value)


def test_no_page_is_written_when_the_registry_cannot_be_parsed(tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text("{", encoding="utf-8")
    out = tmp_path / "out.md"
    assert gen.main(["--registry", str(registry), "--output", str(out)]) == 2
    assert not out.exists(), "an unreadable registry produced a file, which reads as coverage"


def test_an_invalid_registry_produces_no_page_at_all(tmp_path):
    """A registry that parses but breaks a rule is refused, not rendered."""
    bad = _doc(_slot(evidence_mode="research"))
    out = tmp_path / "out.md"
    assert gen.main(["--registry", str(_write(tmp_path, bad)), "--output", str(out)]) == 1
    assert not out.exists()


# ------------------------------------------- an empty collection must not pass (trap 1)


def test_an_empty_registry_raises_instead_of_rendering_a_blank_dashboard():
    with pytest.raises(gen.DashboardError) as excinfo:
        gen.build_coverage(_doc())
    assert "empty coverage page" in str(excinfo.value)


def test_the_cli_exits_one_on_an_empty_registry(tmp_path):
    out = tmp_path / "out.md"
    assert gen.main(["--registry", str(_write(tmp_path, _doc())), "--output", str(out)]) == 1
    assert not out.exists()


def test_a_registry_with_no_slots_key_raises():
    with pytest.raises(gen.DashboardError):
        gen.build_coverage({"schema_version": 1, "generated_from": ["x"]})


def test_an_empty_outcome_file_is_an_error_not_a_silent_no_op(tmp_path):
    out = tmp_path / "out.md"
    empty = _write(tmp_path, {"schema_version": 1, "cells": {}}, "outcomes.json")
    assert gen.main(["--outcomes", str(empty), "--output", str(out)]) == 1
    assert not out.exists()


def test_the_completeness_check_itself_is_not_vacuous():
    """`missing_cells` on a page containing nothing must name every cell, not return []."""
    registry = _registry()
    assert len(gen.missing_cells("", registry)) == len(registry["slots"])


# ------------------------------------------------------------------ acceptance criteria


def test_the_page_carries_a_do_not_hand_edit_marker():
    head = _page().splitlines()[0]
    assert "GENERATED by scripts/gen-eye-validation-dashboard.py" in head
    assert "do not edit by hand" in head


def test_issue_links_are_derived_from_the_registry(tmp_path):
    page = gen.generate(_write(tmp_path, _doc(_slot(issue=428))))
    assert "[#428](https://github.com/MSKazemi/yazses/issues/428)" in page


def test_a_cell_with_no_issue_is_not_given_one(tmp_path):
    page = gen.generate(_write(tmp_path, _doc(_slot(issue=None))))
    assert "none yet" in _row(page, "T0-WIN-A")
    assert "/issues/428" not in page


def test_every_registry_issue_number_is_linked_on_the_committed_page():
    page = _page()
    for slot in _registry()["slots"]:
        if slot.get("issue") is not None:
            assert f"](https://github.com/MSKazemi/yazses/issues/{slot['issue']})" in page


def test_a_planned_cell_is_shown_as_not_runnable_and_awaiting_a_first_report(tmp_path):
    row = _row(gen.generate(_write(tmp_path, _doc(_slot()))), "T0-WIN-A")
    assert "| PLANNED |" in row
    assert "| no |" in row
    assert "awaiting first report" in row


def test_a_ready_cell_is_shown_as_runnable(tmp_path):
    row = _row(gen.generate(_write(tmp_path, _doc(_ready()))), "T0-WIN-A")
    assert "| READY |" in row
    assert "| yes |" in row


def test_a_complete_ab_cell_reports_both_slots_and_two_independent_hosts():
    registry = _doc(
        _ready(),
        _ready(id="T0-WIN-B", slot="B", issue=429, requirement="different computer"),
    )
    outcomes = {
        "T0-WIN-A": {"outcome": "pass", "independent_hosts": 1, "repeat_sessions": 0},
        "T0-WIN-B": {"outcome": "pass", "independent_hosts": 1, "repeat_sessions": 0},
    }
    coverage = gen.build_coverage(registry, outcomes)
    counts = coverage.counts()
    assert counts["reported"] == 2
    assert counts["outcome_pass"] == 2
    assert counts["awaiting_first_report"] == 0
    assert counts["independent_hosts"] == 2
    assert counts["repeat_sessions"] == 0

    page = gen.render(coverage)
    assert "PASS" in _row(page, "T0-WIN-A")
    assert "PASS" in _row(page, "T0-WIN-B")
    assert "A (READY, PASS), B (READY, PASS)" in page


def test_a_failed_cell_is_reported_evidence_and_never_missing_evidence():
    coverage = gen.build_coverage(
        _doc(_ready()),
        {"T0-WIN-A": {"outcome": "fail", "independent_hosts": 1, "repeat_sessions": 0}},
    )
    counts = coverage.counts()
    assert counts["outcome_fail"] == 1
    assert counts["reported"] == 1
    # The criterion: a FAIL must not be counted among the cells that lack a report.
    assert counts["awaiting_first_report"] == 0

    row = _row(gen.render(coverage), "T0-WIN-A")
    assert "FAIL" in row
    assert "awaiting first report" not in row


def test_a_blocked_cell_is_reported_evidence_too():
    coverage = gen.build_coverage(
        _doc(_ready()),
        {"T0-WIN-A": {"outcome": "blocked", "independent_hosts": 1, "repeat_sessions": 0}},
    )
    counts = coverage.counts()
    assert counts["outcome_blocked"] == 1
    assert counts["awaiting_first_report"] == 0
    assert "BLOCKED" in _row(gen.render(coverage), "T0-WIN-A")


def test_three_sessions_on_one_machine_are_one_host_and_three_repeat_sessions():
    """The matrix's first rule: ten sessions by one person are not ten computers."""
    registry = _doc(
        _ready(
            id="T1-ANY-REPEAT",
            pack="T1",
            environment="ANY",
            session="any platform where T1 is actually supported",
            slot="repeat",
            issue=437,
            sessions=3,
            requirement="same person / same machine; three separated sessions",
        )
    )
    outcomes = {
        "T1-ANY-REPEAT": {"outcome": "pass", "independent_hosts": 1, "repeat_sessions": 3}
    }
    coverage = gen.build_coverage(registry, outcomes)
    counts = coverage.counts()
    assert counts["independent_hosts"] == 1
    assert counts["repeat_sessions"] == 3

    page = gen.render(coverage)
    row = _row(page, "T1-ANY-REPEAT")
    assert "1 independent host" in row
    assert "3 repeat sessions" in row
    assert "3 independent" not in page, "repeat sessions were counted as independent hosts"


def test_the_repeat_cell_on_the_committed_page_shows_its_session_count_not_a_host_count():
    row = _row(_page(), "T1-ANY-REPEAT")
    assert "| 3 |" in row, "the registry plans three sessions for the test/retest cell"
    assert "3 independent" not in _page()


def test_the_page_states_that_a_failure_is_not_missing_evidence():
    assert "A FAIL or BLOCKED report is evidence, not missing evidence." in _page()


def test_the_page_states_that_hosts_and_repeat_sessions_are_different_units():
    assert "Independent hosts and repeat sessions are different units." in _page()


def test_the_page_does_not_present_beginner_safety_as_a_live_label():
    """#454 defines `beginner_safe` as intrinsic difficulty; the page must not imply a label."""
    page = _page()
    assert "intrinsic difficulty, not a live label" in page
    rows = [
        line
        for line in page.splitlines()
        if line.startswith("| Cells whose task is intrinsically beginner-safe")
    ]
    assert len(rows) == 1, "the summary must carry exactly one beginner-safety row"
    assert "not a live label" in rows[0]


def test_the_page_says_it_reports_the_registry_rather_than_github():
    assert "It reports the committed registry, not GitHub." in _page()


def test_unmet_blockers_are_grouped_by_prerequisite_issue():
    page = _page()
    blocked_by_423 = [
        slot["id"] for slot in _registry()["slots"] if 423 in slot.get("blocked_by", [])
    ]
    assert blocked_by_423, "the fixture assumes #423 blocks something"
    line = [ln for ln in page.splitlines() if ln.startswith("| [#423](")][0]
    assert f"| {len(blocked_by_423)} |" in line
    for cell_id in blocked_by_423:
        assert f"`{cell_id}`" in line


def test_every_free_text_blocker_in_the_registry_reaches_the_page():
    page = _page()
    conditions = {
        slot["additional_blockers"]
        for slot in _registry()["slots"]
        if slot.get("additional_blockers")
    }
    assert conditions, "the fixture assumes the registry names free-text blockers"
    for condition in conditions:
        assert condition in page


def test_the_gap_table_lists_a_pack_with_no_registered_cell():
    """Where the gaps are: a pack the registry does not cover at all must be visible."""
    registered = {slot["pack"] for slot in _registry()["slots"]}
    uncovered = sorted({f"T{n}" for n in range(8)} - registered)
    assert uncovered, "the fixture assumes some pack has no registered cell"
    gaps = dict(gen.build_coverage(_registry()).gaps())
    for pack in uncovered:
        assert pack in gaps
        assert len(gaps[pack]) == 7, f"{pack} has no cell in any environment"
        assert f"| {pack} |" in _page()


def test_a_gap_is_described_as_an_uncommitted_cell_not_an_overdue_test():
    assert "gaps in the plan, not overdue work" in _page()


def test_the_grid_covers_every_pack_and_environment_in_the_registry_vocabulary():
    """Derived from the validator's vocabulary, so a new value cannot go unshown."""
    page = _page()
    header = [line for line in page.splitlines() if line.startswith("| Pack |")][0]
    for environment in gen.ENVIRONMENTS:
        assert f"| {environment} " in header or f" {environment} |" in header
    for pack in gen.PACKS:
        assert f"| {pack} |" in page


# ------------------------------------------------------- reported-outcome input rules


def test_an_outcome_for_a_cell_that_is_not_registered_is_rejected():
    errors = gen.validate_outcomes(
        {"schema_version": 1, "cells": {"T9-ZZZ-A": {"outcome": "pass"}}}, {"T0-WIN-A"}
    )
    assert any("no such cell" in error for error in errors)


def test_build_coverage_refuses_outcomes_for_unregistered_cells():
    with pytest.raises(gen.DashboardError):
        gen.build_coverage(_doc(_slot()), {"T7-MAC-B": {"outcome": "pass"}})


@pytest.mark.parametrize("outcome", ["ok", "", None, "PASS"])
def test_an_unknown_outcome_class_is_rejected(outcome):
    errors = gen.validate_outcomes(
        {"schema_version": 1, "cells": {"T0-WIN-A": {"outcome": outcome}}}, {"T0-WIN-A"}
    )
    assert any("outcome must be one of" in error for error in errors)


@pytest.mark.parametrize("outcome", list(gen.OUTCOME_ORDER))
def test_every_documented_outcome_class_is_accepted(outcome):
    assert (
        gen.validate_outcomes(
            {"schema_version": 1, "cells": {"T0-WIN-A": {"outcome": outcome}}}, {"T0-WIN-A"}
        )
        == []
    )


@pytest.mark.parametrize("field", ["independent_hosts", "repeat_sessions"])
def test_a_negative_count_is_rejected(field):
    errors = gen.validate_outcomes(
        {"schema_version": 1, "cells": {"T0-WIN-A": {"outcome": "pass", field: -1}}},
        {"T0-WIN-A"},
    )
    assert any(field in error for error in errors)


def test_an_unknown_outcome_key_is_rejected_rather_than_ignored():
    errors = gen.validate_outcomes(
        {"schema_version": 1, "cells": {"T0-WIN-A": {"outcome": "pass", "tester": "x"}}},
        {"T0-WIN-A"},
    )
    assert any("unknown outcome keys" in error for error in errors)


def test_identity_data_in_an_outcome_document_is_rejected():
    """Reuses the registry validator's identity scan: ADR-v2-150 forbids it here too."""
    errors = gen.validate_outcomes(
        {
            "schema_version": 1,
            "description": "reported by someone@example.com",
            "cells": {"T0-WIN-A": {"outcome": "pass"}},
        },
        {"T0-WIN-A"},
    )
    assert any("identity data is forbidden" in error for error in errors)


def test_an_outcome_document_with_the_wrong_schema_version_is_rejected():
    errors = gen.validate_outcomes(
        {"schema_version": 2, "cells": {"T0-WIN-A": {"outcome": "pass"}}}, {"T0-WIN-A"}
    )
    assert any("schema_version" in error for error in errors)


def test_a_valid_outcome_file_reaches_the_rendered_page(tmp_path):
    registry = _write(tmp_path, _doc(_ready()))
    outcomes = _write(
        tmp_path,
        {
            "schema_version": 1,
            "cells": {"T0-WIN-A": {"outcome": "partial", "independent_hosts": 1}},
        },
        "outcomes.json",
    )
    page = gen.generate(registry, outcomes)
    assert "PARTIAL" in _row(page, "T0-WIN-A")


# ------------------------------------------------------------------ offline/determinism


#: Everything the generator may import: the standard library modules it uses, plus the
#: sibling registry validator whose own allowlist test keeps *it* network-free. An
#: allowlist, not a denylist of network module names — a denylist is only as good as the
#: next library nobody thought of.
ALLOWED_IMPORTS = {
    "__future__",
    "argparse",
    "check_eye_validation_slots",
    "dataclasses",
    "pathlib",
    "sys",
    "typing",
}


def test_the_generator_imports_nothing_that_can_reach_the_network():
    tree = ast.parse(GENERATOR.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert imported, "the import scan found nothing, so it proves nothing"
    assert imported <= ALLOWED_IMPORTS, f"unexpected imports: {sorted(imported - ALLOWED_IMPORTS)}"


def test_the_generator_reuses_the_registry_validator_rather_than_reparsing():
    source = GENERATOR.read_text(encoding="utf-8")
    assert "from check_eye_validation_slots import" in source
    assert "load_registry" in source and "validate_registry" in source
    assert "json.loads" not in source, "the generator must not parse the registry itself"


def test_the_page_carries_no_timestamp_or_version_stamp():
    """A stamp would make the committed page drift on a clock or a release, not a change."""
    page = _page()
    assert not re.search(r"\b20\d{2}-\d{2}-\d{2}\b", page)
    assert not re.search(r"\bv?\d+\.\d+\.\d+\b", page)


def test_rendering_is_deterministic():
    registry = _registry()
    first = gen.render(gen.build_coverage(registry))
    second = gen.render(gen.build_coverage(json.loads(json.dumps(registry))))
    assert first == second == _page()


def test_the_output_does_not_depend_on_the_order_of_the_slots_in_the_registry():
    registry = _registry()
    reversed_registry = copy.deepcopy(registry)
    reversed_registry["slots"].reverse()
    assert gen.render(gen.build_coverage(reversed_registry)) == _page()


def test_make_docs_regenerates_the_dashboard():
    """The mechanism, not the freshness: otherwise the page is refreshed by memory alone."""
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    body = text[text.index("\ndocs:\n") + 1 :]
    lines: list[str] = []
    for line in body.splitlines()[1:]:
        if line and not line.startswith(("\t", " ")):
            break
        lines.append(line)
    assert "gen-eye-validation-dashboard.py" in "\n".join(lines)


def test_the_documentation_points_at_the_generated_page():
    """A generated artifact nobody links to is one nobody reads."""
    operations = (ROOT / "design" / "eye-control" / "VALIDATION_OPERATIONS.md").read_text(
        encoding="utf-8"
    )
    assert "generated/validation-coverage.md" in operations
    assert "scripts/gen-eye-validation-dashboard.py" in operations


def test_the_page_ends_with_exactly_one_newline():
    text = _page()
    assert text.endswith("\n") and not text.endswith("\n\n")
