"""`yazses doctor` must not tell a Windows or macOS user to run `apt`.

The "Text-target guard" row offered a remedy for its own imprecision:

    [OK] Text-target guard: clipboard (best-effort; apt install python3-pyatspi
         gir1.2-atspi-2.0 for precision)

and it was not platform-gated, so **every** Windows and macOS install got it. This is
not a hypothetical: the line above is copied verbatim out of the `yazses doctor` output
captured on a real Windows host on 2026-08-23, where `apt` does not exist.

The advice is unfollowable there in the strong sense. `AtspiFocusTracker.available()`
imports `pyatspi`, which needs an AT-SPI accessibility bus — a Linux desktop technology.
Off Linux the precise path is not missing a package, it is unreachable, so no command
can ever move that row from best-effort to precise.

Same rule the neighbouring "Input device" row already follows, and the same rule
`system/backends.py` exists to enforce: never send the user after a fix that cannot
apply on their machine. A command that cannot work is worse than no advice, because it
costs the user a round-trip to discover that the tool was wrong about their OS.
"""

from __future__ import annotations

import pathlib

import pytest

from yazses.config import Config
from yazses.system import doctor as doctor_mod


def _guard_row(monkeypatch, platform: str, *, precise: bool) -> str:
    """Render the config summary and return the Text-target guard row's detail.

    Built from the real `Config` rather than a stub: the row is produced deep inside
    `_config_summary`, so a hand-made object only proves my stub is wrong.
    """
    monkeypatch.setattr(doctor_mod.sys, "platform", platform)

    from yazses.inject import target as target_mod

    monkeypatch.setattr(
        target_mod.AtspiFocusTracker, "available", staticmethod(lambda: precise)
    )
    cfg = Config()
    cfg.injection.target_guard = "clipboard"
    rows = doctor_mod._config_summary(cfg, pathlib.Path("/nonexistent/config.toml"))
    detail = [d for name, _, d in rows if name == "Text-target guard"]
    assert detail, f"no Text-target guard row in {[r[0] for r in rows]}"
    return detail[0]


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_no_apt_command_is_offered_off_linux(monkeypatch, platform: str) -> None:
    """The exact defect: an apt command printed on a machine that has no apt."""
    detail = _guard_row(monkeypatch, platform, precise=False)
    assert "apt" not in detail
    assert "pyatspi" not in detail


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_the_row_still_says_the_guard_is_best_effort(monkeypatch, platform: str) -> None:
    """Removing the advice must not remove the information.

    The user still needs to know the guard is running in its imprecise mode — the fix
    for bad advice is honest advice, not silence.
    """
    detail = _guard_row(monkeypatch, platform, precise=False)
    assert "best-effort" in detail
    assert "Linux-only" in detail


def test_linux_keeps_the_apt_remedy(monkeypatch) -> None:
    """Guards the fix in the other direction — on Linux the package really is the fix.

    Without this, gating the message on `sys.platform` at all would pass by deleting the
    advice everywhere, which is the opposite mistake.
    """
    detail = _guard_row(monkeypatch, "linux", precise=False)
    assert "apt install python3-pyatspi gir1.2-atspi-2.0" in detail


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
def test_an_available_tracker_reports_precise_on_every_platform(
    monkeypatch, platform: str
) -> None:
    """If AT-SPI ever does answer, the row says so and offers nothing to install."""
    detail = _guard_row(monkeypatch, platform, precise=True)
    assert "AT-SPI precise" in detail
    assert "apt" not in detail
