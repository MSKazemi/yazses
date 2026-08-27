"""A frozen macOS .app must not be described as a Windows install.

`detect_install_method` classified *anything* with `sys.frozen` set as
`windows-installer`, because the frozen branch was written when Windows was the
only bundled build. The .dmg .app is frozen too, so every Mac user who opened
"Check for updates" was told, confidently and in detail, to download a
`YazSes-<version>-windows-<arch>.exe` — a file that cannot run on their machine,
with nothing in the message hinting that the advice itself is the problem.

These tests pin the classification per platform and the prose that follows from
it, and one of them proves the .exe wording is gone rather than merely joined by
a .dmg line.
"""
from __future__ import annotations

import ast
import pathlib

from yazses.system import updater

SRC = pathlib.Path(updater.__file__)


def test_a_frozen_mac_build_is_a_macos_app() -> None:
    assert updater.detect_install_method(
        "/Applications/YazSes.app/Contents/MacOS/yazses/system/updater.py",
        frozen=True, choco=False, platform="darwin",
    ) == "macos-app"


def test_a_frozen_windows_build_is_still_the_installer() -> None:
    """The regression guard in the other direction — Windows must not move."""
    assert updater.detect_install_method(
        r"C:\Program Files\YazSes\yazses\system\updater.py",
        frozen=True, choco=False, platform="win32",
    ) == "windows-installer"


def test_chocolatey_still_wins_over_the_platform_branch() -> None:
    assert updater.detect_install_method(
        r"C:\Program Files\YazSes\yazses\system\updater.py",
        frozen=True, choco=True, platform="win32",
    ) == "choco"


def test_a_source_checkout_on_a_mac_is_not_an_app() -> None:
    """Not frozen is not a bundle, whatever the platform says."""
    assert updater.detect_install_method(
        "/Users/m/src/yazses/src/yazses/system/updater.py",
        frozen=False, choco=False, platform="darwin",
    ) == "pip"


def test_the_mac_steps_never_mention_a_windows_exe() -> None:
    """The whole bug, stated as an assertion."""
    steps = "\n".join(updater.manual_update_steps("macos-app"))
    assert ".exe" not in steps and "windows" not in steps.lower()
    assert ".dmg" in steps
    assert updater.RELEASES_URL in steps


def test_the_mac_steps_name_homebrew_as_the_alternative() -> None:
    """Homebrew ships the same .app and is not detectable from inside it."""
    steps = "\n".join(updater.manual_update_steps("macos-app"))
    assert "brew upgrade --cask yazses" in steps


def test_the_windows_steps_still_name_the_exe() -> None:
    steps = "\n".join(updater.manual_update_steps("windows-installer"))
    assert ".exe" in steps and ".dmg" not in steps


def test_the_app_has_no_upgrade_command() -> None:
    """There is nothing safe to shell out to; a guessed command that exits 0 is
    the exact failure this module keeps being rewritten against."""
    assert updater.upgrade_command("macos-app") is None


def test_the_app_is_versioned_against_github_not_pypi() -> None:
    """The artifact *is* a release asset — PyPI carries no .dmg."""
    assert updater.source_name("macos-app") == "github.com"
    assert "macos-app" in updater.GITHUB_METHODS
    assert "macos-app" not in updater.WINDOWS_METHODS


def test_the_pinned_hint_for_an_app_is_a_download_not_a_command() -> None:
    hint = updater.pinned_install_hint("macos-app", None)
    assert ".exe" not in hint
    assert updater.RELEASES_URL in hint
    assert updater.RECOVERY_URL in hint


def test_offline_steps_for_an_app_stay_mac_shaped() -> None:
    """The blocked-network path composes the same steps and must not regress."""
    text = "\n".join(updater.offline_steps("macos-app"))
    assert ".dmg" in text and ".exe" not in text
    assert "github.com" in text


def test_check_update_end_to_end_gives_a_mac_user_mac_steps(monkeypatch) -> None:
    monkeypatch.setattr(updater, "latest_github_release", lambda *a, **k: "9.9.9")
    status = updater.check_update("2.34.0", method="macos-app")
    assert status.available and status.command is None
    joined = "\n".join(status.steps)
    assert ".dmg" in joined and ".exe" not in joined


def test_the_cli_treats_a_mac_app_as_a_known_method() -> None:
    """`yazses update` exits non-zero for a method it has no recipe for.

    Before the fix a Mac install could not reach that branch at all (it looked
    like Windows); after it, `macos-app` must be recognised rather than falling
    through to "no automatic upgrade is available" plus exit 1.
    """
    src = pathlib.Path(__import__("yazses.cli", fromlist=["x"]).__file__)
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "GITHUB_METHODS" in names, (
        "yazses update decides 'known method' from WINDOWS_METHODS again — a "
        "macos-app install then exits 1 with 'no automatic upgrade is available'"
    )


def test_the_platform_branch_is_actually_read() -> None:
    """Vacuity guard: the parameter must reach a comparison, not sit unused."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"), filename=str(SRC))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "detect_install_method"
    )
    assert any(
        isinstance(n, ast.Constant) and n.value == "darwin" for n in ast.walk(fn)
    ), "detect_install_method no longer looks at the platform"
