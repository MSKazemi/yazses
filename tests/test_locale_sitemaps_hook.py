"""Every sitemap.xml that Material's language selector fetches must exist."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks/locale_sitemaps.py"
SITE = "https://mskazemi.com/yazses/"

ROOT_SITEMAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
         <loc>{SITE}index.html</loc>
    </url>
    <url>
         <loc>{SITE}ar/index.html</loc>
         <lastmod>2026-10-01</lastmod>
    </url>
    <url>
         <loc>{SITE}how-to/air-gapped.html</loc>
    </url>
</urlset>
"""


@pytest.fixture(scope="module")
def hook():
    spec = importlib.util.spec_from_file_location("locale_sitemaps", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alternates_are_found_in_minified_and_quoted_html(hook):
    html = (
        '<link rel="alternate" hreflang="ar" href="https://mskazemi.com/yazses/ar/index.html">'
        "<link rel=alternate type=text/markdown href=air-gapped.md>"
        "<link rel=stylesheet href=x.css>"
        "<link href='feed.xml' rel='alternate' type='application/rss+xml'>"
    )
    assert hook.alternate_hrefs(html) == [
        "https://mskazemi.com/yazses/ar/index.html",
        "air-gapped.md",
        "feed.xml",
    ]


def test_requested_sitemaps_resolve_like_the_browser(hook):
    html = (
        '<link rel="alternate" hreflang="ar" href="https://mskazemi.com/yazses/ar/index.html">'
        "<link rel=alternate type=text/markdown href=air-gapped.md>"
        '<link rel="alternate" href="https://elsewhere.example/x.html">'
    )
    wanted = hook.requested_sitemaps(f"{SITE}how-to/air-gapped.html", html, SITE)
    assert wanted == {f"{SITE}ar/sitemap.xml", f"{SITE}how-to/sitemap.xml"}


def test_a_scoped_sitemap_lists_only_its_directory(hook):
    xml = hook.scoped_sitemap(ROOT_SITEMAP, f"{SITE}ar/")
    assert f"<loc>{SITE}ar/index.html</loc>" in xml
    assert "<lastmod>2026-10-01</lastmod>" in xml
    assert f"<loc>{SITE}index.html</loc>" not in xml
    assert xml.startswith('<?xml version="1.0"') and xml.rstrip().endswith("</urlset>")


def test_post_build_writes_missing_sitemaps_and_keeps_the_root(hook, tmp_path):
    (tmp_path / "sitemap.xml").write_text(ROOT_SITEMAP, encoding="utf-8")
    hook.on_pre_build()

    class Page:
        canonical_url = f"{SITE}index.html"

    config = {"site_url": SITE, "site_dir": str(tmp_path)}
    html = (
        '<link rel="alternate" hreflang="ar" href="https://mskazemi.com/yazses/ar/index.html">'
        "<link rel=alternate type=text/markdown href=index.md>"
    )
    assert hook.on_post_page(html, page=Page(), config=config) == html
    hook.on_post_build(config)

    assert (tmp_path / "sitemap.xml").read_text(encoding="utf-8") == ROOT_SITEMAP
    ar = (tmp_path / "ar" / "sitemap.xml").read_text(encoding="utf-8")
    assert f"<loc>{SITE}ar/index.html</loc>" in ar
    assert f"<loc>{SITE}index.html</loc>" not in ar
