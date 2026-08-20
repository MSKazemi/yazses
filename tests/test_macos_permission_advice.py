"""`doctor`'s macOS Accessibility advice must answer the person who is stuck.

Reported on #182/#241 by the first human ever to run the macOS build, on an M2
running macOS 26.6.1: Accessibility visibly enabled for YazSes, three install
routes tried (two `.dmg` versions and Homebrew), and the check answering denied
every time. What `doctor` printed was:

    [FAIL] Keyboard capture: denied — Grant Accessibility access in System
    Settings: … → Accessibility → enable YazSes.

which is precisely the instruction they had already followed. The one place
someone lands *after* the obvious thing failed had nothing else to say.

Both additions are facts this project already had and had never put here: the
install guide states that macOS treats an unsigned app as a new identity when its
hash changes (so a stale grant still renders as an enabled toggle), and
`AXIsProcessTrustedWithOptions` is process-scoped, so the executable it asked
about is worth naming.

Nothing here asserts how macOS attributes trust between a launching shell and a
bundle. That needs a Mac to verify and there is none — naming the binary lets a
reader see a mismatch without being told a mechanism that might be wrong.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from yazses.platform.macos.permissions import _BUNDLE_ID, MacosPermissions


@pytest.fixture
def advice() -> str:
    return MacosPermissions().how_to_grant()


def test_it_still_says_the_obvious_thing_first(advice: str) -> None:
    """The new text is an addition. Losing the actual instruction would be worse."""
    assert "Privacy & Security" in advice
    assert "Accessibility" in advice
    assert "x-apple.systempreferences" in advice


def test_it_answers_the_already_enabled_case(advice: str) -> None:
    """The reported state: the toggle is on and the check still says denied."""
    low = advice.lower()
    assert "unsigned" in low, "never explains why an enabled toggle can be stale"
    assert "still denied" in low or "still looks on" in low


def test_it_names_the_program_it_actually_asked_about(advice: str) -> None:
    assert sys.executable in advice


def test_the_tccutil_advice_is_scoped_to_this_app(advice: str) -> None:
    """A bare reset clears every application's grant — far worse than the problem.

    This is the assertion most worth having: the destructive form is one word
    shorter and is what a hurried edit would leave behind.
    """
    assert f"tccutil reset Accessibility {_BUNDLE_ID}" in advice
    bare = re.findall(r"tccutil reset Accessibility(?!\s+\S)", advice)
    assert not bare, "advised the unscoped reset, which wipes every app's grant"


def test_it_says_why_the_bundle_id_is_there(advice: str) -> None:
    """Otherwise the next reader 'simplifies' it back to the destructive form."""
    assert "every app" in advice.lower()


def test_the_bundle_id_matches_what_the_app_is_actually_built_with() -> None:
    """A tccutil reset naming the wrong bundle silently does nothing at all."""
    spec = (Path(__file__).resolve().parents[1]
            / "packaging" / "macos" / "yazses.spec").read_text()
    ids = set(re.findall(r'CFBundleIdentifier"\s*:\s*"([^"]+)"', spec))
    ids |= set(re.findall(r'bundle_identifier\s*=\s*"([^"]+)"', spec))
    assert ids, "no bundle identifier found in the spec — this guard stopped guarding"
    assert ids == {_BUNDLE_ID}, f"spec says {ids}, permissions.py says {_BUNDLE_ID!r}"


def test_doctor_puts_it_in_front_of_someone_who_is_blocked(mocker) -> None:
    """The advice is only worth writing if the failing row carries it."""
    from yazses.platform.base import PermissionState
    from yazses.system.doctor import _keyboard_capture_check

    perms = mocker.MagicMock()
    perms.check_keyboard_capture.return_value = PermissionState.DENIED
    perms.how_to_grant.return_value = MacosPermissions().how_to_grant()

    name, status, detail = _keyboard_capture_check(perms, "darwin")
    assert name == "Keyboard capture"
    assert status == "FAIL"
    assert "unsigned" in detail.lower()
    assert _BUNDLE_ID in detail
