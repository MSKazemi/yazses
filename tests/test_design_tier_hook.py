"""The hook that publishes the engineering tier must not publish the private ones.

`hooks/design_tier.py` mirrors `design/` into the built site. Two of its behaviours are
worth a test rather than a review:

**The private-tree exclusion**, because getting it wrong publishes material that was
deliberately held back — and it would look like a successful build. This is the same
class of failure as committing to a private path, which already has a guard; the
publishing side deserves one too.

**The link rewriting**, because it is the part with real logic and a non-obvious rule. A
design file is written to be read on GitHub, where `../../docs/x.md` is correct; on the
site the docs tree *is* the root. The first rule keyed off the file extension and missed
that a `.md` link can escape the published set just as easily.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks/design_tier.py"


@pytest.fixture(scope="module")
def hook():
    spec = importlib.util.spec_from_file_location("design_tier", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _File:
    """The bits of `mkdocs.structure.files.File` the hook reads."""

    def __init__(self, src_uri: str) -> None:
        self.src_uri = src_uri


class _Page:
    def __init__(self, src_uri: str) -> None:
        self.file = _File(src_uri)


CONFIG = {"repo_url": "https://github.com/MSKazemi/yazses"}


def _rewrite(hook, src: str, markdown: str) -> str:
    return hook.on_page_markdown(markdown, page=_Page(src), config=CONFIG)


# ---- the exclusion --------------------------------------------------------


def test_the_private_list_is_read_from_the_hook_not_hardcoded(hook):
    """If it silently fell back to a stale constant, a newly-private tree would be
    published and nothing would say so."""
    prefixes = hook._private_prefixes(ROOT)
    assert prefixes, "no private prefixes resolved at all"
    assert any("vision" in p for p in prefixes), (
        f"expected the vision tree among the private prefixes, got {prefixes}"
    )


def test_a_fallback_exists_for_a_clone_with_no_hooks(hook):
    """A fresh clone has no `.git/hooks/pre-commit` until git's template runs."""
    assert hook._private_prefixes(Path("/nonexistent")) == hook._FALLBACK_PRIVATE


def test_nothing_private_is_in_the_published_sections(hook):
    """Structural check: no published section may itself be a private tree."""
    private = hook._private_prefixes(ROOT)
    for section, _title, _blurb in hook._SECTIONS:
        path = f"design/{section}"
        assert not any(path == p or path.startswith(f"{p}/") for p in private), (
            f"{path} is published and also listed as private"
        )


# ---- the link rewriting ---------------------------------------------------


def test_a_docs_link_becomes_site_relative(hook):
    """On the site the docs tree is the root, so the `docs/` segment must go."""
    out = _rewrite(hook, "design/adr/adr-021.md", "see [directions](../../docs/research/directions.md)")
    assert "](../../research/directions.md)" in out, out


def test_a_link_inside_the_design_tier_is_left_alone(hook):
    """`design/` is mirrored one-to-one, so its internal links already resolve."""
    out = _rewrite(hook, "design/adr/adr-021.md", "see [019](adr-019-egress.md)")
    assert "](adr-019-egress.md)" in out, out


def test_a_non_page_artifact_points_at_the_repository(hook):
    """A `.bib` is a source artifact; the site does not serve it."""
    out = _rewrite(hook, "design/research/corpus.md", "the [bibliography](hci-corpus.bib)")
    assert "https://github.com/MSKazemi/yazses/blob/main/design/research/hci-corpus.bib" in out, out


def test_a_markdown_link_escaping_the_published_set_also_goes_to_the_repository(hook):
    """The case the first version of this rule missed: extension alone is not enough."""
    out = _rewrite(hook, "design/README.md", "see [contributing](../.github/CONTRIBUTING.md)")
    assert "https://github.com/MSKazemi/yazses/blob/main/.github/CONTRIBUTING.md" in out, out


def test_absolute_and_anchor_links_are_untouched(hook):
    source = "[x](https://example.com/a) [y](#section) [z](mailto:a@b.c)"
    assert _rewrite(hook, "design/adr/a.md", source) == source


def test_an_anchor_survives_a_rewrite(hook):
    out = _rewrite(hook, "design/adr/a.md", "[x](../../docs/research/agenda.md#question-6)")
    assert "#question-6" in out, out


def test_pages_outside_the_design_tier_are_not_touched(hook):
    """The hook must not rewrite the user documentation, which is already correct."""
    source = "see [x](../../docs/research/directions.md)"
    assert _rewrite(hook, "research/index.md", source) == source


