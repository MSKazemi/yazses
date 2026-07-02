"""Case / identifier transforms (pure) — ADR-v2-087.

Tokenize text (splitting camelCase) and render it in any case convention; detect the spoken style
command. Pure and deterministic; the clipboard read/paste lives elsewhere.
"""
from __future__ import annotations

import re

_STYLES = {
    "snake case": "snake", "snake": "snake",
    "kebab case": "kebab", "kebab": "kebab", "dash case": "kebab",
    "camel case": "camel", "camelcase": "camel",
    "pascal case": "pascal", "pascalcase": "pascal",
    "title case": "title", "sentence case": "sentence",
    "upper case": "upper", "uppercase": "upper", "all caps": "upper", "shout": "upper",
    "lower case": "lower", "lowercase": "lower",
    "constant case": "constant", "screaming snake": "constant", "constant": "constant",
}


def _tokens(text: str):
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text or "")
    return re.findall(r"[A-Za-z0-9]+", spaced)


def transform_case(text: str, style: str) -> str:
    """Render ``text`` in the given case ``style``. Pure."""
    if style == "upper":
        return (text or "").upper()
    if style == "lower":
        return (text or "").lower()
    words = _tokens(text)
    if not words:
        return text or ""
    if style == "title":
        return " ".join(w.capitalize() for w in words)
    if style == "sentence":
        joined = " ".join(w.lower() for w in words)
        return joined[:1].upper() + joined[1:]
    if style == "snake":
        return "_".join(w.lower() for w in words)
    if style == "kebab":
        return "-".join(w.lower() for w in words)
    if style == "constant":
        return "_".join(w.upper() for w in words)
    if style == "camel":
        return words[0].lower() + "".join(w.capitalize() for w in words[1:])
    if style == "pascal":
        return "".join(w.capitalize() for w in words)
    return text or ""


def detect_style_command(text: str):
    """Parse a spoken style command into a style name, or ``None``. Pure."""
    t = (text or "").lower()
    m = re.search(r"(?:make (?:this|it)|convert to|change to|transform to|turn into)\s+(.+)$", t)
    target = m.group(1) if m else t
    for phrase in sorted(_STYLES, key=len, reverse=True):
        if phrase in target:
            return _STYLES[phrase]
    return None
