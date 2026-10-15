"""The eye/camera validation slot registry and its offline validator.

Two failure shapes this repository has shipped before are tested here directly, because
in both of them the guard reported success:

* a check that cannot **parse** its input returning an empty result, which then reads as
  compliance -- so a missing, unreadable, non-JSON or wrongly-typed registry must fail
  loudly (exit 2), never validate;
* a guard that only **iterates** being trivially green on an empty collection -- so a
  registry with zero slots must fail, not pass vacuously.

The rest are the policy rules from `design/eye-control/VALIDATION_OPERATIONS.md` and
ADR-v2-150: human hardware evidence is never cloud-agent-ready, public slots are
`community_qa`, and no participant identity or contact data lives in this file.
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
REGISTRY_PATH = ROOT / "design" / "eye-control" / "validation-slots.json"
SCRIPT = ROOT / "scripts" / "check_eye_validation_slots.py"
MATRIX_PATH = ROOT / "design" / "eye-control" / "VALIDATION_MATRIX.md"
CAMPAIGN_PATH = ROOT / "campaign" / "tasks.json"
CAMPAIGN_SCRIPT = ROOT / "scripts" / "campaign.py"

#: Every no-code hardware slot that already exists as a GitHub issue, and the cell it
#: represents. Taken from the VALIDATION_MATRIX.md A/B table and the AGENT_TASKS.md
#: issue map; the numbers are historical facts and must not drift.
HISTORICAL_SLOTS = {
    428: ("T0", "WIN", "A"),
    429: ("T0", "WIN", "B"),
    430: ("T0", "MAC", "A"),
    431: ("T0", "MAC", "B"),
    432: ("T0", "GNOME", "A"),
    433: ("T0", "GNOME", "B"),
    434: ("T0", "KDE", "A"),
    435: ("T0", "X11", "A"),
    436: ("T5", "HIDPI", "A"),
    437: ("T1", "ANY", "repeat"),
    438: ("T0", "KDE", "B"),
    439: ("T0", "X11", "B"),
    440: ("T5", "HIDPI", "B"),
}


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_eye_validation_slots", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _slot(**overrides: Any) -> dict[str, Any]:
    """A minimal valid PLANNED slot, so each test varies exactly one thing."""
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


def _doc(*slots: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_from": ["design/eye-control/VALIDATION_MATRIX.md"],
        "slots": list(slots),
    }


def _errors(*slots: dict[str, Any]) -> list[str]:
    return checker.validate_registry(_doc(*slots), root=ROOT)


# --------------------------------------------------------------------------- baseline


def test_the_committed_registry_is_valid():
    assert checker.validate_registry(_registry(), root=ROOT) == []


def test_the_synthetic_baseline_slot_is_valid():
    """Guards the fixture itself: if this ever fails, every negative test below is a lie."""
    assert _errors(_slot()) == []


# ------------------------------------------------------- cannot-parse must fail loudly


def test_a_missing_registry_raises_rather_than_returning_an_empty_document(tmp_path):
    with pytest.raises(checker.RegistryError):
        checker.load_registry(tmp_path / "nope.json")


def test_an_unparseable_registry_raises_rather_than_returning_an_empty_document(tmp_path):
    broken = tmp_path / "validation-slots.json"
    broken.write_text('{"schema_version": 1, "slots": [', encoding="utf-8")
    with pytest.raises(checker.RegistryError):
        checker.load_registry(broken)


def test_a_registry_that_is_not_an_object_raises(tmp_path):
    listy = tmp_path / "validation-slots.json"
    listy.write_text("[]", encoding="utf-8")
    with pytest.raises(checker.RegistryError):
        checker.load_registry(listy)


@pytest.mark.parametrize("payload", ["", "{", "null", "[]", "not json at all"])
def test_the_cli_exits_two_on_input_it_cannot_parse(tmp_path, payload):
    path = tmp_path / "validation-slots.json"
    path.write_text(payload, encoding="utf-8")
    assert checker.main(["--registry", str(path)]) == 2


def test_the_cli_exits_two_when_the_registry_file_is_absent(tmp_path):
    assert checker.main(["--registry", str(tmp_path / "absent.json")]) == 2


def test_the_cli_reports_unreadable_input_as_unreadable_in_json_mode(tmp_path, capsys):
    path = tmp_path / "validation-slots.json"
    path.write_text("{", encoding="utf-8")
    assert checker.main(["--registry", str(path), "--json"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["unreadable"] is True
    assert report["errors"]


# ------------------------------------------------------ empty collection must not pass


def test_an_empty_registry_fails_instead_of_passing_vacuously():
    errors = checker.validate_registry(_doc(), root=ROOT)
    assert any("empty" in error for error in errors)


def test_the_cli_exits_one_on_an_empty_registry(tmp_path):
    path = tmp_path / "validation-slots.json"
    path.write_text(json.dumps(_doc()), encoding="utf-8")
    assert checker.main(["--registry", str(path)]) == 1


def test_a_registry_with_no_slots_key_at_all_fails():
    assert checker.validate_registry(
        {"schema_version": 1, "generated_from": ["design/eye-control/VALIDATION_MATRIX.md"]},
        root=ROOT,
    )


# ------------------------------------------------------------------ acceptance criteria


def test_duplicate_cell_ids_fail_validation():
    errors = _errors(_slot(), _slot(issue=429))
    assert any("duplicate slot id" in error for error in errors)


def test_two_cells_may_not_claim_the_same_issue():
    errors = _errors(_slot(), _slot(id="T0-WIN-B", slot="B"))
    assert any("already represented by" in error for error in errors)


@pytest.mark.parametrize("field", ["issue", "time_estimate_minutes"])
def test_a_ready_cell_with_a_missing_required_field_fails(field):
    errors = _errors(_slot(state="ready", blocked_by=[], **{field: None}))
    assert any(f"missing required field {field!r}" in error for error in errors)


def test_a_ready_cell_with_an_unresolved_prerequisite_fails():
    errors = _errors(_slot(state="ready", blocked_by=[423]))
    assert any("unresolved prerequisite" in error for error in errors)


def test_a_ready_cell_that_still_names_a_free_text_blocker_fails():
    errors = _errors(
        _slot(state="ready", blocked_by=[], additional_blockers="camera runtime not reachable")
    )
    assert any("unresolved blocker" in error for error in errors)


def test_a_ready_cell_with_everything_resolved_passes():
    assert _errors(_slot(state="ready", blocked_by=[], additional_blockers=None)) == []


@pytest.mark.parametrize("field", sorted({"pack", "environment", "session", "slot", "state"}))
def test_a_cell_missing_a_universally_required_field_fails(field):
    errors = _errors(_slot(**{field: None}))
    assert any("missing required field" in error for error in errors)


def test_a_human_hardware_slot_can_never_be_cloud_agent_ready():
    errors = _errors(_slot(hardware_required=True, cloud_agent_ready=True))
    assert any("never be cloud_agent_ready" in error for error in errors)


def test_community_qa_evidence_can_never_be_cloud_agent_ready():
    errors = _errors(
        _slot(hardware_required=False, cloud_agent_ready=True, evidence_mode="community_qa")
    )
    assert any("human-operated" in error for error in errors)


def test_community_qa_is_the_default_evidence_mode_for_a_public_slot():
    slot = _slot()
    del slot["evidence_mode"]
    assert _errors(slot) == []


def test_a_public_slot_may_not_declare_another_evidence_mode():
    errors = _errors(_slot(evidence_mode="ci"))
    assert any("must be 'community_qa'" in error for error in errors)


def test_research_evidence_mode_is_rejected_outright():
    errors = _errors(_slot(evidence_mode="research"))
    assert any("forbidden" in error for error in errors)


def test_an_unknown_evidence_mode_is_rejected():
    errors = _errors(_slot(evidence_mode="vibes"))
    assert any("evidence_mode" in error for error in errors)


@pytest.mark.parametrize(
    "key,value",
    [
        ("tester_email", "someone@example.com"),
        ("contact", "someone"),
        ("participant_id", "P07"),
        ("hostname", "laptop-1"),
    ],
)
def test_identity_and_contact_fields_are_rejected(key, value):
    errors = _errors(_slot(**{key: value}))
    assert any("identity/contact field" in error for error in errors)


@pytest.mark.parametrize(
    "value",
    ["reported by someone@example.com", "ping @somecontributor", "call +49 151 2345678"],
)
def test_identity_looking_values_are_rejected(value):
    errors = _errors(_slot(requirement=value))
    assert any("identity data is forbidden" in error for error in errors)


def test_the_committed_registry_contains_no_identity_or_contact_data():
    errors: list[str] = []
    checker._scan_identity(_registry(), "", errors)
    assert errors == []


def test_an_id_that_disagrees_with_its_pack_environment_and_slot_fails():
    errors = _errors(_slot(id="T3-MAC-B"))
    assert any("id should be" in error for error in errors)


def test_an_unknown_slot_key_is_rejected_rather_than_silently_ignored():
    errors = _errors(_slot(prioroty="high"))
    assert any("unknown slot keys" in error for error in errors)


def test_a_repeat_slot_must_record_more_than_one_session():
    errors = _errors(_slot(id="T1-ANY-REPEAT", pack="T1", environment="ANY", slot="repeat"))
    assert any("more than one session" in error for error in errors)


def test_generated_from_must_point_at_files_that_exist():
    doc = _doc(_slot())
    doc["generated_from"] = ["design/eye-control/DOES_NOT_EXIST.md"]
    assert any("does not exist" in error for error in checker.validate_registry(doc, root=ROOT))


# ------------------------------------------------- the historical issues, unchanged


def test_every_existing_no_code_issue_is_represented_exactly_once():
    by_issue = {
        slot["issue"]: slot for slot in _registry()["slots"] if slot.get("issue") is not None
    }
    assert set(by_issue) == set(HISTORICAL_SLOTS)


def test_each_existing_issue_keeps_its_pack_environment_and_slot():
    by_issue = {
        slot["issue"]: slot for slot in _registry()["slots"] if slot.get("issue") is not None
    }
    actual = {
        issue: (slot["pack"], slot["environment"], slot["slot"])
        for issue, slot in by_issue.items()
    }
    assert actual == HISTORICAL_SLOTS


def test_every_existing_no_code_slot_is_planned_hardware_and_human_only():
    for slot in _registry()["slots"]:
        if slot.get("issue") not in HISTORICAL_SLOTS:
            continue
        assert slot["state"] == "planned", f"{slot['id']} must stay PLANNED (nothing is validated)"
        assert slot["hardware_required"] is True
        assert slot["cloud_agent_ready"] is False
        assert slot["beginner_safe"] is True
        assert slot["evidence_mode"] == "community_qa"
        assert slot["blocked_by"] or slot["additional_blockers"], (
            f"{slot['id']} is PLANNED, so it must say what it is waiting for"
        )


def test_future_cells_may_stay_planned_without_an_open_issue():
    planned_without_issue = [
        slot
        for slot in _registry()["slots"]
        if slot.get("issue") is None and slot["state"] == "planned"
    ]
    assert planned_without_issue, "the registry must be able to hold a cell with no issue"
    assert all(slot["pack"] in {f"T{n}" for n in range(8)} for slot in planned_without_issue)


def test_a_planned_cell_without_an_issue_is_valid():
    assert _errors(_slot(issue=None)) == []


# ------------------------------------------------------------------ offline/determinism


#: Everything the validator is allowed to import. An allowlist, not a denylist of
#: network module names: a substring scan for `"gh "` matched `high, ...` on its first
#: run, and any denylist is only as good as the next library nobody thought of.
ALLOWED_IMPORTS = {"__future__", "argparse", "json", "re", "sys", "pathlib", "typing"}


def test_the_validator_imports_nothing_that_can_reach_the_network():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert imported, "the import scan found nothing, so it proves nothing"
    assert imported <= ALLOWED_IMPORTS, f"unexpected imports: {sorted(imported - ALLOWED_IMPORTS)}"


def test_validation_is_deterministic():
    data = _registry()
    first = checker.validate_registry(data, root=ROOT)
    second = checker.validate_registry(json.loads(json.dumps(data)), root=ROOT)
    assert first == second == []


# ------------------------------------------------ the invalid-input corpus, every kind


def _mutated(fn) -> dict[str, Any]:
    data = copy.deepcopy(_registry())
    fn(data)
    return data


def _first(data: dict[str, Any], **changes: Any) -> None:
    data["slots"][0].update(changes)


#: One entry per *kind* of invalid registry, each derived from the committed registry so
#: it stays a one-fault mutation of a document known to be valid. The control below
#: proves the unmutated document passes, so a failure here is the mutation's doing.
INVALID_KINDS: dict[str, Any] = {
    "empty slots": lambda d: d.update(slots=[]),
    "slots null": lambda d: d.update(slots=None),
    "slots object": lambda d: d.update(slots={}),
    "slot is null": lambda d: d["slots"].append(None),
    "slot is string": lambda d: d["slots"].append("x"),
    "no slots key": lambda d: d.pop("slots"),
    "empty object": lambda d: d.clear(),
    "schema_version true": lambda d: d.update(schema_version=True),
    "schema_version 1.0": lambda d: d.update(schema_version=1.0),
    "schema_version string": lambda d: d.update(schema_version="1"),
    "schema_version 2": lambda d: d.update(schema_version=2),
    "duplicate id": lambda d: d["slots"].append(copy.deepcopy(d["slots"][0])),
    "duplicate issue": lambda d: d["slots"][1].update(issue=428),
    "state done": lambda d: _first(d, state="done"),
    "state validated": lambda d: _first(d, state="validated"),
    "state is a list": lambda d: _first(d, state=["ready"]),
    "pack is a list": lambda d: _first(d, pack=[]),
    "pack is an object": lambda d: _first(d, pack={}),
    "environment is a list": lambda d: _first(d, environment=[]),
    "slot is a list": lambda d: _first(d, slot=[]),
    "evidence_mode is a list": lambda d: _first(d, evidence_mode=[]),
    "evidence_mode research": lambda d: _first(d, evidence_mode="research"),
    "ready with open prerequisite": lambda d: _first(
        d, state="ready", blocked_by=[999], additional_blockers=None
    ),
    "ready with free-text blocker": lambda d: _first(d, state="ready", blocked_by=[]),
    "ready without an issue": lambda d: _first(
        d, state="ready", blocked_by=[], additional_blockers=None, issue=None
    ),
    "ready without an estimate": lambda d: _first(
        d, state="ready", blocked_by=[], additional_blockers=None, time_estimate_minutes=None
    ),
    "hardware cloud_agent_ready": lambda d: _first(d, cloud_agent_ready=True),
    "community_qa cloud_agent_ready": lambda d: _first(
        d, cloud_agent_ready=True, hardware_required=False
    ),
    "email in a value": lambda d: _first(d, requirement="tester a@b.co"),
    "email key": lambda d: _first(d, email="a@b.co"),
    "participant key": lambda d: _first(d, participant_id="P1"),
    "email in the description": lambda d: d.update(description="by a@b.co"),
    "handle in a value": lambda d: _first(d, session="run by @bob"),
    "phone in a value": lambda d: _first(d, additional_blockers="call +49 151 2345678"),
    "unknown slot key": lambda d: _first(d, foo=1),
    "unknown top-level key": lambda d: d.update(foo=1),
    "id disagrees with its fields": lambda d: _first(d, id="T0-WIN-B"),
    "empty id": lambda d: _first(d, id=""),
    "integer id": lambda d: _first(d, id=5),
    "issue is a bool": lambda d: _first(d, issue=True),
    "issue is a string": lambda d: _first(d, issue="428"),
    "issue is zero": lambda d: _first(d, issue=0),
    "blocked by itself": lambda d: _first(d, blocked_by=[428]),
    "blocked_by repeats an issue": lambda d: _first(d, blocked_by=[423, 423]),
    "blocked_by is a string": lambda d: _first(d, blocked_by="423"),
    "A slot with several sessions": lambda d: _first(d, sessions=5),
    "zero sessions": lambda d: _first(d, sessions=0),
    "repeat slot with one session": lambda d: next(
        s for s in d["slots"] if s["slot"] == "repeat"
    ).update(sessions=1),
    "negative estimate": lambda d: _first(d, time_estimate_minutes={"min": -1, "max": 5}),
    "inverted estimate": lambda d: _first(d, time_estimate_minutes={"min": 30, "max": 5}),
    "estimate longer than a sitting": lambda d: _first(
        d, time_estimate_minutes={"min": 15, "max": 99999}
    ),
    "estimate is a bare int": lambda d: _first(d, time_estimate_minutes=15),
    "generated_from missing file": lambda d: d.update(generated_from=["nope.md"]),
    "generated_from absolute": lambda d: d.update(generated_from=["/etc/passwd"]),
    "generated_from escapes the repo": lambda d: d.update(
        generated_from=["design/eye-control/../../../../../../etc/passwd"]
    ),
    "generated_from empty": lambda d: d.update(generated_from=[]),
    "generated_from absent": lambda d: d.pop("generated_from"),
    "flag is a string": lambda d: _first(d, beginner_safe="yes"),
    "required field absent": lambda d: d["slots"][0].pop("hardware_required"),
}


def test_the_corpus_control_is_valid_so_each_mutation_is_the_only_fault():
    assert checker.validate_registry(_registry(), root=ROOT) == []


@pytest.mark.parametrize("kind", sorted(INVALID_KINDS))
def test_every_kind_of_invalid_registry_is_reported_not_crashed(kind, tmp_path):
    data = _mutated(INVALID_KINDS[kind])
    errors = checker.validate_registry(data, root=ROOT)  # must not raise
    assert errors, f"{kind!r} validated clean"

    path = tmp_path / "validation-slots.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert checker.main(["--registry", str(path), "--campaign", str(CAMPAIGN_PATH)]) == 1


def test_the_invalid_corpus_does_not_shrink():
    assert len(INVALID_KINDS) >= 50


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff\xfe{}",  # not UTF-8
        b"[" * 200_000,  # deeper than the JSON parser allows
        b'{"schema_version": NaN, "slots": []}',  # non-finite number
        b'{"schema_version": 1, "slots": [], "slots": []}',  # repeated key
        b'{"schema_version": 1, "state": "ready", "state": "planned"}',
    ],
)
def test_bytes_the_parser_cannot_trust_exit_two_without_a_traceback(tmp_path, payload):
    path = tmp_path / "validation-slots.json"
    path.write_bytes(payload)
    assert checker.main(["--registry", str(path)]) == 2


def test_a_repeated_json_key_cannot_hide_a_state_change(tmp_path):
    """`json` keeps the last of two equal keys, so the file the author wrote is not the
    file that was checked. The second `state` here is the one a plain loader would see."""
    text = REGISTRY_PATH.read_text(encoding="utf-8").replace(
        '"state": "planned",', '"state": "planned", "state": "ready",', 1
    )
    path = tmp_path / "validation-slots.json"
    path.write_text(text, encoding="utf-8")
    assert json.loads(text)["slots"][0]["state"] == "ready"  # the silent override
    assert checker.main(["--registry", str(path)]) == 2


# ----------------------------------------------- the prose matrix and the registry agree


def _matrix_ab_table() -> list[tuple[str, int, int | None]]:
    """(environment label, A issue, B issue) rows of the prose A/B table."""
    rows = []
    for line in MATRIX_PATH.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and re.fullmatch(r"#\d+", cells[1]):
            b = int(cells[2][1:]) if re.fullmatch(r"#\d+", cells[2]) else None
            rows.append((cells[0], int(cells[1][1:]), b))
    return rows


def test_the_matrix_table_was_actually_parsed():
    assert len(_matrix_ab_table()) == 7, "the A/B table moved; the cross-check below is blind"


def test_the_registry_agrees_with_the_prose_matrix_issue_for_issue():
    """Derived from VALIDATION_MATRIX.md, not from a second hand-written list."""
    by_issue = {s["issue"]: s for s in _registry()["slots"] if s.get("issue") is not None}
    table = _matrix_ab_table()
    matrix_issues = {n for _, a, b in table for n in (a, b) if n is not None}
    assert set(by_issue) == matrix_issues, "an issue is in one of matrix/registry and not the other"
    for _label, a, b in table:
        if b is None:  # the same-person row: one repeat slot, no B
            assert by_issue[a]["slot"] == "repeat"
            continue
        assert by_issue[a]["slot"] == "A"
        assert by_issue[b]["slot"] == "B"
        assert by_issue[a]["environment"] == by_issue[b]["environment"]
        assert by_issue[a]["pack"] == by_issue[b]["pack"]


# ------------------------------------------------- the registry tells the truth: nothing done


def test_no_slot_is_ready_because_no_slot_has_been_validated_by_a_human():
    """Every cell is PLANNED. The day one becomes READY this fails on purpose: that is
    a claim about a platform, and it needs a human to flip it and this test to be
    rewritten with the evidence, not a quiet edit."""
    slots = _registry()["slots"]
    assert slots, "an empty registry would satisfy 'none are ready' vacuously"
    assert {s["state"] for s in slots} == {"planned"}


def test_the_registry_has_no_field_that_could_carry_a_result():
    allowed = checker.SLOT_KEYS
    for slot in _registry()["slots"]:
        assert set(slot) <= allowed
    assert not {"outcome", "result", "results", "passed", "validated", "evidence"} & allowed


def test_no_reported_outcome_file_is_committed():
    """The dashboard says no outcome exists. Committing one must be a deliberate act that
    also rewrites that statement, so this fails first."""
    found = [
        p
        for p in (ROOT / "design" / "eye-control").rglob("*")
        if p.is_file() and "outcome" in p.name.lower()
    ]
    assert found == []


def test_the_one_person_hands_free_workflow_has_no_cell_and_no_claim():
    assert "T7" not in {s["pack"] for s in _registry()["slots"]}


# ---------------------------------------- READY slots reach the contributor task finder


def _load_campaign():
    name = "campaign_for_eye_tests"
    spec = importlib.util.spec_from_file_location(name, CAMPAIGN_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


campaign = _load_campaign()


def _ready_registry(**overrides: Any) -> dict[str, Any]:
    return _doc(_slot(state="ready", blocked_by=[], additional_blockers=None, **overrides))


def _eye_task(**overrides: Any) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": "MEASURE-EYE-T0-WIN-A-001",
        "family": "measurement",
        "title": "T0 Windows 11 camera lifecycle - 20 min - no coding",
        "value": "One independent Windows host for the camera lifecycle check.",
        "risk": "L1",
        "minutes": 20,
        "skills": [],
        "requires": {"os": "Windows 11", "hardware": "a webcam"},
        "cloud_agent_ready": False,
        "allowed_paths": ["design/eye-control/**"],
        "validation": ["uv run python scripts/check_eye_validation_slots.py"],
        "evidence": ["PASS / PARTIAL / FAIL / BLOCKED plus the privacy-safe result JSON"],
        "state": "open",
        "source": "eye-validation slot T0-WIN-A (issue #428)",
    }
    task.update(overrides)
    return task


def test_the_real_task_finder_advertises_no_eye_slot_because_none_is_ready():
    tasks = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
    assert checker.validate_campaign_exposure(_registry(), tasks) == []
    assert not [t for t in tasks if "eye-validation slot" in str(t.get("source", ""))]


def test_the_exposure_check_is_not_vacuous_on_the_real_inventory():
    """Make one real slot READY and the real inventory must be reported as missing it."""
    tasks = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
    data = _mutated(lambda d: _first(d, state="ready", blocked_by=[], additional_blockers=None))
    errors = checker.validate_campaign_exposure(data, tasks)
    assert any("exactly one advertised campaign task" in e for e in errors)


def test_a_ready_slot_with_a_proper_task_passes_and_the_task_is_a_valid_campaign_task():
    task = _eye_task()
    assert checker.validate_campaign_exposure(_ready_registry(), [task]) == []
    assert campaign.validate_task(task) == []


def test_a_ready_slot_with_no_task_fails():
    assert checker.validate_campaign_exposure(_ready_registry(), [])


def test_a_ready_slot_with_two_tasks_fails():
    errors = checker.validate_campaign_exposure(
        _ready_registry(), [_eye_task(), _eye_task(id="MEASURE-EYE-T0-WIN-A-002")]
    )
    assert any("exactly one" in e for e in errors)


def test_a_planned_slot_must_not_be_advertised():
    errors = checker.validate_campaign_exposure(_doc(_slot()), [_eye_task()])
    assert any("PLANNED" in e for e in errors)


def test_a_planned_slot_may_have_an_internal_draft_task():
    assert checker.validate_campaign_exposure(_doc(_slot()), [_eye_task(state="draft")]) == []


def test_a_task_naming_an_unregistered_slot_is_an_error_not_a_typo_that_vanishes():
    stray = _eye_task(id="MEASURE-EYE-X-001", source="eye-validation slot T9-ZZZ-A")
    errors = checker.validate_campaign_exposure(_ready_registry(), [_eye_task(), stray])
    assert any("not registered" in e for e in errors)


@pytest.mark.parametrize(
    "change,needle",
    [
        ({"family": "docs"}, "'measurement'"),
        ({"minutes": 5}, "understates"),
        ({"requires": {}}, "requires"),
        ({"evidence": []}, "evidence"),
        ({"validation": ["uv run python scripts/campaign.py --check"]}, "check_eye_validation"),
    ],
)
def test_a_ready_slots_task_must_be_honest_visible_and_checkable(change, needle):
    errors = checker.validate_campaign_exposure(_ready_registry(), [_eye_task(**change)])
    assert any(needle in e for e in errors), errors


def test_a_hardware_task_claiming_cloud_agent_ready_is_refused_by_both_validators():
    task = _eye_task(cloud_agent_ready=True)
    assert any(
        "cloud_agent_ready" in e
        for e in checker.validate_campaign_exposure(_ready_registry(), [task])
    )
    assert any("cloud_agent_ready" in e for e in campaign.validate_task(task))


def test_a_repeat_slots_task_covers_every_session():
    registry = _doc(
        _slot(
            id="T1-ANY-REPEAT",
            pack="T1",
            environment="ANY",
            slot="repeat",
            sessions=3,
            state="ready",
            blocked_by=[],
            additional_blockers=None,
            issue=437,
        )
    )
    source = "eye-validation slot T1-ANY-REPEAT"
    short = checker.validate_campaign_exposure(registry, [_eye_task(source=source, minutes=20)])
    assert any("understates" in e for e in short)
    assert checker.validate_campaign_exposure(registry, [_eye_task(source=source, minutes=60)]) == []


def test_the_cli_exits_two_when_the_campaign_inventory_cannot_be_read(tmp_path):
    tasks = tmp_path / "tasks.json"
    assert checker.main(["--campaign", str(tasks)]) == 2  # absent
    tasks.write_text("{", encoding="utf-8")
    assert checker.main(["--campaign", str(tasks)]) == 2  # unparseable


def test_the_cli_exits_one_when_a_ready_slot_is_not_advertised(tmp_path):
    ready = _mutated(lambda d: _first(d, state="ready", blocked_by=[], additional_blockers=None))
    registry = tmp_path / "validation-slots.json"
    registry.write_text(json.dumps(ready), encoding="utf-8")
    tasks = tmp_path / "tasks.json"
    tasks.write_text("[]", encoding="utf-8")
    assert checker.main(["--registry", str(registry), "--campaign", str(tasks)]) == 1
