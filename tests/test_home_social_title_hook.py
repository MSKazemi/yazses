"""The home page's share card carries the page title, not the bare site name."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks/home_social_title.py"
TITLE = "YazSes — offline voice dictation for Linux, macOS & Windows"


@pytest.fixture(scope="module")
def hook():
    spec = importlib.util.spec_from_file_location("home_social_title", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Page:
    def __init__(self, homepage: bool) -> None:
        self.is_homepage = homepage
        self.meta = {"title": TITLE}
        self.title = TITLE


MINIFIED = (
    "<meta property=og:type content=website>"
    "<meta property=og:title content=YazSes>"
    "<meta property=twitter:title content=YazSes>"
    '<meta name="description" content="Hold a key">'
)


def test_minified_tags_on_the_home_page_get_the_page_title(hook):
    out = hook.on_post_page(MINIFIED, page=_Page(True))
    assert '<meta property="og:title" content="YazSes — offline voice dictation for Linux, macOS &amp; Windows">' in out
    assert '<meta property="twitter:title" content="YazSes — offline voice dictation for Linux, macOS &amp; Windows">' in out
    # Everything else is untouched.
    assert "<meta property=og:type content=website>" in out
    assert '<meta name="description" content="Hold a key">' in out


def test_quoted_name_form_is_handled(hook):
    out = hook.retitle('<meta name="twitter:title" content="YazSes">', TITLE)
    assert out.startswith('<meta name="twitter:title" content="YazSes — ')


def test_other_pages_are_left_alone(hook):
    assert hook.on_post_page(MINIFIED, page=_Page(False)) == MINIFIED


def test_the_hook_is_registered_in_the_site_build():
    assert "- hooks/home_social_title.py" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
