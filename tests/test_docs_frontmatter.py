"""Docs front-matter must survive being rendered into a meta tag.

MkDocs writes `description:` straight into `<meta name=description content="...">`
**without escaping**, so a double quote inside the value closes the attribute early.
The page then ships a description truncated mid-sentence, with the remainder leaking
out as junk attributes — and nothing fails: the build is green, the page looks fine,
and only the search snippet and the summary an AI answer engine quotes are wrong.

Found live on `docs/research/eye-control.md`, whose description mentioned a spoken
command in quotes and was cut off at the first one.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        loaded = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _pages_with_description() -> list[tuple[Path, str]]:
    out = []
    for path in sorted(DOCS.rglob("*.md")):
        desc = _front_matter(path).get("description")
        if isinstance(desc, str) and desc.strip():
            out.append((path, desc))
    return out


def test_there_are_pages_to_check():
    """Guard the guard: a parser that silently finds nothing would pass forever."""
    assert len(_pages_with_description()) >= 40


@pytest.mark.parametrize(
    "path,description",
    _pages_with_description(),
    ids=[str(p.relative_to(DOCS)) for p, _ in _pages_with_description()],
)
def test_description_has_no_double_quote(path: Path, description: str):
    assert '"' not in description, (
        f"{path.relative_to(DOCS)}: the description contains a double quote, which "
        "MkDocs emits unescaped into the meta tag and which truncates it there. "
        "Use single quotes for a quoted phrase."
    )


@pytest.mark.parametrize(
    "path,description",
    _pages_with_description(),
    ids=[str(p.relative_to(DOCS)) for p, _ in _pages_with_description()],
)
def test_description_is_a_usable_length(path: Path, description: str):
    """Catch a description that is missing in substance or has run away entirely.

    Not a style rule — search engines truncate the *display* around 155 characters and
    a longer one costs nothing. This only fails the two shapes that are always wrong:
    a stub too short to say anything, and a paragraph pasted in by accident.
    """
    assert 50 <= len(description) <= 360, (
        f"{path.relative_to(DOCS)}: description is {len(description)} characters; "
        "aim for roughly 50–360 so it reads as a summary rather than a stub or a page."
    )
