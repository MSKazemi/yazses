"""Minimal-edit guard + article rules (pure) — ADR-v2-050.

The safety primitive that keeps a grammar model from paraphrasing (``is_minimal_edit``) plus a
small dependency-free article-agreement fixer. Pure and deterministic; the neural GEC model
lives behind the ``gec`` extra and is always gated by ``is_minimal_edit``.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# Vowel-letter words pronounced with a consonant onset → take "a".
_CONSONANT_SOUND = frozenset(
    ["university", "unicorn", "unique", "unit", "user", "usage", "european", "euro",
     "one", "once", "ubiquitous", "useful", "uniform", "url", "ufo"]
)
# Consonant-letter words with a vowel onset → take "an".
_VOWEL_SOUND = frozenset(["hour", "honest", "honor", "honour", "heir", "heiress", "honestly"])


def is_minimal_edit(src: str, out: str, min_keep_ratio: float = 0.6, max_edit_ratio: float = 0.4) -> bool:
    """True when ``out`` is a minimal edit of ``src`` (safe to apply). Pure.

    Requires high token overlap and a bounded length change, so a model that paraphrases or
    rewrites (rather than minimally correcting) is rejected. Empty ``src`` accepts only empty
    ``out``.
    """
    s = (src or "").split()
    o = (out or "").split()
    if not s:
        return not o
    overlap = SequenceMatcher(None, s, o).ratio()
    len_ok = abs(len(o) - len(s)) <= max(2, int(len(s) * max_edit_ratio))
    return overlap >= min_keep_ratio and len_ok


def _wants_an(word: str) -> bool:
    w = word.lower()
    if w in _CONSONANT_SOUND:
        return False
    if w in _VOWEL_SOUND:
        return True
    return w[:1] in "aeiou"


def fix_articles(text: str) -> str:
    """Fix a/an agreement before the following word (heuristic + exceptions). Pure."""
    def repl(m: re.Match) -> str:
        art, word = m.group(1), m.group(2)
        correct = "an" if _wants_an(word) else "a"
        if art[0].isupper():
            correct = correct.capitalize()
        return f"{correct} {word}"

    return re.sub(r"\b([Aa]n?)\s+([A-Za-z]+)", repl, text or "")
