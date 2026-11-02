"""Publish the engineering-and-science tier (`design/`) on the docs site.

`design/README.md` defines three tiers: `docs/` is user-facing, `design/` is public
engineering and science, and the strategy and coding-agent trees are private. The middle
one has been public in the repository for a while and **absent from the documentation site**,
which means the decision records, specifications and threat model — the material a
reviewer, a packager or a collaborating researcher would most want — were reachable only
by browsing GitHub.

This hook mirrors that tier into the built site. Three properties, and each rules out an
easier approach:

**It is not a copy in the source tree.** `design/` stays where contributors edit it. A
second copy under `docs/` would be two files to keep in step, and this project has enough
of those; the files are injected into MkDocs' virtual file set at build time instead.

**It is not in the navigation.** There are 255 markdown files under `design/`, and 155 of
them are ADRs. Putting that in the sidebar would bury the user documentation the site
exists for — the same reason 46 release notes are already `not_in_nav`. Generated index
pages carry the structure instead, and the nav gets one entry per index.

**Private trees are excluded structurally, not by convention.** The exclusion list is read
from the pre-commit hook's own regex, so a tree that becomes private later cannot be
published here by an omission. A path that fails that check is skipped and logged rather
than published-and-apologised-for.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger("mkdocs.hooks.design_tier")

#: Written titles and blurbs for the sections that have earned one. Any other section
#: under `design/` is still published — it takes a title from its own README and a
#: generic blurb. This is deliberately *not* the list of what gets published: it used
#: to be, and four whole subtrees stayed off the site for months because nobody had
#: added a line here. See `_sections()`.
_SECTION_META: dict[str, tuple[str, str]] = {
    "adr": ("Decision records",
            "Every architectural decision, why it was made, and what would reverse it."),
    "specs": ("Specifications",
              "Implementation-ready designs: what gets built, and how it is judged done."),
    "research": ("Research notes",
                 "Studies, surveys and the literature watch behind the design decisions."),
}

#: Order for the sections that have one; anything else follows, alphabetically.
_SECTION_ORDER = ["adr", "specs", "research"]

#: Used only when git cannot answer what is tracked — see `_tracked()`. Publishing the
#: previously-curated set is the conservative answer there, not the complete one.
_FALLBACK_SECTIONS = tuple(_SECTION_ORDER)

#: Fallback set of single files at the top of `design/`, used only when git cannot
#: answer. `README.md` is in it because the tier documents link to it as the statement
#: of what is public and why — the one page that explains the rest.
_FALLBACK_TOP_LEVEL = ["README.md", "architecture.md", "threat-model.md", "emg-protocol.md"]

#: Read from the pre-commit hook so the two cannot disagree about what is private.
_FALLBACK_PRIVATE = ("strategy", "design/vision", "design/marketing", "design/seo", ".claude")


def _private_prefixes(repo_root: Path) -> tuple[str, ...]:
    hook = repo_root / ".git" / "hooks" / "pre-commit"
    try:
        text = hook.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return _FALLBACK_PRIVATE
    match = re.search(r"\(\^\|\[\^a-zA-Z0-9_/-\]\)\(([^)]+)\)/", text)
    if not match:
        return _FALLBACK_PRIVATE
    return tuple(p.replace("\\", "") for p in match.group(1).split("|"))



def _tracked(repo_root: Path) -> frozenset[str] | None:
    """Repo-relative paths under `design/` that git tracks, or `None` if git cannot say.

    Tracked-ness, not the filesystem, is what decides publication. A file that is not
    committed is not in the public repository, so publishing it to the site would be the
    first place it appeared — `design/vision/` is untracked on this machine for exactly
    that reason. Deriving from `os.walk` instead would have published it.

    `None` means git could not answer (no `.git`, no git binary, a timeout). Callers fall
    back to the previously-curated lists: publishing a known-safe subset is the right
    failure, and publishing everything found on disk is not.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z", "--", "design"],
            capture_output=True, timeout=30, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return frozenset(p for p in done.stdout.decode("utf-8", "replace").split("\0") if p)


