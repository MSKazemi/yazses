"""READY eye-validation slots reach the contributor task finder, and nothing else does (#456).

The slot registry (`design/eye-control/validation-slots.json`) is the single source of
truth. `scripts/campaign.py --generate` derives one campaign task per READY slot into
`campaign/tasks.json`, and the finder (`docs/contribute/find.md`) is rendered from that.
These tests hold the two together in both directions -- a READY slot missing from the
finder fails, and so does a PLANNED slot shown in it -- and refuse to go green on a
registry with nothing in it.

Today every slot is PLANNED, so the real finder carries no eye task. That makes every
real-tree equality here trivially satisfiable by an empty set, which is why each one is
paired with the same comparison on a registry whose slots have been flipped READY: the
guard has to find thirteen rows there, or the real-tree test proves nothing.
"""

from __future__ import annotations

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
TASKS_PATH = ROOT / "campaign" / "tasks.json"
FINDER_PATH = ROOT / "docs" / "contribute" / "find.md"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


campaign = _load("campaign_for_eye_finder_tests", "campaign.py")
eye = campaign.eye_slots


def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _tasks() -> list[dict[str, Any]]:
    return json.loads(TASKS_PATH.read_text(encoding="utf-8"))


def _flipped(predicate=lambda slot: slot.get("issue") is not None) -> dict[str, Any]:
    """The real registry with every slot matching *predicate* made READY, validly."""
    data = copy.deepcopy(_registry())
    for slot in data["slots"]:
        if predicate(slot):
            slot.update(state="ready", blocked_by=[], additional_blockers=None)
    assert eye.validate_registry(data) == [], "the flipped fixture is not a valid registry"
    return data


def _ready_ids(registry: dict[str, Any]) -> set[str]:
    return {campaign.eye_slot_task_id(s["id"]) for s in registry["slots"] if s["state"] == "ready"}


_FINDER_EYE_ID = re.compile(r"<code>(MEASURE-EYE-[A-Z0-9-]+)</code>")


def _finder_eye_ids(html: str) -> set[str]:
    # A parse that silently matched nothing would make every comparison below vacuous.
    assert html.count('class="yz-row"') > 0, "the finder has no rows; the parse is blind"
    return set(_FINDER_EYE_ID.findall(html))


def _slot_task_ids(tasks: list[dict[str, Any]]) -> set[str]:
    return {t["id"] for t in tasks if "eye-validation slot" in str(t.get("source", ""))}


# ── Vocabulary: no hand-written set may lag the registry's ───────────────────


def test_every_registry_pack_has_a_plain_language_name():
    assert set(campaign.EYE_PACK_LABELS) == eye.PACKS


def test_every_registry_hardware_class_has_a_visible_need():
    assert set(campaign._EYE_HARDWARE_NEEDS) == eye.HARDWARE_CLASSES
    for hardware_class in eye.HARDWARE_CLASSES - {"none"}:
        assert campaign._EYE_HARDWARE_NEEDS[hardware_class].get("hardware")


# ── The real tree: finder, inventory and registry agree ──────────────────────


def test_the_registry_the_real_tree_is_checked_against_is_not_empty():
    assert _registry()["slots"], "an empty registry would make every agreement vacuous"


def test_the_committed_inventory_is_exactly_what_the_registry_derives():
    """Either direction of drift makes `campaign.py --check` report tasks.json stale."""
    tasks = _tasks()
    assert campaign.sync_eye_slot_tasks(tasks, _registry()) == tasks, (
        "campaign/tasks.json disagrees with the eye-validation slot registry -- run "
        "`uv run python scripts/campaign.py --generate`"
    )


def test_the_published_finder_shows_exactly_the_ready_slots():
    registry = _registry()
    shown = _finder_eye_ids(FINDER_PATH.read_text(encoding="utf-8"))
    assert shown == _ready_ids(registry)
    assert _slot_task_ids(_tasks()) == _ready_ids(registry)


