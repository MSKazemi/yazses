"""Minimal section-aware TOML editor — set one key, preserving comments.

Used by config-writing CLI commands (`yazses hotkey set`, …). It scopes the edit
to the target ``[section]`` so a generic key name like ``key`` is only changed in
the right place. Not a full TOML writer — just enough to flip a single setting
without disturbing the rest of the file or its comments.
"""
from __future__ import annotations

import re
from pathlib import Path

#: The escapes a TOML basic string requires. Anything else below U+0020 has no literal
#: form at all and must go out as \uXXXX.
_TOML_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def quote_toml_string(text: str) -> str:
    """Render *text* as a TOML basic string, escaped so the file still parses.

    The single place a value becomes TOML. There used to be two: this rendering escaped
    backslashes and quotes, while the explicit ``quote=True`` branch of `set_config_key`
    interpolated the value raw -- and that is the branch `yazses audio use` and the
    settings window take. So a microphone named ``My "Best" Mic`` wrote

        device = "My "Best" Mic"

    which does not parse. An unparseable config.toml is not a small failure here:
    `configcheck` falls back to "could not be read; using defaults throughout", so
    **every** setting the user had is silently reset by an unrelated one-word command.

    Neither renderer handled a newline, which is illegal inside a basic string and does
    the same thing. The settings window works around that by collapsing newlines in
    `[stt] initial_prompt` before calling here; that stays as defence in depth, but it
    is no longer the only thing standing between a pasted two-line prompt and a reset
    `[stt]` section.
    """
    out = []
    for ch in str(text):
        if ch in _TOML_ESCAPES:
            out.append(_TOML_ESCAPES[ch])
        elif ch < "\u0020" or ch == "\u007f":
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _render_toml_value(value) -> str:
    """Render *value* as a TOML scalar, inferred from its Python type."""
    if isinstance(value, bool):  # must precede the int check: bool is a subclass of int
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        # A TOML array, not `str(list)`. Without this a list value was rendered as the
        # quoted Python repr -- `filler_words = "['um', 'uh']"` -- which parses as a
        # STRING, so `configcheck` reports "should be a list" and falls back to the
        # default, discarding the change the user had just approved.
        return "[" + ", ".join(_render_toml_value(v) for v in value) + "]"
    return quote_toml_string(value)


def set_config_key(path, section: str, key: str, value, *, quote: bool | None = None) -> str:
    """Set ``[section] key = value`` in *path*, preserving comments and other keys.

    By default the TOML rendering is inferred from ``value``'s type (bool, int/float,
    or string). Pass ``quote`` to override: ``True`` always double-quotes the value,
    ``False`` renders it bare via ``str()``. Returns a short description of the change.
    """
    p = Path(path)
    if quote is None:
        rendered = _render_toml_value(value)
    else:
        rendered = quote_toml_string(value) if quote else str(value)
    line = f"{key} = {rendered}"

    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"[{section}]\n{line}\n", encoding="utf-8")
        return f"created {p} with [{section}] {line}"

    # utf-8-sig: a BOM written by an earlier editor is dropped rather than carried
    # into the rewritten file, where it would keep the whole config unparseable.
    text = p.read_text(encoding="utf-8-sig")
    header = re.search(rf"(?m)^\[{re.escape(section)}\]\s*$", text)
    if not header:
        sep = "" if (not text or text.endswith("\n")) else "\n"
        p.write_text(f"{text}{sep}\n[{section}]\n{line}\n", encoding="utf-8")
        return f"added [{section}] {line}"

    # Bound the section: from the header to the next "[...]" line (or EOF).
    start = header.end()
    nxt = re.search(r"(?m)^\[", text[start:])
    end = start + nxt.start() if nxt else len(text)
    block = text[start:end]

    key_re = re.compile(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=.*$")
    if key_re.search(block):
        new_block = key_re.sub(line, block, count=1)
        p.write_text(text[:start] + new_block + text[end:], encoding="utf-8")
        return f"updated [{section}] {line}"

    # Section exists but the key doesn't — insert right after the header.
    p.write_text(text[:header.end()] + "\n" + line + text[header.end():], encoding="utf-8")
    return f"added {line} under [{section}]"
