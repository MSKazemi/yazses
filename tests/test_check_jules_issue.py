"""Offline tests for scripts/check-jules-issue.py."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-jules-issue.py"
SPEC = importlib.util.spec_from_file_location("check_jules_issue", SCRIPT)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)

CLOUD = preflight.CLOUD_READY


def body(
    *,
    remote: str = CLOUD,
    blockers: str = "_No response_",
    suitability: str = (
        "- [x] A coding agent can implement this end-to-end from this description alone"
    ),
) -> str:
    return f"""### One-sentence goal

Add a deterministic read-only preflight.

### Explicitly out of scope

No writes and no Jules API.

### Where this plugs in

scripts/check-jules-issue.py

### Acceptance criteria (Given / When / Then)

- [ ] Given an eligible issue, exit zero.

### Required tests

Pure unit tests with mocked HTTP.

### Definition-of-done command

uv run python -m pytest tests/test_check_jules_issue.py -q

### Blocked by (issue numbers)

{blockers}

### Remote-agent execution class

{remote}

### Suitable for

{suitability}
"""


def issue(
    *,
    author: str = "MSKazemi",
    labels: tuple[str, ...] = ("agent-ready",),
    state: str = "open",
    rendered_body: str | None = None,
    is_pr: bool = False,
):
    return preflight.IssueSnapshot(
        number=100,
        state=state,
        author=author,
        labels=frozenset(label.lower() for label in labels),
        body=rendered_body if rendered_body is not None else body(),
        is_pull_request=is_pr,
    )


def failure_text(report) -> str:
    return "\n".join(report.failures)


def test_eligible_structured_issue_passes():
    report = preflight.evaluate(issue())
    assert report.eligible
    assert report.failures == ()


def test_untrusted_author_fails():
    report = preflight.evaluate(issue(author="outside-contributor"))
    assert not report.eligible
    assert "trusted execution-contract author" in failure_text(report)


def test_missing_agent_ready_fails():
    report = preflight.evaluate(issue(labels=()))
    assert "missing required label: agent-ready" in report.failures


def test_existing_jules_label_fails_before_execution():
    report = preflight.evaluate(issue(labels=("agent-ready", "JULES")))
    assert "preflight is too late" in failure_text(report)


def test_non_cloud_remote_classes_fail():
    code_only = (
        "Code-ready only — implementation can run remotely, but "
        "human/device/native-language evidence is still required"
    )
    for value in (code_only, "Not suitable for remote-agent execution"):
        report = preflight.evaluate(issue(rendered_body=body(remote=value)))
        assert "remote-agent execution class is not Cloud-ready" in report.failures


def test_hardware_and_native_language_evidence_fail():
    suitability = """- [x] A coding agent can implement this end-to-end from this description alone
- [x] Needs a native-language/domain reviewer before merge
- [x] Needs real hardware to verify (cannot be done in a container)"""
    report = preflight.evaluate(issue(rendered_body=body(suitability=suitability)))
    text = failure_text(report)
    assert "real-hardware evidence is required" in text
    assert "native-language/domain evidence is required" in text


def test_hardware_and_research_labels_fail():
    report = preflight.evaluate(
        issue(labels=("agent-ready", "hardware-required", "research"))
    )
    text = failure_text(report)
    assert "hardware-required label" in text
    assert "research evidence issues" in text


def test_closed_blocker_passes():
    rendered = body(blockers="#378 (ADR approval)")
    report = preflight.evaluate(
        issue(rendered_body=rendered),
        blocker_states={378: "closed"},
    )
    assert report.eligible
    assert report.blockers == (378,)


def test_open_blocker_fails_and_names_it():
    rendered = body(blockers="#378 (ADR approval)")
    report = preflight.evaluate(
        issue(rendered_body=rendered),
        blocker_states={378: "open"},
    )
    assert "blocker #378 is still open" in report.failures


def test_two_blockers_with_one_open_fails_only_open_one():
    rendered = body(blockers="- #378\n- #463")
    report = preflight.evaluate(
        issue(rendered_body=rendered),
        blocker_states={378: "closed", 463: "open"},
    )
    assert "blocker #463 is still open" in report.failures
    assert "blocker #378 is still closed" not in report.failures


def test_unrelated_issue_reference_outside_blockers_is_ignored():
    rendered = body().replace(
        "Add a deterministic read-only preflight.",
        "Add a deterministic read-only preflight. Background: #999.",
    )
    report = preflight.evaluate(issue(rendered_body=rendered))
    assert report.eligible
    assert 999 not in report.blockers


def test_ambiguous_blocker_field_fails_closed():
    report = preflight.evaluate(
        issue(rendered_body=body(blockers="waiting on the ADR"))
    )
    assert "ambiguous blocker line" in failure_text(report)


def test_missing_required_section_fails_closed():
    rendered = body().replace(
        "### Required tests\n\nPure unit tests with mocked HTTP.\n\n",
        "",
    )
    report = preflight.evaluate(issue(rendered_body=rendered))
    assert "missing or empty structured section: Required tests" in report.failures


def test_issue_comments_are_not_part_of_snapshot_or_policy():
    api_payload = {
        "number": 100,
        "state": "open",
        "user": {"login": "MSKazemi"},
        "labels": [{"name": "agent-ready"}],
        "body": body(),
        "comments": 99,
        "comments_url": "https://example.invalid/comments",
    }
    snapshot = preflight.snapshot_from_api(api_payload)
    report = preflight.evaluate(snapshot)

    assert report.eligible
    assert not hasattr(snapshot, "comments_url")


def test_multiple_failures_are_reported_together():
    report = preflight.evaluate(
        issue(
            author="outside",
            labels=("jules", "research"),
            state="closed",
            rendered_body=body(remote="Not suitable for remote-agent execution"),
        )
    )
    text = failure_text(report)
    assert "issue is not open" in text
    assert "trusted execution-contract author" in text
    assert "missing required label: agent-ready" in text
    assert "preflight is too late" in text
    assert "remote-agent execution class is not Cloud-ready" in text
    assert "research evidence issues" in text


class FakeResponse(io.BytesIO):
    status = 200
    headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_github_io_is_get_only_and_token_is_optional(monkeypatch):
    seen: list[urllib.request.Request] = []

    def fake_urlopen(request, timeout):
        assert timeout == 30
        seen.append(request)
        payload = {
            "number": 100,
            "state": "open",
            "user": {"login": "MSKazemi"},
            "labels": [{"name": "agent-ready"}],
            "body": body(),
        }
        return FakeResponse(json.dumps(payload).encode())

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(preflight.urllib.request, "urlopen", fake_urlopen)

    snapshot = preflight.fetch_issue(100)

    assert snapshot.number == 100
    assert len(seen) == 1
    assert seen[0].get_method() == "GET"
    assert seen[0].get_header("Authorization") is None


def test_render_success_is_explicitly_not_execution_or_merge_authority():
    text = preflight.render(100, preflight.EligibilityReport((), ()))
    assert "ELIGIBLE" in text
    assert "does not start Jules" in text
    assert "not authorization to merge" in text


def test_positive_issue_number_rejects_non_positive_values():
    for value in ("0", "-1"):
        try:
            preflight.positive_issue_number(value)
        except Exception:
            pass
        else:
            raise AssertionError(f"{value} should have been rejected")
