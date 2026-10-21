"""Docs validation and deployment must cover the same source tree.

A strict MkDocs failure discovered only after merge is a CI design failure: the
information existed on the PR, but the validating workflow did not run there.
These tests keep the pull-request validation trigger aligned with the main deploy
trigger and with the trees MkDocs actually reads.
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "docs.yml"
MKDOCS = ROOT / "mkdocs.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers() -> dict:
    doc = _workflow()
    # YAML 1.1 parses the key on: as boolean True rather than the string "on".
    return doc.get(True, doc.get("on")) or {}


def _trigger_paths(event: str) -> list[str]:
    return list((_triggers().get(event) or {}).get("paths") or [])


def _mkdocs_sources() -> set[str]:
    """Trees the site build reads, read out of the build configuration."""
    sources = {"mkdocs.yml"}
    for line in MKDOCS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("docs_dir:"):
            sources.add(f"{stripped.split(':', 1)[1].strip()}/**")
        elif stripped.startswith("custom_dir:"):
            # Theme overrides (overrides/home.html is the landing page). Missing
            # from the filter, a template-only change built and deployed nothing.
            sources.add(f"{stripped.split(':', 1)[1].strip()}/**")
        elif stripped.startswith("- hooks/"):
            sources.add(f"{stripped.removeprefix('- ').split('/')[0]}/**")
    return sources


def _hook_build_inputs() -> set[str]:
    """Files outside the hook trees that a hook declares it reads (``BUILD_INPUTS``).

    Read with ``ast`` rather than by importing, so the test does not execute build code.
    """
    inputs: set[str] = set()
    for line in MKDOCS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- hooks/"):
            continue
        tree = ast.parse((ROOT / stripped.removeprefix("- ")).read_text(encoding="utf-8"))
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "BUILD_INPUTS" for t in node.targets)
            ):
                inputs.update(ast.literal_eval(node.value))
    return inputs


def test_a_file_a_hook_reads_triggers_both_validation_and_deploy() -> None:
    # hooks/project_status.py renders release status from CHANGELOG.md. Without
    # CHANGELOG.md in the filter, a release would leave the home page announcing the
    # previous one until an unrelated docs commit happened to rebuild it.
    inputs = _hook_build_inputs()
    assert "CHANGELOG.md" in inputs, f"BUILD_INPUTS was not read from the hooks: {inputs}"
    for event in ("push", "pull_request"):
        missing = sorted(inputs - set(_trigger_paths(event)))
        assert not missing, f"a hook reads {missing} but {event} does not run docs.yml"


def test_push_and_pull_request_both_have_path_filters() -> None:
    for event in ("push", "pull_request"):
        assert _trigger_paths(event), (
            f"docs.yml has no {event} paths filter -- the docs contract is vacuous"
        )


def test_the_configuration_actually_yielded_sources() -> None:
    sources = _mkdocs_sources()
    assert "docs/**" in sources, f"docs_dir was not parsed out of mkdocs.yml: {sources}"
    assert "hooks/**" in sources, f"no hooks entries were parsed: {sources}"
    assert "overrides/**" in sources, f"theme.custom_dir was not parsed: {sources}"


def test_every_site_source_triggers_both_validation_and_deploy() -> None:
    for event in ("push", "pull_request"):
        missing = sorted(_mkdocs_sources() - set(_trigger_paths(event)))
        assert not missing, (
            f"the site is built from {missing} but {event} does not run docs.yml"
        )


def test_design_tier_is_validated_before_merge_and_deployed_after_merge() -> None:
    for event in ("push", "pull_request"):
        assert "design/**" in _trigger_paths(event), (
            f"hooks/design_tier.py publishes design/ but {event} ignores design changes"
        )


def test_pr_and_push_path_filters_cannot_drift() -> None:
    assert set(_trigger_paths("pull_request")) == set(_trigger_paths("push"))


def test_pull_requests_build_but_cannot_deploy_pages() -> None:
    doc = _workflow()
    deploy_if = str(doc["jobs"]["deploy"].get("if", ""))
    assert "github.event_name" in deploy_if
    assert "pull_request" in deploy_if
    assert "!=" in deploy_if

    raw = WORKFLOW.read_text(encoding="utf-8")
    assert raw.count("if: ${{ github.event_name != 'pull_request' }}") >= 3


def test_docs_prs_cancel_obsolete_heads_but_main_deploys_do_not() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "group: docs-${{ github.event.pull_request.number || github.ref }}" in raw
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in raw
