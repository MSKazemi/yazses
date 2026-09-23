"""Regression checks for the public Jules connection guide.

The guide deliberately has two different trust paths:
- contributors use Jules against their own fork today;
- direct upstream Jules remains gated by #447.

These checks are intentionally textual. They protect the high-risk part of the docs from
quietly drifting back to the superseded "connect upstream immediately" model.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "contribute" / "jules.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_jules_guide_exists_and_separates_the_two_access_paths() -> None:
    text = _read(GUIDE)

    assert "Path A — contributor: connect Jules to your own fork" in text
    assert "Path B — repository owner: direct upstream Jules connection" in text
    assert "Do not connect Jules directly to upstream yet" in text
    assert "#447" in text
    assert "Do not use #448 as the smoke task" in text


def test_jules_contributor_path_is_fork_first_and_self_owned() -> None:
    text = _read(GUIDE)

    for required in (
        "Only select repositories",
        "your fork",
        "Commit Authoring",
        "User only",
        "uv sync",
        "Run and Snapshot",
        "AGENTS.md",
        "cloud_agent_ready: true",
        "normal fork → upstream pull request",
    ):
        assert required in text


def test_jules_guide_is_discoverable_from_contributor_surfaces() -> None:
    surfaces = {
        ROOT / "README.md": "docs/contribute/jules.md",
        ROOT / "docs" / "contribute" / "ai-agents.md": "jules.md",
        ROOT / "campaign" / "agent-workers.md": "../docs/contribute/jules.md",
        ROOT / ".github" / "CONTRIBUTING.md": "../docs/contribute/jules.md",
        ROOT / "docs" / "contribute" / "start.md": "jules.md",
        ROOT / "mkdocs.yml": "Connect Google Jules: contribute/jules.md",
    }

    for path, link in surfaces.items():
        assert link in _read(path), f"{path.relative_to(ROOT)} does not link to Jules guide"


def test_jules_guide_does_not_present_trigger_label_as_readiness() -> None:
    text = _read(GUIDE)

    assert "execution trigger" in text
    assert "It is not:" in text
    assert "equivalent to `agent-ready`" in text
