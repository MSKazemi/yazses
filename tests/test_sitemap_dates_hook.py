"""Sitemap dates must describe source changes, not the latest docs build."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from tests.gitprobe import require_git

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks/sitemap_dates.py"


@pytest.fixture(scope="module")
def hook():
    spec = importlib.util.spec_from_file_location("sitemap_dates", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _File:
    def __init__(self, path: Path) -> None:
        self.abs_src_path = str(path)


class _Page:
    def __init__(self, path: Path) -> None:
        self.file = _File(path)
        self.update_date = "the-build-date"


def test_a_tracked_page_uses_its_latest_commit_date(hook):
    # The hook returns an empty date when `git log` cannot run, so without this the
    # failure is `assert None` against an empty string -- true, and silent about the
    # fact that git, not the hook, is what did not work.
    require_git()
    page = _Page(ROOT / "docs/index.md")
    assert hook.on_page_markdown("content", page) == "content"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", page.update_date)


def test_an_untracked_or_generated_page_omits_lastmod(hook, tmp_path):
    source = tmp_path / "generated.md"
    source.write_text("generated", encoding="utf-8")
    page = _Page(source)
    hook.on_page_markdown("content", page)
    assert page.update_date == ""
