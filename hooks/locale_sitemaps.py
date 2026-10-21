"""Publish a ``sitemap.xml`` wherever Material's instant navigation will ask for one.

Material's language-selector integration runs on every page: for each
``<link rel="alternate">`` in the head it fetches ``new URL("sitemap.xml", href)`` and uses
the result to keep a reader on the same page when they switch language. This site emits
many alternates -- an ``hreflang`` link per translation (hooks/hreflang.py) and a Markdown
twin per page (hooks/markdown_mirrors.py) -- but MkDocs writes only the root
``sitemap.xml``. Measured on the live home page on 2026-10-21: 27 console errors, one 404
per translation directory (``/yazses/ar/sitemap.xml``, ``/yazses/de/sitemap.xml``, ...), on
every page view.

The fix is derived, not listed: ``on_post_page`` records the directory of every
``sitemap.xml`` that a page's alternates resolve to, exactly as the browser computes it,
and ``on_post_build`` writes a sitemap into each such directory that lacks one, containing
the root sitemap's ``<url>`` entries that live under it. A sitemap scoped to its own
directory is valid under the sitemaps protocol, and none of these is advertised to search
engines -- robots.txt and Search Console keep pointing at the root one.

The parsing is pure and tested in ``tests/test_locale_sitemaps_hook.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

_LINK = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
# Minified output drops attribute quotes, so accept quoted and bare values alike.
_ATTR = re.compile(r"""([a-zA-Z][\w:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
_URL_BLOCK = re.compile(r"<url>.*?</url>", re.DOTALL)
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")

_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
    'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
)


def alternate_hrefs(html: str) -> list[str]:
    """Every ``href`` of a ``<link>`` whose ``rel`` includes ``alternate``."""
    hrefs: list[str] = []
    for tag in _LINK.findall(html):
        attrs = {m.group(1).lower(): next(v for v in m.groups()[1:] if v is not None) for m in _ATTR.finditer(tag)}
        if "alternate" in attrs.get("rel", "").lower().split() and attrs.get("href"):
            hrefs.append(attrs["href"])
    return hrefs


def requested_sitemaps(page_url: str, html: str, site_url: str) -> set[str]:
    """Absolute sitemap URLs the browser will fetch for this page, limited to this site."""
    wanted = set()
    for href in alternate_hrefs(html):
        target = urljoin(urljoin(page_url, href), "sitemap.xml")
        if target.startswith(site_url):
            wanted.add(target)
    return wanted


def scoped_sitemap(root_sitemap: str, directory_url: str) -> str:
    """The root sitemap's ``<url>`` blocks whose ``<loc>`` is under *directory_url*."""
    blocks = []
    for block in _URL_BLOCK.findall(root_sitemap):
        loc = _LOC.search(block)
        if loc and loc.group(1).startswith(directory_url):
            blocks.append(block)
    return _HEADER + "".join(f"  {b}\n" for b in blocks) + "</urlset>\n"


_WANTED: set[str] = set()


def on_pre_build(**_: Any) -> None:
    _WANTED.clear()


def on_post_page(output: str, page: Any = None, config: Any = None, **_: Any) -> str:
    site_url = (config or {}).get("site_url") or ""
    url = getattr(page, "canonical_url", None) or ""
    if site_url and url:
        _WANTED.update(requested_sitemaps(url, output, site_url))
    return output


def on_post_build(config: Any, **_: Any) -> None:
    site_url = config.get("site_url") or ""
    site_dir = Path(config["site_dir"])
    root = site_dir / "sitemap.xml"
    if not site_url or not root.is_file():
        return
    root_xml = root.read_text(encoding="utf-8")
    for target in sorted(_WANTED):
        relative = target[len(site_url) :]
        path = site_dir / relative
        if path.exists():
            continue
        directory_url = target[: -len("sitemap.xml")]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(scoped_sitemap(root_xml, directory_url), encoding="utf-8")