def test_the_real_inventory_passes_the_registrys_own_exposure_check():
    assert eye.validate_campaign_exposure(_registry(), _tasks()) == []


# ── The same comparisons on a registry that has READY slots ──────────────────


def test_ready_slots_reach_the_generated_finder_and_planned_ones_do_not():
    registry = _flipped(lambda s: s["pack"] == "T0" and s["slot"] == "A")
    tasks = campaign.sync_eye_slot_tasks(_tasks(), registry)
    ready = _ready_ids(registry)
    assert len(ready) == 5  # WIN, MAC, GNOME, KDE, X11 -- slot A only
    html = campaign.render_task_finder(tasks)
    assert _finder_eye_ids(html) == ready
    planned = {campaign.eye_slot_task_id(s["id"]) for s in registry["slots"]} - ready
    assert planned and not planned & _finder_eye_ids(html)
    assert eye.validate_campaign_exposure(registry, tasks) == []
    assert campaign.validate_inventory(tasks) == []


def test_every_registered_issue_slot_can_be_advertised():
    registry = _flipped()
    tasks = campaign.sync_eye_slot_tasks(_tasks(), registry)
    assert len(_ready_ids(registry)) == 13
    assert _finder_eye_ids(campaign.render_task_finder(tasks)) == _ready_ids(registry)
    assert eye.validate_campaign_exposure(registry, tasks) == []


def test_a_ready_slot_missing_from_the_inventory_is_drift():
    registry = _flipped(lambda s: s["id"] == "T0-WIN-A")
    tasks = _tasks()  # the committed inventory: no eye row
    assert campaign.sync_eye_slot_tasks(tasks, registry) != tasks
    assert any(
        "exactly one advertised campaign task" in e
        for e in eye.validate_campaign_exposure(registry, tasks)
    )


def test_a_planned_slot_shown_in_the_inventory_is_drift_and_is_removed():
    registry = _flipped(lambda s: s["id"] == "T0-WIN-A")
    mac = _flipped(lambda s: s["id"] == "T0-MAC-A")
    stray = campaign.eye_slot_task(next(s for s in mac["slots"] if s["id"] == "T0-MAC-A"))
    assert stray["id"] == "MEASURE-EYE-T0-MAC-A"
    tasks = campaign.sync_eye_slot_tasks(_tasks(), registry) + [stray]
    assert any("PLANNED" in e for e in eye.validate_campaign_exposure(_registry(), tasks))
    synced = campaign.sync_eye_slot_tasks(tasks, registry)
    assert synced != tasks
    assert _slot_task_ids(synced) == {"MEASURE-EYE-T0-WIN-A"}


def test_a_hand_written_slot_row_is_replaced_not_merged():
    registry = _flipped(lambda s: s["id"] == "T0-WIN-A")
    hand = dict(campaign.eye_slot_task(registry["slots"][0]), minutes=5, title="edited")
    synced = campaign.sync_eye_slot_tasks([hand], registry)
    assert synced == [campaign.eye_slot_task(registry["slots"][0])]


def test_sync_keeps_every_other_row_in_order_and_is_idempotent():
    tasks = _tasks()
    registry = _flipped()
    once = campaign.sync_eye_slot_tasks(tasks, registry)
    assert once[: len(tasks)] == tasks
    assert campaign.sync_eye_slot_tasks(once, registry) == once


# ── Each derived task is honest, human and checkable ─────────────────────────


