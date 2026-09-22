"""Minimal section-aware TOML editor — set one key, preserving comments.

Used by config-writing CLI commands (`yazses hotkey set`, …). It scopes the edit
to the target ``[section]`` so a generic key name like ``key`` is only changed in
the right place. Not a full TOML writer — just enough to flip a single setting
without disturbing the rest of the file or its comments.
"""
from __future__ import annotations

import os
import re
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from yazses.system.single_instance import SingleInstanceLock

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


def _set_config_key_unlocked(path, section: str, key: str, value, *, quote: bool | None = None) -> str:
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



@dataclass(frozen=True)
class ConfigChange:
    """One key mutation for the atomic multi-key writer."""

    section: str
    key: str
    value: object
    quote: bool | None = None


class ConfigEditBusyError(RuntimeError):
    """Another process is currently writing the same config file."""


def _config_lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def _lock_config(path: Path) -> SingleInstanceLock:
    """Acquire the repository's cross-platform OS lock for a config file."""

    lock = SingleInstanceLock(_config_lock_path(path))
    if not lock.acquire():
        raise ConfigEditBusyError(
            f"Config is being changed by another YazSes process: {path}"
        )
    return lock


def set_config_key(path, section: str, key: str, value, *, quote: bool | None = None) -> str:
    """Set one config key while excluding concurrent YazSes config writers."""

    p = Path(path)
    lock = _lock_config(p)
    try:
        return _set_config_key_unlocked(p, section, key, value, quote=quote)
    finally:
        lock.release()


def _fsync_parent(path: Path) -> None:
    """Best-effort directory fsync after atomic replace where supported."""

    flags = getattr(os, "O_DIRECTORY", 0)
    if not flags:
        return
    try:
        fd = os.open(str(path), os.O_RDONLY | flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def set_config_keys_atomic(
    path,
    changes: Iterable[ConfigChange],
) -> tuple[str, ...]:
    """Apply several comment-preserving TOML edits as one visible transaction.

    All edits happen on a same-directory temporary file while the target config lock is
    held. The candidate is parsed before commit, flushed to disk, then installed with
    an atomic replace. Any failure before the replace leaves the original byte-for-byte
    untouched.

    This function does not download models, install dependencies, or restart the daemon.
    Those preflight/application steps belong to the higher orchestration layer; this
    function owns only the durable config commit.
    """

    planned = tuple(changes)
    if not planned:
        return ()

    p = Path(path)
    lock = _lock_config(p)
    temp_path: Path | None = None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        mode = None
        original = b""
        if existed:
            original = p.read_bytes()
            try:
                mode = p.stat().st_mode & 0o777
            except OSError:
                mode = None

        fd, name = tempfile.mkstemp(
            prefix=f".{p.name}.",
            suffix=".tmp",
            dir=str(p.parent),
        )
        os.close(fd)
        temp_path = Path(name)

        if existed:
            temp_path.write_bytes(original)
        else:
            # The single-key editor distinguishes a missing file from an empty existing
            # one so the first section starts at byte 0 rather than after a blank line.
            temp_path.unlink()

        descriptions: list[str] = []
        for change in planned:
            descriptions.append(
                _set_config_key_unlocked(
                    temp_path,
                    change.section,
                    change.key,
                    change.value,
                    quote=change.quote,
                )
            )

        # Parse the complete candidate before the target path becomes visible.
        tomllib.loads(temp_path.read_text(encoding="utf-8-sig"))

        if mode is not None:
            os.chmod(temp_path, mode)

        with temp_path.open("r+b") as fh:
            fh.flush()
            os.fsync(fh.fileno())

        os.replace(temp_path, p)
        temp_path = None
        _fsync_parent(p.parent)
        return tuple(descriptions)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        lock.release()
