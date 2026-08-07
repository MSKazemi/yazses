"""Generate schema.org JSON-LD for the research pages at build time.

Why this exists, and why it is derived rather than hand-written: the research
section makes cited scientific claims, and the thing that makes a page useful to
a search engine or an AI answer engine is knowing *that it is a cited survey* and
*what it cites*. A hand-maintained JSON-LD block would drift the first time
somebody adds a reference and forgets the duplicate — so the markup is generated
from the same "## References" list the reader sees. There is one source.

What this does NOT claim to buy: there is no rich-result treatment for
`ScholarlyArticle` in Google Search, and none is expected. The justification is
machine comprehension — answer engines read structured data directly when
deciding what a page is and whether to cite it, and `citation` gives them the
provenance chain to the primary sources instead of stopping at us.

Emits `ScholarlyArticle` for pages that carry a references list, `TechArticle`
otherwise. Registered via `hooks:` in mkdocs.yml.
"""

from __future__ import annotations

import json
import re

# Only pages under this directory are touched. Anything else passes through.
RESEARCH_DIR = "research/"

_REFERENCES_HEADING = re.compile(r"^##\s+References\s*$", re.M)
_NEXT_HEADING = re.compile(r"^##\s+", re.M)
# A numbered reference item, including its wrapped continuation lines. The
# marker must sit at column 0 and continuations must be indented: a wrapped line
# can legitimately start with something like "2025. [doi:...]", and treating
# that as a new list item would split one reference into two.
_NUMBERED_ITEM = re.compile(r"^\d+\.[ \t]+(.*(?:\n(?![ \t]*$)(?!\d+\.[ \t]).*)*)", re.M)
_URL_IN_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")

_ANCHOR = re.compile(r"<a id=\"[^\"]*\"></a>")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3})(.+?)\1")
_CODE = re.compile(r"`([^`]+)`")
_WHITESPACE = re.compile(r"\s+")


def _to_plain_text(markdown: str) -> str:
    """Reduce a reference entry to one line of readable plain text."""
    text = _ANCHOR.sub("", markdown)
    text = _LINK.sub(r"\1", text)
    text = _CODE.sub(r"\1", text)
    text = _EMPHASIS.sub(r"\2", text)
    return _WHITESPACE.sub(" ", text).strip()


def _extract_references(markdown: str) -> list[tuple[str, str | None]]:
    """Pull (plain-text citation, first URL) pairs out of the References section."""
    heading = _REFERENCES_HEADING.search(markdown)
    if not heading:
        return []

    rest = markdown[heading.end() :]
    following = _NEXT_HEADING.search(rest)
    section = rest[: following.start()] if following else rest

    references: list[tuple[str, str | None]] = []
    for item in _NUMBERED_ITEM.finditer(section):
        raw = item.group(1)
        url_match = _URL_IN_LINK.search(raw)
        name = _to_plain_text(raw)
        if name:
            references.append((name, url_match.group(1) if url_match else None))
    return references


def _build_jsonld(page, config, references: list[tuple[str, str | None]]) -> str:
    site_url = (config.get("site_url") or "").rstrip("/")
    page_url = f"{site_url}/{page.file.dest_uri}" if site_url else None

    payload: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle" if references else "TechArticle",
        "headline": page.meta.get("title") or page.title,
        "name": page.meta.get("title") or page.title,
        "author": {"@type": "Person", "name": config.get("site_author")},
        "publisher": {"@type": "Organization", "name": config.get("site_name")},
        "license": "https://www.apache.org/licenses/LICENSE-2.0",
        "isAccessibleForFree": True,
    }
    if description := page.meta.get("description"):
        payload["description"] = description
    if page_url:
        payload["url"] = page_url
        payload["mainEntityOfPage"] = page_url
    if references:
        payload["citation"] = [
            {"@type": "CreativeWork", "name": name, **({"url": url} if url else {})}
            for name, url in references
        ]

    return (
        '<script type="application/ld+json">\n'
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n</script>\n\n"
    )


def on_page_markdown(markdown, page, config, files):  # noqa: ARG001 - MkDocs hook signature
    """Prepend research JSON-LD to pages under `research/`; others pass through."""
    if not page.file.src_uri.startswith(RESEARCH_DIR):
        return markdown

    return _build_jsonld(page, config, _extract_references(markdown)) + markdown
