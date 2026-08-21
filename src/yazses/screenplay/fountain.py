"""Spoken utterance → Fountain screenplay markup (pure) — ADR-v2-110.

Detect scene headings, character cues, transitions, and action lines, and smart-quote dialogue. Pure
regex/string transformation; no model.
"""
from __future__ import annotations

import re

# Every separator below is OPTIONAL, and that is the whole point of this module: it
# formats *dictated* lines, and a colon, a comma and a pair of parentheses are three
# things no speech model produces. Each documented form used to require one, so said
# aloud it matched nothing and the raw words were passed straight through -- silently,
# into a screenplay:
#
#   "scene: interior coffee shop, day"  ->  INT. COFFEE SHOP - DAY
#   "scene interior coffee shop day"    ->  scene interior coffee shop day
#
# The time-of-day group stays greedy while the location is lazy, so with the comma gone
# "coffee shop day" still splits into location "coffee shop" and time "day" rather than
# swallowing the time into the location.
_SCENE = re.compile(
    r"^\s*scene\s*[:\-]?\s*(interior|exterior|int|ext)\s+(.+?)"
    r"(?:\s*,?\s*(day|night|dawn|dusk|morning|evening|continuous))?\s*$", re.IGNORECASE)
_TRANS = re.compile(r"^\s*transition\s*[:\-]?\s*(.+?)\s*$", re.IGNORECASE)

#: Words that start an action line rather than a name. Bare "character" -- the spoken
#: form of "(character)" -- is an ordinary English word, so without the parentheses to
#: disambiguate, "the character walks in" would become a character cue for THE. Requiring
#: a short, non-determiner name keeps the dictated form working without turning prose
#: into cues. The parenthesised form is unambiguous and is not subject to either check.
_DETERMINERS = frozenset(
    "the a an this that these those his her their its my your our one".split()
)
#: A cue is a name, not a sentence. Three words covers "Mary Anne Smith".
_MAX_NAME_WORDS = 3

_CHAR_PAREN = re.compile(r"^\s*(.+?)\s*\(character\)\s*(.*)$", re.IGNORECASE)
_CHAR_SPOKEN = re.compile(r"^\s*(.+?)\s+character\s*(.*)$", re.IGNORECASE)


def smart_quote_dialogue(text: str) -> str:
    """Turn spoken quote/unquote and straight ``"…"`` into curly quotes. Pure."""
    s = text or ""
    s = re.sub(r'"([^"]*)"', "“\\1”", s)
    s = re.sub(r"\bquote\b\s*", "“", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\bunquote\b", "”", s, flags=re.IGNORECASE)
    return s


def to_fountain(utterance: str) -> str:
    """Format one dictated utterance as a Fountain element. Pure."""
    u = (utterance or "").strip()
    m = _SCENE.match(u)
    if m:
        io = "INT" if m.group(1).lower().startswith(("int", "interior")) else "EXT"
        loc = re.sub(r"\s+", " ", m.group(2).strip()).upper()
        tod = (m.group(3) or "day").upper()
        return f"{io}. {loc} - {tod}"
    m = _TRANS.match(u)
    if m:
        return m.group(1).strip().upper().rstrip(":") + ":"
    m = _CHAR_PAREN.match(u) or _spoken_character(u)
    if m:
        name = m.group(1).strip().upper()
        dialogue = smart_quote_dialogue(m.group(2).strip())
        return f"{name}\n{dialogue}" if dialogue else name
    return smart_quote_dialogue(u)


def _spoken_character(utterance: str):
    """The parenthesis-free character cue, or ``None``. Pure.

    Only accepted when what precedes "character" actually looks like a name: at most
    three words, and not opening with a determiner. Without that, every action line
    containing the ordinary word "character" would become a cue.
    """
    m = _CHAR_SPOKEN.match(utterance)
    if not m:
        return None
    words = m.group(1).split()
    if not words or len(words) > _MAX_NAME_WORDS:
        return None
    if words[0].lower() in _DETERMINERS:
        return None
    return m
