"""Delimiter balancing + wrap-selection (pure) — ADR-v2-088.

Append missing bracket/quote closers and wrap a selection in a named pair. Pure and deterministic.
"""
from __future__ import annotations

import re

_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = {")", "]", "}"}
_WRAP = {
    "parens": ("(", ")"), "parentheses": ("(", ")"), "round brackets": ("(", ")"),
    "brackets": ("[", "]"), "square brackets": ("[", "]"),
    "braces": ("{", "}"), "curly braces": ("{", "}"),
    "quotes": ('"', '"'), "double quotes": ('"', '"'), "single quotes": ("'", "'"),
    "backticks": ("`", "`"), "angle brackets": ("<", ">"),
}


_QUOTES = ('"', "'", "`")


def balance_delimiters(text: str) -> str:
    """Append the closers needed to balance brackets and quotes in ``text``. Pure.

    Quotes are tracked in the same stack as brackets so nested closers are emitted in the correct
    order (an open quote closes before the bracket that contains it). Text inside an open quote is
    treated literally (brackets there are not counted).
    """
    s = text or ""
    stack = []          # expected closer chars, innermost last
    open_quote = None
    for ch in s:
        if open_quote is not None:
            if ch == open_quote:
                open_quote = None
                stack.pop()
            continue
        if ch in _QUOTES:
            open_quote = ch
            stack.append(ch)
        elif ch in _OPEN:
            stack.append(_OPEN[ch])
        elif ch in _CLOSE and stack and stack[-1] == ch:
            stack.pop()
    return s + "".join(reversed(stack))


def wrap(selection: str, pair: str):
    """Wrap ``selection`` in a named ``pair`` (parens/brackets/quotes/…), or ``None``. Pure."""
    p = _WRAP.get((pair or "").lower().strip())
    if p is None:
        return None
    return f"{p[0]}{selection}{p[1]}"


def detect_wrap_command(text: str):
    """Parse "wrap this in <pair>" → the pair name, or ``None``. Pure."""
    m = re.search(r"\bwrap\s+(?:this|it|the\s+selection|that)?\s*(?:in|with)\s+(.+)$",
                  (text or "").lower())
    if not m:
        return None
    target = m.group(1).strip()
    for phrase in sorted(_WRAP, key=len, reverse=True):
        if phrase in target:
            return phrase
    return None