def _publishable(repo_root: Path, private: tuple[str, ...]) -> frozenset[str] | None:
    """Tracked `design/` paths that are not under a private prefix."""
    tracked = _tracked(repo_root)
    if tracked is None:
        return None
    return frozenset(
        rel for rel in tracked
        if not any(rel == p or rel.startswith(f"{p}/") for p in private)
    )


def _sections(publishable: frozenset[str] | None) -> list[str]:
    """Immediate subdirectories of `design/` that have something to publish.

    Derived, because the hand-written version was the defect: `design/packaging/`,
    `design/v2-cognitive-layer/`, `design/mobile/` and `design/meeting-mode/` — 14 files,
    every one already committed to the public repository — were absent from the site
    purely because no line here named them, and an omission leaves no trace to notice.
    """
    if publishable is None:
        return list(_FALLBACK_SECTIONS)
    found = {rel.split("/")[1] for rel in publishable if rel.count("/") >= 2}
    ordered = [s for s in _SECTION_ORDER if s in found]
    return ordered + sorted(found - set(ordered))


def _top_level(publishable: frozenset[str] | None) -> list[str]:
    """Files directly under `design/`, README first so it reads as the entry point."""
    if publishable is None:
        return list(_FALLBACK_TOP_LEVEL)
    names = sorted(
        rel.split("/", 1)[1] for rel in publishable
        if rel.count("/") == 1 and rel.endswith(".md")
    )
    return sorted(names, key=lambda n: (n.upper() != "README.MD", n))


def _section_meta(root: Path, section: str) -> tuple[str, str]:
    """Title and blurb for a section index — written where one exists, derived otherwise."""
    if section in _SECTION_META:
        return _SECTION_META[section]
    readme = root / "README.md"
    title = _title_of(readme) if readme.is_file() else section.replace("-", " ").capitalize()
    return title, f"Engineering notes kept under `design/{section}/`."


def _title_of(path: Path) -> str:
    """The document's own H1 or front-matter title, falling back to its filename."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return path.stem
    front = re.match(r"^---\n(.*?)\n---", text, re.S)
    if front:
        title = re.search(r"^title:\s*(.+)$", front.group(1), re.M)
        if title:
            return title.group(1).strip().strip("\"'")
    heading = re.search(r"^#\s+(.+)$", text, re.M)
    return heading.group(1).strip() if heading else path.stem


def _status_of(path: Path) -> str:
    """An ADR's declared status, for the index. Empty when it declares none."""
    try:
        head = path.read_text(encoding="utf-8")[:1200]
    except OSError:
        return ""
    match = re.search(r"^\*\*Status:\*\*\s*(.+)$", head, re.M)
    if not match:
        return ""
    # Keep it short: the first clause is the status, the rest is usually a caveat.
    return re.split(r"[—·(]", match.group(1))[0].strip().rstrip(".").strip("* ")


def _index_page(section: str, title: str, blurb: str, entries: list[tuple[str, str, str]]) -> str:
    lines = [
        "---",
        f"title: {title}",
        f"description: {blurb} Part of the YazSes engineering and science documentation.",
        "---",
        "",
        f"# {title}",
        "",
        blurb,
        "",
        "!!! info \"This is the engineering tier\"",
        "",
        "    These pages are written for contributors, reviewers and researchers rather",
        "    than for people using YazSes. For the user documentation, start at",
        # Written as a repo-relative path into docs/ so the link rewriter maps it to
        # the site root, exactly as it does for the hand-written design pages.
        "    [Home](../../docs/index.md).",
        "",
        f"**{len(entries)} documents.**",
        "",
    ]
    if section == "adr":
        lines += ["| Decision | Status |", "|---|---|"]
        for name, doc_title, status in entries:
            lines.append(f"| [{doc_title}]({name}) | {status or '—'} |")
    else:
        for name, doc_title, _status in entries:
            lines.append(f"- [{doc_title}]({name})")
    lines.append("")
    return "\n".join(lines)


