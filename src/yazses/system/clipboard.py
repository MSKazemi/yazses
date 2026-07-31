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
