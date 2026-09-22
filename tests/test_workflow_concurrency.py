"""PR workflow concurrency must retire obsolete heads without dropping main checks."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def _read(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_mixed_event_workflows_cancel_only_pull_requests():
    """run_id isolates non-PR runs; only same-PR runs share a cancellable group."""
    expected = {
        "test.yml": "tests",
        "codeql.yml": "codeql",
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
