"""Mine + apply a self-learning correction table (pure) — ADR-v2-079.

Turn repeated (wrong→right) edit pairs into a high-precision substitution table and apply it,
longest-match and word-boundary-guarded. Pure and deterministic; the corpus supplies the events.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict


def mine_substitutions(events, min_support: int = 3) -> dict:
    """Build a ``{wrong: right}`` table from (wrong, right) edit pairs. Pure.

    Keeps a substitution only when its dominant correction reaches ``min_support`` and no rival
    correction ties it (so ambiguous edits are dropped).
    """
    counts: Counter = Counter()
    for pair in events or ():
        wrong, right = (pair[0] or "").strip(), (pair[1] or "").strip()
        if wrong and right and wrong != right:
            counts[(wrong, right)] += 1

    by_wrong = defaultdict(list)
    for (wrong, right), c in counts.items():
        by_wrong[wrong].append((right, c))

    table: dict = {}
    for wrong, rights in by_wrong.items():
        rights.sort(key=lambda rc: rc[1], reverse=True)
        top_right, top_count = rights[0]
        if top_count >= min_support and (len(rights) == 1 or top_count > rights[1][1]):
            table[wrong] = top_right
    return table


def apply_corrections(text: str, table: dict) -> str:
    """Apply a correction ``table`` to ``text``, longest key first, boundary-guarded. Pure."""
    if not table or not text:
        return text or ""
    out = text
    for key in sorted(table, key=len, reverse=True):
        repl = table[key]
        # \b only helps when the key edges are word chars; fall back to a plain replace otherwise.
        left = r"\b" if key[:1].isalnum() else ""
        right = r"\b" if key[-1:].isalnum() else ""
        out = re.sub(f"{left}{re.escape(key)}{right}", lambda _m, r=repl: r, out)
    return out
