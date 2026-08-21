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


#: The verbs that introduce a spoken style command.
_LEAD_IN = r"(?:make (?:this|it)|convert to|change to|transform to|turn into)\s+"

#: A connective the speaker puts *before* a trailing directive: "hello world **in**
#: snake case". It belongs to the directive, not to the text being recased.
_TRAILING_CONNECTIVE = r"\s+(?:in|to|as|into)(?:\s+the)?\s*$"

#: Punctuation that may separate the directive from its payload when it was *typed*.
#: Optional by design -- none of it can be dictated, and this is a voice command.
_SEPARATOR = r"^[\s:,\-\u2013\u2014]+"


def split_style_command(text: str) -> tuple[str | None, str]:
    """Split a spoken style command into ``(style, payload)``. Pure.

    The caller used to strip the directive by splitting on ``":"``, which meant the
    documented spoken form *"make this snake case: hello world"* only worked when the
    colon was there -- and **a colon cannot be dictated**. Said aloud, the directive was
    recased along with the text:

        make this snake case hello world  ->  make_this_snake_case_hello_world

    and it did so silently, producing a plausible wrong answer rather than refusing,
    which is the failure mode `gitvoice` explicitly avoids.

    The style phrase is located instead, and everything after it is the payload. The
    payload is sliced from the **original** string, not the lower-cased copy used for
    matching, so `make this snake case MyThing` still sees `MyThing`.
    """
    raw = text or ""
    low = raw.lower()
    lead = re.search(_LEAD_IN, low)
    start_at = lead.end() if lead else 0

    # Longest phrase first: "snake case" must win over the bare "snake" it contains,
    # otherwise the payload keeps the stray word "case".
    for phrase in sorted(_STYLES, key=len, reverse=True):
        idx = low.find(phrase, start_at)
        if idx == -1:
            continue
        payload = re.sub(_SEPARATOR, "", raw[idx + len(phrase):])
        if not payload.strip():
            # "hello world in snake case" -- the directive trails the text it applies to.
            payload = raw[:lead.start() if lead else idx]
            # ...and takes its connective with it. Without this, "hello world in snake
            # case" recased the word "in" as part of the payload: `hello_world_in`.
            payload = re.sub(_TRAILING_CONNECTIVE, "", payload)
        return _STYLES[phrase], payload
    return None, raw


def detect_style_command(text: str):
    """Parse a spoken style command into a style name, or ``None``. Pure."""
    return split_style_command(text)[0]
