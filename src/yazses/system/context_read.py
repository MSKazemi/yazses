"""Best-effort, transient reads of desktop context for Context-Primed Dictation
(ADR-v2-004).

Every reader swallows all errors and returns ``""`` — this runs on the dictation
hot path and must NEVER break it. Reads are bounded by a short timeout and are used
transiently to bias the STT prompt; nothing read here is stored or logged.
"""
from __future__ import annotations

import shutil
import subprocess

from yazses.commands.context import ContextSources
from yazses.system.wayland_env import wayland_run_kwargs

_TIMEOUT_S = 0.5


def _run(cmd: list[str]) -> str:
    try:
        extra = wayland_run_kwargs() if cmd[0] == "wl-paste" else {}
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT_S, **extra)
        return (out.stdout or "").strip()
    except Exception:
        return ""


def active_window_title() -> str:
    """Active window title (X11 via xdotool). Wayland usually forbids this → ''."""
    if shutil.which("xdotool"):
        return _run(["xdotool", "getactivewindow", "getwindowname"])
    return ""


def selection_text() -> str:
    """Current primary selection (X11 xclip, else Wayland wl-paste -p)."""
    if shutil.which("xclip"):
        return _run(["xclip", "-o", "-selection", "primary"])
    if shutil.which("wl-paste"):
        return _run(["wl-paste", "-p", "-n"])
    return ""


def clipboard_text() -> str:
    """Clipboard contents (Wayland wl-paste, else X11 xclip)."""
    if shutil.which("wl-paste"):
        return _run(["wl-paste", "-n"])
    if shutil.which("xclip"):
        return _run(["xclip", "-o", "-selection", "clipboard"])
    return ""


def read_sources(
    use_window_title: bool = True,
    use_selection: bool = True,
    use_clipboard: bool = False,
) -> ContextSources:
    """Read only the enabled signals; disabled ones stay empty. Never raises."""
    return ContextSources(
        window_title=active_window_title() if use_window_title else "",
        selection=selection_text() if use_selection else "",
        clipboard=clipboard_text() if use_clipboard else "",
    )
