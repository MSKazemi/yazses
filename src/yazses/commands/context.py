"""Context-Primed Dictation & Commanding core (v2.0.0 Wave A, ADR-v2-004).

Pure logic that turns transient, already-consented desktop signals (active window
title, current selection, clipboard, editor LSP symbols, and -- with ``use_git`` -- the
focused repository's name and branch) into a compact term list
for Whisper's ``initial_prompt``, and helps resolve deictic command references.
Reading the signals is platform-specific and lives in ``platform/*``; this module
only processes strings handed to it, and NEVER stores them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_DEIXIS = re.compile(r"\b(this|that|these|those|it|here)\b", re.IGNORECASE)

# Small stoplist so common words don't crowd out domain terms.
_STOPWORDS = frozenset(
    """the and for you are was were with this that from have has had not but
    all any can will your our their they them his her its out off then than
    into over under about above below when what which who whom whose how why
    where here there also more most some such only very just like into onto""".split()
)


@dataclass
class ContextSources:
    window_title: str = ""
    selection: str = ""
    clipboard: str = ""
    lsp_symbols: list[str] = field(default_factory=list)
    # Repository name, branch and the branch's words (`commands/git_hint.py`).
    git_terms: list[str] = field(default_factory=list)


def _salience(term: str) -> int:
    """Rank identifier-like terms above Capitalized above plain words."""
    body = term[1:]
    if "_" in term or any(c.isupper() for c in body) or any(c.isdigit() for c in term):
        return 2  # snake_case / camelCase / has-digit → likely a domain identifier
    if term[0].isupper():
        return 1  # Proper noun / capitalized
    return 0


def extract_terms(text: str, max_terms: int = 48) -> list[str]:
    """Salient, de-duplicated terms from free text, most-useful first."""
    if not text:
        return []
    seen: set[str] = set()
    terms: list[str] = []
    for m in _WORD.finditer(text):
        term = m.group(0)
        key = term.lower()
        if key in _STOPWORDS or key in seen:
            continue
        seen.add(key)
        terms.append(term)
    terms.sort(key=_salience, reverse=True)  # stable → original order within a rank
    return terms[:max_terms]


def compose_context_prompt(
    sources: ContextSources,
    *,
    max_terms: int = 48,
    use_window_title: bool = True,
    use_selection: bool = True,
    use_clipboard: bool = False,
    use_lsp: bool = True,
    use_git: bool = False,
) -> str:
    """Build a comma-joined prompt fragment from the enabled context sources.

    LSP symbols (already structured) come first, then the git terms when ``use_git``
    (also structured, and few), then salient terms mined from the enabled text sources. De-duplicated case-insensitively and capped at ``max_terms``.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        key = term.lower()
        if key and key not in seen:
            seen.add(key)
            ordered.append(term)

    if use_lsp:
        for sym in sources.lsp_symbols:
            add(sym)
    if use_git:
        for term in sources.git_terms:
            add(term)
    blob_parts = []
    if use_window_title:
        blob_parts.append(sources.window_title)
    if use_selection:
        blob_parts.append(sources.selection)
    if use_clipboard:
        blob_parts.append(sources.clipboard)
    for term in extract_terms(" ".join(p for p in blob_parts if p), max_terms):
        add(term)

    return ", ".join(ordered[:max_terms])


def has_deixis(command: str) -> bool:
    """True if the command contains a deictic reference (this/that/it/here)."""
    return bool(_DEIXIS.search(command))


def deictic_target(sources: ContextSources) -> str:
    """The most likely referent of 'this'/'that' — the current selection, else ''."""
    return sources.selection.strip()
