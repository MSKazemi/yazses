"""Token labeling + structural-reference resolution + edit planning (pure) — ADR-v2-115.

Assign phonetic labels to tokens, resolve "alpha to charlie" spans, and plan structural edits. Pure
over an already-extracted token list; the editor bridge applies the ops.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_NATO = [
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india",
    "juliet", "kilo", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo",
    "sierra", "tango", "uniform", "victor", "whiskey", "xray", "yankee", "zulu",
]
_VERBS = {
    "select": "select", "take": "select", "delete": "delete", "cut": "delete",
    "remove": "delete", "wrap": "wrap", "swap": "swap",
}


@dataclass(frozen=True)
class TokenRef:
    index: int
    text: str


@dataclass(frozen=True)
class Selection:
    start: int
    end: int


def assign_labels(tokens):
    """Assign deterministic NATO labels to the first 26 tokens → ``{label: TokenRef}``. Pure."""
    return {_NATO[i]: TokenRef(i, t) for i, t in enumerate(tokens or ()) if i < len(_NATO)}


def resolve_reference(utterance: str, labels):
    """Resolve a spoken reference to a token :class:`Selection`, or ``None``. Pure.

    Two labels around "to" form an inclusive range; a single label is a one-token span.
    """
    words = re.findall(r"[a-z]+", (utterance or "").lower())
    hits = [w for w in words if w in labels]
    if not hits:
        return None
    if "to" in words and len(hits) >= 2:
        idxs = sorted(labels[w].index for w in hits)
        return Selection(idxs[0], idxs[-1])
    idx = labels[hits[0]].index
    return Selection(idx, idx)


def plan_structural_edit(verb: str, selection):
    """Plan a structural edit over ``selection`` → a list of ``{op, start, end}`` ops. Pure."""
    if selection is None or not verb:
        return []
    op = _VERBS.get(verb.lower().split()[0])
    if op is None:
        return []
    return [{"op": op, "start": selection.start, "end": selection.end}]
