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

from tests.gitprobe import require_git

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


def _publishable(hook):
    # `design_tier._tracked()` returns `None` when git cannot answer, and the hook
    # then publishes a small curated fallback so a docs build never dies on a broken
    # checkout. That is right for the build and wrong for a test: every assertion
    # below compares the published set against the repository, so on a machine where
    # git is broken they report the *fallback* as a defect -- "design/packaging/ is
    # tracked but not published" -- which is a statement about this hook that is not
    # true. `require_git()` makes the environment the finding instead.
    require_git()
    return hook._publishable(ROOT, hook._private_prefixes(ROOT))


def test_nothing_private_is_in_the_published_sections(hook):
    """Structural check: no published section may itself be a private tree."""
    private = hook._private_prefixes(ROOT)
    for section in hook._sections(_publishable(hook)):
        path = f"design/{section}"
        assert not any(path == p or path.startswith(f"{p}/") for p in private), (
            f"{path} is published and also listed as private"
        )


# ---- what gets published is derived, not listed ---------------------------
#
# It used to be listed, and that was the defect: `design/packaging/`,
# `design/v2-cognitive-layer/`, `design/mobile/` and `design/meeting-mode/` -- 14 files,
# every one already committed to the public repository -- were absent from the site
# because no line in the hook named them. An omission leaves nothing to notice: no
# warning, no broken link, no red build. Three top-level design documents were missing
# for the same reason.


def test_the_published_set_is_every_tracked_design_file_that_is_not_private(hook):
    """The whole point: publication follows the repository, not a maintained list."""
    import subprocess

    tracked = set(subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", "design"],
        capture_output=True, check=True,
    ).stdout.decode().split("\0")) - {""}
    private = hook._private_prefixes(ROOT)
    expected = {
        rel for rel in tracked
        if not any(rel == p or rel.startswith(f"{p}/") for p in private)
    }
    assert _publishable(hook) == expected


def test_an_untracked_tree_is_never_published(hook, tmp_path):
    """`design/vision/` exists on this machine and is in no commit.

    Deriving from the filesystem would publish it -- the site would be the first place it
    appeared. Deriving from `git ls-files` cannot.
    """
    assert hook._tracked(tmp_path) is None or "design/vision" not in " ".join(
        sorted(hook._tracked(ROOT) or [])
    )
    pub = _publishable(hook)
    assert pub is not None
    assert not [rel for rel in pub if rel.startswith("design/vision/")]


def test_git_being_unavailable_publishes_the_curated_subset_not_the_disk(hook, tmp_path):
    """Fail closed. A directory that is not a repository must not widen what is published."""
    assert hook._tracked(tmp_path) is None
    assert hook._sections(None) == list(hook._FALLBACK_SECTIONS)
    assert hook._top_level(None) == hook._FALLBACK_TOP_LEVEL


def test_every_section_that_exists_today_is_published(hook):
    """Names the four that were missing, so a regression is legible rather than a count."""
    sections = hook._sections(_publishable(hook))
    for expected in ("adr", "specs", "research", "packaging", "v2-cognitive-layer",
                     "mobile", "meeting-mode"):
        assert expected in sections, f"design/{expected}/ is tracked but not published"
    assert sections[:3] == ["adr", "specs", "research"], "the written sections lead"


def test_a_section_with_no_written_blurb_still_gets_a_title(hook):
    """Otherwise a derived section would publish an index titled after nothing."""
    title, blurb = hook._section_meta(ROOT / "design" / "packaging", "packaging")
    assert title and blurb
    assert "packaging" in blurb


def test_the_readme_leads_the_top_level_files(hook):
    top = hook._top_level(_publishable(hook))
    assert top[0] == "README.md", f"the entry point is not first: {top[:3]}"
    for expected in ("ci-cd-audit.md", "accessibility-and-throughput-spec.md",
                     "troubleshooting-full-review.md"):
        assert expected in top, f"design/{expected} is tracked but not published"


