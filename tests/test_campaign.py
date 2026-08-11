"""The campaign task inventory and its preflight must hold together.

A task inventory is only worth having if a bad row cannot enter it. The failure modes
that matter are not typos — they are the ones that waste a newcomer's evening: a task
that points at paths nobody may touch, a task that claims a container can produce
evidence only a human with hardware can produce, an id that two PRs both claim, and a
generated file that has quietly stopped matching the data it was generated from.

The schema is generated from `FIELD_SPEC` rather than hand-written, so these also assert
the two cannot drift apart — a schema nobody validates against is the dead-registry
pattern this repository has been bitten by before.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def campaign():
    return _load("campaign")


@pytest.fixture(scope="module")
def preflight():
    return _load("campaign_preflight")


@pytest.fixture(scope="module")
def tasks(campaign):
    return campaign.load_tasks()


# ── The inventory itself ──────────────────────────────────────────────────────

def test_every_task_in_the_inventory_is_valid(campaign, tasks):
    errors = campaign.validate_inventory(tasks)
    assert not errors, "campaign/tasks.json is invalid:\n  " + "\n  ".join(errors)


def test_generated_files_are_in_sync(campaign, tasks):
    """Same contract as the docs generator: regenerate and commit, do not hand-edit."""
    stale = [
        str(p.relative_to(ROOT))
        for p, content in campaign.generate(tasks).items()
        if not p.exists() or p.read_text(encoding="utf-8") != content
    ]
    assert not stale, (
        f"generated campaign files are stale: {stale} — "
        "run `uv run python scripts/campaign.py --generate` and commit the result"
    )


def test_the_schema_is_derived_from_the_field_spec(campaign):
    """If someone hand-edits the JSON Schema, it stops describing the validator."""
    schema = json.loads((ROOT / "campaign" / "schemas" / "task.schema.json").read_text())
    assert set(schema["properties"]) == set(campaign.FIELD_SPEC), (
        "the committed schema's fields differ from FIELD_SPEC — FIELD_SPEC is the source "
        "of truth; regenerate rather than editing the schema"
    )
    required = {n for n, (_t, req, _d) in campaign.FIELD_SPEC.items() if req}
    assert set(schema["required"]) == required


def test_open_tasks_point_at_paths_that_exist(tasks):
    """A task whose allowed_paths are fiction cannot be completed or preflighted."""
    bad: list[str] = []
    for t in tasks:
        if t["state"] != "open":
            continue
        for pattern in t["allowed_paths"]:
            root = pattern.split("*")[0].rstrip("/")
            if not root:
                continue
            # Either the literal path exists, or its parent directory does (the task
            # creates a new file inside a real directory — README.fr.md, examples/x.toml).
            p = ROOT / root
            if not (p.exists() or p.parent.is_dir()):
                bad.append(f"{t['id']}: {pattern}")
    assert not bad, "open tasks reference paths that do not exist:\n  " + "\n  ".join(bad)


def test_no_open_task_is_advertised_as_architecture_work(tasks):
    assert not [t["id"] for t in tasks if t["state"] == "open" and t["risk"] == "L3"]


def test_feature_wiring_tasks_track_the_live_registry():
    """A wiring task for an already-wired capability sends someone to do nothing.

    The registry is the truth; this catches the inventory going stale behind it, which
    is guaranteed to happen as capabilities get wired.
    """
    from yazses.system.features import _UNWIRED

    campaign_mod = _load("campaign")
    stale = []
    for t in campaign_mod.load_tasks():
        if t["family"] != "feature-wiring":
            continue
        slug = t["id"].removeprefix("WIRE-").removesuffix("-001").lower().replace("-", "_")
        if slug not in _UNWIRED:
            stale.append(f"{t['id']} (slug {slug!r} is no longer unwired)")
    assert not stale, (
        "feature-wiring tasks exist for capabilities that are already wired:\n  "
        + "\n  ".join(stale)
        + "\nRemove them from campaign/tasks.json and regenerate."
    )


# ── Preflight: scope ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path,allowed,expected",
    [
        ("SHOWCASE.md", ["SHOWCASE.md"], True),
        ("src/yazses/core/daemon.py", ["src/yazses/**"], True),
        ("src/yazses/a/b/c/d.py", ["src/yazses/**"], True),
        ("examples/vscode.toml", ["examples/**"], True),
        ("examples/nested/deep.toml", ["examples/**"], True),
        ("pyproject.toml", ["src/yazses/**"], False),
        ("uv.lock", ["examples/**"], False),
        (".github/workflows/test.yml", ["docs/**"], False),
        ("README.fr.md", ["README.fr.md", "README.md"], True),
    ],
)
def test_path_allowed(preflight, path, allowed, expected):
    assert preflight.path_allowed(path, allowed) is expected


def test_check_paths_names_every_file_outside_scope(preflight):
    outside = preflight.check_paths(
        ["docs/a.md", "pyproject.toml", "uv.lock"], ["docs/**"]
    )
    assert outside == ["pyproject.toml", "uv.lock"]


def test_a_lockfile_bump_smuggled_into_a_docs_task_is_caught(preflight):
    """The specific thing that makes a cheap review expensive."""
    assert preflight.check_paths(["docs/faq.md", "uv.lock"], ["docs/**"]) == ["uv.lock"]


# ── Preflight: task id ────────────────────────────────────────────────────────

def test_find_task_id_prefers_the_explicit_line(preflight):
    body = "## Task\nTask ID: APP-001\nCloses #43"
    assert preflight.find_task_id(body, {"APP-001"}) == "APP-001"


def test_find_task_id_accepts_lowercase_label(preflight):
    assert preflight.find_task_id("task-id: mic-004", {"MIC-004"}) == "MIC-004"


def test_find_task_id_falls_back_to_a_known_bare_id(preflight):
    """People put the id in the title and nowhere else."""
    assert preflight.find_task_id("Add a config for kitty (APP-014)", {"APP-014"}) == "APP-014"


def test_find_task_id_ignores_unknown_bare_tokens(preflight):
    """Otherwise 'MIT-LICENSE' or 'UTF-8' in a PR body becomes a task id."""
    assert preflight.find_task_id("Relicensed under MIT-LICENSE, encoded UTF-8", {"APP-001"}) is None


def test_no_task_id_is_not_a_failure(preflight):
    ok, report = preflight.render_report(
        task_id=None, task=None, changed=["a.md"], outside=[], findings=[]
    )
    assert ok is True
    assert "does not block you" in report


def test_an_unknown_task_id_fails_without_blaming_the_contributor(preflight):
    ok, report = preflight.render_report(
        task_id="NOPE-001", task=None, changed=[], outside=[], findings=[]
    )
    assert ok is False
    assert "not something you need to fix alone" in report


# ── Preflight: personal data ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text",
    [
        "+ model path: /home/mohsen/.cache/yazses",
        "+ /Users/janedoe/Library/Application Support/yazses",
        r"+ C:\Users\Jane\AppData\yazses",
        "+ contact me at real.person@gmail.com",
        "+ token=ghp_abcdefghijklmnopqrstuvwxyz0123",
    ],
)
def test_personal_data_is_detected(preflight, text):
    assert preflight.scan_personal_data(text), f"missed personal data in {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "+ /home/user/.config/yazses      # the documented placeholder",
        "+ /home/runner/work/yazses       # a CI path, not a person",
        "+ write to you@example.com",
        "+ MSKazemi@users.noreply.github.com",
        "+ see https://github.com/MSKazemi/yazses for details",
        "+ uv run python -m pytest tests/ -v",
        "+ | Blue Yeti | USB condenser | Ubuntu 24.04 | 0.004 | works well |",
    ],
)
def test_ordinary_content_is_not_flagged(preflight, text):
    """A false positive on someone's first PR costs more than it saves."""
    assert preflight.scan_personal_data(text) == [], f"false positive on {text!r}"


def test_report_is_actionable_when_scope_is_wrong(preflight, tasks):
    task = next(t for t in tasks if t["state"] == "open")
    ok, report = preflight.render_report(
        task_id=task["id"],
        task=task,
        changed=["uv.lock"],
        outside=["uv.lock"],
        findings=[],
    )
    assert ok is False
    assert "uv.lock" in report
    # It must tell them what they may touch and how to validate, not just say no.
    assert task["allowed_paths"][0] in report
    assert task["validation"][0] in report


def test_report_passes_a_clean_pr(preflight, tasks):
    task = next(t for t in tasks if t["state"] == "open")
    ok, _ = preflight.render_report(
        task_id=task["id"], task=task, changed=["SHOWCASE.md"], outside=[], findings=[]
    )
    assert ok is True
