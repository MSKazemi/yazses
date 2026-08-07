"""Minimal section-aware TOML editor — set one key, preserving comments.

Used by config-writing CLI commands (`yazses hotkey set`, …). It scopes the edit
to the target ``[section]`` so a generic key name like ``key`` is only changed in
the right place. Not a full TOML writer — just enough to flip a single setting
without disturbing the rest of the file or its comments.
"""
from __future__ import annotations

import re
from pathlib import Path


def _render_toml_value(value) -> str:
    """Render *value* as a TOML scalar, inferred from its Python type."""
    if isinstance(value, bool):  # must precede the int check: bool is a subclass of int
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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
        rendered = f'"{value}"' if quote else str(value)
    line = f"{key} = {rendered}"

    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"[{section}]\n{line}\n")
        return f"created {p} with [{section}] {line}"

    text = p.read_text()
    header = re.search(rf"(?m)^\[{re.escape(section)}\]\s*$", text)
    if not header:
        sep = "" if (not text or text.endswith("\n")) else "\n"
        p.write_text(f"{text}{sep}\n[{section}]\n{line}\n")
        return f"added [{section}] {line}"

    # Bound the section: from the header to the next "[...]" line (or EOF).
    start = header.end()
    nxt = re.search(r"(?m)^\[", text[start:])
    end = start + nxt.start() if nxt else len(text)
    block = text[start:end]

    key_re = re.compile(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=.*$")
    if key_re.search(block):
        new_block = key_re.sub(line, block, count=1)
        p.write_text(text[:start] + new_block + text[end:])
        return f"updated [{section}] {line}"

    # Section exists but the key doesn't — insert right after the header.
    p.write_text(text[:header.end()] + "\n" + line + text[header.end():])
    return f"added {line} under [{section}]"
