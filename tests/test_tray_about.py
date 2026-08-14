"""The pure content behind the tray's About / Help / Check-for-updates entries.

No toolkit and no network here, so these run on any CI runner and cover what all three
trays render — the part that would otherwise only be testable on the OS that ships it.
"""

from __future__ import annotations

from yazses import branding
from yazses.system.updater import UpdateStatus
from yazses.tray.about import (
    DOCS_URL,
    REPORT_BUG_URL,
    TROUBLESHOOTING_URL,
    about_html,
    about_lines,
    about_title,
    help_links,
    needs_terminal,
    update_message,
    upgrade_result_message,
)
from yazses.tray.menu import DOCS_LABEL, REPORT_BUG_LABEL, TROUBLESHOOTING_LABEL


def _status(**kw) -> UpdateStatus:
    base = dict(
        method="uv", current="2.18.2", latest=None, available=False, command=None, note=""
    )
    base.update(kw)
    return UpdateStatus(**base)  # type: ignore[arg-type]


# ---- About -----------------------------------------------------------------


def test_about_leads_with_the_version():
    """The one thing About is opened for; on pystray the body may be truncated."""
    first = about_lines()[0]
    assert first == f"{branding.APP_NAME} {branding.version()}"


def test_about_carries_every_contact_link():
    body = "\n".join(about_lines())
    for url in (branding.WEBSITE, branding.SOURCE, branding.ISSUES):
        assert url in body
    assert branding.TAGLINE in body


def test_about_reuses_the_shared_contact_block():
    """Same block ``doctor`` and ``yazses about`` print, so the surfaces can't drift."""
    body = about_lines()
    for line in branding.contact_lines():
        assert line in body


def test_the_html_about_makes_the_urls_clickable():
    html = about_html()
    for url in (branding.WEBSITE, branding.SOURCE, branding.ISSUES):
        assert f'<a href="{url}">' in html
    assert branding.version() in html


def test_the_about_title_names_the_app():
    assert about_title() == f"About {branding.APP_NAME}"


# ---- Help ------------------------------------------------------------------


def test_the_help_submenu_is_docs_troubleshooting_and_report_a_bug():
    assert help_links() == [
        (DOCS_LABEL, DOCS_URL),
        (TROUBLESHOOTING_LABEL, TROUBLESHOOTING_URL),
        (REPORT_BUG_LABEL, REPORT_BUG_URL),
    ]


def test_the_help_urls_come_from_branding():
    assert DOCS_URL == branding.WEBSITE
    assert TROUBLESHOOTING_URL.startswith(branding.WEBSITE)
    assert REPORT_BUG_URL == branding.ISSUES


# ---- updates ---------------------------------------------------------------


def test_a_newer_version_is_reported_with_both_versions():
    title, body = update_message(
        _status(latest="2.19.0", available=True, command=["uv", "tool", "upgrade", "yazses"])
    )
    assert title == "Update available"
    assert "2.18.2" in body and "2.19.0" in body
    assert "uv tool upgrade yazses" in body


def test_being_current_says_so_rather_than_saying_nothing():
    title, body = update_message(_status(latest="2.18.2", available=False))
    assert "up to date" in title
    assert "2.18.2" in body


def test_a_failed_lookup_still_reports_the_running_version():
    """No network is not an error state — the user still asked what they're running."""
    title, body = update_message(_status(note="could not determine the latest version"))
    assert "Could not check" in body
    assert "could not determine the latest version" in body
    assert "2.18.2" in body


def test_a_snap_upgrade_needs_a_terminal():
    """``sudo snap refresh`` from a tray click has no terminal to take a password."""
    status = _status(
        method="snap", latest="2.19.0", available=True,
        command=["sudo", "snap", "refresh", "yazses"],
    )
    assert needs_terminal(status) is True
    _title, body = update_message(status)
    assert "in a terminal" in body
    assert "sudo snap refresh yazses" in body


def test_the_pip_family_upgrades_do_not_need_a_terminal():
    for command in (
        ["uv", "tool", "upgrade", "yazses"],
        ["pipx", "upgrade", "yazses"],
        ["pip", "install", "--upgrade", "yazses"],
    ):
        assert needs_terminal(_status(command=command, available=True)) is False


def test_no_command_is_not_mistaken_for_a_terminal_upgrade():
    assert needs_terminal(_status()) is False


def test_a_finished_upgrade_says_the_daemon_is_still_the_old_one():
    """The new code is on disk; the process running your dictation is not."""
    _title, body = upgrade_result_message(0)
    assert "Restart" in body

    _title, failed = upgrade_result_message(1)
    assert "failed" in failed
    assert "yazses update" in failed


def test_a_source_checkout_is_never_told_to_upgrade(monkeypatch):
    """``branding.version()`` is "dev" from a source tree, which is not a version.

    ``updater.is_newer`` answers False for anything unparseable, so the tray cannot
    offer to "upgrade" a working copy over the top of itself.
    """
    from yazses.system.updater import is_newer

    monkeypatch.setattr(branding, "version", lambda: "dev")
    assert is_newer("2.19.0", branding.version()) is False
