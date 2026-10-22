"""Spoken-code grammar (pure) — ADR-v2-031.

Two composable transforms: spoken symbol phrases → punctuation (`spoken_symbols`), and a
spoken style phrase plus words → one cased identifier (`spoken_identifiers`, built on
`to_case`). Pure and deterministic; activated only in code mode so the symbol words don't
collide with ordinary dictation. The code-mode caller runs them in that order — symbols
first — so a symbol word always ends an identifier (see `spoken_identifiers`).
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


#: Spoken style word(s) -> the `to_case` style it names. Every style `to_case` knows is
#: speakable, and nothing here names a style it does not --
#: `tests/test_code_spoken_identifiers.py` holds both directions. "title case" and
#: "upper case" are deliberately absent: they are not identifier conventions, and
#: `yazses case` / Voice Case Transform own them.
_CASE_STYLE_WORDS: dict[str, str] = {
    "camel": "camel",
    "pascal": "pascal",
    "snake": "snake",
    "kebab": "kebab",
    "constant": "constant",
    "screaming": "constant",
    "screaming snake": "constant",
}

# "<style> case", tolerant only of the spellings Whisper actually writes for it:
# "camel case", "camelCase", "camel-case", "snake_case". Word-bounded on both sides, so
# "showcase", "uppercase" and "camels case" never match. Longest style first so
# "screaming snake case" is one keyword, not "screaming" + a "snake case" run.
_CASE_KEYWORD = re.compile(
    r"\b(?P<style>"
    + "|".join(k.replace(" ", r"\s+")
               for k in sorted(_CASE_STYLE_WORDS, key=len, reverse=True))
    + r")(?:\s+|[-_])?case\b",
    re.IGNORECASE,
)

# One identifier word: letters/digits only, preceded by whitespace. Anything else -- a
# symbol `spoken_symbols` produced, or punctuation Whisper inserted -- is not a word, so
# it ends the run.
_CASE_WORD = re.compile(r"\s+([^\W_]+)")

# The explicit terminator, consumed with the run so it is never typed.
_END_CASE = re.compile(r"\s+end\s+case\b", re.IGNORECASE)


def _identifier_words(text: str, pos: int) -> tuple[list[str], int]:
    """The words of one identifier run starting at ``pos``, and where the run ends.

    The run ends at the first of: the spoken terminator "end case" (consumed), the next
    "<style> case" keyword (left for the caller to start a new run), any character that is
    not whitespace-separated letters/digits (a symbol or punctuation), or the end of text.
    """
    words: list[str] = []
    while True:
        stop = _END_CASE.match(text, pos)
        if stop is not None:
            return words, (stop.end() if words else pos)
        word = _CASE_WORD.match(text, pos)
        if word is None or _CASE_KEYWORD.match(text, word.start(1)) is not None:
            return words, pos
        words.append(word.group(1))
        pos = word.end()


def spoken_identifiers(text: str) -> str:
    """Turn "<style> case <words>" into one cased identifier. Pure.

    ``"camel case user name"`` -> ``userName``; ``"snake case max retries"`` ->
    ``max_retries``; ``"pascal case http server"`` -> ``HttpServer``;
    ``"kebab case main menu"`` -> ``main-menu``; ``"constant case max size"`` and
    ``"screaming snake case max size"`` -> ``MAX_SIZE``.

    The signal is the two-word keyword "<style> case" (Whisper may also write it
    ``camelCase``, ``camel-case`` or ``snake_case``) immediately followed by at least one
    word that starts with a letter. The words that follow are the identifier, and the run
    ends at the **first** of:

    * the spoken terminator **"end case"**, which is consumed -- "camel case user name
      end case if ready" -> ``userName if ready``;
    * another "<style> case" keyword, which starts the next identifier;
    * any symbol or punctuation -- in code mode `spoken_symbols` runs first, so "equals",
      "comma", "open paren", "dot" end the identifier ("camel case user name equals none"
      -> ``userName = none``) and a symbol word can never be part of one;
    * the end of the text.

    Anything else is left exactly as it was: a keyword with no word after it ("I prefer
    camel case"), followed by punctuation ("camel case, please"), by a number ("snake
    case 2 factor"), or by "end case" alone. Words are lower-cased before casing, as
    `to_case` always does, so "pascal case HTTP server" is ``HttpServer``.

    This is a code-mode grammar: the only caller is the ``code ...`` handler in
    `spokencmd/registry.py`, which itself only runs while the command key is held. It is
    not safe on ordinary dictation and is not applied there.
    """
    src = text or ""
    out: list[str] = []
    pos = 0
    while True:
        hit = _CASE_KEYWORD.search(src, pos)
        if hit is None:
            break
        words, end = _identifier_words(src, hit.end())
        if not words or not words[0][0].isalpha():
            # Not an identifier run: keep the keyword as spoken and scan on past it.
            out.append(src[pos:hit.end()])
            pos = hit.end()
            continue
        style = _CASE_STYLE_WORDS[" ".join(hit.group("style").lower().split())]
        out.append(src[pos:hit.start()])
        out.append(to_case(words, style))
        pos = end
    out.append(src[pos:])
    return "".join(out)
