#!/usr/bin/env python3
"""Sweep the literature for work relevant to YazSes, and write a dated digest.

**Why this is a script and not a feature.** ADR-019 enumerates every way data can leave
the machine and enforces it with a test: a new outbound call inside `src/yazses/` fails
the build until it is registered. A literature watcher living in the daemon would be a
sixth network path on a tool whose central promise is that it makes none you did not ask
for. So it lives here, in maintainer tooling, run deliberately by a person — and the
daemon's egress inventory stays as short as it is.

**What it does.** Queries the arXiv API for the categories and terms this project
actually works in, drops anything already seen, and writes a dated Markdown digest plus
an updated seen-index. Both are committed, which is what makes the next run produce only
what is new.

**What it deliberately does not do.** It does not download PDFs. The repository blocks
committed PDFs outright (redistributing other people's papers is a copyright problem),
and the digest is our summary plus a link to the publisher's copy — which is the same
rule the research pages already follow.

Usage:
    uv run python scripts/research-watch.py                  # last 30 days
    uv run python scripts/research-watch.py --days 90
    uv run python scripts/research-watch.py --dry-run        # print, write nothing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCH_DIR = ROOT / "design/research/watch"
SEEN_PATH = WATCH_DIR / "seen.json"

ARXIV_API = "http://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"

#: arXiv's stated courtesy limit is one request every three seconds. This makes a
#: handful of requests per run, so there is no reason to go near it.
_REQUEST_GAP_S = 3.0

#: The searches, each tied to a direction this project has actually written down.
#: A query that cannot say which of our problems it serves does not belong here —
#: the point is a digest someone reads, not a firehose nobody does.
QUERIES: list[tuple[str, str]] = [
    ("on-device ASR",
     'cat:cs.CL AND (abs:"on-device" OR abs:"edge") AND abs:"speech recognition"'),
    # Narrowed after the first run: "speech input" alone pulled in an LLM-code-security
    # paper that merely used the phrase. Requiring a text-entry term as well keeps the
    # topic about entering text by voice.
    ("dictation & text entry",
     'cat:cs.HC AND (abs:"dictation" OR abs:"text entry" OR abs:"voice typing")'),
    ("correction & error cost",
     'cat:cs.HC AND abs:"speech" AND (abs:"error correction" OR abs:"repair")'),
    ("code-switching ASR",
     'cat:cs.CL AND abs:"code-switching" AND abs:"speech recognition"'),
    ("dysarthric & atypical speech",
     'cat:cs.CL AND (abs:"dysarthric" OR abs:"atypical speech")'),
    ("silent speech & sEMG",
     '(cat:cs.HC OR cat:eess.AS) AND (abs:"silent speech" OR abs:"electromyograph")'),
    # Also narrowed: "accessibility AND voice" matched a voice-controlled game-editing
    # paper. Anchoring on the assistive framing rather than on the word "voice" alone.
    ("accessibility & hands-free input",
     'cat:cs.HC AND (abs:"assistive" OR abs:"accessibility") '
     'AND (abs:"hands-free" OR abs:"speech interface" OR abs:"voice interface")'),
]


def _fetch(query: str, max_results: int) -> str:
    url = f"{ARXIV_API}?" + urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    request = urllib.request.Request(url, headers={
        # arXiv asks that automated clients identify themselves.
        "User-Agent": "yazses-research-watch/1.0 (+https://github.com/MSKazemi/yazses)",
    })
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed host
        return response.read().decode("utf-8", errors="replace")


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _parse(xml_text: str, topic: str, since: datetime) -> list[dict]:
    """Atom → the fields we keep. Never the PDF."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for entry in root.findall(f"{ATOM}entry"):
        published = _clean(entry.findtext(f"{ATOM}published"))
        try:
            when = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < since:
            continue
        arxiv_id = _clean(entry.findtext(f"{ATOM}id"))
        out.append({
            "id": arxiv_id,
            "topic": topic,
            "title": _clean(entry.findtext(f"{ATOM}title")),
            "authors": [
                _clean(a.findtext(f"{ATOM}name"))
                for a in entry.findall(f"{ATOM}author")
            ][:6],
            "published": published[:10],
            "summary": _clean(entry.findtext(f"{ATOM}summary")),
            "link": arxiv_id,
        })
    return out


def _load_seen() -> dict:
    try:
        return json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ids": [], "last_run": None}


def _render(new: list[dict], days: int, when: date) -> str:
    lines = [
        "---",
        f"title: Research digest — {when.isoformat()}",
        f"description: New work relevant to offline voice input, from the last {days} days.",
        "---",
        "",
        f"# Research digest — {when.isoformat()}",
        "",
        f"Automated sweep of the last **{days} days**, generated by "
        "`scripts/research-watch.py`. Titles and abstracts are arXiv's; anything under "
        "*So what* is a maintainer's note, not the authors' claim.",
        "",
        "!!! note \"No PDFs are hosted here\"",
        "",
        "    Every entry links to the publisher's copy. We cite work; we do not "
        "redistribute it.",
        "",
    ]
    if not new:
        lines += ["Nothing new matched this run. That is a normal result for a "
                  "30-day window on a narrow query set.", ""]
        return "\n".join(lines)

    by_topic: dict[str, list[dict]] = {}
    for paper in new:
        by_topic.setdefault(paper["topic"], []).append(paper)

    lines.append(f"**{len(new)} new** across {len(by_topic)} topics.\n")
    for topic in sorted(by_topic):
        lines.append(f"## {topic}\n")
        for paper in by_topic[topic]:
            authors = ", ".join(paper["authors"])
            if len(paper["authors"]) == 6:
                authors += " et al."
            lines += [
                f"### [{paper['title']}]({paper['link']})",
                "",
                f"*{authors} — {paper['published']}*",
                "",
                paper["summary"][:600] + ("…" if len(paper["summary"]) > 600 else ""),
                "",
                "**So what:** _(unreviewed — add a note or delete the entry)_",
                "",
            ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=30, help="how far back to look")
    ap.add_argument("--max-per-query", type=int, default=25)
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    seen = _load_seen()
    known = set(seen.get("ids", []))

    found: list[dict] = []
    for index, (topic, query) in enumerate(QUERIES):
        if index:
            time.sleep(_REQUEST_GAP_S)
        try:
            xml_text = _fetch(query, args.max_per_query)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"  {topic:32s} unreachable ({exc})", file=sys.stderr)
            continue
        papers = _parse(xml_text, topic, since)
        fresh = [p for p in papers if p["id"] not in known]
        found.extend(fresh)
        known.update(p["id"] for p in fresh)
        print(f"  {topic:32s} {len(papers):3d} in window, {len(fresh):3d} new", flush=True)

    today = date.today()
    digest = _render(found, args.days, today)
    if args.dry_run:
        print("\n" + digest)
        return 0

    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    out = WATCH_DIR / f"{today.isoformat()}-digest.md"
    out.write_text(digest, encoding="utf-8")
    SEEN_PATH.write_text(
        json.dumps({"ids": sorted(known), "last_run": today.isoformat()},
                   indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out.relative_to(ROOT)} ({len(found)} new)")
    print(f"wrote {SEEN_PATH.relative_to(ROOT)} ({len(known)} known)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
