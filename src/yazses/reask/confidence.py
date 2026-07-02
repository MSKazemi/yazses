"""Low-confidence spans + confusion sets + choice parsing (pure) — ADR-v2-077.

Find uncertain token spans from faster-whisper log-probs, offer confusable alternatives, and parse
the user's spoken pick. Pure and deterministic; a learned confidence head lives elsewhere.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Homophone / confusable groups keyed by every member (normalized, apostrophes dropped).
_GROUPS = [
    ("their", "there", "they're"),
    ("to", "too", "two"),
    ("your", "you're"),
    ("its", "it's"),
    ("hear", "here"),
    ("no", "know"),
    ("write", "right", "rite"),
    ("weather", "whether"),
    ("accept", "except"),
    ("affect", "effect"),
    ("then", "than"),
    ("lose", "loose"),
]
_CONFUSIONS: dict = {}
for _grp in _GROUPS:
    for _w in _grp:
        _CONFUSIONS[_w.replace("'", "")] = list(_grp)

# Explicit ordinals win over bare number-words ("the second one" → 2, not 1).
_STRONG_ORDINALS = {"first": 0, "1": 0, "second": 1, "2": 1, "third": 2, "3": 2}
_WEAK_ORDINALS = {"one": 0, "two": 1, "three": 2}


@dataclass(frozen=True)
class Span:
    """A contiguous low-confidence token span: ``[start, end)`` with its joined ``text``."""
    start: int
    end: int
    text: str


def low_confidence_spans(tokens, logprobs, threshold: float = -1.0):
    """Group consecutive tokens whose log-prob is below ``threshold`` into spans. Pure."""
    spans = []
    i = 0
    n = min(len(tokens), len(logprobs))
    while i < n:
        if logprobs[i] < threshold:
            j = i
            while j < n and logprobs[j] < threshold:
                j += 1
            text = " ".join(str(t) for t in tokens[i:j]).strip()
            spans.append(Span(i, j, text))
            i = j
        else:
            i += 1
    return spans


def confusion_set(word: str):
    """Return the confusable alternatives for ``word`` (including itself), or ``[]``. Pure."""
    key = re.sub(r"[^a-z']", "", (word or "").lower()).replace("'", "")
    return list(_CONFUSIONS.get(key, []))


def parse_choice(text: str, options):
    """Resolve a spoken pick to one of ``options`` (ordinal or literal), or ``None``. Pure."""
    t = (text or "").lower().strip()
    for table in (_STRONG_ORDINALS, _WEAK_ORDINALS):
        for word, idx in table.items():
            if re.search(rf"\b{word}\b", t):
                return options[idx] if idx < len(options) else None
    for opt in options:
        if re.search(rf"\b{re.escape(opt.lower())}\b", t):
            return opt
    return None
