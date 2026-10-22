"""Derive the site's "what we are building" status from the repository, at build time.

Hand-written status rots. The roadmap's timeline still placed "Settings GUI finished" in
the v2.18+ future twenty-five releases after that line was written, and the release
index needed a dedicated test just to keep its "current stable" sentence honest. The
facts a visitor actually wants -- what the latest release is, when it shipped, and what
is on ``main`` but not released yet -- already live in two places that every change
updates anyway:

* ``CHANGELOG.md``: one ``## [x.y.z] - YYYY-MM-DD`` heading per release and, under
  ``## [Unreleased]``, one ``### <Kind> — <headline>`` heading per change;
* ``docs/releases/v<x.y.z>.md``: the release's own title and one-sentence description.

This hook reads both once per build and publishes the result two ways:

1. ``config.extra.yazses_status`` -- a plain dict the landing template (overrides/home.html)
   renders, so the home page's "Building now" band cannot disagree with the changelog;
2. Markdown placeholders, replaced in any page that contains them::

       <!-- yazses-status:latest -->
       <!-- yazses-status:recent-releases -->
       <!-- yazses-status:unreleased -->
       <!-- yazses-status:unreleased-summary -->

The parsing is pure (``parse_changelog``, ``read_release_note``) and unit-tested in
``tests/test_project_status_hook.py``. Nothing here touches the network.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, NamedTuple

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Repository files outside docs/ that this hook reads. .github/workflows/docs.yml must
#: rebuild the site when one changes; tests/test_docs_deploy_trigger.py reads this tuple.
BUILD_INPUTS = ("CHANGELOG.md",)

_CHANGELOG = _REPO_ROOT / "CHANGELOG.md"
_RELEASES_DIR = _REPO_ROOT / "docs" / "releases"

_RELEASE_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\](?:\s*-\s*(?P<date>\d{4}-\d{2}-\d{2}))?\s*$")
_ENTRY_HEADING = re.compile(r"^### (?P<kind>[A-Za-z][A-Za-z ]*?)\s*(?:—|--|-|:)\s*(?P<headline>.+?)\s*$")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_STABLE = re.compile(r"^\d+\.\d+\.\d+$")

# How many unreleased headlines the landing page shows; the full list is on docs/now.md.
HOME_ITEMS = 6
RECENT_RELEASES = 6

PLACEHOLDER = "<!-- yazses-status:{name} -->"


class Entry(NamedTuple):
    """One ``### Kind — headline`` change under a changelog section."""

    kind: str
    headline: str

    @property
    def text(self) -> str:
        """The headline with Markdown links and code ticks flattened, for HTML templates."""
        return _LINK.sub(r"\1", self.headline).replace("`", "")


class Release(NamedTuple):
    version: str
    date: str


