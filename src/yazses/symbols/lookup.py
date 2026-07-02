"""Spoken symbol/emoji → Unicode (pure) — ADR-v2-055.

Replace spoken symbol/emoji names with their Unicode character from a curated table, longest
phrase first, word-boundary protected. Pure and deterministic; no dependency.
"""
from __future__ import annotations

import re

# Curated spoken-name → character table. Multi-word names are matched before their prefixes.
_SYMBOLS = {
    "shrug emoji": "🤷",
    "thumbs up emoji": "👍",
    "thumbs down emoji": "👎",
    "thumbs up": "👍",
    "thumbs down": "👎",
    "laughing emoji": "😂",
    "crying emoji": "😢",
    "smile emoji": "🙂",
    "heart emoji": "❤️",
    "fire emoji": "🔥",
    "rocket emoji": "🚀",
    "star emoji": "⭐",
    "check mark": "✓",
    "checkmark": "✓",
    "cross mark": "✗",
    "x mark": "✗",
    "warning sign": "⚠️",
    "right arrow": "→",
    "left arrow": "←",
    "up arrow": "↑",
    "down arrow": "↓",
    "degree sign": "°",
    "bullet point": "•",
    "bullet": "•",
    "ellipsis": "…",
    "em dash": "—",
    "en dash": "–",
    "copyright sign": "©",
    "registered sign": "®",
    "trademark sign": "™",
    "euro sign": "€",
    "pound sign": "£",
    "yen sign": "¥",
    "section sign": "§",
    "plus minus sign": "±",
    "times sign": "×",
    "divide sign": "÷",
    "not equal sign": "≠",
    "less than or equal": "≤",
    "greater than or equal": "≥",
    "infinity sign": "∞",
    "arrow right": "→",
    "arrow left": "←",
}

# Longest phrase first so "thumbs up emoji" wins over "thumbs up".
_PHRASES = sorted(_SYMBOLS, key=len, reverse=True)
_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _PHRASES) + r")\b", re.IGNORECASE
)


def apply_symbols(text: str) -> str:
    """Replace spoken symbol/emoji names in ``text`` with their character. Pure."""
    if not text:
        return text
    return _PATTERN.sub(lambda m: _SYMBOLS[m.group(1).lower()], text)
