"""Spoken-code grammar (pure) — ADR-v2-031.

Two composable transforms: spoken symbol phrases → punctuation, and word-groups → cased
identifiers. Pure and deterministic; activated only in code mode so the symbol words don't
collide with ordinary dictation.
"""
from __future__ import annotations

import re
from collections.abc import Callable


def _literal(value: str) -> Callable[[re.Match[str]], str]:
    """A ``re.sub`` replacement that emits ``value`` verbatim.

    Binding the value in a factory rather than a lambda default argument keeps the
    per-iteration capture correct *and* stays inferable — ``lambda _m, s=sym: s``
    was neither typed nor obvious about why the default was there.
    """
    return lambda _m: value


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

# The authored list above is grouped by meaning, which is how it stays readable -- and is
# exactly why it cannot also be the substitution order. `arrow` was written above
# `fat arrow`, so `\barrow\b` matched first and "fat arrow" became "fat ->" instead of "=>".
#
# Ordering is therefore DERIVED, not maintained by hand: a word-bounded phrase can only be
# shadowed by a longer one, so longest-first is correct by construction and a phrase added
# in the wrong place cannot reintroduce the bug.
_ORDERED: list[tuple[str, str]] = sorted(_SYMBOLS, key=lambda kv: -len(kv[0]))

_STYLES = ("camel", "snake", "pascal", "constant", "kebab")


def spoken_symbols(text: str) -> str:
    """Replace spoken symbol phrases with their punctuation (longest-match, word bounded).

    Pure. Case-insensitive on the phrase; surrounding text is otherwise preserved.
    """
    out = text or ""
    for phrase, sym in _ORDERED:
        # function replacement so literal backslashes/symbols aren't re-interpreted
        out = re.sub(rf"\b{re.escape(phrase)}\b", _literal(sym), out, flags=re.IGNORECASE)
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
