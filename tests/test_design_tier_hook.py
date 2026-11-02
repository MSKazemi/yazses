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


def test_a_section_readme_link_goes_to_the_repository(hook):
    """`on_files` replaces each section README with a generated index, so the README
    is not published -- and a link written for GitHub resolves to nothing on the site.

    Two pages under `design/eye-control/` did exactly that and failed `mkdocs build
    --strict` on main: the warning text says the target `is not found among
    documentation files` because there is no `design/eye-control/README.md` page for
    it to find. The prose those links promise ("the reason README.md gives for keeping
    no status snapshot") lives only in the repository, so that is where the link must
    point. A top-level README is not a section README and is published, so it must
    stay a site path.
    """
    out = _rewrite(hook, "design/eye-control/VALIDATION_OPERATIONS.md",
                   "the reason [README.md](README.md) gives")
    assert (
        "https://github.com/MSKazemi/yazses/blob/main/design/eye-control/README.md"
        in out
    ), out

    out = _rewrite(hook, "design/eye-control/generated/validation-coverage.md",
                   "see the note in [README.md](../README.md)")
    assert (
        "https://github.com/MSKazemi/yazses/blob/main/design/eye-control/README.md"
        in out
    ), out


def test_a_top_level_readme_link_stays_a_site_path(hook):
    """The exception must not widen past section READMEs: the tier's own README *is*
    published, so a link to it has a site target to resolve against."""
    out = _rewrite(hook, "design/architecture.md", "tiers: [README](README.md)")
    assert out == "tiers: [README](README.md)", out


def test_a_readme_below_a_section_root_is_left_alone(hook):
    """Only the immediate section README is replaced by an index. A README one level
    deeper, such as `design/adr/series/README.md`, is published as itself, and its link to `authorship/README.md`
    resolves on the site -- rewriting that one would be the defect."""
    out = _rewrite(hook, "design/adr/series/README.md",
                   "start with [authorship/README.md](authorship/README.md)")
    assert out == "start with [authorship/README.md](authorship/README.md)", out


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
    # A cell may name more than one path (two backticked paths in one cell), and
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


# ---- search metadata: a description and a short title per page -------------
#
# A design page with no description of its own inherited the site-wide one, so about 380
# of ~400 engineering pages told a search engine the same sentence (Bing reports that as
# "identical meta descriptions"), and decision records whose H1 is a whole sentence made
# `<title>` text of 100+ characters. These are derived from the document, never invented,
# and an author's own front matter always wins.


def test_a_short_title_is_left_alone(hook):
    assert hook._short_title("Threat model") == "Threat model"


def test_a_long_title_is_cut_at_the_clause_before_the_colon(hook):
    title = "ADR-028 — Feature add-on packs: a frozen install fetches a feature's libraries when it is turned on"
    assert hook._short_title(title) == "ADR-028 — Feature add-on packs"


def test_a_long_title_without_a_colon_is_cut_at_a_word_never_inside_one(hook):
    title = "ADR-026 — Remote coding agents use the existing task contract and tool identity is not authorship"
    short = hook._short_title(title)
    assert len(short) <= hook._TITLE_BUDGET
    assert title.startswith(short), "the shortened title must be a prefix of the real one"
    assert title[len(short)] == " ", f"cut inside a word: {short!r}"


def test_a_major_clause_break_beats_a_later_comma(hook):
    title = "ADR-028 — Feature add-on packs: a frozen install, fetches libraries when it is turned on"
    assert hook._short_title(title) == "ADR-028 — Feature add-on packs"


def test_a_parenthetical_is_dropped_whole_not_cut_open(hook):
    title = "ADR-v2-009 — Personal Speech Adapter (on-device LoRA fine-tuning for a single speaker)"
    assert hook._short_title(title) == "ADR-v2-009 — Personal Speech Adapter"


def test_a_title_never_ends_on_a_dangling_word(hook):
    title = "Spec: Head-Pointer Runtime — Pose to Pointer with Recenter, Clutch and Dwell"
    short = hook._short_title(title)
    assert short == "Spec: Head-Pointer Runtime"
    assert short.split()[-1].lower() not in hook._DANGLING
    assert hook._tidy_title("Voice-Driven a") == "Voice-Driven"
    assert hook._tidy_title("Personal Speech Adapter (two") == "Personal Speech Adapter"


def test_long_published_titles_never_end_as_fragments(hook):
    """The regression: ~48 of 158 shortened titles ended '(on-device', '(two' or '— a'."""
    published = _publishable(hook)
    assert published is not None
    seen = 0
    for rel in sorted(p for p in published if p.endswith(".md")):
        text = (ROOT / rel).read_text(encoding="utf-8")
        if text.startswith("---\n"):
            continue
        heading = hook._H1.search(text)
        if not heading:
            continue
        full = hook._plain(heading.group(1))
        if len(full) <= hook._TITLE_BUDGET:
            continue
        short = hook._short_title(full)
        seen += 1
        assert len(short) <= hook._TITLE_BUDGET, rel
        assert short.count("(") <= short.count(")"), f"{rel}: open parenthesis in {short!r}"
        assert short.split()[-1].lower() not in hook._DANGLING, f"{rel}: dangling word in {short!r}"
        assert short[-1] not in ",;:—–-", f"{rel}: trailing punctuation in {short!r}"
    assert seen > 50, f"expected many long titles in the design tier, saw {seen}"


def test_a_title_is_never_shortened_to_nothing(hook):
    assert hook._short_title("A" * 200)
    assert hook._short_title("x: " + "y " * 80)


