"""Pure content for the tray's About / Help / Check-for-updates entries.

No toolkit, no network, no I/O — just the strings and the decisions, so the three trays
(Qt, rumps, pystray) render the same answers and this file can be unit-tested on any CI
runner. The rendering differences live in the platform trays: Qt gets rich text with
clickable links, rumps gets an alert, pystray gets a notification.

The version comes from ``branding.version()``, which returns ``"dev"`` in a source tree.
That is deliberate on the update path too: ``"dev"`` is not a parseable version, so
``updater.is_newer`` already answers False and a source checkout is never told to upgrade.
"""
from __future__ import annotations

from yazses import branding

# Deep links into the docs site. mkdocs runs with ``use_directory_urls: false``, so every
# page is a ``.html`` file rather than a directory.
DOCS_URL = branding.WEBSITE
TROUBLESHOOTING_URL = branding.WEBSITE + "troubleshooting.html"
REPORT_BUG_URL = branding.ISSUES


def about_title() -> str:
    """Window/notification title for the About entry."""
    return f"About {branding.APP_NAME}"


def about_lines() -> list[str]:
    """Plain-text About body, for the trays that can only show text.

    Reuses ``branding.contact_lines()`` — the same block ``yazses doctor`` and
    ``yazses about`` print, so the three surfaces cannot drift apart.
    """
    return [
        f"{branding.APP_NAME} {branding.version()}",
        branding.TAGLINE,
        "",
        *branding.contact_lines(),
    ]


def about_html() -> str:
    """The same About body as rich text, with the URLs as clickable links (Qt)."""
    links = "<br>".join(
        f'{label}: <a href="{url}">{url}</a>'
        for label, url in (
            ("Website", branding.WEBSITE),
            ("Source", branding.SOURCE),
            ("Issues", branding.ISSUES),
        )
    )
    return (
        f"<b>{branding.APP_NAME} {branding.version()}</b><br>"
        f"{branding.TAGLINE}<br><br>"
        f"{links}<br><br>"
        f"{branding.AUTHOR} &lt;{branding.EMAIL}&gt;"
    )


def help_links() -> list[tuple[str, str]]:
    """``(label, url)`` pairs driving the Help submenu, in menu order."""
    from yazses.tray.menu import DOCS_LABEL, REPORT_BUG_LABEL, TROUBLESHOOTING_LABEL

    return [
        (DOCS_LABEL, DOCS_URL),
        (TROUBLESHOOTING_LABEL, TROUBLESHOOTING_URL),
        (REPORT_BUG_LABEL, REPORT_BUG_URL),
    ]


def needs_terminal(status) -> bool:
    """True when the upgrade command cannot be run from a tray click.

    A snap install upgrades with ``sudo snap refresh`` — launched from a tray there is no
    terminal to type a password into, so it hangs or dies invisibly. Those users are shown
    the command to run instead of an Install button that could not work.
    """
    command = list(getattr(status, "command", None) or [])
    return command[:1] == ["sudo"]


def update_message(status) -> tuple[str, str]:
    """``(title, body)`` describing an ``UpdateStatus``, for a dialog or a toast."""
    if status.latest is None:
        note = status.note or "no network?"
        return (
            branding.APP_NAME,
            f"Could not check for updates — {note}.\n"
            f"You're running {branding.APP_NAME} {status.current}.",
        )
    if not status.available:
        return (
            f"{branding.APP_NAME} is up to date",
            f"You're on the latest version ({status.current}). ✓",
        )
    body = f"{branding.APP_NAME} {status.current} → {status.latest}"
    if status.command:
        joined = " ".join(status.command)
        if needs_terminal(status):
            body += f"\n\nRun this in a terminal to upgrade:\n    {joined}"
        else:
            body += f"\n\nUpgrade command: {joined}"
    return ("Update available", body)


def upgrade_result_message(code: int) -> tuple[str, str]:
    """``(title, body)`` for a finished in-place upgrade.

    A successful upgrade replaces the code on disk but the running daemon is still the old
    one, so the message says so rather than leaving the user thinking they are on the new
    version already.
    """
    if code == 0:
        return (
            branding.APP_NAME,
            "Update installed. Restart the daemon to run it "
            "(tray → Restart daemon, or `yazses restart`).",
        )
    return (
        branding.APP_NAME,
        "The upgrade command failed. Run `yazses update` in a terminal to see why.",
    )