def test_the_nav_carries_every_published_section_and_top_level_page(hook):
    """A published page nobody can navigate to is only half-published.

    The nav is hand-written YAML and cannot derive itself, so the completeness check lives
    here: adding a `design/` subtree now fails this test until the sidebar names it.
    """
    nav = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    pub = _publishable(hook)
    missing = [f"design/{s}/index.md" for s in hook._sections(pub)
               if f"design/{s}/index.md" not in nav]
    missing += [f"design/{f}" for f in hook._top_level(pub) if f"design/{f}" not in nav]
    assert not missing, f"published but absent from the mkdocs.yml nav: {missing}"


def test_generated_section_indexes_have_unique_site_urls(hook, tmp_path):
    """A section README and its generated index must not both become index.html.

    MkDocs accepts duplicate destination URLs without warning, then writes both into
    sitemap.xml. Search crawlers see two records for one page, potentially with different
    freshness signals, even though the strict docs build is green.

    `on_files` builds real `mkdocs.structure.files.File` objects, and the whole point of
    the assertion is the `dest_uri` MkDocs derives -- README.md and index.md collapsing
    onto one index.html is MkDocs' mapping, not this hook's. Stubbing `File` would mean
    asserting against a local reimplementation of that mapping, which is the thing most
    likely to drift away from the behaviour being guarded.

    So this needs the real package, which lives in the `docs` dependency group. The test
    and release jobs run a bare `uv sync` and do not have it. Skipping alone would leave
    the guard running nowhere, so `docs.yml` -- which already syncs `--group docs` --
    runs this file explicitly; see the "Design-tier hook unit tests" step there.
    """
    pytest.importorskip(
        "mkdocs",
        reason="needs the docs dependency group; docs.yml runs this file with it",
    )
    files = []
    hook.on_files(files, {
        "docs_dir": str(ROOT / "docs"),
        "site_dir": str(tmp_path),
        "use_directory_urls": False,
    })
    destinations = [file.dest_uri for file in files]
    duplicates = sorted({dest for dest in destinations if destinations.count(dest) > 1})
    assert duplicates == []
    for section in ("adr", "specs", "meeting-mode", "mobile"):
        assert destinations.count(f"design/{section}/index.html") == 1


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


# ---- the visibility contract is a claim, so it is checked ------------------


def _visibility_rows() -> list[tuple[str, str]]:
    """(path, Public|Private) pairs from `design/README.md`'s contract table."""
    import re

    text = (ROOT / "design" / "README.md").read_text(encoding="utf-8")
    rows: list[tuple[str, str]] = []
    # A cell may name more than one path ("`paper/benchmark/`, `paper/results/`"), and
    # capturing only the first is how the first draft of this test reported a leak that
    # was not one -- it could not see the second half of its own Public row.
    for cell, visibility in re.findall(r"^\|([^|]+)\| \*\*(Public|Private)\*\* \|", text, re.M):
        rows += [(path, visibility) for path in re.findall(r"`([^`]+)`", cell)]
    return rows


def test_the_visibility_table_was_parsed() -> None:
    """Otherwise the check below passes on a table that moved or changed shape."""
    rows = _visibility_rows()
    assert len(rows) >= 5, f"only parsed {rows} out of the contract table"
    assert {v for _, v in rows} == {"Public", "Private"}


def test_nothing_under_a_private_path_is_committed() -> None:
    """`design/README.md` states which trees are private. Git is the ground truth.

    The table said `paper/` was private while 18 files under it were tracked — deliberately,
    for a good reason recorded in `.gitignore`, but the contract had not been updated to
    say so. A visibility contract that disagrees with the repository is worse than none:
    it is the document a reader consults to decide what is safe to write there.
    """
    import subprocess

    rows = _visibility_rows()
    public = [p for p, v in rows if v == "Public"]
    leaked: dict[str, list[str]] = {}
    for path, visibility in rows:
        if visibility != "Private":
            continue
        tracked = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", path],
            capture_output=True, check=True,
        ).stdout.decode().split()
        unexplained = [f for f in tracked if not any(f.startswith(q) for q in public)]
        if unexplained:
            leaked[path] = unexplained[:5]
    assert not leaked, f"committed under a path the contract calls private: {leaked}"
