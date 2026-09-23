"""Planning traceability stays aligned with the live code and campaign queue."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "design" / "traceability.yml"


def _load_checker():
    path = ROOT / "scripts" / "check-traceability.py"
    spec = importlib.util.spec_from_file_location("check_traceability", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _manifest():
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_committed_traceability_manifest_is_valid():
    checker = _load_checker()
    assert checker.validate_manifest(_manifest()) == []


def test_every_unwired_capability_has_exactly_one_manifest_entry_and_campaign_task():
    from yazses.system.features import _UNWIRED

    manifest = _manifest()
    capability_entries = {
        entry["id"].removeprefix("capability:"): entry
        for entry in manifest["entries"]
        if entry["kind"] == "capability"
    }
    assert set(capability_entries) == set(_UNWIRED)

    tasks = json.loads((ROOT / "campaign" / "tasks.json").read_text(encoding="utf-8"))
    task_ids = {task["id"] for task in tasks if task["family"] == "feature-wiring"}

    for slug, entry in capability_entries.items():
        expected_task = f"WIRE-{slug.upper().replace('_', '-')}-001"
        tracking = entry["tracking"]
        assert tracking["kind"] == "campaign"
        assert tracking["issues"] == [164]
        assert tracking["task"] == expected_task
        assert expected_task in task_ids


def test_scheduled_work_cannot_be_untracked():
    checker = _load_checker()
    data = _manifest()
    entry = next(item for item in data["entries"] if item["kind"] == "programme").copy()
    entry["id"] = "test:untracked-scheduled"
    entry["delivery_status"] = "scheduled"
    entry["tracking"] = {"kind": "none", "issues": [], "task": None, "milestone": None}
    errors = checker.validate_manifest({"version": 1, "entries": [entry]})
    assert any("requires a tracking surface" in error for error in errors)


def test_deferred_work_cannot_claim_a_milestone():
    checker = _load_checker()
    data = _manifest()
    entry = next(
        item for item in data["entries"] if item["delivery_status"] == "deferred"
    ).copy()
    entry["id"] = "test:deferred-with-milestone"
    entry["tracking"] = {
        "kind": "issue",
        "issues": [999],
        "task": None,
        "milestone": 9,
    }
    errors = checker.validate_manifest({"version": 1, "entries": [entry]})
    assert any("cannot carry a milestone" in error for error in errors)


def test_research_questions_do_not_pretend_to_be_architecture_decisions():
    for entry in _manifest()["entries"]:
        if entry["kind"] == "research":
            assert "decision_status" not in entry
            assert entry["delivery_status"] == "research"
