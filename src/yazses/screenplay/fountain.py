"""Spoken utterance → Fountain screenplay markup (pure) — ADR-v2-110.

Detect scene headings, character cues, transitions, and action lines, and smart-quote dialogue. Pure
regex/string transformation; no model.
"""
from __future__ import annotations

import re

_SCENE = re.compile(
    r"^\s*scene\s*[:\-]\s*(interior|exterior|int|ext)\s+(.+?)"
    r"(?:,\s*(day|night|dawn|dusk|morning|evening|continuous))?\s*$", re.IGNORECASE)
_CHAR = re.compile(r"^\s*(.+?)\s*\(character\)\s*(.*)$", re.IGNORECASE)
_TRANS = re.compile(r"^\s*transition\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)


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
    m = _CHAR.match(u)
    if m:
        name = m.group(1).strip().upper()
        dialogue = smart_quote_dialogue(m.group(2).strip())
        return f"{name}\n{dialogue}" if dialogue else name
    return smart_quote_dialogue(u)
