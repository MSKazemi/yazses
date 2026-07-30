"""Document-scoped acronym state (pure) — ADR-v2-114.

Learn "Full Name (ACR)" definitions, expand an acronym on first use / contract after, and audit for
undefined acronyms. Pure regex/dict; no model.
"""
from __future__ import annotations

import re

_PAREN = re.compile(r"\(([A-Z][A-Z0-9]{1,})\)")
_WORD = re.compile(r"[A-Za-z0-9&\-']+")
_ACR = re.compile(r"\b([A-Z][A-Z0-9]{1,})\b")


def _key(term: str) -> str:
    return re.sub(r"[\s\-]", "", (term or "")).upper()


def _match_expansion(words, acr):
    """Simplified Schwartz-Hearst: smallest trailing window of ``words`` whose initials contain
    ``acr`` as an ordered subsequence, starting at the acronym's first letter. Pure."""
    low = acr.lower()
    for size in range(len(acr), min(len(words), len(acr) * 2) + 1):
        cand = words[-size:]
        if cand[0][0].lower() != low[0]:
            continue
        li = 0
        for w in cand:
            if li < len(low) and w[0].lower() == low[li]:
                li += 1
        if li == len(low):
            return " ".join(cand)
    return None


def _find_definitions(text: str) -> dict:
    defs = {}
    for m in _PAREN.finditer(text or ""):
        acr = m.group(1)
        words = _WORD.findall(text[:m.start()])
        expansion = _match_expansion(words, acr)
        if expansion:
            defs[acr] = expansion
    return defs


def expand_document(text: str, definitions: dict) -> str:
    """Expand each known acronym on its first occurrence, contract after. Pure.

    ``definitions`` maps ``ACR`` → full name. The first time an acronym appears it becomes
    ``Full Name (ACR)``; later occurrences stay as ``ACR``. Unknown acronyms pass through.
    Drives the persistent-glossary ``yazses acronyms expand`` command.
    """
    state = AcronymState()
    for acr, full in (definitions or {}).items():
        state.define(acr, full)
    return _ACR.sub(lambda m: state.resolve(m.group(0)), text or "")


class AcronymState:
    """Tracks acronym definitions and first-use expansion for one document. Pure state."""

    def __init__(self) -> None:
        self._defs: dict = {}      # ACR -> full name
        self._expanded: set = set()  # ACRs already written out

    def observe(self, text: str) -> None:
        """Learn "Full Name (ACR)" definitions already present in ``text`` (marks them expanded)."""
        for acr, full in _find_definitions(text).items():
            self._defs[acr] = full
            self._expanded.add(acr)

    def define(self, acr: str, full: str) -> None:
        """Register a known expansion to expand on first spoken use (not yet expanded)."""
        self._defs[acr.upper()] = full

    def resolve(self, term: str) -> str:
        """Expand a known acronym on first use, contract after; unknown terms pass through. Pure state."""
        acr = _key(term)
        if acr in self._defs:
            if acr not in self._expanded:
                self._expanded.add(acr)
                return f"{self._defs[acr]} ({acr})"
            return acr
        return term

    def audit(self, doc: str):
        """Warn for acronyms used in ``doc`` but never defined there or registered. Pure."""
        defined = set(_find_definitions(doc))
        warnings = []
        for acr in sorted(set(_ACR.findall(doc or ""))):
            if acr not in defined and acr not in self._defs:
                warnings.append(f"'{acr}' used but never defined")
        return warnings
