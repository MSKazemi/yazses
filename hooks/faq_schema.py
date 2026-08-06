"""Generate schema.org FAQPage JSON-LD for the FAQ page at build time.

Google requires structured data to match the content visible on the page, so a
hand-maintained JSON-LD block is a liability: the moment someone edits an answer
in `faq.md` and forgets the duplicate, the page is making claims in its markup
that it does not make on screen. Deriving the markup from the markdown removes
that failure mode entirely — the schema cannot drift because there is only one
source.

FAQ rich results are also one of the formats AI answer engines read directly, so
this is the highest-value structured-data surface on the site after the
SoftwareApplication block on the homepage.

Registered via `hooks:` in mkdocs.yml.
"""

from __future__ import annotations

import json
import re

# The page this applies to. Anything else passes through untouched.
FAQ_SRC = "faq.md"

_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.M)

# Markdown inline constructs to reduce to their plain-text content. Schema.org
# answers may carry limited HTML, but plain text is unambiguous and avoids
# emitting half-escaped markup into the JSON.
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_CODE = re.compile(r"`([^`]+)`")
_BOLD_ITALIC = re.compile(r"(\*{1,3}|_{1,3})(.+?)\1")
_WHITESPACE = re.compile(r"\s+")


def _to_plain_text(markdown: str) -> str:
    """Reduce a markdown answer to a single line of readable plain text."""
    text = _IMAGE.sub("", markdown)
    text = _LINK.sub(r"\1", text)
    text = _CODE.sub(r"\1", text)
    text = _BOLD_ITALIC.sub(r"\2", text)
    # Drop fenced blocks, list bullets and blockquote markers; the answers are
    # prose, and any stray marker would read as literal punctuation.
    text = re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)
    text = re.sub(r"^\s*[->*+]\s+", "", text, flags=re.M)
    return _WHITESPACE.sub(" ", text).strip()


def _extract_qa_pairs(markdown: str) -> list[tuple[str, str]]:
    """Pull (question, answer) pairs from `## …` headings and the prose under them."""
    pairs: list[tuple[str, str]] = []
    matches = list(_HEADING.finditer(markdown))
    for i, match in enumerate(matches):
        question = _to_plain_text(match.group(1))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        answer = _to_plain_text(markdown[match.end() : end])
        if question and answer:
            pairs.append((question, answer))
    return pairs


def _build_jsonld(pairs: list[tuple[str, str]], page_url: str) -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "url": page_url,
        "mainEntity": [
            {
                "@type": "Question",
                "name": question,
                "acceptedAnswer": {"@type": "Answer", "text": answer},
            }
            for question, answer in pairs
        ],
    }
    return (
        '<script type="application/ld+json">\n'
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n</script>\n\n"
    )


def on_page_markdown(markdown, page, config, files):  # noqa: ARG001 - MkDocs hook signature
    """Prepend FAQPage JSON-LD to the FAQ page. Other pages are returned unchanged."""
    if page.file.src_uri != FAQ_SRC:
        return markdown

    pairs = _extract_qa_pairs(markdown)
    if not pairs:
        return markdown

    page_url = (config.get("site_url") or "").rstrip("/") + "/" + FAQ_SRC.replace(".md", ".html")
    return _build_jsonld(pairs, page_url) + markdown
