"""The Settings window's update and install decisions, without Qt (settingsui/maintenance.py).

Offers come from the real ``installer_update.one_click_offer`` with a fake launcher, and
the rollback wording is checked against what the real ``deps._undo`` prints, so the box
cannot drift from the code that does the work.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yazses.settingsui import maintenance as m
from yazses.system.dormant import DormantFeature
from yazses.system.installer_update import HandoffResult, Offer, one_click_offer
from yazses.system.updater import UpdateStatus, UpgradeOutcome, manual_update_steps


def _status(method="windows-installer", *, latest="2.44.0", available=True, command=None,
            note=""):
    return UpdateStatus(
        method=method, current="2.43.2", latest=latest, available=available,
        command=command, note=note, steps=manual_update_steps(method),
    )


class _Launcher:
    def __init__(self, scope="user", feed=None):
        self._scope, self._feed = scope, feed

    def staging_dir(self) -> Path:  # pragma: no cover - not reached by the offer
        return Path(".")

    def install_scope(self) -> str:
        return self._scope

    def query_package_manager(self, method):
        return self._feed


# ---- updates -----------------------------------------------------------------


def test_a_check_that_could_not_reach_the_network_says_so_and_keeps_the_steps():
    status = _status("uv", latest=None, available=False, note="no network")
    view = m.plan_update(status, None)
    assert view.action is m.UpdateAction.NONE
    assert "Installed: 2.43.2" in view.text
    assert "Could not check for updates" in view.text and "no network" in view.text


def test_up_to_date_shows_both_versions_and_no_button():
    view = m.plan_update(_status("uv", latest="2.43.2", available=False), None)
    assert view.action is m.UpdateAction.NONE
    assert "Installed: 2.43.2" in view.text and "Available: 2.43.2" in view.text
    assert "latest version" in view.text


def test_a_per_user_windows_install_gets_the_one_click_button():
    status = _status()
    offer = one_click_offer(status, _Launcher("user"))
    view = m.plan_update(status, offer)
    assert view.action is m.UpdateAction.ONE_CLICK
    assert view.label == m.INSTALL_LABEL
    assert "Installed: 2.43.2" in view.text and "Available: 2.44.0" in view.text


def test_an_all_users_install_is_refused_with_the_reason_and_the_manual_steps():
    status = _status()
    offer = one_click_offer(status, _Launcher("machine"))
    assert offer is not None and not offer.ok
    view = m.plan_update(status, offer)
    assert view.action is m.UpdateAction.OPEN_PAGE
    assert "installed for all users" in view.text
    assert "no uninstall" in view.text
    # Every manual step is on screen, so the user is never left with just "refused".
    for step in status.steps:
        if step.strip():
            assert step in view.text


def test_a_package_feed_that_has_not_caught_up_is_refused_not_promised():
    status = _status("choco")
    offer = one_click_offer(status, _Launcher(feed="yazses|2.43.2"))
    view = m.plan_update(status, offer)
    assert view.action is m.UpdateAction.OPEN_PAGE
    assert "still offers 2.43.2" in view.text


def test_a_pip_family_install_runs_its_upgrade_command():
    status = _status("uv", command=["uv", "tool", "upgrade", "yazses"])
    view = m.plan_update(status, None)
    assert view.action is m.UpdateAction.UPGRADE
    assert "uv tool upgrade yazses" in view.text


def test_a_snap_is_shown_the_terminal_command_not_a_button_that_would_hang():
    status = _status("snap", command=["sudo", "snap", "refresh", "yazses"])
    view = m.plan_update(status, None)
    assert view.action is m.UpdateAction.NONE
    assert "sudo snap refresh yazses" in view.text and "terminal" in view.text


def test_a_macos_app_opens_the_download_page_but_msix_does_not():
    mac = m.plan_update(_status("macos-app"), None)
    assert mac.action is m.UpdateAction.OPEN_PAGE
    msix = m.plan_update(_status("msix"), None)
    # The page carries no .msix; its .exe would install a second copy.
    assert msix.action is m.UpdateAction.NONE


def test_handoff_success_says_the_window_closes_and_failure_offers_the_page():
    ok = m.describe_handoff(HandoffResult(ok=True, title="Updating", message="Closing to install."))
    assert ok.action is m.UpdateAction.NONE and "closes now" in ok.text
    bad = m.describe_handoff(HandoffResult(
        ok=False, title="Update not installed", message="checksum mismatch",
        steps=["Download it from the releases page."],
    ))
    assert bad.action is m.UpdateAction.OPEN_PAGE
    assert "checksum mismatch" in bad.text and "Download it from the releases page." in bad.text


def test_a_restart_is_offered_only_when_the_version_really_moved():
    moved = UpgradeOutcome(code=0, before="2.43.2", after="2.44.0", expected="2.44.0",
                           method="uv")
    text, restart = m.describe_upgrade(moved)
    assert restart and "2.44.0" in text
    pinned = UpgradeOutcome(code=0, before="2.43.2", after="2.43.2", expected="2.44.0",
                            method="uv", command=["uv", "tool", "upgrade", "yazses"])
    text, restart = m.describe_upgrade(pinned)
    assert not restart and "still 2.43.2" in text
    failed = UpgradeOutcome(code=2, before="2.43.2", after="2.43.2", expected="2.44.0")
    assert m.describe_upgrade(failed)[1] is False


def test_unapplied_changes_are_named_before_the_window_closes_for_an_update():
    assert m.unapplied_note(0) == ""
    assert "1 staged change " in m.unapplied_note(1)
    assert "3 staged changes" in m.unapplied_note(3)


def test_progress_lines_carry_a_percentage_only_when_there_is_one():
    assert m.progress_line("Downloading…", 0.42) == "Downloading… 42 %"
    assert m.progress_line("Waiting for the tray", None) == "Waiting for the tray"


def test_the_upgrade_question_quotes_the_command_that_runs():
    title, text = m.upgrade_confirmation(_status("pipx", command=["pipx", "upgrade", "yazses"]))
    assert "pipx upgrade yazses" in text and "2.43.2 → 2.44.0" in text


# ---- dormant features ----------------------------------------------------------


def _dormant(slug="tts", *, installable=True, remedy="Install them with:  yazses features enable tts"):
    return DormantFeature(
        slug=slug, name=slug.upper(), missing=("kokoro_onnx",), packages=("kokoro-onnx",),
        remedy=remedy, installable=installable, command=f"yazses features enable {slug}",
    )


def test_an_installable_feature_gets_a_button_carrying_its_size():
    rows = m.install_rows([_dormant()], size_note=lambda item: ("downloads ~80 MB", "~80 MB"))
    assert len(rows) == 1
    row = rows[0]
    assert row.route == m.PIP and row.installable
    assert row.button_label == "Install now (~80 MB)"
    assert "kokoro_onnx is not installed" in row.detail and "~80 MB" in row.detail


@pytest.mark.parametrize("reason", [
    "this is a snap, whose packages are fixed",            # snap
    "this is the Homebrew cask, whose payload is fixed",   # Homebrew cask
    "this is the Windows installer build, whose payload is fixed",  # frozen
    "this Python is managed by your distribution (PEP 668); use pipx install yazses",
])
def test_an_environment_that_can_never_install_disables_the_button_with_its_reason(reason):
    rows = m.install_rows([_dormant(installable=False, remedy=reason)],
                          size_note=lambda item: ("unused", "unused"))
    row = rows[0]
    assert not row.installable and row.route == ""
    assert reason in row.detail


class _PackStatus:
    def __init__(self, state, message, download=0, unpacked=0):
        self.state, self.message = state, message
        self.download_bytes, self.unpacked_bytes = download, unpacked


def test_a_frozen_build_with_packs_installs_the_add_on_instead_of_refusing():
    from yazses.packs.state import NOT_INSTALLED

    entry = object()
    rows = m.install_rows(
        [_dormant(installable=False, remedy="install YazSes from PyPI instead")],
        size_note=lambda item: ("", ""),
        pack_status=lambda slug: _PackStatus(NOT_INSTALLED, "Needs the Tts add-on.",
                                             220_000_000, 600_000_000),
        pack_entry=lambda slug: entry,
    )
    row = rows[0]
    assert row.route == m.PACK and row.item is entry
    assert row.button_label == "Install now (220 MB)"
    assert "220 MB download" in row.size


def test_an_installed_pack_says_restart_and_an_unavailable_one_says_why():
    from yazses.packs.state import OK, UNAVAILABLE

    ok = m.install_rows([_dormant(installable=False)], size_note=lambda i: ("", ""),
                        pack_status=lambda s: _PackStatus(OK, "The Tts add-on is installed."),
                        pack_entry=lambda s: object())[0]
    assert not ok.installable and "Restart YazSes" in ok.detail
    no = m.install_rows([_dormant(installable=False)], size_note=lambda i: ("", ""),
                        pack_status=lambda s: _PackStatus(UNAVAILABLE, "Run YazSes normally."),
                        pack_entry=lambda s: object())[0]
    assert not no.installable and "Run YazSes normally." in no.detail


def test_a_feature_without_a_pack_keeps_the_dormant_answer():
    rows = m.install_rows([_dormant(installable=False, remedy="install from PyPI")],
                          size_note=lambda i: ("", ""),
                          pack_status=lambda s: None, pack_entry=lambda s: None)
    assert not rows[0].installable and "install from PyPI" in rows[0].detail


def test_summary_counts_say_how_many_can_be_installed_here():
    assert m.summary_counts([]) == ""
    rows = m.install_rows([_dormant(), _dormant("gaze", installable=False, remedy="snap")],
                          size_note=lambda i: ("", ""))
    assert "2 switched-on features" in m.summary_counts(rows)
    assert "1 can be installed here" in m.summary_counts(rows)


# ---- the install's result, including the rollback ---------------------------------


def _row():
    return m.install_rows([_dormant()], size_note=lambda i: ("", ""))[0]


def test_a_successful_install_says_restart():
    result = m.pip_result(_row(), True, ["Installing dependencies: kokoro-onnx"])
    assert result.ok and result.rollback is m.Rollback.NOT_NEEDED
    assert "Restart YazSes" in result.message


def test_a_failure_before_any_change_says_nothing_was_changed():
    result = m.pip_result(_row(), False, ["ERROR: No matching distribution found"])
    assert not result.ok and result.rollback is m.Rollback.NOT_NEEDED
    assert "Nothing was changed" in result.message
    assert "No matching distribution" in result.message


def _drive_real_undo(monkeypatch, *, undo_works: bool) -> list[str]:
    """Run the real ``deps._undo`` with the environment faked, and return what it said."""
    import subprocess

    from yazses.system import deps

    before = {"yazses": "2.43.2", "numpy": "2.1.0"}
    after = {"yazses": "2.43.2", "numpy": "2.3.0", "kokoro-onnx": "0.4.0"}
    snapshots = iter([after, before if undo_works else after])
    monkeypatch.setattr(deps, "_installed_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
    lines: list[str] = []
    deps._undo(before, {}, echo=lines.append)
    return lines


def test_the_real_undo_reports_a_complete_rollback(monkeypatch):
    lines = ["The install failed part-way, after changing: numpy. Undoing it."]
    lines += _drive_real_undo(monkeypatch, undo_works=True)
    result = m.pip_result(_row(), False, lines)
    assert result.rollback is m.Rollback.COMPLETE
    assert "undone" in result.message and "exactly as it was" in result.message


def test_the_real_undo_reports_an_incomplete_rollback_with_its_restore_commands(monkeypatch):
    lines = _drive_real_undo(monkeypatch, undo_works=False)
    result = m.pip_result(_row(), False, lines)
    assert result.rollback is m.Rollback.INCOMPLETE
    assert "did not finish" in result.message
    assert "Restore it by hand" in result.message  # the commands, verbatim


def test_a_pack_result_passes_the_add_on_message_and_steps_through():
    from yazses.packs.install import InstallResult

    good = m.pack_result(_row(), InstallResult(True, "Installed", "The Tts add-on is installed."))
    assert good.ok and "Restart YazSes" in good.message
    bad = m.pack_result(_row(), InstallResult(
        False, "Add-on not installed", "Couldn't reach github.com. Nothing was changed.",
        steps=["Download tts.yazpack by hand."],
    ))
    assert not bad.ok and "Nothing was changed" in bad.message
    assert "Download tts.yazpack by hand." in bad.message


def test_offer_reasons_are_used_verbatim():
    view = m.plan_update(_status(), Offer(False, "A reason with a remedy."))
    assert "A reason with a remedy." in view.text
