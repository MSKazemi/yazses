"""The site-search index leaves out design-tier bodies and preview release notes only."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks/search_scope.py"


@pytest.fixture(scope="module")
def hook():
    spec = importlib.util.spec_from_file_location("search_scope", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "src_uri",
    [
        "design/adr/adr-019-egress-inventory-and-escalation.md",
        "design/specs/eye-implicit-calibration.md",
        "design/research/2026-10-21-pay-for-what-you-enable.md",
        "design/architecture.md",
        "releases/v2.9.0-dev.3.md",
    ],
)
def test_design_bodies_and_previews_are_left_out(hook, src_uri):
    assert hook.excluded(src_uri)


@pytest.mark.parametrize(
    "src_uri",
    [
        "design/adr/index.md",
        "design/README.md",
        "design/specs/index.md",
        "releases/v2.43.2.md",
        "releases/index.md",
        "index.md",
        "get-started.md",
        "how-to/air-gapped.md",
        "research/eye-control.md",
        "zh/chinese-voice-typing.md",
    ],
)
def test_user_pages_section_indexes_and_stable_releases_stay(hook, src_uri):
    assert not hook.excluded(src_uri)


def test_the_hook_sets_material_search_exclude_and_keeps_other_meta(hook):
    class File:
        src_uri = "design/adr/adr-020-agent-protocols.md"

    class Page:
        file = File()
        meta = {"title": "ADR-020", "search": {"boost": 2}}

    page = Page()
    assert hook.on_page_markdown("body", page=page) == "body"
    assert page.meta["search"] == {"boost": 2, "exclude": True}
    assert page.meta["title"] == "ADR-020"


def test_the_hook_is_registered_in_the_site_build():
    assert "- hooks/search_scope.py" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
