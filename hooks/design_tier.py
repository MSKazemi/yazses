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
from pathlib import Path
from typing import Any

log = logging.getLogger("mkdocs.hooks.design_tier")

#: Directories under `design/` to publish, in nav order, with the index we generate.
_SECTIONS: list[tuple[str, str, str]] = [
    ("adr", "Decision records",
     "Every architectural decision, why it was made, and what would reverse it."),
    ("specs", "Specifications",
     "Implementation-ready designs: what gets built, and how it is judged done."),
    ("research", "Research notes",
     "Studies, surveys and the literature watch behind the design decisions."),
]

#: Single files at the top of `design/` worth publishing on their own.
#:  is included because the tier documents link to it as the statement of
#: what is public and why — the one page that explains the rest.
_TOP_LEVEL = ["README.md", "architecture.md", "threat-model.md", "emg-protocol.md"]

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

    for filename in _TOP_LEVEL:
        source = design / filename
        if source.is_file():
            _add(source)

    for section, title, blurb in _SECTIONS:
        root = design / section
        if not root.is_dir():
            continue
        entries: list[tuple[str, str, str]] = []
        for source in sorted(root.rglob("*.md")):
            rel = source.relative_to(repo_root).as_posix()
            if _is_private(rel):
                skipped += 1
                continue
            relative = source.relative_to(root).as_posix()
            _add(source)
            if source.name.upper() != "README.MD":
                entries.append((relative, _title_of(source), _status_of(source)))

        files.append(_generated(
            f"design/{section}/index.md",
            _index_page(section, title, blurb, entries),
            config,
        ))

    if skipped:
        log.info("design_tier: skipped %d file(s) under a private tree", skipped)
    log.info("design_tier: published %d section index(es)", len(_SECTIONS))
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
