"""Is there a desktop to put a window on?

Three components ask this: the Settings window (may I open?), the daemon (should I
spawn the voice-activity overlay?), and the daemon again (should I spawn the tray?).
All three used to answer it with the same two lines --

    bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))

-- which is not a test for "a desktop". It is a test for **X11 or Wayland**. Windows
and macOS set neither variable and never have, so on those two platforms all three
gates answered *headless* on every install that has ever existed: the tray's
"Settings…" opened nothing, and dictation ran with no overlay at all.

It survived because none of the three failures raises. `has_display` returning False
sends Settings into a diagnostic `print` on a windowed binary that has no console;
a suppressed overlay looks exactly like an overlay the user turned off. The product
kept transcribing correctly the whole time, which is why it read as "no feedback"
rather than as a defect.

**Why the platform has to be an argument rather than a lookup.** The evidence
available differs by platform, so the honest predicate does too:

* **Windows, macOS** -- an interactive process belongs to a desktop session by
  construction, and there is no environment variable that says so. The absence of
  one is not evidence of absence. (A true non-interactive context there -- a Windows
  service in session 0 -- is not distinguishable from the environment either, and the
  three callers all handle a failed launch already: the tray and overlay are spawned
  detached and their failure is logged, not fatal.)
* **Linux, the BSDs** -- `DISPLAY` / `WAYLAND_DISPLAY` really are the only evidence,
  and their absence really does mean an SSH session or a headless box.

Passing it in also lets every case above be tested from any machine, which is the
only reason the Windows behaviour is provable here at all.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping

__all__ = ["has_graphical_session"]

#: Platforms where a desktop session exists by construction and announces itself
#: with no variable. Matched by prefix: `sys.platform` is `win32` or `cygwin`.
_ALWAYS_GRAPHICAL = ("win32", "cygwin", "darwin")


def has_graphical_session(
    env: Mapping[str, str],
    *,
    platform: str | None = None,
) -> bool:
    """Whether a window can be shown, given *env* on *platform*.

    *platform* defaults to :data:`sys.platform`. ``QT_QPA_PLATFORM`` wins everywhere:
    an explicit Qt platform (``offscreen``, ``vnc``, ``minimal``) means the caller has
    said where the window goes, and it is how the headless smoke tests drive the
    Settings window.
    """
    if env.get("QT_QPA_PLATFORM"):
        return True
    platform = sys.platform if platform is None else platform
    if platform.startswith(_ALWAYS_GRAPHICAL):
        return True
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))
