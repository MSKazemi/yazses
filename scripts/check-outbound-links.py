#!/usr/bin/env python3
"""Report outbound links in the docs that are definitively gone.

Nothing checked outbound links, and it showed: `github.com/Sushanttmishraa` — the
credited **native reviewer** for the Hindi translation — returned 404 on a
published page. That column is how the project knows who to ask when the English
README changes, so the table was telling a maintainer to contact someone
unreachable. It was found only because someone swept all 334 links by hand.

## Why this reports so little

The hard design problem for a link checker is not finding dead links; it is not
crying wolf. A check that reports things a human then has to dismiss gets muted,
and a muted check is worse than none, because its silence now means nothing.

So only **404** and **410** fail. Everything else is deliberately ignored:

- **403** is the single most common status from a real bibliography. Publishers
  behind Cloudflare — ACM, Elsevier, Springer, Wiley, PNAS, NEJM — refuse any
  client that is not a browser. In one sweep of this repo, 40+ citation links
  answered 403 and *every one of them* was alive.
- **429** is rate limiting, usually self-inflicted by the checker itself. The
  first sweep here produced eight 429s from github.com purely from parallelism;
  all eight were 200 when retried serially.
- **5xx and timeouts** are the remote having a bad minute. A weekly check that
  fails on those fails randomly forever.

404 and 410 are the two the web actually means: this is not here, and this is
gone on purpose. Both are worth a human's attention; nothing else is.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Files whose outbound links are checked. Deliberately the published surfaces —
#: a dead link in a design note costs nothing; one in the docs site costs trust.
SEARCH_GLOBS = ("docs/**/*.md", "README.md", "ROADMAP.md", "CONTRIBUTORS.md")

#: Only these mean "this resource is not there". See the module docstring.
DEAD = {404, 410}

#: A real browser UA. Many hosts 403 anything that looks automated, and a 403 is
#: not a finding here — but there is no reason to provoke one.
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

#: Hosts that are always placeholders, never resolvable. `example.com` is
#: reserved by RFC 2606 exactly so documentation can use it.
SKIP_HOSTS = {"example.com", "www.example.com", "example.org", "localhost"}

_HTML_HREF = re.compile(r'href="(https?://[^"]+)"')
_BARE = re.compile(r"<(https?://[^>]+)>")
_MD_OPEN = re.compile(r"\]\((https?://)")


def _markdown_urls(text: str) -> list[str]:
    """Markdown link targets, counting parentheses instead of stopping at one.

    A naive `\\((https?://[^\\s)]+)\\)` is wrong for this repo specifically, and
    the checker caught it on its own first run: Elsevier DOIs embed a balanced
    pair, so `10.1016/S0020-7373(86)80049-9` was truncated at `(86` and reported
    as a 404. The full DOI resolves, and Python-Markdown renders it correctly —
    the only broken thing was the extractor. A checker whose first report is a
    phantom is exactly the one nobody trusts again.
    """
    urls = []
    for match in _MD_OPEN.finditer(text):
        start = match.start(1)
        depth = 1
        i = start
        while i < len(text):
            char = text[i]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            elif char.isspace():
                # Markdown allows `[x](url "title")`; the title is not a link.
                break
            i += 1
        urls.append(text[start:i])
    return urls


def extract_links(text: str) -> set[str]:
    """Every outbound URL in one markdown file.

    Covers the three forms the docs actually use: markdown links, raw HTML
    `href=` (the contributor wall is generated HTML), and autolinks in angle
    brackets (the citation blocks).
    """
    found: set[str] = set()
    candidates = _markdown_urls(text)
    for pattern in (_HTML_HREF, _BARE):
        candidates.extend(pattern.findall(text))
    for url in candidates:
        # Strip a trailing fragment and any punctuation the prose leaked in.
        url = url.split("#")[0].rstrip(".,;:")
        if url:
            found.add(url)
    return found


def collect(root: Path = ROOT) -> dict[str, set[str]]:
    """url -> the repo-relative files that link to it."""
    where: dict[str, set[str]] = {}
    for glob in SEARCH_GLOBS:
        for path in sorted(root.glob(glob)):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for url in extract_links(text):
                where.setdefault(url, set()).add(
                    path.relative_to(root).as_posix()
                )
    return where


def is_skipped(url: str) -> bool:
    """Reserved documentation hosts are placeholders, not links."""
    host = urllib.parse.urlsplit(url).hostname or ""
    return host.lower() in SKIP_HOSTS


def status_of(url: str, timeout: float = 25.0) -> int:
    """HTTP status, following redirects. 0 means "could not tell" — never a finding."""
    request = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        # DNS failure, TLS problem, timeout, connection reset. Real breakage looks
        # like this too, but so does a flaky runner, and we cannot tell them apart
        # from one sample. Not a finding.
        return 0


@dataclass
class Finding:
    url: str
    status: int
    files: list[str]


def check(where: dict[str, set[str]], workers: int = 8) -> list[Finding]:
    urls = [u for u in sorted(where) if not is_skipped(u)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        statuses = list(pool.map(status_of, urls))

    dead = [(u, s) for u, s in zip(urls, statuses) if s in DEAD]
    # Re-check serially before reporting. The parallel pass is what provokes rate
    # limiting, and a 404 that becomes a 200 on a calm retry was never a finding.
    findings = []
    for url, _ in dead:
        confirmed = status_of(url)
        if confirmed in DEAD:
            findings.append(Finding(url, confirmed, sorted(where[url])))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workers", type=int, default=8, help="parallel requests (default 8)"
    )
    args = parser.parse_args()

    where = collect()
    checked = sum(1 for u in where if not is_skipped(u))
    print(f"checking {checked} outbound links across {len(SEARCH_GLOBS)} surfaces")

    findings = check(where, workers=args.workers)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")

    if not findings:
        print(f"OK - no dead links among {checked} checked")
        if summary:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(f"No dead outbound links ({checked} checked).\n")
        return 0

    lines = [
        "## Dead outbound links",
        "",
        "Only `404` and `410` are reported — a `403` from a publisher is a bot",
        "block, not a dead link. Each of these was re-checked serially to rule out",
        "rate limiting.",
        "",
        "| Status | URL | Linked from |",
        "|---|---|---|",
    ]
    for f in findings:
        lines.append(f"| {f.status} | {f.url} | {', '.join(f.files)} |")

    report = "\n".join(lines)
    print(report)
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