def on_files(files: Any, config: Any, **_: Any):  # noqa: ANN401 - mkdocs passes its own types
    """Inject `design/**` into the site as `design/…`, plus a generated index each."""
    from mkdocs.structure.files import File

    docs_dir = Path(config["docs_dir"]).resolve()
    repo_root = docs_dir.parent
    design = repo_root / "design"
    if not design.is_dir():
        log.warning("design/ not found at %s — nothing to publish", design)
        return files

    private = _private_prefixes(repo_root)
    publishable = _publishable(repo_root, private)
    if publishable is None:
        log.warning("design_tier: git could not list design/ — publishing the curated subset only")
    site_dir = config["site_dir"]
    use_directory_urls = config.get("use_directory_urls", True)
    skipped = 0

    def _add(source: Path) -> None:
        """Add *source* at the site path that matches its repo path.

        `src_dir` is the repository root, not the file's own directory: MkDocs resolves
        a File by joining `src_dir` and `path`, so they have to describe the same place.
        `design/adr/x.md` under the repo root becomes `design/adr/x.md` on the site,
        which is the mapping we want anyway.
        """
        files.append(File(
            path=source.relative_to(repo_root).as_posix(),
            src_dir=str(repo_root),
            dest_dir=site_dir, use_directory_urls=use_directory_urls,
        ))

    def _is_private(rel: str) -> bool:
        return any(rel == p or rel.startswith(f"{p}/") for p in private)

    for filename in _top_level(publishable):
        source = design / filename
        if not source.is_file():
            continue
        if _is_private(source.relative_to(repo_root).as_posix()):
            skipped += 1
            continue
        _add(source)

    sections = _sections(publishable)
    for section in sections:
        root = design / section
        if not root.is_dir():
            continue
        title, blurb = _section_meta(root, section)
        entries: list[tuple[str, str, str]] = []
        # Not `*.md`: a design note may link to a sibling it ships with, and
        # `design/meeting-mode/README.md` links to a 57-source SoA report as raw HTML.
        # Publishing the prose and dropping the artefact it cites leaves a dead link.
        for source in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = source.relative_to(repo_root).as_posix()
            if _is_private(rel) or (publishable is not None and rel not in publishable):
                skipped += 1
                continue
            relative = source.relative_to(root).as_posix()
            # The generated section index replaces a top-level README. Adding both
            # maps README.md and index.md to the same index.html, which used to put
            # duplicate URLs (and conflicting freshness data) in the sitemap.
            if relative.upper() == "README.MD":
                continue
            _add(source)
            if source.suffix.lower() == ".md":
                entries.append((relative, _title_of(source), _status_of(source)))

        files.append(_generated(
            f"design/{section}/index.md",
            _index_page(section, title, blurb, entries),
            config,
        ))

    if skipped:
        log.info("design_tier: skipped %d file(s) under a private tree", skipped)
    log.info("design_tier: published %d section index(es): %s", len(sections), ", ".join(sections))
    return files


def _generated(dest: str, content: str, config: Any):  # noqa: ANN401
    """A File whose site path is *dest*, backed by a temp dir so nothing lands in the repo.

    MkDocs derives a File's URL from `path` relative to `src_dir`, so the temporary
    directory has to mirror the destination layout — writing the file flat and hoping the
    path argument alone relocates it does not work.
    """
    import tempfile

    from mkdocs.structure.files import File

    tmp = Path(tempfile.mkdtemp(prefix="yz-design-"))
    target = tmp / dest
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return File(
        path=dest,
        src_dir=str(tmp),
        dest_dir=config["site_dir"],
        use_directory_urls=config.get("use_directory_urls", True),
    )


# --------------------------------------------------------------------------- #
# Search metadata
# --------------------------------------------------------------------------- #
# A page with no `description` of its own inherits the site-wide one, so every
# engineering page told a search engine the same thing: ~380 of the ~400 design pages
# carried one identical description (Bing flags that as "identical meta descriptions"),
# and the decision records, whose H1 is a full sentence, produced `<title>` text of 100+
# characters. Both are derived here from the document itself, and only when the author
# has not written one: front matter always wins, and the visible H1 is never changed.

#: MkDocs Material appends " - YazSes" to the `<title>`; search results show about 60.
_TITLE_BUDGET = 60 - len(" - YazSes")

#: Search results show roughly 155-160 characters of a description.
_DESCRIPTION_BUDGET = 155

_H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)
_METADATA_LINE = re.compile(r"^\*\*[A-Za-z][A-Za-z ]{0,30}:\*\*")


