"""BibTeX parse + fuzzy citation resolve + format (pure) — ADR-v2-071.

Parse a local ``.bib``, match a spoken "author year" query to an entry, and format it. Pure and
deterministic; an embedding index for large libraries is deferred.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_ENTRY = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)\n\s*\}", re.DOTALL)
_FIELD = re.compile(r"(\w+)\s*=\s*(?:\{(.*?)\}|\"(.*?)\")", re.DOTALL)
_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_WORD = re.compile(r"[A-Za-z]+")


@dataclass(frozen=True)
class Entry:
    """A bibliography entry: citation ``key``, ``authors`` string, ``year``, ``title``."""
    key: str
    authors: str = ""
    year: str = ""
    title: str = ""


def parse_bibtex(text: str):
    """Parse a BibTeX string into a list of :class:`Entry`. Pure (covers common entries)."""
    entries = []
    for key, body in _ENTRY.findall(text or ""):
        fields = {}
        for name, braced, quoted in _FIELD.findall(body):
            fields[name.lower()] = (braced or quoted).strip()
        entries.append(Entry(
            key=key.strip(),
            authors=fields.get("author", ""),
            year=fields.get("year", ""),
            title=fields.get("title", ""),
        ))
    return entries


def _surnames(authors: str):
    # "Vaswani, Ashish and Shazeer, Noam" → {"vaswani", "shazeer"}; also handles "Ashish Vaswani".
    out = set()
    for chunk in re.split(r"\s+and\s+", authors or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        surname = chunk.split(",")[0].strip() if "," in chunk else chunk.split()[-1]
        for w in _WORD.findall(surname.lower()):
            out.add(w)
    return out


def resolve_citation(query: str, entries):
    """Return the entry best matching a spoken "author year" query, or ``None``. Pure."""
    q = (query or "").lower()
    q_year = _YEAR.search(q)
    q_year = q_year.group(1) if q_year else ""
    q_words = {w for w in _WORD.findall(q) if w not in ("cite", "citation", "reference")}

    best, best_score = None, 0
    for e in entries:
        score = 0
        surnames = _surnames(e.authors)
        if surnames & q_words:
            score += 2
        if q_year and e.year == q_year:
            score += 2
        # a title word match is a weak tiebreak
        if q_words & {w.lower() for w in _WORD.findall(e.title)}:
            score += 1
        if score > best_score:
            best, best_score = e, score
    return best if best_score >= 2 else None


def format_citation(entry: Entry, style: str = "latex") -> str:
    """Format an :class:`Entry` in ``latex`` / ``plain`` / ``apa`` style. Pure."""
    if style == "latex":
        return f"\\cite{{{entry.key}}}"
    surnames = list(_surnames(entry.authors))
    label = entry.authors.split(",")[0].split(" and ")[0].strip() if entry.authors else entry.key
    lead = label.split()[-1] if label and "," not in label else (label.split(",")[0] if label else entry.key)
    if len(surnames) > 1:
        return f"{lead} et al. ({entry.year})"
    return f"{lead} ({entry.year})"
