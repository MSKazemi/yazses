"""Spoken-code grammar (pure) — ADR-v2-031.

Two composable transforms: spoken symbol phrases → punctuation, and word-groups → cased
identifiers. Pure and deterministic; activated only in code mode so the symbol words don't
collide with ordinary dictation.
"""
from __future__ import annotations

import re

# Spoken phrase → symbol. Longest phrases first so "open paren" beats "paren".
_SYMBOLS = [
    ("open paren", "("), ("close paren", ")"),
    ("open bracket", "["), ("close bracket", "]"),
    ("open brace", "{"), ("close brace", "}"),
    ("less than or equal", "<="), ("greater than or equal", ">="),
    ("double equals", "=="), ("not equals", "!="),
    ("less than", "<"), ("greater than", ">"),
    ("arrow", "->"), ("fat arrow", "=>"),
    ("semicolon", ";"), ("colon", ":"), ("comma", ","), ("dot", "."),
    ("underscore", "_"), ("equals", "="), ("plus", "+"), ("minus", "-"),
    ("star", "*"), ("slash", "/"), ("backslash", "\\"), ("percent", "%"),
    ("pipe", "|"), ("ampersand", "&"), ("caret", "^"), ("tilde", "~"),
    ("bang", "!"), ("question mark", "?"), ("at sign", "@"), ("hash", "#"),
    ("dollar", "$"), ("single quote", "'"), ("double quote", '"'), ("backtick", "`"),
]

_STYLES = ("camel", "snake", "pascal", "constant", "kebab")


def spoken_symbols(text: str) -> str:
    """Replace spoken symbol phrases with their punctuation (longest-match, word bounded).

    Pure. Case-insensitive on the phrase; surrounding text is otherwise preserved.
    """
    out = text or ""
    for phrase, sym in _SYMBOLS:
        # function replacement so literal backslashes/symbols aren't re-interpreted
        out = re.sub(rf"\b{re.escape(phrase)}\b", lambda _m, s=sym: s, out, flags=re.IGNORECASE)
    return out


def to_case(words, style: str) -> str:
    """Join ``words`` into an identifier in ``style``.

    Styles: ``camel`` (userId), ``pascal`` (UserId), ``snake`` (user_id),
    ``constant`` (USER_ID), ``kebab`` (user-id). Unknown style joins with spaces. Pure.
    """
    toks = [w for w in (str(w).strip().lower() for w in words) if w]
    if not toks:
        return ""
    if style == "snake":
        return "_".join(toks)
    if style == "constant":
        return "_".join(t.upper() for t in toks)
    if style == "kebab":
        return "-".join(toks)
    if style == "pascal":
        return "".join(t.capitalize() for t in toks)
    if style == "camel":
        return toks[0] + "".join(t.capitalize() for t in toks[1:])
    return " ".join(toks)
