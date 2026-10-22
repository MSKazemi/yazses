"""Give the home page's share card its real title, not the bare site name.

Material's social plugin titles every page "<page title> - <site name>", except the home
page, which gets the site name alone (its `page_title_with_site_name` template branches on
`page.is_homepage`). So a link to https://mskazemi.com/yazses/ shared anywhere previewed
as "YazSes" -- no hint of what it is -- while the page's own <title> says "YazSes --
offline voice dictation for Linux, macOS & Windows".

This rewrites only the `og:title` and `twitter:title` meta tags, only on the home page,
to that page title. Overriding the plugin's layout instead would mean copying a template
of more than 200 lines that changes with every Material release. The rewrite accepts
quoted and minified (unquoted) attribute forms, because the minify plugin may run first.
Tested in tests/test_home_social_title_hook.py.
"""

from __future__ import annotations

import html
import re
from typing import Any

_META = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r"""([a-zA-Z][\w:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
_TITLE_KEYS = {"og:title", "twitter:title"}


def _attrs(tag: str) -> dict[str, str]:
    return {m.group(1).lower(): next(v for v in m.groups()[1:] if v is not None) for m in _ATTR.finditer(tag)}


def retitle(output: str, title: str) -> str:
    """Return *output* with the og/twitter title meta tags set to *title*."""
    value = html.escape(title, quote=True)

    def fix(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = _attrs(tag)
        key = attrs.get("property") or attrs.get("name") or ""
        if key.lower() not in _TITLE_KEYS:
            return tag
        prefix = "property" if "property" in attrs else "name"
        return f'<meta {prefix}="{key}" content="{value}">'

    return _META.sub(fix, output)


def on_post_page(output: str, page: Any = None, config: Any = None, **_: Any) -> str:
    if page is None or not getattr(page, "is_homepage", False):
        return output
    title = (page.meta or {}).get("title") or page.title
    return retitle(output, title) if title else output
