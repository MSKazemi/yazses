"""Open a URL in the user's browser, without ever raising into the caller.

The tray menus (Help → Documentation, Report a bug…, About's links) need to hand a URL
to the desktop. ``webbrowser`` already picks the right mechanism per OS, but it raises on
some misconfigured desktops and returns False when it finds no browser at all — from a
tray menu either one is a click that appears to do nothing.

So this returns a plain bool with the same contract as the tray's other launch actions
(``TrayController.launch_settings``): *was it handed off?* The caller reports a False to
the user rather than leaving the click looking ignored.

``fileopen.launcher.launch_file`` is deliberately not reused here — it is file-oriented
and runs with ``check=True``, so it raises on failure.
"""
from __future__ import annotations

import logging
import webbrowser

log = logging.getLogger(__name__)


def open_url(url: str, *, opener=webbrowser.open) -> bool:
    """Open ``url`` in the default browser. Returns whether it was handed off.

    ``opener`` is injected so this is testable without launching a real browser.
    """
    if not url:
        return False
    try:
        return bool(opener(url))
    except Exception:
        log.exception("could not open %s in a browser", url)
        return False
