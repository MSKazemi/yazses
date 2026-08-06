"""Tests for the FAQPage JSON-LD build hook (`hooks/faq_schema.py`).

The hook exists so the structured data cannot drift from the visible page, so
the behaviour worth pinning is: it reads the real headings, it strips markdown
to plain text, and it refuses to touch any page other than the FAQ.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "hooks" / "faq_schema.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("faq_schema", _HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["faq_schema"] = module
    spec.loader.exec_module(module)
    return module


faq_schema = _load_hook()


class _File:
    def __init__(self, src_uri: str) -> None:
        self.src_uri = src_uri


class _Page:
    def __init__(self, src_uri: str) -> None:
        self.file = _File(src_uri)


SAMPLE = """# Frequently asked questions

Intro prose that is not a question.

## What is YazSes?

YazSes is an **offline** [voice-dictation](https://example.com/x) daemon.
It runs on `Linux`.

## Does it need a GPU?

No. It runs on CPU.
"""


def test_extracts_every_heading_as_a_question():
    pairs = faq_schema._extract_qa_pairs(SAMPLE)
    assert [q for q, _ in pairs] == ["What is YazSes?", "Does it need a GPU?"]


def test_answer_is_plain_text_with_markdown_stripped():
    pairs = dict(faq_schema._extract_qa_pairs(SAMPLE))
    answer = pairs["What is YazSes?"]
    assert answer == "YazSes is an offline voice-dictation daemon. It runs on Linux."
    # No markdown syntax survives into the structured data.
    for token in ("**", "[", "](", "`"):
        assert token not in answer


def test_intro_prose_before_the_first_heading_is_not_a_question():
    pairs = faq_schema._extract_qa_pairs(SAMPLE)
    assert all("Intro prose" not in q for q, _ in pairs)
    assert all("Intro prose" not in a for _, a in pairs)


def test_heading_with_no_answer_body_is_skipped():
    pairs = faq_schema._extract_qa_pairs("## Dangling question?\n\n## Real one?\n\nYes.\n")
    assert pairs == [("Real one?", "Yes.")]


@pytest.mark.parametrize("src_uri", ["index.md", "comparison.md", "how-to/faq.md"])
def test_other_pages_are_returned_untouched(src_uri):
    out = faq_schema.on_page_markdown(SAMPLE, _Page(src_uri), {"site_url": "https://x/"}, None)
    assert out == SAMPLE


def test_faq_page_gets_valid_faqpage_jsonld_prepended():
    out = faq_schema.on_page_markdown(
        SAMPLE, _Page("faq.md"), {"site_url": "https://mskazemi.com/yazses/"}, None
    )
    assert out.endswith(SAMPLE), "original markdown must be preserved verbatim"

    payload = json.loads(out.split("<script type=\"application/ld+json\">")[1].split("</script>")[0])
    assert payload["@context"] == "https://schema.org"
    assert payload["@type"] == "FAQPage"
    assert payload["url"] == "https://mskazemi.com/yazses/faq.html"
    assert len(payload["mainEntity"]) == 2
    first = payload["mainEntity"][0]
    assert first["@type"] == "Question"
    assert first["acceptedAnswer"]["@type"] == "Answer"


def test_missing_site_url_does_not_crash_the_build():
    out = faq_schema.on_page_markdown(SAMPLE, _Page("faq.md"), {}, None)
    payload = json.loads(out.split("<script type=\"application/ld+json\">")[1].split("</script>")[0])
    assert payload["url"] == "/faq.html"


def test_real_faq_page_produces_questions():
    """Guards against the real page being restructured so the hook silently emits nothing."""
    faq = Path(__file__).resolve().parents[1] / "docs" / "faq.md"
    pairs = faq_schema._extract_qa_pairs(faq.read_text(encoding="utf-8"))
    assert len(pairs) >= 10
    assert all(q.endswith("?") for q, _ in pairs), "every FAQ heading should be a question"
