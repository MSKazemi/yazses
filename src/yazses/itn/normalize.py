"""Entity inverse text normalization (pure) — ADR-v2-045.

A conservative, false-positive-averse rule set (stdlib ``re`` only) covering the two
highest-value, lowest-ambiguity entities: email addresses and version numbers. Higher-ambiguity
entities (URLs, dates, currency) are deferred to the neural ITN tier.
"""
from __future__ import annotations

import re

# Number words → value, enough to normalize spoken version components.
_NUM = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

# An email: local-part "at" dotted-domain. The domain MUST contain a spoken "dot" so a plain
# "at" in ordinary speech ("meet at noon") never matches.
_EMAIL_RE = re.compile(
    r"\b(\w+(?:\s+dot\s+\w+)*)\s+at\s+(\w+(?:\s+dot\s+\w+)+)\b",
    re.IGNORECASE,
)
# A version: the leading word "version" anchors it, avoiding false positives on bare numbers.
_VERSION_RE = re.compile(r"\bversion\s+(\w+(?:\s+point\s+\w+)*)\b", re.IGNORECASE)
_DOT_RE = re.compile(r"\s+dot\s+", re.IGNORECASE)
_POINT_RE = re.compile(r"\s+point\s+", re.IGNORECASE)


def _num_token(tok: str):
    """A single number token (digits or a number word) → digit string, or None. Pure."""
    t = tok.lower()
    if t.isdigit():
        return t
    if t in _NUM:
        return str(_NUM[t])
    return None


def _emails(text: str) -> str:
    def repl(m: re.Match) -> str:
        local = _DOT_RE.sub(".", m.group(1)).lower()
        domain = _DOT_RE.sub(".", m.group(2)).lower()
        return f"{local}@{domain}"

    return _EMAIL_RE.sub(repl, text)


def _versions(text: str) -> str:
    def repl(m: re.Match) -> str:
        parts = _POINT_RE.split(m.group(1))
        nums = [_num_token(p) for p in parts]
        if not nums or any(n is None for n in nums):
            return m.group(0)  # not a version number — leave "version control" etc. untouched
        return "v" + ".".join(nums)

    return _VERSION_RE.sub(repl, text)


def normalize_entities(text: str) -> str:
    """Normalize spoken emails and version numbers into written form. Pure.

    Conservative by design: emails need an "at" with a dotted domain; versions need the leading
    word "version". Non-matching text is returned unchanged.
    """
    if not text:
        return text
    return _versions(_emails(text))
