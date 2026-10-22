"""Keep the site-search index to the pages a visitor searches for.

Material downloads the whole ``search/search_index.json`` at high priority on every page
view. Measured on 2026-10-22, it was 6.1 MB uncompressed (1.8 MB over the wire) and 6,818
entries. 57 % of it was the published design tier (ADRs, specifications, research notes),
which hooks/design_tier.py injects, plus every development-preview release note. Under
Lighthouse's mobile throttling that one file held the home page's largest paint back by
tens of seconds.

The design pages stay published, in the navigation, in the sitemap and in search engines.
Only the in-browser index drops their bodies. Each section's index page (``index.md`` /
``README.md``) stays searchable, so a search for "ADR" or "specification" still lands
on the right list. Stable release notes stay too. Previews (``v2.9.0-dev.3``) are
superseded by the stable release they lead to, so they are dropped from the index.

The decision is pure (``excluded``) and tested in ``tests/test_search_scope_hook.py``.
"""

from __future__ import annotations

import re
from typing import Any

_DEV_RELEASE = re.compile(r"^releases/v[^/]*-dev[^/]*\.md$")
_SECTION_INDEX = {"index.md", "README.md"}


def excluded(src_uri: str) -> bool:
    """True when a page should be left out of the site-search index."""
    name = src_uri.rsplit("/", 1)[-1]
    if src_uri.startswith("design/"):
        return name not in _SECTION_INDEX
    return bool(_DEV_RELEASE.match(src_uri))


def on_page_markdown(markdown: str, page: Any = None, **_: Any) -> str:
    if page is not None and excluded(page.file.src_uri):
        # Material's search plugin reads this from the page meta in on_page_context,
        # which runs after every on_page_markdown handler.
        search = dict(page.meta.get("search") or {})
        search["exclude"] = True
        page.meta["search"] = search
    return markdown