#: Clause boundaries a title can end at. The first ``" — "`` of a decision-record title
#: sits after the ADR number (``ADR-028 — Feature add-on packs``) and is too early to
#: end on, which the `>= _MIN_TITLE` test below rules out.
_TITLE_BREAKS_MAJOR = (": ", "; ")
_TITLE_BREAKS_MINOR = (" (", " — ", " – ", " - ", ", ")

#: Shortest title worth returning; keeps a leading "ADR-028:" from being the whole title.
_MIN_TITLE = 12

#: Words a title must not end on: cut there it reads as a fragment ("... Voice-Driven a").
_DANGLING = frozenset({
    "a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "from", "with", "without",
    "and", "or", "but", "as", "is", "are", "vs", "via", "into", "over", "per", "than",
    "two", "three", "four", "five", "six", "one", "its", "their", "our", "your", "-", "—", "–", "+",
})


def _tidy_title(head: str) -> str:
    """Drop what a cut leaves behind: an unclosed parenthesis, trailing punctuation and
    function words, so the title ends on a content word."""
    while True:
        before = head
        head = head.rstrip(" ,;:—–-")
        if head.count("(") > head.count(")"):
            head = head[: head.rfind("(")]
        words = head.split()
        if words and words[-1].lower() in _DANGLING:
            head = " ".join(words[:-1])
        if head == before:
            return head


def _short_title(title: str, budget: int = _TITLE_BUDGET) -> str:
    """*title*, shortened to *budget* characters, ending at a clause where one fits.

    Takes the longest head that ends at a clause boundary (``: ``, ``; ``, `` (``, a dash
    or a comma) within the budget (decision-record titles read ``ADR-028 — Feature
    add-on packs: a frozen install fetches ...``). With no boundary in range it cuts at
    the last word that fits. Either way the result never ends on an open parenthesis or
    a dangling word, never cuts a word in half, and is never empty.
    """
    title = " ".join(title.split())
    if len(title) <= budget:
        return title
    window = title[: budget + 1]
    best = -1
    for breaks in (_TITLE_BREAKS_MAJOR, _TITLE_BREAKS_MINOR):
        best = max(window.rfind(sep) for sep in breaks)
        if best >= _MIN_TITLE:
            break
    cut = window[:best] if best >= _MIN_TITLE else window.rsplit(" ", 1)[0]
    head = _tidy_title(cut[:budget])
    if len(head) >= _MIN_TITLE:
        return head
    return title[:budget].rstrip(" ,;:—–-") or title[:budget]


