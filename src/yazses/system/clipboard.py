"""Set the system clipboard — used as the fallback when dictation has no text target.

When you dictate with no editable field focused, YazSes copies the transcript here instead
of typing it into the wrong place, so your words are never lost. Wayland → ``wl-copy``;
X11 → ``xclip`` then ``xsel``. Best-effort and injectable (never raises into the daemon).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Callable

log = logging.getLogger(__name__)


def _candidates() -> list[list[str]]:
    """Clipboard-set commands to try, in order, for the current session."""
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        return [["wl-copy", "--"]]
    cmds: list[list[str]] = []
    if shutil.which("xclip"):
        cmds.append(["xclip", "-selection", "clipboard"])
    if shutil.which("xsel"):
        cmds.append(["xsel", "--clipboard", "--input"])
    # Wayland with no wl-copy but xclip present (XWayland) still works.
    if not cmds and os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        cmds.append(["wl-copy", "--"])
    return cmds


def set_clipboard(
    text: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    candidates: list[list[str]] | None = None,
) -> bool:
    """Put ``text`` on the clipboard. Returns True on success; never raises.

    ``wl-copy`` takes the text as a trailing argument; ``xclip``/``xsel`` read it from
    stdin. Tries each available tool until one succeeds.
    """
    if not text:
        return False
    cmds = candidates if candidates is not None else _candidates()
    # xclip/wl-copy fork a background process to *serve* the selection that inherits our
    # stdout/stderr — without redirecting them, subprocess.run blocks waiting for that pipe
    # to close (which it never does), hanging the caller. DEVNULL makes run() return promptly.
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    for cmd in cmds:
        try:
            if cmd and cmd[0] == "wl-copy":
                runner([*cmd, text], check=True, timeout=5, **quiet)
            else:
                runner(cmd, input=text.encode(), check=True, timeout=5, **quiet)
            return True
        except Exception as exc:
            log.debug("clipboard set via %s failed: %s", cmd[0] if cmd else "?", exc)
    if not cmds:
        log.info("No clipboard tool found (install wl-clipboard or xclip).")
    return False


def _read_candidates(primary: bool) -> list[list[str]]:
    """Clipboard-READ commands to try, in order, for the current session.

    `primary` selects X11's PRIMARY selection — the "highlight to select" buffer —
    rather than CLIPBOARD. Command Mode wants PRIMARY first: a user who has just
    highlighted a sentence has not pressed ctrl+c, and asking them to would make a
    voice feature depend on a keystroke.
    """
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        return [["wl-paste", "--no-newline"] + (["--primary"] if primary else [])]
    cmds: list[list[str]] = []
    selection = "primary" if primary else "clipboard"
    if shutil.which("xclip"):
        cmds.append(["xclip", "-selection", selection, "-o"])
    if shutil.which("xsel"):
        cmds.append(["xsel", f"--{selection}", "--output"])
    return cmds


def get_clipboard(
    *,
    primary: bool = False,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    candidates: list[list[str]] | None = None,
) -> str:
    """Read the clipboard (or PRIMARY selection). Empty string on any failure.

    Never raises, for the same reason `set_clipboard` does not: this runs on the
    dictation path, and a missing clipboard tool must degrade to "no selection"
    rather than take the daemon down.
    """
    cmds = candidates if candidates is not None else _read_candidates(primary)
    for cmd in cmds:
        try:
            result = runner(cmd, capture_output=True, timeout=5, check=True)
        except Exception as exc:
            log.debug("clipboard read via %s failed: %s", cmd[0] if cmd else "?", exc)
            continue
        out = getattr(result, "stdout", b"") or b""
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        if out:
            return out
    return ""


def read_selection(
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str:
    """The text the user currently has selected, or "".

    PRIMARY first, then CLIPBOARD. Highlighting is the gesture people actually
    make before saying "make this shorter"; falling back to CLIPBOARD covers
    applications (and Wayland compositors) that do not serve PRIMARY.
    """
    return get_clipboard(primary=True, runner=runner) or get_clipboard(runner=runner)
