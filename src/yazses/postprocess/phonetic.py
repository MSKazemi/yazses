"""Phonetic Corrector (pure) — ADR-v2-027.

Fix mis-heard proper nouns/commands by matching transcript tokens against a personal
lexicon in *sound* space. Uses a compact, documented phonetic key (a deterministic
consonant-skeleton reduction — not a claim to be Metaphone) + normalized edit distance.
Pure and conservative; a stronger G2P backend is opt-in elsewhere.

.. warning::

   **`known` is not optional in practice, and the daemon does not pass it.**

   A personal lexicon naturally contains ordinary English words -- "Git", "head" -- and a
   token that merely *sounds* like one is rewritten to it. Measured against a real
   24-entry vocabulary, six of eleven ordinary sentences were corrupted::

       "get the file"          ->  "Git the file"
       "go ahead and try it"   ->  "go head and try it"
       "we had a great time"   ->  "we head a Git time"

   Tuning ``max_distance`` cannot fix this, and that is worth stating because it is the
   obvious thing to try. The scores collide exactly::

       get    -> Git      0.000     <- must NOT be corrected
       had    -> head     0.000     <- must NOT be corrected
       githab -> GitHub   0.000     <- MUST be corrected

   "get" and "Git" are phonetic twins; no threshold, minimum length or scoring tweak can
   separate a real word that sounds like a lexicon entry from a misrecognition of it.
   Only a set of correctly-spelled words can -- which is exactly what the ``known``
   parameter is for, and `core/daemon.py` calls `correct_text(text, _vocab)` without it.

   `[phonetic] enabled` is off by default, so this affects whoever turns it on. Wiring a
   word list is a data decision (which list, how large, what licence) and is left open
   rather than guessed at.
"""
from __future__ import annotations

import re

_VOWELS = set("aeiou")
# Rough homophone folding so near-sounds share a key (c→k, ph→f, etc.).
_FOLD = [("ph", "f"), ("ck", "k"), ("qu", "kw"), ("x", "ks"), ("z", "s"), ("c", "k")]


def phonetic_key(word: str) -> str:
    """A deterministic sound-skeleton key for a word. Pure.

    Lowercases, folds common homophone digraphs, keeps the first letter, then drops
    non-leading vowels and collapses consecutive duplicates. "Kubernetes" and
    "cubernetties" reduce to the same key.
    """
    w = re.sub(r"[^a-z]", "", (word or "").lower())
    if not w:
        return ""
    for a, b in _FOLD:
        w = w.replace(a, b)
    first, rest = w[0], w[1:]
    rest = "".join(ch for ch in rest if ch not in _VOWELS)
    key = first + rest
    out: list[str] = []
    for ch in key:
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def correct_word(token: str, vocab, *, max_distance: float = 0.34, known=None):
    """Return a vocab term whose sound matches ``token``, or the token unchanged.

    Skips tokens already in ``known`` (a set of correctly-spelled words). Compares the
    token's phonetic key to each vocab term's key; replaces only when the normalized
    key-distance (edit distance / longer key length) is ``<= max_distance`` and strictly
    the best match. Conservative: an exact vocab spelling is never rewritten. Pure.
    """
    raw = (token or "")
    low = raw.lower()
    if not low:
        return token
    if known and low in known:
        return token
    if any(low == str(v).lower() for v in vocab):
        return token
    tkey = phonetic_key(low)
    if not tkey:  # pragma: no cover — unreachable: a non-empty letter token always keys
        return token
    best, best_score = None, 1.0
    for term in vocab:
        vkey = phonetic_key(str(term))
        if not vkey:
            continue
        denom = max(len(tkey), len(vkey))
        score = _edit_distance(tkey, vkey) / denom if denom else 1.0
        if score < best_score:
            best, best_score = term, score
    if best is not None and best_score <= max_distance:
        return str(best)
    return token


def correct_text(text, vocab, *, max_distance: float = 0.34, known=None) -> str:
    """Apply :func:`correct_word` token-wise, preserving separators. Pure."""
    if not text or not vocab:
        return text
    return re.sub(
        r"[A-Za-z]+",
        lambda m: correct_word(m.group(0), vocab, max_distance=max_distance, known=known),
        text,
    )
