"""Static contract for the manual Jules pre-trigger workflow."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "jules-issue-preflight.yml"


def _doc() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_is_manual_only():
    doc = _doc()
    triggers = doc[True]

    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["issue_number"]["required"] is True


def test_permissions_are_exactly_read_only():
    doc = _doc()
    assert doc["permissions"] == {"contents": "read", "issues": "read"}

    job = doc["jobs"]["preflight"]
    assert "permissions" not in job


def test_workflow_calls_the_checker_and_never_mutates_github():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/check-jules-issue.py" in text
    assert "GITHUB_STEP_SUMMARY" in text
    assert "gh issue edit" not in text
    assert "gh issue close" not in text
    assert "gh label" not in text
    assert "curl -X POST" not in text
    assert "curl -X PATCH" not in text
    assert "JULES_API_KEY" not in text


def test_user_input_is_passed_via_env_not_interpolated_into_shell():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ISSUE_NUMBER: ${{ inputs.issue_number }}" in text
    assert 'check-jules-issue.py "${{ inputs.issue_number }}"' not in text


def test_checker_result_always_reaches_step_summary():
    run_block = next(
        step["run"]
        for step in _doc()["jobs"]["preflight"]["steps"]
        if step.get("name") == "Run read-only preflight"
    )

    assert "set +e" in run_block
    assert "PIPESTATUS[0]" in run_block
    assert 'cat preflight.md >> "$GITHUB_STEP_SUMMARY"' in run_block
    assert 'exit "$status"' in run_block
    assert "python3 scripts/check-jules-issue.py" in run_block
