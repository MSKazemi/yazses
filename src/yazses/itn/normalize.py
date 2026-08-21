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


#: Top-level domains a person actually speaks. A spoken address ends in one of these;
#: "at the dot matrix printer" does not. Not exhaustive on purpose -- the cost of missing
#: a rare TLD is that the user types one address by hand, and the cost of being too
#: permissive is ordinary dictation silently rewritten into an email address.
_TLDS = frozenset("""
    com org net edu gov mil int io co ai app dev me info biz tv cc us uk de fr it es
    nl be ch at se no fi dk pl cz ru ua tr gr pt ie nz au ca jp cn kr in br mx ar za
    eu xyz online site tech cloud page blog wiki news email
""".split())

#: A domain never starts with one of these; a sentence very often does. "look at **the**
#: dot com boom" is prose, and its "domain" opens with an article.
_DOMAIN_STOPWORDS = frozenset(
    "the a an this that these those my your our their his her its and or but".split()
)


def _looks_like_a_domain(domain: str) -> bool:
    """Is this dotted phrase a spoken domain rather than ordinary English? Pure.

    The original rule was "the domain must contain a spoken dot", which its comment
    justified as stopping "meet at noon". It does -- and it does not stop the far commoner
    shape, an ordinary sentence containing "at <word> dot <word>":

        "look at the dot com boom"           -> "look@the.com boom"
        "point at the dot on the screen"     -> "point@the.on the screen"
        "meet me at the dot matrix printer"  -> "meet me@the.matrix printer"

    Eight of eight realistic sentences were rewritten. Two extra conditions, both of which
    every spoken address satisfies and ordinary prose rarely does: the last label must be
    a real TLD, and the first must not be an article.
    """
    labels = domain.split(".")
    if len(labels) < 2:
        return False
    if labels[-1] not in _TLDS:
        return False
    return labels[0] not in _DOMAIN_STOPWORDS


def _emails(text: str) -> str:
    def repl(m: re.Match) -> str:
        local = _DOT_RE.sub(".", m.group(1)).lower()
        domain = _DOT_RE.sub(".", m.group(2)).lower()
        if not _looks_like_a_domain(domain):
            # Leave the words exactly as spoken. A missed address costs one hand-typed
            # line; a false one silently corrupts a sentence the user dictated.
            return m.group(0)
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
