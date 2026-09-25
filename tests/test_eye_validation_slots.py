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
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "design" / "eye-control" / "validation-slots.json"
SCRIPT = ROOT / "scripts" / "check_eye_validation_slots.py"

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
        assert slot["state"] == "planned", f"{slot['id']} must stay PLANNED (#423 is open)"
        assert slot["hardware_required"] is True
        assert slot["cloud_agent_ready"] is False
        assert slot["beginner_safe"] is True
        assert slot["evidence_mode"] == "community_qa"
        assert slot["blocked_by"], f"{slot['id']} must name its prerequisite issue"


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
