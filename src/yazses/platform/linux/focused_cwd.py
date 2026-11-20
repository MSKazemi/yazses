"""The focused window's working directory on Linux (``[context] use_git``).

`Platform.focused_cwd_factory` on an X11 session. Two steps, both best-effort:

1. **Which process.** ``xdotool getactivewindow getwindowpid`` -- the window's
   ``_NET_WM_PID``. X11 only: a native Wayland session names no focused process to a
   client, and xdotool there sees only XWayland windows, so the bundle sets no factory
   on Wayland at all (`platform/linux/__init__.py`).
2. **Which directory.** ``/proc/<pid>/cwd``. A terminal emulator's own directory is
   rarely the one being typed in -- the shell (or the coding agent the shell started) is
   its child -- so the youngest descendant chain is followed and the deepest process's
   directory is the answer. That is a heuristic: a terminal serving several windows
   from one process (``gnome-terminal-server``) answers for its most recently started
   shell, which need not be the focused tab. A wrong guess costs one decode a few
   irrelevant prompt words, never an action.

Nothing here is stored or logged: the directory is returned to the caller and dropped.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_TIMEOUT_S = 0.5
#: How many generations below the window's process to follow. A terminal → shell →
#: agent → tool chain is four; the bound keeps a fork bomb from becoming a walk.
_MAX_DEPTH = 8
_PROC = Path("/proc")


def xdotool_focused_pid() -> int | None:
    """The focused X11 window's ``_NET_WM_PID`` via xdotool, or None. Never raises."""
    if not shutil.which("xdotool"):
        return None
    try:
        out = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowpid"],
            capture_output=True, text=True, timeout=_TIMEOUT_S,
        )
    except Exception:
        return None
    text = (out.stdout or "").strip()
    return int(text) if out.returncode == 0 and text.isdigit() and int(text) > 0 else None


def process_cwd(pid: int, proc_root: Path = _PROC) -> Path | None:
    """``/proc/<pid>/cwd`` resolved, or None (gone, not ours, deleted). Never raises."""
    try:
        target = os.readlink(proc_root / str(pid) / "cwd")
    except OSError:
        return None
    path = Path(target)
    # The kernel appends " (deleted)" to a removed directory; it is no longer a place.
    if not path.is_absolute() or target.endswith(" (deleted)") or not path.is_dir():
        return None
    return path


def _children(pid: int, proc_root: Path) -> list[int]:
    try:
        text = (proc_root / str(pid) / "task" / str(pid) / "children").read_text()
    except OSError:
        return []
    return [int(tok) for tok in text.split() if tok.isdigit()]


def _start_time(pid: int, proc_root: Path) -> int:
    """Field 22 of ``/proc/<pid>/stat`` (start time in clock ticks), or -1."""
    try:
        stat = (proc_root / str(pid) / "stat").read_text()
    except OSError:
        return -1
    # The command name (field 2) is parenthesised and may contain spaces or ")", so
    # split after the LAST ")"; what follows starts at field 3.
    rest = stat.rpartition(")")[2].split()
    try:
        return int(rest[19])
    except (IndexError, ValueError):
        return -1


def youngest_descendant(pid: int, proc_root: Path = _PROC, max_depth: int = _MAX_DEPTH) -> int:
    """Follow the most recently started child from *pid* down; the deepest pid reached."""
    current = pid
    for _ in range(max_depth):
        kids = _children(current, proc_root)
        if not kids:
            break
        current = max(kids, key=lambda k: (_start_time(k, proc_root), k))
    return current


def focused_cwd(
    pid: int | None,
    proc_root: Path = _PROC,
) -> Path | None:
    """The working directory for the focused window's process *pid*. Never raises.

    The deepest youngest descendant's directory, else the window process's own.
    """
    if pid is None:
        return None
    try:
        leaf = youngest_descendant(pid, proc_root)
        if leaf != pid:
            found = process_cwd(leaf, proc_root)
            if found is not None:
                return found
        return process_cwd(pid, proc_root)
    except Exception:
        return None


class LinuxFocusedCwd:
    """`FocusedCwdProvider` for an X11 session: xdotool's PID, then ``/proc``."""

    def __init__(self, pid_source=xdotool_focused_pid, proc_root: Path = _PROC) -> None:
        self._pid_source = pid_source
        self._proc_root = proc_root

    def cwd(self) -> Path | None:
        try:
            return focused_cwd(self._pid_source(), self._proc_root)
        except Exception:
            return None


__all__ = [
    "LinuxFocusedCwd",
    "focused_cwd",
    "process_cwd",
    "xdotool_focused_pid",
    "youngest_descendant",
]