def test_plain_strips_markdown_but_keeps_the_words(hook):
    text = "See [`design/specs/x.md`](../specs/x.md) and [[adr-011]] for **why** — *nothing* leaves <b>the</b> machine."
    assert hook._plain(text) == "See design/specs/x.md and adr-011 for why — nothing leaves the machine."


def test_a_description_skips_the_metadata_block_and_headings(hook):
    markdown = (
        "# ADR-099 — A decision\n\n"
        "**Status:** Accepted (2026-10-01)\n"
        "**Deciders:** The owner\n\n"
        "---\n\n"
        "## Context\n\n"
        "The daemon must never need the network to transcribe speech, and the packaging has to say so.\n\n"
        "A second paragraph that must not be used.\n"
    )
    assert hook._describe(markdown) == (
        "The daemon must never need the network to transcribe speech, and the packaging has to say so."
    )


def test_a_description_skips_tables_lists_and_code(hook):
    markdown = (
        "# Doc\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- a bullet that is not prose\n\n"
        "```\ncode\n```\n\nThis is the first sentence of real prose that a reader would meet first.\n"
    )
    assert hook._describe(markdown).startswith("This is the first sentence of real prose")


def test_a_long_description_ends_at_a_sentence_or_a_word_within_the_budget(hook):
    sentence = "This design record explains one decision in plain words. "
    text = (sentence * 12).strip()
    out = hook._describe(f"# T\n\n{text}\n")
    assert len(out) <= hook._DESCRIPTION_BUDGET
    assert out.endswith("."), f"expected a sentence end, got {out!r}"
    nospace = hook._describe("# T\n\n" + "word " * 60 + "\n")
    assert len(nospace) <= hook._DESCRIPTION_BUDGET + 1 and nospace.endswith("…")


def test_a_document_with_no_prose_yields_no_description(hook):
    assert hook._describe("# Only a heading\n\n| a | b |\n|---|---|\n") == ""


class _MetaPage(_Page):
    def __init__(self, src_uri: str, meta: dict | None = None) -> None:
        super().__init__(src_uri)
        self.meta = {} if meta is None else meta


def test_a_design_page_gets_a_description_and_a_short_title(hook):
    page = _MetaPage("design/adr/adr-099.md")
    markdown = (
        "# ADR-099 — A decision whose heading is a whole sentence about what must change next\n\n"
        "The daemon must never need the network to transcribe speech.\n"
    )
    out = hook.on_page_markdown(markdown, page=page, config=CONFIG)
    assert out == markdown, "the body must be untouched (it has no links to rewrite)"
    assert page.meta["description"] == "The daemon must never need the network to transcribe speech."
    assert len(page.meta["seo_title"]) <= hook._TITLE_BUDGET
    # `title` would also relabel Material's header bar, which is visible UI.
    assert "title" not in page.meta


def test_front_matter_always_wins(hook):
    page = _MetaPage("design/adr/adr-099.md", {"title": "Mine", "description": "Written by the author."})
    hook.on_page_markdown(
        "# A very long heading that would otherwise be shortened by the hook for the title\n\nSome prose that is long enough to be used.\n",
        page=page, config=CONFIG,
    )
    assert page.meta == {"title": "Mine", "description": "Written by the author."}


def test_pages_outside_design_are_not_touched(hook):
    page = _MetaPage("how-to/x.md")
    hook.on_page_markdown(
        "# A very long heading that would otherwise be shortened by the hook for the title\n\nSome prose that is long enough to be used.\n",
        page=page, config=CONFIG,
    )
    assert page.meta == {}


def test_a_page_object_without_meta_is_tolerated(hook):
    """MkDocs always provides `meta`; a stand-in that lacks it must not crash the build."""
    assert hook.on_page_markdown("# T\n\nA paragraph that is long enough to describe.\n",
                                 page=_Page("design/x.md"), config=CONFIG)


def test_a_document_with_only_a_table_still_gets_a_title_based_description(hook):
    page = _MetaPage("design/x.md")
    hook.on_page_markdown("# Comparison matrix\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", page=page, config=CONFIG)
    assert page.meta["description"].startswith("Comparison matrix.")
    assert len(page.meta["description"]) <= hook._DESCRIPTION_BUDGET


def test_published_design_pages_no_longer_share_one_description(hook):
    """The regression this exists for: ~380 pages with the same sentence.

    Derived from the real published files, so it moves with the repository; the bound is
    loose on purpose (a few documents legitimately open alike) and tight enough that
    going back to one shared description fails it at once.
    """
    import collections

    published = _publishable(hook)
    assert published is not None
    descriptions: collections.Counter[str] = collections.Counter()
    checked = 0
    for rel in sorted(p for p in published if p.endswith(".md")):
        text = (ROOT / rel).read_text(encoding="utf-8")
        if text.startswith("---\n"):
            continue  # hand-written front matter: the author's own description or title wins
        page = _MetaPage(rel)
        hook.on_page_markdown(text, page=page, config=CONFIG)
        if "description" in page.meta:
            descriptions[page.meta["description"]] += 1
            checked += 1
            assert len(page.meta["description"]) <= hook._DESCRIPTION_BUDGET + 1, rel
        if "seo_title" in page.meta:
            assert len(page.meta["seo_title"]) <= hook._TITLE_BUDGET, rel
    assert checked > 100, f"expected to derive descriptions for the design tier, got {checked}"
    shared = sum(n for n in descriptions.values() if n > 1)
    assert shared <= checked * 0.05, f"{shared} of {checked} pages share a description"
