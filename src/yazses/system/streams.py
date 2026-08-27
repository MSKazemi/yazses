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

__all__ = [
    "stdout",
    "stdin",
    "is_a_tty",
    "stdout_isatty",
    "stdin_isatty",
    "write_out",
    "ensure_printable_streams",
]


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


# Characters the CLI prints in ordinary output: the arrow in nearly every "fix it
# like this" line, the warning sign, the rule that frames a panel, and the markers
# `yazses audio devices` uses for the default and pinned microphone. Counted in the
# tree, `\u2192` alone appears 437 times across 166 modules. None of them can be
# encoded by cp1252.
_PRINTS = "\u2192\u26a0\u2500\u25cf\u2605\u2713\u2014"


def ensure_printable_streams() -> None:
    """Make stdout/stderr able to carry the characters the CLI actually prints.

    Python encodes stdout with the *locale* encoding whenever it is not attached to a
    console -- a redirect, a pipe, a CI capture, `yazses report`. On Windows that is
    the ANSI code page, cp1252 here, and none of the characters above survive it, so

        yazses doctor > log.txt
        yazses features | findstr something

    died with `UnicodeEncodeError: 'charmap' codec can't encode characters`. Verified
    on a real Windows Server 2022 host: `doctor`, `features` and `quickstart` all exit
    1 that way -- which are exactly the three commands someone runs when something is
    already wrong, and then pastes into an issue. The same thing happens on a Linux
    container with no locale set, where the answer is ASCII.

    Even where the locale encoding *can* encode a character the result is wrong: an em
    dash leaves as the single byte 0x97, and a console on code page 437 draws that as
    `\u00f9`. Observed on the same host.

    Two deliberate choices:

    * It reconfigures only when the current encoding fails the probe, so a UTF-8
      machine -- every Linux and macOS install -- is left exactly as it was. Byte-exact
      output like `yazses vocab export` must not change under it.
    * `errors="replace"`, because the fallback matters as much as the encoding. A
      diagnostic command that meets one unmappable character should print `?` and keep
      going, never abort halfway through the report the user is trying to send.

    Never raises. A stream may be ``None`` (a PyInstaller windowed build), already
    detached, or not a reconfigurable text wrapper at all.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        encoding = getattr(stream, "encoding", None)
        if encoding:
            try:
                _PRINTS.encode(encoding)
            except (LookupError, UnicodeEncodeError):
                pass
            else:
                continue  # already able to carry them; leave it alone
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 -- a stream that cannot be reconfigured is
            pass          # no worse off than before this was attempted