@pytest.mark.parametrize(
    "slot_id", [s["id"] for s in _registry()["slots"] if s.get("issue") is not None]
)
def test_a_derived_task_is_what_the_issue_asks_for(slot_id):
    registry = _flipped()
    slot = next(s for s in registry["slots"] if s["id"] == slot_id)
    task = campaign.eye_slot_task(slot)

    assert campaign.validate_task(task) == []
    assert task["family"] == "measurement"
    assert task["cloud_agent_ready"] is False
    assert task["skills"] == []
    assert "no coding" in task["title"]
    assert f"#{slot['issue']}" in task["title"]

    # Honest time: the upper estimate for every session, and still one task's worth.
    assert task["minutes"] == slot["time_estimate_minutes"]["max"] * slot.get("sessions", 1)
    assert task["minutes"] <= campaign.MAX_MINUTES

    # The OS/session and the camera/display need are visible before claiming.
    assert task["requires"]["session"] == slot["session"]
    if slot["hardware_class"] != "none":
        assert "webcam" in task["requires"]["hardware"]
    if slot["hardware_class"] == "camera_display_topology":
        assert task["requires"]["display"]

    # The exact validator and the evidence workflow are named.
    assert task["validation"] == ["uv run python scripts/check_eye_validation_slots.py"]
    assert all(campaign.validation_command_problem(c) is None for c in task["validation"])
    evidence = " ".join(task["evidence"])
    assert "No-code eye-control test" in evidence
    assert "no research consent" in evidence
    assert "DATA_SHARING.md" in evidence
    for path in task["allowed_paths"]:
        assert (ROOT / path).is_file(), path


def test_the_campaign_validator_still_refuses_a_cloud_ready_slot_task():
    """The authoritative rule is the campaign validator's, not the derivation's."""
    task = campaign.eye_slot_task(_flipped()["slots"][0])
    errors = campaign.validate_task(dict(task, cloud_agent_ready=True))
    assert any("cloud_agent_ready must be false" in e for e in errors)


# ── Unreadable or empty registries fail; they never derive "no tasks" ────────


def _write(tmp_path: Path, data: Any) -> Path:
    path = tmp_path / "validation-slots.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_an_empty_registry_is_an_error_not_an_empty_finder(tmp_path):
    data = dict(_registry(), slots=[], issues=[])
    registry, errors = campaign.load_eye_registry(_write(tmp_path, data))
    assert registry is None
    assert any("empty" in e for e in errors)


def test_an_unreadable_registry_is_an_error(tmp_path):
    registry, errors = campaign.load_eye_registry(tmp_path / "missing.json")
    assert registry is None and errors


@pytest.mark.parametrize("flag", ["--check", "--generate"])
def test_the_generator_refuses_to_run_on_an_empty_registry(tmp_path, monkeypatch, capsys, flag):
    path = _write(tmp_path, dict(_registry(), slots=[], issues=[]))
    monkeypatch.setattr(campaign, "EYE_SLOTS_JSON", path)
    written: list[Path] = []
    monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: written.append(self))
    assert campaign.main([flag]) == 1
    assert written == [], "nothing may be written from a registry that failed validation"
    assert "eye-validation" in capsys.readouterr().err


def test_check_reports_the_inventory_stale_when_a_slot_turns_ready(tmp_path, monkeypatch, capsys):
    """End to end: flip a slot READY and `--check` fails until `--generate` runs."""
    path = _write(tmp_path, _flipped(lambda s: s["id"] == "T0-WIN-A"))
    monkeypatch.setattr(campaign, "EYE_SLOTS_JSON", path)
    assert campaign.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "tasks.json" in err and "find.md" in err  # separator-neutral: Windows CI


def test_the_registrys_exposure_check_gates_the_generator(tmp_path, monkeypatch, capsys):
    """A derivation bug that drops a READY slot must stop `--generate`, not ship a finder
    that silently lacks it: the registry's own checker is the post-condition."""
    path = _write(tmp_path, _flipped(lambda s: s["id"] == "T0-WIN-A"))
    monkeypatch.setattr(campaign, "EYE_SLOTS_JSON", path)
    monkeypatch.setattr(campaign, "eye_slot_tasks", lambda registry: [])
    written: list[Path] = []
    monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: written.append(self))
    assert campaign.main(["--generate"]) == 1
    assert written == []
    assert "exactly one advertised campaign task" in capsys.readouterr().err
