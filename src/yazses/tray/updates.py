"""The tray's update check — the one shared piece that actually does I/O.

``system/updater.py`` owns the real logic; this is the thin wrapper the trays need on top
of it: it never raises (a menu click must always end in something the user can read) and
it answers with an ``UpdateStatus`` even when the lookup failed, so ``about.update_message``
has something to describe.

It lives here rather than on ``TrayController`` because the macOS and Windows trays have
static menus and never build a controller — they import this directly.

**Blocking.** ``check_update`` reaches PyPI (5 s timeout) or shells ``snap info`` (10 s).
Every caller runs it on a worker thread; running it on a UI loop freezes the tray.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def check_updates(current: str | None = None):
    """Return an ``UpdateStatus`` for the running install. Never raises."""
    from yazses import branding
    from yazses.system.updater import UpdateStatus, check_update

    current = current if current is not None else branding.version()
    try:
        return check_update(current)
    except Exception as exc:
        log.warning("tray update check failed: %s", exc)
        return UpdateStatus(
            method="unknown", current=current, latest=None, available=False,
            command=None, note=str(exc),
        )


def check_and_describe(current: str | None = None) -> tuple[str, str]:
    """Check for updates and return the ``(title, body)`` to show. Never raises."""
    from yazses.tray.about import update_message

    return update_message(check_updates(current))
