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


def describe_update(current: str | None = None, *, opener=None) -> tuple[str, str]:
    """Check for updates, *act* where a click can act, and describe the result.

    The difference from :func:`check_and_describe` is the one thing the user was
    asking for when they clicked the entry. Some installs have no upgrade command
    at all — a ``windows-installer`` install upgrades by downloading and running a
    new ``.exe``, a ``macos-app`` one by opening a new ``.dmg``, and
    ``updater.upgrade_command`` deliberately answers ``None`` for both rather than
    shelling out to something that cannot work. The tray's only
    response was to print the releases URL into a balloon, where it is not a link
    and cannot be clicked, so the honest reading of the entry was "it finds nothing
    and does nothing".

    Opening the page is the smallest action that makes the click mean something. It
    is deliberately *not* downloading and running the installer: that is executing a
    fetched binary on the user's behalf, and it needs the code-signing question
    settled first.

    Never raises, like everything else in this module — a menu click must always end
    in something readable.
    """
    from yazses.system.updater import MACOS_METHODS, RELEASES_URL
    from yazses.tray.about import update_message

    status = check_updates(current)
    title, body = update_message(status)
    if not (status.available and not status.command):
        return title, body

    open_page = opener
    if open_page is None:
        from yazses.system.browser import open_url as open_page
    try:
        opened = bool(open_page(RELEASES_URL))
    except Exception:  # pragma: no cover - open_url already swallows its own
        log.warning("could not open the releases page", exc_info=True)
        opened = False
    if not opened:
        return title, body
    # Replace the steps block rather than appending to it: the balloon is trimmed
    # from the end, so a line added last is the first one dropped — and the whole
    # point is that this line survives.
    headline = body.split("\n", 1)[0]
    # What to do with the download is not the same on the two bundled platforms,
    # and this text is the last thing the user reads before acting on it. A macOS
    # .app has no installer to run; saying "run the installer" there would repeat,
    # in miniature, the very bug that made `macos-app` a separate method.
    if status.method in MACOS_METHODS:
        follow = (
            "Open the .dmg and drag YazSes to Applications, replacing the old one."
        )
    else:
        follow = (
            "Run the installer — it upgrades in place and keeps your settings and models."
        )
    return title, f"{headline}\n\nOpening the download page in your browser.\n{follow}"
