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
    ids=[p.relative_to(DOCS).as_posix() for p, _ in _pages_with_description()],
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
    ids=[p.relative_to(DOCS).as_posix() for p, _ in _pages_with_description()],
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


# ---- front matter that does not parse at all ----------------------------
#
# The guard above reads the front matter with `yaml.safe_load` and returns `{}`
# when that raises. That is the right behaviour for a helper and the wrong
# behaviour for a guard: a page whose front matter is *unparseable* declares no
# description, so it is skipped rather than reported, and the one check meant to
# protect descriptions goes quiet exactly when a description has been destroyed.
#
# The trigger is an unquoted colon. YAML reads `description: A vs B: notes` as a
# nested mapping, fails, and MkDocs discards the **whole block** — so the page
# loses its `title:` as well and falls back to `site_description`, identically on
# every affected page. Nothing goes red: `mkdocs build --strict` is silent about
# it, the page renders, and only the search snippet and the tab title are wrong.
#
# Found on five `docs/compare/` pages at once, all with the same shape
# (`... dictation tools: GPU vs CPU`). Quoting the value fixes it.


def _pages_with_front_matter() -> list[Path]:
    """Every page that opens a `---` block, parseable or not."""
    return [
        p
        for p in sorted(DOCS.rglob("*.md"))
        if p.read_text(encoding="utf-8").startswith("---")
        and p.read_text(encoding="utf-8").find("\n---", 3) != -1
    ]


def test_there_is_front_matter_to_parse():
    """Guard the guard: this passes over an empty list."""
    assert len(_pages_with_front_matter()) >= 40


@pytest.mark.parametrize(
    "path",
    _pages_with_front_matter(),
    ids=[p.relative_to(DOCS).as_posix() for p in _pages_with_front_matter()],
)
def test_front_matter_parses(path: Path):
    text = path.read_text(encoding="utf-8")
    block = text[3 : text.find("\n---", 3)]
    try:
        loaded = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise AssertionError(
            f"{path.relative_to(DOCS)}: the front matter is not valid YAML, so "
            f"MkDocs drops all of it -- the page loses its title and its "
            f"description and silently falls back to site_description. The usual "
            f"cause is an unquoted colon in a value; wrap the value in double "
            f"quotes. YAML said: {exc}"
        ) from exc
    assert isinstance(loaded, dict), (
        f"{path.relative_to(DOCS)}: the front matter parsed as "
        f"{type(loaded).__name__}, not a mapping, so MkDocs reads no keys from it."
    )


# ---- the compare pages are built to win a search click ------------------
#
# Scoped to `docs/compare/` on purpose. 87 of the 135 pages that declare a
# description are longer than this and that is fine -- they are documentation a
# reader has already arrived at. The compare tree is the opposite: its whole job
# is the snippet under a search result for someone deciding between two tools, and
# Google truncates that near 160 characters. A description that says what makes
# YazSes different in its last 70 characters says it to nobody.

COMPARE = DOCS / "compare"
SNIPPET_LIMIT = 160


def _compare_pages() -> list[Path]:
    return sorted(COMPARE.rglob("*.md"))


def test_there_are_compare_pages():
    assert len(_compare_pages()) >= 5


@pytest.mark.parametrize(
    "path",
    _compare_pages(),
    ids=[p.relative_to(DOCS).as_posix() for p in _compare_pages()],
)
def test_compare_description_fits_a_search_snippet(path: Path):
    desc = _front_matter(path).get("description")
    assert isinstance(desc, str) and desc.strip(), (
        f"{path.relative_to(DOCS)}: a compare page with no description gets the "
        f"generic site_description as its search snippet, which says nothing "
        f"about the comparison the reader searched for."
    )
    assert len(desc) <= SNIPPET_LIMIT, (
        f"{path.relative_to(DOCS)}: the description is {len(desc)} characters and "
        f"Google truncates near {SNIPPET_LIMIT}, so the tail is cut. Put the "
        f"differentiator first and shorten."
    )


# --------------------------------------------------------------------------
# A page that declares no description at all is invisible to the check above
# --------------------------------------------------------------------------
#
# `_pages_with_description()` filters to pages that *have* one, so a page whose
# front matter is missing -- or silently voided, which an unquoted colon does to
# the whole block -- simply drops out of the parametrization and is checked by
# nothing. The build stays green either way: MkDocs falls back to the site-wide
# `site_description`, so the page still renders a `<meta name=description>` tag.
#
# Measured before this was added: 14 pages reachable from the site nav declared
# none, and all 14 therefore shipped one identical sentence as their search
# snippet -- the same one the home page uses. A search engine cannot tell them
# apart, and neither can a person reading a results list.
#
# The set is derived from `mkdocs.yml`'s own `nav` rather than from a list kept
# here, so a page added to the site is covered the day it is added. Pages outside
# the nav (the generated `design/` tier, translation stubs) are deliberately not
# in scope: they are not the pages people arrive on.

MKDOCS_YML = DOCS.parent / "mkdocs.yml"


class _IgnoreUnknownTags(yaml.SafeLoader):
    """mkdocs.yml carries `!!python/name:` tags that SafeLoader refuses."""


_IgnoreUnknownTags.add_multi_constructor("", lambda loader, suffix, node: None)


def _nav_pages() -> list[str]:
    config = yaml.load(MKDOCS_YML.read_text(encoding="utf-8"), Loader=_IgnoreUnknownTags)

    def walk(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                yield from walk(value)

    return [p for p in walk(config.get("nav") or []) if isinstance(p, str)
            and p.endswith(".md") and (DOCS / p).exists()]


def test_the_nav_still_lists_pages():
    """Guard the guard: an unparseable nav would silently check nothing."""
    assert len(_nav_pages()) >= 100, (
        "mkdocs.yml's nav could not be read, so every check below passes vacuously"
    )


@pytest.mark.parametrize("page", _nav_pages())
def test_every_page_in_the_nav_declares_its_own_description(page: str):
    description = _front_matter(DOCS / page).get("description")
    assert isinstance(description, str) and description.strip(), (
        f"docs/{page} declares no `description:` in its front matter, so MkDocs "
        "falls back to the site-wide one and the page ships the same search "
        "snippet as the home page. Write one sentence describing this page. "
        "If the file is generated, set it in the generator -- a hand-added block "
        "is overwritten on the next run (see scripts/campaign.py)."
    )