def _plain(text: str) -> str:
    """Markdown inline syntax removed, for use in a meta description."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)              # images
    text = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", r"\1", text)  # [[wiki]] links
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)           # [text](url)
    text = re.sub(r"<[^>]+>", "", text)                            # raw HTML
    text = re.sub(r"[`*_]{1,3}", "", text)                         # code and emphasis marks
    return " ".join(text.split())


def _fit(text: str, budget: int = _DESCRIPTION_BUDGET) -> str:
    """*text* cut to *budget* characters, at a sentence end when one is near enough."""
    if len(text) <= budget:
        return text
    window = text[: budget + 1]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s)", window)]
    if ends and ends[-1] >= 70:
        return window[: ends[-1]].rstrip()
    return window[:budget].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"


def _describe(markdown: str) -> str:
    """A description from the document's first real prose paragraph, or ``""``.

    Skips headings, tables, lists, quotes, code, admonitions and the ``**Status:**``-style
    metadata block that decision records open with, so the text is what a reader would
    meet first, not the bookkeeping.
    """
    for block in re.split(r"\n\s*\n", markdown):
        block = block.strip()
        if not block or block.startswith(("#", "|", ">", "```", "---", "<", "!", "-", "+", "1.", ":")):
            continue
        if _METADATA_LINE.match(block):
            continue
        text = _plain(block)
        if len(text) >= 40:
            return _fit(text)
    return ""


def _search_metadata(markdown: str, page: Any) -> None:  # noqa: ANN401 - mkdocs passes its own types
    """Fill in a description and a short `<title>` (`seo_title`) for a design page that has neither."""
    meta = getattr(page, "meta", None)
    if not isinstance(meta, dict):
        return
    heading = _H1.search(markdown)
    full = _plain(heading.group(1)) if heading else ""
    if not meta.get("description"):
        described = _describe(markdown)
        if not described and full:
            # No prose paragraph to quote (a document that opens with a table, say):
            # a description built from the title still beats the site-wide one.
            described = _fit(f"{_short_title(full, 90)}. Part of the YazSes engineering and science documentation.")
        if described:
            meta["description"] = described
    if full and not meta.get("title"):
        shortened = _short_title(full)
        if shortened != full:
            # `seo_title`, not `title`: `title` would also relabel Material's header bar.
            # `overrides/main.html` reads this key for the `<title>` tag only.
            meta["seo_title"] = shortened


# --------------------------------------------------------------------------- #
# Link rewriting
# --------------------------------------------------------------------------- #
# A file under `design/` is written to be read on GitHub, where `../../docs/x.md`
# is correct. On the site the docs tree *is* the root, so that same link points at a
# `docs/` directory that does not exist there. And several design pages link to
# non-markdown siblings — a `.bib` bibliography, a verification script — which are
# source artifacts rather than pages.
#
# Rewriting at build time keeps one source of truth: the file on GitHub stays correct
# for a reader browsing the repository, and the published copy is corrected on the way
# out. The alternative — editing the sources to suit the site — would break them where
# most people actually read them.

_RELATIVE_LINK = re.compile(r"\]\((?!https?://|#|mailto:)([^)]+)\)")
_PAGE_SUFFIXES = {".md", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}


def on_page_markdown(markdown: str, page: Any = None, config: Any = None, **_: Any) -> str:  # noqa: ANN401
    """Correct relative links on published `design/` pages only."""
    src = getattr(getattr(page, "file", None), "src_uri", "") or ""
    if not src.startswith("design/"):
        return markdown

    _search_metadata(markdown, page)

    repo_url = (config or {}).get("repo_url", "https://github.com/MSKazemi/yazses").rstrip("/")

    def _fix(match: re.Match) -> str:
        target = match.group(1)
        anchor = ""
        if "#" in target:
            target, anchor = target.split("#", 1)
            anchor = "#" + anchor
        if not target:
            return match.group(0)

        # Resolve the link against the source file's *repository* path first, then
        # decide where it lives. Guessing from the link text alone was not enough: a
        # `.md` target can escape the published set just as easily as a `.bib` one
        # (design/README.md links to ../.github/CONTRIBUTING.md).
        resolved = _normalise((Path(src).parent / target).as_posix())

        if resolved.startswith("docs/"):
            # The docs tree is the site root, so drop that segment and re-relativise.
            return f"]({_relative_to(src, resolved[len('docs/'):])}{anchor})"
        if resolved.startswith("design/") and Path(target).suffix.lower() in _PAGE_SUFFIXES:
            # A section's own README is the one exception: `on_files` never publishes
            # it (the generated index takes its URL, so both cannot exist), which
            # leaves a GitHub-written `README.md` link pointing at nothing on the
            # site — the two eye-control warnings that fail `mkdocs build --strict`
            # on main. The prose the link promises exists only in the repository,
            # so the repository is where it must go.
            parts = resolved.split("/")
            if len(parts) == 3 and parts[0] == "design" and parts[2].upper() == "README.MD":
                return f"]({repo_url}/blob/main/{resolved}{anchor})"
            # Mirrored one-to-one; the original relative link is already correct.
            return f"]({target}{anchor})"

        # Everything else is a repository artifact the site does not serve — a script,
        # a bibliography, a file outside the published tiers. Point at the repository
        # rather than leave a link that resolves to nothing.
        return f"]({repo_url}/blob/main/{resolved}{anchor})"

    return _RELATIVE_LINK.sub(_fix, markdown)


def _normalise(path: str) -> str:
    """Collapse `a/b/../c` without touching the filesystem."""
    out: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if out:
                out.pop()
            continue
        out.append(part)
    return "/".join(out)


def _relative_to(from_src: str, to_site_path: str) -> str:
    """A link from *from_src* (a site source path) to *to_site_path* (also site-relative)."""
    up = "../" * len(Path(from_src).parent.parts)
    return f"{up}{to_site_path}"
