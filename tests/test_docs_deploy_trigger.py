"""The docs site must rebuild when anything it is built *from* changes.

`docs.yml` deploys on a `paths:` filter, and a path filter is a hand-written set — the
failure mode this project keeps meeting. It listed `docs/**` and `mkdocs.yml` and nothing
else, while `hooks/design_tier.py` injects the entire `design/` tree (269 tracked files:
ADRs, specifications, research notes) into the built site.

So a new decision record, or a correction to an existing one, deployed **nothing**. The
live site kept serving the previous text until some unrelated `docs/` commit happened to
trigger a rebuild. Six of the sixty commits before this test was written were in that
position, including two ADR corrections and one that changed what an ADR *claims a flag
does*. Nothing failed, nothing warned: a workflow that does not run leaves no trace.

The expected set is derived from `mkdocs.yml` — `docs_dir` and every entry under `hooks:` —
so a new hook reading a new tree fails here rather than going quietly stale.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "docs.yml"
MKDOCS = ROOT / "mkdocs.yml"


def _trigger_paths() -> list[str]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1: the key `on:` parses as the boolean True, not the string "on".
    triggers = doc.get(True, doc.get("on"))
    return list((triggers or {}).get("push", {}).get("paths") or [])


def _mkdocs_sources() -> set[str]:
    """Trees the site build reads, read out of the build's own configuration.

    `mkdocs.yml` is not valid YAML to a plain loader (it uses `!!python/name:` tags for
    the Material extensions), so the two keys are pulled out by line rather than parsed.
    """
    sources = {"mkdocs.yml"}
    for line in MKDOCS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("docs_dir:"):
            sources.add(f"{stripped.split(':', 1)[1].strip()}/**")
        elif stripped.startswith("- hooks/"):
            sources.add(f"{stripped.removeprefix('- ').split('/')[0]}/**")
    return sources


def test_the_workflow_declares_a_paths_filter_at_all() -> None:
    """Without a filter every push deploys, and the assertions below mean nothing."""
    assert _trigger_paths(), "docs.yml has no push `paths:` filter — this guard is vacuous"


def test_the_configuration_actually_yielded_sources() -> None:
    """If the line parse silently found nothing, the completeness test would pass empty."""
    sources = _mkdocs_sources()
    assert "docs/**" in sources, f"docs_dir was not parsed out of mkdocs.yml: {sources}"
    assert "hooks/**" in sources, f"no hooks: entries were parsed: {sources}"


def test_every_tree_the_site_is_built_from_triggers_a_deploy() -> None:
    missing = sorted(_mkdocs_sources() - set(_trigger_paths()))
    assert not missing, (
        f"the site is built from {missing} but a change there deploys nothing"
    )


def test_the_design_tier_triggers_a_deploy() -> None:
    """Named separately because it is the one the derivation cannot see.

    `design/` reaches the site through `hooks/design_tier.py`, not through `docs_dir`, so
    only the hook's own source is derivable — the tree it publishes is not.
    """
    assert "design/**" in _trigger_paths(), (
        "hooks/design_tier.py publishes design/ but a design-only commit does not deploy"
    )
