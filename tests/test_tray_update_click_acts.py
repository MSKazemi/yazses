"""Clicking "Check for updates…" does something on an install with no upgrade command.

``updater.upgrade_command("windows-installer")`` answers ``None`` deliberately: that
upgrade is a downloaded ``.exe`` and there is nothing safe to shell out to. The tray's
entire response was to print the releases URL into a balloon — where it is text, not a
link, and cannot be clicked. Reported as "it never updates it, I need to uninstall and
then install the new version manually".

``describe_update`` opens the page instead. It stops short of downloading and running
the installer: that is executing a fetched binary on the user's behalf and needs the
code-signing question settled first.
"""

from __future__ import annotations

from yazses.system.updater import RELEASES_URL, UpdateStatus, manual_update_steps
from yazses.tray import updates as tray_updates


def _status(**kw):
    base = dict(
        method="windows-installer", current="2.33.0", latest="2.34.0", available=True,
        command=None, note="", steps=manual_update_steps("windows-installer"),
    )
    base.update(kw)
    return UpdateStatus(**base)


def test_an_update_with_no_command_opens_the_releases_page(monkeypatch):
    monkeypatch.setattr(tray_updates, "check_updates", lambda *_a, **_k: _status())
    opened: list[str] = []
    title, body = tray_updates.describe_update(opener=lambda url: opened.append(url) or True)

    assert opened == [RELEASES_URL]
    assert title == "Update available"
    assert body.splitlines()[0] == "YazSes 2.33.0 → 2.34.0"
    assert "Opening the download page" in body


def test_the_acted_body_still_says_the_installer_upgrades_in_place():
    """The reported workaround was uninstall-then-reinstall, which was never needed."""
    monkey = _status()
    original = tray_updates.check_updates
    try:
        tray_updates.check_updates = lambda *_a, **_k: monkey  # type: ignore[assignment]
        _t, body = tray_updates.describe_update(opener=lambda _u: True)
    finally:
        tray_updates.check_updates = original  # type: ignore[assignment]
    assert "upgrades in place" in body


def test_a_browser_that_refuses_leaves_the_written_instructions(monkeypatch):
    """Falling back to the steps beats a balloon claiming a page opened that did not."""
    monkeypatch.setattr(tray_updates, "check_updates", lambda *_a, **_k: _status())
    _title, body = tray_updates.describe_update(opener=lambda _u: False)
    assert "Opening the download page" not in body
    assert "How to update" in body


def test_an_opener_that_raises_does_not_reach_the_caller(monkeypatch):
    """A menu click must always end in something readable."""
    monkeypatch.setattr(tray_updates, "check_updates", lambda *_a, **_k: _status())

    def _boom(_url):
        raise RuntimeError("no browser")

    _title, body = tray_updates.describe_update(opener=_boom)
    assert "How to update" in body


def test_an_install_with_a_command_opens_nothing(monkeypatch):
    """A scoop/choco/winget user gets a command; opening a download page would be noise."""
    monkeypatch.setattr(
        tray_updates, "check_updates",
        lambda *_a, **_k: _status(method="scoop", command=["scoop", "update", "yazses"]),
    )
    opened: list[str] = []
    _title, body = tray_updates.describe_update(opener=lambda url: opened.append(url) or True)
    assert opened == []
    assert "scoop update yazses" in body


def test_being_up_to_date_opens_nothing(monkeypatch):
    monkeypatch.setattr(
        tray_updates, "check_updates",
        lambda *_a, **_k: _status(latest="2.33.0", available=False, steps=[]),
    )
    opened: list[str] = []
    title, _body = tray_updates.describe_update(opener=lambda url: opened.append(url) or True)
    assert opened == []
    assert title == "YazSes is up to date"


def test_a_failed_check_opens_nothing(monkeypatch):
    """No latest version means nothing to download; a browser popping open would be wrong."""
    monkeypatch.setattr(
        tray_updates, "check_updates",
        lambda *_a, **_k: _status(latest=None, available=False, note="offline"),
    )
    opened: list[str] = []
    _title, body = tray_updates.describe_update(opener=lambda url: opened.append(url) or True)
    assert opened == []
    assert "Could not check for updates" in body


def test_the_windows_tray_uses_the_acting_variant():
    """Swapping back to `check_and_describe` restores the reported bug in full.

    Nothing else pins it: `test_tray_settings_parity` accepts either name, because it
    asks whether the entry is *wired*, not whether the wire does anything. Reverting
    this one call gives back a click that finds the update, prints a URL nobody can
    click, and opens nothing — which is exactly what was reported.
    """
    import ast
    from pathlib import Path

    tray = Path(__file__).resolve().parents[1] / "src" / "yazses" / "platform" / "windows" / "tray.py"
    called = {
        node.func.id
        for node in ast.walk(ast.parse(tray.read_text(encoding="utf-8"), filename=str(tray)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "describe_update" in called, (
        "the Windows tray's Check-for-updates handler no longer calls describe_update; "
        "check_and_describe only describes, so an install with no upgrade command is "
        "left with a URL printed into a balloon where it is not clickable"
    )


def test_a_mac_click_is_not_told_to_run_an_installer(monkeypatch):
    """The follow-up line has to match the artifact the page will hand over.

    A `macos-app` install downloads a .dmg; "run the installer — it upgrades in
    place" describes the Windows .exe and nothing a Mac user is about to see.
    """
    monkeypatch.setattr(
        tray_updates, "check_updates",
        lambda *_a, **_k: _status(
            method="macos-app", steps=manual_update_steps("macos-app")
        ),
    )
    _title, body = tray_updates.describe_update(opener=lambda _u: True)
    assert ".dmg" in body
    assert "installer" not in body


def test_a_windows_click_still_says_run_the_installer(monkeypatch):
    monkeypatch.setattr(tray_updates, "check_updates", lambda *_a, **_k: _status())
    _title, body = tray_updates.describe_update(opener=lambda _u: True)
    assert "Run the installer" in body
    assert ".dmg" not in body
