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


def _outcome(code=0, before="2.19.0", after="2.20.0", method="uv"):
    from yazses.system.updater import UpgradeOutcome

    return UpgradeOutcome(
        code=code, before=before, after=after, expected="2.20.0", method=method,
        command=["uv", "tool", "upgrade", "yazses"],
    )


def test_a_windows_install_gets_steps_instead_of_a_dead_end():
    """No command exists for a .exe install — the upgrade is a downloaded installer.

    Without the steps the tray showed "2.19.0 → 2.20.0" and then nothing the user
    could act on, since the Install button is (correctly) gated on `status.command`.
    """
    from yazses.system.updater import RELEASES_URL, manual_update_steps

    _title, body = update_message(
        _status(method="windows-installer", latest="2.20.0", available=True,
                steps=manual_update_steps("windows-installer"))
    )
    assert RELEASES_URL in body
    # The Windows tray renders this as a balloon, and Windows truncates those at
    # roughly 256 characters. The one actionable thing has to survive that.
    assert RELEASES_URL in body[:200]


def test_a_blocked_check_says_yazses_still_works_and_how_to_update():
    from yazses.system.updater import offline_steps

    _title, body = update_message(
        _status(note="could not reach PyPI — offline, or a firewall is blocking it",
                steps=offline_steps("pip"))
    )
    assert "keeps working" in body
    assert "pip install --upgrade yazses" in body


def test_a_finished_upgrade_says_the_daemon_is_still_the_old_one():
    """The new code is on disk; the process running your dictation is not."""
    _title, body = upgrade_result_message(_outcome())
    assert "Restart" in body
    assert "2.20.0" in body

    _title, failed = upgrade_result_message(_outcome(code=1))
    assert "failed" in failed
    assert "yazses update" in failed


def test_an_upgrade_that_changed_nothing_is_not_reported_as_installed():
    """The bug a user hit: `uv tool upgrade` exits 0 on a version-pinned install.

    The tray said "Update installed. Restart the daemon", the daemon came back on the
    same version, and nothing on screen explained why. Success has to mean the version
    moved, not that the command exited 0.
    """
    title, body = upgrade_result_message(_outcome(after="2.19.0"))

    assert "did not apply" in title.lower()
    assert "still 2.19.0" in body
    assert "Restart" not in body
    assert "installed." not in body.lower()
    # and it must say how to get out of it
    assert "uv tool install" in body


def test_a_version_that_cannot_be_read_is_not_claimed_as_success():
    _title, body = upgrade_result_message(_outcome(after=None))
    assert "not confirmed" in body
    assert "Updated to" not in body


def test_the_pin_hint_keeps_the_extras():
    """A bare `yazses@latest` reinstalls base deps only and deletes PySide6 with it,
    which silently removes the tray and the overlay — the exact way this machine lost
    them once already."""
    from yazses.system.updater import pinned_install_hint

    hint = pinned_install_hint("uv", ["uv", "tool", "upgrade", "yazses"])
    assert "[desktop]" in hint

    # A non-uv method has no pin story, so it quotes the command back instead.
    other = pinned_install_hint("pip", ["pip", "install", "--upgrade", "yazses"])
    assert "pip install --upgrade yazses" in other


def test_a_source_checkout_is_never_told_to_upgrade(monkeypatch):
    """``branding.version()`` is "dev" from a source tree, which is not a version.

    ``updater.is_newer`` answers False for anything unparseable, so the tray cannot
    offer to "upgrade" a working copy over the top of itself.
    """
    from yazses.system.updater import is_newer

    monkeypatch.setattr(branding, "version", lambda: "dev")
    assert is_newer("2.19.0", branding.version()) is False