class Changelog:
    # A plain class, not a dataclass: MkDocs and the tests load this file by path, and
    # dataclasses look the defining module up in sys.modules, where it may not be.
    def __init__(self) -> None:
        self.unreleased: list[Entry] = []
        self.releases: list[Release] = []

    @property
    def stable(self) -> list[Release]:
        return [r for r in self.releases if _STABLE.match(r.version)]

    def kind_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.unreleased:
            counts[entry.kind] = counts.get(entry.kind, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def parse_changelog(text: str) -> Changelog:
    """Parse a Keep-a-Changelog file into unreleased entries and dated releases.

    Only ``###`` headings directly under ``## [Unreleased]`` become entries; everything
    under a released version is ignored except the version heading itself. Fenced code
    blocks are skipped so a ``## [`` inside an example cannot be mistaken for a release.
    """
    log = Changelog()
    section: str | None = None
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = _RELEASE_HEADING.match(line)
        if heading:
            version = heading.group("version")
            if version.lower() == "unreleased":
                section = "unreleased"
            else:
                section = "released"
                log.releases.append(Release(version, heading.group("date") or ""))
            continue
        if section == "unreleased":
            entry = _ENTRY_HEADING.match(line)
            if entry:
                log.unreleased.append(Entry(entry.group("kind").strip(), entry.group("headline")))
    return log


def read_release_note(version: str, releases_dir: Path = _RELEASES_DIR) -> tuple[str, str]:
    """Return ``(headline, description)`` from ``docs/releases/v<version>.md`` front matter.

    The headline is the part of the title after the dash ("no more words nobody said");
    either value is ``""`` when the note or the field is missing.
    """
    path = releases_dir / f"v{version}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    if not text.startswith("---"):
        return "", ""
    end = text.find("\n---", 3)
    front = text[3:end] if end != -1 else ""
    fields: dict[str, str] = {}
    for raw in front.splitlines():
        key, sep, value = raw.partition(":")
        if sep:
            fields[key.strip()] = value.strip().strip('"').strip("'")
    title = fields.get("title", "")
    headline = re.split(r"\s+[—–-]\s+", title, maxsplit=1)
    return (headline[1] if len(headline) == 2 else ""), fields.get("description", "")


def build_status(changelog: Changelog, releases_dir: Path = _RELEASES_DIR) -> dict[str, Any]:
    """The dict the templates consume. Keys are stable; values are plain strings/ints/lists."""
    stable = changelog.stable
    recent = []
    for release in stable[:RECENT_RELEASES]:
        headline, description = read_release_note(release.version, releases_dir)
        recent.append(
            {
                "version": release.version,
                "date": release.date,
                "headline": headline,
                "description": description,
                "note": f"releases/v{release.version}.html"
                if (releases_dir / f"v{release.version}.md").is_file()
                else "",
            }
        )
    return {
        "latest": recent[0] if recent else None,
        "recent": recent,
        "unreleased_count": len(changelog.unreleased),
        "unreleased_kinds": changelog.kind_counts(),
        "unreleased_top": [
            {"kind": e.kind, "text": e.text} for e in changelog.unreleased[:HOME_ITEMS]
        ],
    }


# --------------------------------------------------------------------- Markdown blocks


def _latest_md(status: dict[str, Any]) -> str:
    latest = status["latest"]
    if not latest:
        return ""
    name = f"[v{latest['version']}]({latest['note'].replace('.html', '.md')})" if latest["note"] else f"v{latest['version']}"
    line = f"**Latest release: {name}**, published {latest['date']}"
    if latest["headline"]:
        line += f" — *{latest['headline']}*"
    line += "."
    if latest["description"]:
        line += f" {latest['description']}"
    return line


def _recent_md(status: dict[str, Any]) -> str:
    rows = ["| Release | Date | What it brought |", "|---|---|---|"]
    for r in status["recent"]:
        name = f"[v{r['version']}]({r['note'].replace('.html', '.md')})" if r["note"] else f"v{r['version']}"
        what = r["headline"] or "—"
        rows.append(f"| {name} | {r['date']} | {what} |")
    return "\n".join(rows)


def _unreleased_summary_md(status: dict[str, Any]) -> str:
    count = status["unreleased_count"]
    if not count:
        return "Everything on `main` has been released."
    kinds = " · ".join(f"{k} {n}" for k, n in status["unreleased_kinds"].items())
    return f"**{count} changes are on `main` and not yet in a release** — {kinds}."


def _unreleased_md(changelog: Changelog) -> str:
    if not changelog.unreleased:
        return "Nothing is waiting for a release right now."
    groups: dict[str, list[Entry]] = {}
    for entry in changelog.unreleased:
        groups.setdefault(entry.kind, []).append(entry)
    out: list[str] = []
    for kind, entries in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out.append(f"**{kind}** ({len(entries)})\n")
        out.extend(f"- {e.headline}" for e in entries)
        out.append("")
    return "\n".join(out).rstrip()


def render_placeholders(markdown: str, changelog: Changelog, status: dict[str, Any]) -> str:
    """Replace every known placeholder in *markdown*; unknown text is left untouched."""
    blocks = {
        "latest": lambda: _latest_md(status),
        "recent-releases": lambda: _recent_md(status),
        "unreleased-summary": lambda: _unreleased_summary_md(status),
        "unreleased": lambda: _unreleased_md(changelog),
    }
    for name, make in blocks.items():
        marker = PLACEHOLDER.format(name=name)
        if marker in markdown:
            markdown = markdown.replace(marker, make())
    return markdown


# ------------------------------------------------------------------------ MkDocs hooks

_STATE: dict[str, Any] = {}


def on_config(config: Any, **_: Any) -> Any:
    try:
        text = _CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        text = ""
    changelog = parse_changelog(text)
    status = build_status(changelog)
    _STATE["changelog"] = changelog
    _STATE["status"] = status
    config.extra["yazses_status"] = status
    return config


def on_page_markdown(markdown: str, page: Any = None, **_: Any) -> str:
    if "<!-- yazses-status:" not in markdown or "changelog" not in _STATE:
        return markdown
    return render_placeholders(markdown, _STATE["changelog"], _STATE["status"])
