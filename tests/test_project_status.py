"""`scripts/project_status.py` and the workflow that runs it with a personal token.

The script's rule is small, but a wrong answer is visible to everyone who opens the board:
a card dragged back to Todo while its pull request is open, or one pulled out of a column
someone set by hand. The workflow half pins why it may hold a secret at all -- an issue
event is its only trigger, so no pull request's code ever runs next to the token.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "project-status.yml"


def _load():
    """Load the script as a module; `scripts/` is not a package, so it cannot be imported."""
    spec = importlib.util.spec_from_file_location(
        "project_status", ROOT / "scripts" / "project_status.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ps = _load()
TODO, IN_PROGRESS = ps.TODO, ps.IN_PROGRESS


@pytest.mark.parametrize(
    ("is_open", "assignees", "open_linked_prs", "current", "expected"),
    [
        # Claimed: Todo or a card with no status yet moves to In Progress.
        (True, 1, 0, TODO, IN_PROGRESS),
        (True, 2, 0, None, IN_PROGRESS),
        # Already there, or moved by hand to Done: left alone.
        (True, 1, 0, IN_PROGRESS, None),
        (True, 1, 0, "Done", None),
        # Last assignee left: back to Todo...
        (True, 0, 0, IN_PROGRESS, TODO),
        # ...unless an open pull request is why it is in progress.
        (True, 0, 1, IN_PROGRESS, None),
        # Unassigned from Todo or Done: nothing to undo.
        (True, 0, 0, TODO, None),
        (True, 0, 0, "Done", None),
        (True, 0, 0, None, None),
        # A closed issue belongs to the built-in "Item closed" workflow.
        (False, 1, 0, TODO, None),
        (False, 0, 0, IN_PROGRESS, None),
    ],
)
def test_target_status(is_open, assignees, open_linked_prs, current, expected):
    got = ps.target_status(
        is_open=is_open, assignees=assignees, open_linked_prs=open_linked_prs, current=current
    )
    assert got == expected


def test_a_missing_token_is_a_notice_not_a_failure(monkeypatch, capsys):
    monkeypatch.setenv("GH_TOKEN", "")
    monkeypatch.setattr(ps, "graphql", lambda *a, **k: pytest.fail("must not call the API"))
    assert ps.main() == 0
    assert "::notice::PROJECT_TOKEN is not set" in capsys.readouterr().out


def _lookup(*, state="OPEN", assignees=1, linked=0, item_status=TODO, on_board=True):
    items = []
    if on_board:
        items.append(
            {
                "id": "ITEM",
                "project": {"id": "PROJ"},
                "fieldValueByName": {"name": item_status} if item_status else None,
            }
        )
    # A card on some other project must never be the one moved.
    items.append({"id": "OTHER", "project": {"id": "ELSEWHERE"}, "fieldValueByName": None})
    return {
        "user": {
            "projectV2": {
                "id": "PROJ",
                "field": {
                    "id": "FIELD",
                    "options": [
                        {"id": "opt-todo", "name": TODO},
                        {"id": "opt-prog", "name": IN_PROGRESS},
                        {"id": "opt-done", "name": "Done"},
                    ],
                },
            }
        },
        "node": {
            "number": 7,
            "state": state,
            "assignees": {"totalCount": assignees},
            "closedByPullRequestsReferences": {"totalCount": linked},
            "projectItems": {"nodes": items},
        },
    }


@pytest.fixture
def run(monkeypatch, tmp_path):
    """Run `main()` against a fake API; return the (query, variables) of every call."""

    def _run(lookup):
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"issue": {"node_id": "ISSUE"}}), encoding="utf-8")
        monkeypatch.setenv("GH_TOKEN", "t")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
        monkeypatch.setenv("PROJECT_OWNER", "MSKazemi")
        monkeypatch.setenv("PROJECT_NUMBER", "8")
        calls = []

        def fake(token, query, variables):
            calls.append((query, variables))
            if query is ps.LOOKUP:
                return lookup
            if query is ps.ADD_ITEM:
                return {"addProjectV2ItemById": {"item": {"id": "NEW"}}}
            return {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "x"}}}

        monkeypatch.setattr(ps, "graphql", fake)
        assert ps.main() == 0
        return calls

    return _run


def test_assigning_moves_the_card_on_this_project(run):
    calls = run(_lookup(item_status=TODO))
    assert [q for q, _ in calls] == [ps.LOOKUP, ps.SET_STATUS]
    assert calls[0][1] == {"owner": "MSKazemi", "number": 8, "issue": "ISSUE"}
    assert calls[1][1] == {
        "project": "PROJ",
        "item": "ITEM",
        "field": "FIELD",
        "option": "opt-prog",
    }


def test_an_issue_not_yet_on_the_board_is_added_first(run):
    calls = run(_lookup(on_board=False))
    assert [q for q, _ in calls] == [ps.LOOKUP, ps.ADD_ITEM, ps.SET_STATUS]
    assert calls[1][1] == {"project": "PROJ", "content": "ISSUE"}
    assert calls[2][1]["item"] == "NEW"


def test_unassigning_with_an_open_pr_writes_nothing(run):
    calls = run(_lookup(assignees=0, linked=1, item_status=IN_PROGRESS))
    assert [q for q, _ in calls] == [ps.LOOKUP]


def _doc() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_an_issue_event_is_the_only_trigger():
    triggers = _doc()[True]
    assert triggers == {"issues": {"types": ["assigned", "unassigned"]}}


def test_permissions_stay_read_only():
    doc = _doc()
    assert doc["permissions"] == {"contents": "read"}
    assert "permissions" not in doc["jobs"]["status"]


def test_the_token_reaches_the_script_through_the_environment():
    job = _doc()["jobs"]["status"]
    step = next(s for s in job["steps"] if s.get("name") == "Move the card")
    assert step["env"]["GH_TOKEN"] == "${{ secrets.PROJECT_TOKEN }}"
    assert step["run"] == "python3 scripts/project_status.py"
    assert "secrets." not in step["run"]


def test_forks_do_not_run_it_and_runs_queue_per_issue():
    doc = _doc()
    assert doc["jobs"]["status"]["if"] == "github.repository == 'MSKazemi/yazses'"
    assert doc["concurrency"]["cancel-in-progress"] is False
    assert "github.event.issue.number" in doc["concurrency"]["group"]
