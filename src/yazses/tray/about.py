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


#: Usable characters in a Windows balloon body. ``NOTIFYICONDATA.szInfo`` is a
#: 256-wide-character buffer including the terminator, and pystray's win32 backend
#: writes straight into it. The full About body is 347 characters, so it overran —
#: and the caller reports failures to ``log.debug``, which nobody reads.
BALLOON_LIMIT = 255


def fit_balloon(text: str, limit: int = BALLOON_LIMIT) -> str:
    """Trim any notification body to fit the balloon, keeping the first line.

    Drops whole lines from the end rather than cutting mid-URL: a half-printed link
    is worse than an absent one, because it looks clickable and is not. The first
    line always survives — every body fitted here leads with the one fact it was
    opened for (the version, or ``2.33.0 → 2.34.0``), and a body that omits it has
    failed at the only job it had.

    Generic rather than About-specific because the same overrun shipped **twice** in
    ``platform/windows/tray.py``: About was fixed, and *Check for updates…* — six
    lines below it — was not. An "update available" body on a Windows-installer
    install measures 512 characters and an offline one 623, so the two cases that
    carry information were exactly the two that vanished, leaving only "you are up
    to date" able to render. Every balloon now passes through here at the single
    point that calls the Windows API, so a new menu entry inherits the fix instead
    of repeating the bug.
    """
    lines = text.split("\n")
    while len(lines) > 1 and len("\n".join(lines).rstrip()) > limit:
        lines.pop()

    body = "\n".join(lines).rstrip()
    if len(body) > limit:
        # One line and still too long. Truncating beats handing the API something
        # it discards wholesale — which is the failure being fixed here.
        body = body[: max(0, limit - 1)] + "…"
    return body


def balloon_body(limit: int = BALLOON_LIMIT) -> str:
    """The About text, trimmed to fit a fixed-size notification."""
    lines = [ln for ln in about_lines() if ln.strip()]
    if not lines:
        return ""
    return fit_balloon("\n".join(lines), limit)


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

    A status with no command at all is *not* this case and answers False: the callers
    already gate the Install button on ``status.command``, and a "run it in a terminal"
    message for a Windows-installer upgrade would be wrong — there is no command to run,
    only an .exe to download (see :func:`update_message`).
    """
    command = list(getattr(status, "command", None) or [])
    return command[:1] == ["sudo"]


def _steps_block(status) -> str:
    """The status's manual steps as an indented block, or "" when it has none."""
    steps = list(getattr(status, "steps", None) or [])
    if not steps:
        return ""
    return "\n" + "\n".join(f"    {s}" if s else "" for s in steps)


def update_message(status) -> tuple[str, str]:
    """``(title, body)`` describing an ``UpdateStatus``, for a dialog or a toast."""
    if status.latest is None:
        note = status.note or "no network?"
        return (
            branding.APP_NAME,
            f"Could not check for updates — {note}.\n"
            f"You're running {branding.APP_NAME} {status.current}, and it keeps working."
            + _steps_block(status),
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
    else:
        # No command — a Windows-installer install, where the upgrade is a
        # downloaded .exe. Without this the tray showed the headline and then
        # nothing the user could act on.
        body += "\n\nHow to update:" + _steps_block(status)
    return ("Update available", body)


def upgrade_result_message(outcome) -> tuple[str, str]:
    """``(title, body)`` for a finished in-place upgrade.

    Three outcomes, because an exit status of 0 is not evidence that anything happened:

    * the version really moved — say so, and say the running daemon is still the old one
    * the command failed — say that
    * the command succeeded and the version did **not** move — the case that made this
      function take an outcome instead of an exit code. `uv tool upgrade` exits 0 on a
      pinned install, and reporting "Update installed. Restart the daemon" then sends the
      user to restart into the very same version, over and over, with nothing to explain it.
    """
    if outcome.ok:
        return (
            branding.APP_NAME,
            f"Updated to {outcome.after}. Restart the daemon to run it "
            "(tray → Restart daemon, or `yazses restart`).",
        )
    if outcome.code != 0:
        return (
            branding.APP_NAME,
            f"The upgrade command failed (exit {outcome.code}). "
            "Run `yazses update` in a terminal to see why.",
        )
    if outcome.after is None:
        return (
            branding.APP_NAME,
            "The upgrade command finished, but the installed version could not be read, "
            "so it is not confirmed. Check with `yazses --version`.",
        )
    from yazses.system.updater import pinned_install_hint

    return (
        "Update did not apply",
        f"The upgrade command finished without an error, but {branding.APP_NAME} is "
        f"still {outcome.after}.\n\n"
        + pinned_install_hint(outcome.method, outcome.command),
    )
