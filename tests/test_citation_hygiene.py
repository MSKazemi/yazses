"""We cite other people's work; we never redistribute it.

Two rules, and the repository already enforces the first one twice — `.gitignore`
blocks `*.pdf` and the pre-commit hook blocks it again. This adds the checks those two
cannot make:

**No committed PDF, asserted rather than assumed.** The ignore rule and the hook both
protect the *commit*; neither notices a PDF that arrived some other way (a merge, a
`git add -f`, a rebase from a branch that predates the rule). One assertion over the
index closes that.

**No published page deep-links at a third-party PDF.** Linking is not redistribution, so
this is a weaker rule than the first — but it is still the wrong citation. A direct file
link skips the landing page that carries the version, the licence and the DOI; it rots
when the file moves, which is often; and in a repository that blocks committed PDFs it
invites the obvious next step. The scholarly form is the abstract or publisher page.

This matters more since the engineering tier was published: 242 more pages became part
of the public documentation, and every citation in them is now a citation the site makes.

`hooks/design_tier.py` copies *every* tracked file under a `design/` section into the built
site, not just the Markdown, so the LaTeX manuscript sources and their `.bib` are published
pages too. Their citations are scanned by a second pass: a BibTeX entry writes its link as
`url = {...}`, which the Markdown/HTML link pattern cannot match, so the rule would otherwise
hold everywhere except the one file whose entire job is citing other people's work.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.gitprobe import require_git

ROOT = Path(__file__).resolve().parent.parent

#: Trees whose contents are published as documentation.
PUBLISHED = ("docs", "design")

#: Markdown or HTML link straight at a PDF on another host.
_PDF_LINK = re.compile(r'(?:\]\(|href=["\']?)(https?://[^)"\'\s]+\.pdf)', re.I)

#: Manuscript source published alongside the Markdown by `hooks/design_tier.py`.
_MANUSCRIPT_SUFFIXES = (".tex", ".bib")

#: Any PDF URL at all, however it is delimited. `.tex` and `.bib` wrap a URL in braces,
#: in `\url{}`, or in nothing; matching only the Markdown form would read the file and
#: find nothing, which is the failure mode that looks exactly like compliance.
_PDF_URL = re.compile(r'https?://[^\s{}<>"\')\]]+\.pdf', re.I)

#: Deep links that are *not* third-party redistribution: our own domain, and the
#: canonical preprint/publisher landing patterns that happen to end in .pdf.
_ALLOWED_HOSTS = ("mskazemi.com", "github.com/MSKazemi")

#: Known exceptions, each with the reason it is tolerated. Empty is the goal.
#: A file listed here is a debt, not a decision — see the module docstring.
_KNOWN: dict[str, str] = {
    # One remaining link, to an IAFPA 2019 conference *presentation* hosted by its
    # author. Conference presentations frequently have no landing page at all, and
    # inventing a plausible-looking one would be a worse citation than a direct link
    # to the real file. Repointed the other link in these files to arXiv:1710.10468,
    # which is the same paper's abstract page.
    "design/meeting-mode/soa-report.html":
        "IAFPA19 presentation with no resolvable landing page",
    "design/meeting-mode/README.md":
        "the same IAFPA19 presentation",
}


def _tracked(paths: tuple[str, ...]) -> list[str]:
    require_git()
    out = subprocess.run(
        ["git", "ls-files", *paths], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def test_no_pdf_is_committed_anywhere():
    """`.gitignore` and the hook guard the commit; this guards the index itself."""
    pdfs = [f for f in _tracked(()) if f.lower().endswith(".pdf")]
    assert not pdfs, (
        f"these PDFs are tracked: {pdfs}. Other people's papers are cited, never "
        f"redistributed — and our own generated PDFs are build artifacts."
    )


def test_the_scan_actually_reads_the_published_trees():
    """Guard the guard: an empty file list would make the check below vacuous."""
    files = [f for f in _tracked(PUBLISHED) if f.endswith((".md", ".html"))]
    assert len(files) > 100, f"only {len(files)} published files found — is the scan right?"


def test_no_published_page_deep_links_at_a_third_party_pdf():
    offenders: dict[str, list[str]] = {}
    for rel in _tracked(PUBLISHED):
        if not rel.endswith((".md", ".html")) or rel in _KNOWN:
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hits = [
            url for url in _PDF_LINK.findall(text)
            if not any(host in url for host in _ALLOWED_HOSTS)
        ]
        if hits:
            offenders[rel] = sorted(set(hits))
    assert not offenders, (
        f"these published pages link straight at a third-party PDF: {offenders}\n\n"
        f"Cite the landing page (abstract, DOI or publisher page) instead. It carries "
        f"the version and licence, and it does not rot when the file moves."
    )


def _manuscript_sources() -> list[str]:
    return [f for f in _tracked(PUBLISHED) if f.lower().endswith(_MANUSCRIPT_SUFFIXES)]


def test_the_scan_actually_reads_the_manuscript_sources():
    """Guard the guard: no `.tex`/`.bib` found means the check below proves nothing."""
    files = _manuscript_sources()
    assert files, (
        "no .tex or .bib is tracked under docs/ or design/, so the manuscript citation "
        "check below is vacuous. If the manuscript moved, point PUBLISHED at its new "
        "home; do not leave a check that passes because it reads nothing."
    )


def test_no_manuscript_source_cites_a_third_party_pdf():
    """A `.bib` entry is a citation; the landing-page rule applies to it too."""
    offenders: dict[str, list[str]] = {}
    for rel in _manuscript_sources():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hits = [
            url for url in _PDF_URL.findall(text)
            if not any(host in url for host in _ALLOWED_HOSTS)
        ]
        if hits:
            offenders[rel] = sorted(set(hits))
    assert not offenders, (
        f"these manuscript sources cite a third-party PDF directly: {offenders}\n\n"
        f"Use the abstract, DOI or publisher landing page. arXiv, for example, is "
        f"arxiv.org/abs/ID and never arxiv.org/pdf/ID."
    )


@pytest.mark.parametrize("rel", sorted(_KNOWN))
def test_every_known_exception_still_exists(rel: str):
    """An exception for a deleted file is a rule quietly getting weaker."""
    assert (ROOT / rel).is_file(), (
        f"{rel} is listed as a citation-hygiene exception but no longer exists — "
        f"remove it from _KNOWN"
    )


def test_the_exception_list_stays_small():
    """It is a debt list. If it grows, the rule is not being applied."""
    assert len(_KNOWN) <= 2, (
        f"{len(_KNOWN)} citation-hygiene exceptions. Each is a page that cites badly; "
        f"fix one before adding another."
    )
