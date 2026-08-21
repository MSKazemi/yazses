"""Standard streams that may not exist.

``sys.stdout`` / ``sys.stderr`` / ``sys.stdin`` are not guaranteed to be file
objects. In a PyInstaller **windowed** (GUI-subsystem) build there is no console
attached, so PyInstaller sets all three to ``None`` — and every
``sys.stdout.isatty()`` in the codebase becomes an ``AttributeError``. That is
not hypothetical: on Windows it crashed ``yazses doctor`` into a "Unhandled
exception in script" dialog box, because the windowed ``YazSes.exe`` shadowed
the console shim on ``PATH`` (see ``packaging/windows/yazses.cmd``).

A missing stream is a *degraded* condition, never a fatal one: a diagnostic
command that cannot colour its output should still run, and one that cannot
print at all should still exit with a meaningful status code. These helpers
answer "is this stream usable?" without ever raising.
"""

from __future__ import annotations

import sys
from typing import TextIO

__all__ = ["stdout", "stdin", "is_a_tty", "stdout_isatty", "stdin_isatty", "write_out"]


def stdout() -> TextIO | None:
    """``sys.stdout`` if it is usable, else ``None``."""
    return getattr(sys, "stdout", None)


def stdin() -> TextIO | None:
    """``sys.stdin`` if it is usable, else ``None``."""
    return getattr(sys, "stdin", None)


def is_a_tty(stream: TextIO | None) -> bool:
    """``stream.isatty()``, treating a missing or broken stream as "not a tty".

    A detached stream is the *least* interactive thing there is, so ``False`` is
    the honest answer as well as the safe one.
    """
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except Exception:  # noqa: BLE001 — a closed//detached stream is just "not a tty"
        return False


def stdout_isatty() -> bool:
    return is_a_tty(stdout())


def stdin_isatty() -> bool:
    return is_a_tty(stdin())


def write_out(text: str) -> bool:
    """Write ``text`` to stdout verbatim. Returns False if there was nowhere to
    write it.

    Used where ``typer.echo`` is wrong because the output must be byte-exact
    (no added newline) — e.g. ``yazses vocab export``, whose round-trip is
    tested.
    """
    out = stdout()
    if out is None:
        return False
    try:
        out.write(text)
        out.flush()
        return True
    except Exception:  # noqa: BLE001 — a broken pipe must not become a traceback
        return False