@pytest.mark.parametrize(
    "path, expected",
    [("a/b/../c", "a/c"), ("./a/b", "a/b"), ("../a", "a"), ("a//b", "a/b")],
)
def test_path_normalisation(hook, path, expected):
    assert hook._normalise(path) == expected


# ---- the generated indexes ------------------------------------------------


def test_the_adr_index_is_a_table_with_status(hook):
    page = hook._index_page("adr", "Decision records", "blurb",
                            [("adr-001.md", "ADR-001: Something", "Accepted")])
    assert "| Decision | Status |" in page
    assert "[ADR-001: Something](adr-001.md)" in page
    assert "Accepted" in page


def test_a_document_with_no_status_renders_a_dash_not_a_blank(hook):
    page = hook._index_page("adr", "t", "b", [("x.md", "X", "")])
    assert "| [X](x.md) | — |" in page


def test_a_title_comes_from_front_matter_then_heading_then_filename(hook, tmp_path):
    front = tmp_path / "a.md"
    front.write_text("---\ntitle: From Front Matter\n---\n\n# Ignored\n", encoding="utf-8")
    assert hook._title_of(front) == "From Front Matter"

    heading = tmp_path / "b.md"
    heading.write_text("# From Heading\n", encoding="utf-8")
    assert hook._title_of(heading) == "From Heading"

    bare = tmp_path / "c.md"
    bare.write_text("no title at all\n", encoding="utf-8")
    assert hook._title_of(bare) == "c"


def test_a_status_is_trimmed_to_its_first_clause(hook, tmp_path):
    path = tmp_path / "adr.md"
    path.write_text("# T\n\n**Status:** Accepted (2026-08-15) · Wave Z\n", encoding="utf-8")
    assert hook._status_of(path) == "Accepted"


# --- the reverse direction: docs/ linking INTO design/ ------------------------


def test_docs_pages_link_into_design_by_absolute_url_not_relative_path():
    """The convention looks like a mistake and is not. Do not "fix" it.

    The design tier is published to the site, so a link from `docs/` to `design/`
    looks as though it should be a plain relative path. Whether that works depends on
    **how deep the docs page sits**, and it fails silently at the shallow end:

    * `docs/research/x.md` -> `site/research/x.html`; `../design/y.md` resolves to
      `site/design/y.html`, and mkdocs rewrites the extension. Correct.
    * `docs/faq.md` -> `site/faq.html`; `../design/y.md` points *outside the site
      root*. Measured: mkdocs warns "the target is not found among documentation
      files" — so it fails `--strict` — and emits the href unrewritten, still `.md`.

    So a relative link is right on some pages and broken on others, which is the
    worst available property. An absolute `blob/main/...` URL is the one form that
    works from every docs page, on the site **and** in the GitHub rendering of the
    same file, and it is why all 21 of these links are written that way.

    This test exists because the convention reads as leftover from before the design
    tier was published, and the obvious tidy-up ships broken links on exactly the
    pages nobody thinks to check.
    """
    docs = ROOT / "docs"
    pages = sorted(docs.rglob("*.md"))
    assert len(pages) > 20, "no docs pages found — this guard would be vacuous"

    offenders: list[str] = []
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for match in re.finditer(r"\]\((\.\./[^)]*design/[^)]+)\)", text):
            offenders.append(f"{page.relative_to(ROOT)} -> {match.group(1)}")

    assert not offenders, (
        "these docs pages link into design/ with a relative path. That resolves only "
        "from a page one directory deep; from a top-level page it points outside the "
        "site root, fails --strict, and is emitted without the .md->.html rewrite. "
        "Use https://github.com/MSKazemi/yazses/blob/main/design/... instead:\n  "
        + "\n  ".join(offenders)
    )


def test_the_design_links_that_do_exist_point_at_files_that_exist():
    """An absolute URL is not checked by anything — mkdocs treats it as external and
    the link checker only runs on a schedule. A blob link to a renamed ADR is a 404
    that nothing in the normal gate would catch."""
    docs = ROOT / "docs"
    dead: list[str] = []
    for page in sorted(docs.rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        for match in re.finditer(
            r"https://github\.com/MSKazemi/yazses/blob/main/(design/[A-Za-z0-9/._-]+)", text
        ):
            target = ROOT / match.group(1)
            # A bare directory link (…/design/adr/) is legitimate.
            if match.group(1).endswith("/"):
                if not target.is_dir():
                    dead.append(f"{page.relative_to(ROOT)} -> {match.group(1)}")
            elif not target.exists():
                dead.append(f"{page.relative_to(ROOT)} -> {match.group(1)}")

    assert not dead, "docs pages link to design files that do not exist:\n  " + "\n  ".join(dead)
