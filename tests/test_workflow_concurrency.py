"""PR workflow concurrency must retire obsolete heads without dropping durable runs."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
PULL_REQUEST_TRIGGER = re.compile(r"(?m)^  pull_request:\s*$")


def _read(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_mixed_event_workflows_cancel_only_pull_requests():
    """run_id isolates non-PR runs; same-PR runs share a cancellable group."""
    expected = {
        "test.yml": "tests",
        "codeql.yml": "codeql",
        "build-macos.yml": "build-macos",
        "build-windows.yml": "build-windows",
        "flatpak.yml": "flatpak",
        "macos-smoke.yml": "macos-smoke",
        "msix-validate.yml": "msix-validate",
    }
    for name, prefix in expected.items():
        text = _read(name)
        assert (
            f"group: {prefix}-${{{{ github.event.pull_request.number || github.run_id }}}}"
            in text
        )
        assert "cancel-in-progress: true" in text


def test_pr_only_workflows_cancel_prior_run_for_same_pr():
    """Different PR numbers get different groups; the same PR keeps only its newest run."""
    expected = {
        "dependency-review.yml": "dependency-review",
        "labeler.yml": "label-prs",
    }
    for name, prefix in expected.items():
        text = _read(name)
        assert (
            f"group: {prefix}-${{{{ github.event.pull_request.number }}}}"
            in text
        )
        assert "cancel-in-progress: true" in text


def test_every_pull_request_workflow_declares_a_superseding_policy():
    """A newly-added PR workflow must decide how obsolete heads leave the queue."""
    missing = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        doc = yaml.safe_load(text) or {}
        # YAML 1.1 parses the key on: as boolean True.
        triggers = doc.get(True, doc.get("on")) or {}
        if "pull_request" not in triggers:
            continue
        if "\nconcurrency:" not in text or "cancel-in-progress:" not in text:
            missing.append(path.name)
    assert not missing, (
        "pull_request workflows without an explicit concurrency/cancellation policy: "
        f"{missing}"
    )


def test_docs_uses_pr_only_cancellation_not_global_deploy_cancellation():
    text = _read("docs.yml")
    assert "group: docs-${{ github.event.pull_request.number || github.ref }}" in text
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
