"""Contract tests for the agent-ready GitHub issue form.

Remote execution is a stricter property than ordinary agent readiness.  Keep that
distinction machine-readable because the Jules pre-trigger checker will fail
closed on this field instead of guessing from prose.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / "agent_task.yml"

EXPECTED_REMOTE_OPTIONS = [
    "Cloud-ready — implementation and all required evidence can be completed in a clean VM",
    "Code-ready only — implementation can run remotely, but human/device/native-language evidence is still required",
    "Not suitable for remote-agent execution",
]


def _body_items() -> list[dict]:
    form = yaml.safe_load(FORM.read_text(encoding="utf-8"))
    assert isinstance(form, dict)
    body = form.get("body")
    assert isinstance(body, list)
    return body


def _item(item_id: str) -> dict:
    matches = [item for item in _body_items() if item.get("id") == item_id]
    assert len(matches) == 1, f"expected exactly one issue-form item with id={item_id!r}"
    return matches[0]


def test_remote_execution_class_is_required_and_three_state():
    item = _item("remote_execution")

    assert item["type"] == "dropdown"
    assert item["validations"]["required"] is True
    assert item["attributes"]["options"] == EXPECTED_REMOTE_OPTIONS


def test_remote_execution_wording_separates_readiness_from_execution_and_merge():
    text = " ".join(
        [
            str(_item("remote_execution")["attributes"].get("label", "")),
            str(_item("remote_execution")["attributes"].get("description", "")),
            *EXPECTED_REMOTE_OPTIONS,
        ]
    ).lower()

    assert "does not start an agent" in text
    assert "authorize a merge" in text
    assert "all required evidence" in text
    assert "human/device/native-language evidence" in text
    assert "cloud_agent_ready" in text


def test_existing_human_evidence_suitability_signals_remain_present():
    options = [
        option["label"]
        for option in _item("suitability")["attributes"]["options"]
    ]

    assert "A coding agent can implement this end-to-end from this description alone" in options
    assert "Needs a native-language/domain reviewer before merge" in options
    assert "Needs real hardware to verify (cannot be done in a container)" in options
