"""Give a windowed Windows binary a console to print to.

A GUI-subsystem executable starts with no console, so PyInstaller sets
``sys.stdout``/``stderr``/``stdin`` to ``None``. Every CLI command run through
such a binary then either prints into the void or dies on ``AttributeError``.

The bundle avoids this by shipping a separate console binary
(``yazses-cli.exe``) and pointing the ``yazses`` shim at it. This module is the
second line of defence for when something reaches the windowed binary anyway —
a stale install, a hand-made shortcut, ``YazSesApp.exe doctor``:

1. ``AttachConsole(ATTACH_PARENT_PROCESS)`` — when the process was launched from
   an existing terminal, this borrows that terminal and output really appears.
2. Failing that, bind the streams to ``os.devnull`` so writes are discarded
   instead of raising.

Both steps are best-effort and never raise: this runs before argument parsing,
so a failure here must not become the error the user sees.
"""

from __future__ import annotations

import os
import sys

# Win32 constant: attach to the console of the parent process, if it has one.
_ATTACH_PARENT_PROCESS = -1


def _attach_parent_console() -> bool:
    """Borrow the launching terminal's console. False if there wasn't one."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.kernel32.AttachConsole(_ATTACH_PARENT_PROCESS))
    except Exception:  # noqa: BLE001 — no console is a normal outcome, not an error
        return False


def _rebind(name: str, target: str, mode: str) -> None:
    """Point ``sys.<name>`` at ``target``, leaving it as-is if that fails."""
    try:
        stream = open(target, mode, buffering=1, encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return
    setattr(sys, name, stream)


#: MB_OK | MB_ICONERROR | MB_SETFOREGROUND — the box must come to the front, because
#: it is often the only thing the user will see.
_MB_FLAGS = 0x0 | 0x10 | 0x10000


def alert(message: str, title: str) -> bool:
    """Show a native Windows message box. Returns whether one appeared.

    The last resort for a windowed binary that has something the user must read.
    ``ensure_streams`` will happily bind ``stderr`` to ``os.devnull`` when there is
    no console to borrow — which is correct (writes must not raise) and invisible,
    so a carefully written explanation is discarded in exactly the situation that
    produced it.

    ``user32`` is always present on Windows and this needs no dependency, which
    matters because the usual reason for calling it is that a GUI toolkit is
    missing. Never raises: a failure here would replace the message with nothing.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, str(message), str(title), _MB_FLAGS)
        return True
    except Exception:  # noqa: BLE001 — a missing box must not mask the real fault
        return False


def ensure_streams() -> bool:
    """Make ``sys.stdout``/``stderr``/``stdin`` safe to use. Idempotent.

    Returns True if the streams are attached to a real console (output will be
    visible), False if they were merely made non-``None``.
    """
    missing = [n for n in ("stdout", "stderr", "stdin") if getattr(sys, n, None) is None]
    if not missing:
        return True

    attached = _attach_parent_console()
    for name in missing:
        if name == "stdin":
            _rebind(name, "CONIN$" if attached else os.devnull, "r")
        else:
            _rebind(name, "CONOUT$" if attached else os.devnull, "w")

    # A rebind can still fail; guarantee the invariant callers rely on.
    for name in missing:
        if getattr(sys, name, None) is None:
            _rebind(name, os.devnull, "r" if name == "stdin" else "w")

    return attached
