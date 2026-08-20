"""A refused microphone must be answered on the OS the reader is sitting at.

`doctor`'s microphone row ended at the bare word `denied` on every platform. The
`PermissionsBackend` protocol carried exactly one remedy, `how_to_grant()`, and
`_keyboard_capture_check` was its only caller -- so:

* macOS, where the microphone is a real per-app TCC service and can genuinely be
  refused, printed `denied` and nothing else. Sending that reader to the one
  message that existed would have been worse than silence: it names Accessibility,
  a different service, whose toggle is probably already on.
* Windows had the right words in the wrong place. `WindowsPermissions.how_to_grant()`
  was almost entirely microphone text (`ms-settings:privacy-microphone`), and it is
  only ever printed on the keyboard row -- where `check_keyboard_capture()` always
  answers OK. Unreachable advice, beside a row that renders `denied`.
* And when PortAudio could not load at all, every OS was told
  `sudo apt install libportaudio2` -- including the two that have no apt, and where
  the sounddevice wheel bundles PortAudio so the real cause is a partial install.

These tests are all pure: the remedies are strings on classes that import lazily,
so a Linux box can check what a Mac and a Windows machine would be told.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from yazses.platform.base import (
    LINUX_PLATFORM_NAME,
    MACOS_PLATFORM_NAME,
    WINDOWS_PLATFORM_NAME,
    PermissionsBackend,
)
from yazses.platform.linux.permissions import LinuxPermissions
from yazses.platform.macos.permissions import _BUNDLE_ID, MacosPermissions
from yazses.platform.windows.permissions import WindowsPermissions
from yazses.system.doctor import microphone_detail, portaudio_advice

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = {
    LINUX_PLATFORM_NAME: LinuxPermissions,
    MACOS_PLATFORM_NAME: MacosPermissions,
    WINDOWS_PLATFORM_NAME: WindowsPermissions,
}


# ---- every backend answers, and answers about the microphone ------------


def test_the_protocol_declares_the_microphone_remedy():
    assert hasattr(PermissionsBackend, "how_to_grant_microphone")


@pytest.mark.parametrize("name,cls", sorted(BACKENDS.items()))
def test_every_backend_has_a_microphone_remedy(name, cls):
    advice = cls().how_to_grant_microphone()
    assert isinstance(advice, str) and advice.strip(), name


@pytest.mark.parametrize("name,cls", sorted(BACKENDS.items()))
def test_the_microphone_remedy_is_about_the_microphone(name, cls):
    """Not the keyboard one under a new name: the two are different panes."""
    advice = cls().how_to_grant_microphone().lower()
    assert "microphone" in advice or "mic" in advice, name
    assert advice != cls().how_to_grant().lower(), name


def test_backends_were_actually_collected():
    """This file is parametrized over a dict; an empty one would pass silently."""
    assert len(BACKENDS) == 3


# ---- macOS: the right service, scoped, and the never-asked case ---------


def test_the_macos_remedy_names_the_microphone_pane_not_accessibility():
    advice = MacosPermissions().how_to_grant_microphone()
    assert "Privacy_Microphone" in advice
    assert "Privacy_Accessibility" not in advice


def test_the_macos_reset_is_scoped_to_this_app():
    """`tccutil reset Microphone` with no bundle id clears every app's grant."""
    advice = MacosPermissions().how_to_grant_microphone()
    assert f"tccutil reset Microphone {_BUNDLE_ID}" in advice
    unscoped = re.findall(r"tccutil reset Microphone(?!\s+\S)", advice)
    assert not unscoped, unscoped


def test_the_macos_remedy_covers_never_having_been_asked():
    """`AVCaptureDevice` reports NotDetermined until something records, so the
    prompt has not appeared yet -- hunting through Settings finds nothing."""
    advice = MacosPermissions().how_to_grant_microphone().lower()
    assert "hold the hotkey" in advice


def test_the_two_macos_remedies_do_not_send_the_reader_to_the_other_pane():
    perms = MacosPermissions()
    assert "Privacy_Microphone" not in perms.how_to_grant()
    assert "Accessibility" not in perms.how_to_grant_microphone().replace(
        "not Accessibility", ""
    )


# ---- Windows: the advice moved to the row that can fail -----------------


def test_the_windows_microphone_pane_is_now_on_the_microphone_remedy():
    assert "ms-settings:privacy-microphone" in WindowsPermissions().how_to_grant_microphone()


def test_the_windows_keyboard_remedy_no_longer_hides_the_microphone_pane():
    """It is printed on a check that always answers OK, so anything only said
    there is said nowhere."""
    assert "ms-settings:privacy-microphone" not in WindowsPermissions().how_to_grant()


def test_the_windows_keyboard_remedy_still_explains_elevation():
    assert "elevated" in WindowsPermissions().how_to_grant().lower()


# ---- PortAudio advice matches the operating system ----------------------


@pytest.mark.parametrize(
    "platform_name,wrong",
    [
        (MACOS_PLATFORM_NAME, "apt install"),
        (WINDOWS_PLATFORM_NAME, "apt install"),
        (WINDOWS_PLATFORM_NAME, "sudo"),
        ("freebsd14", "apt install"),
    ],
)
def test_no_os_is_handed_a_package_manager_it_does_not_have(platform_name, wrong):
    assert wrong not in portaudio_advice(platform_name)


def test_debian_still_gets_the_apt_line_it_needs():
    """The commonest real cause on Linux; the fix must not lose it."""
    advice = portaudio_advice(LINUX_PLATFORM_NAME)
    assert "sudo apt install libportaudio2" in advice


def test_each_platform_gets_a_distinct_portaudio_answer():
    answers = {
        portaudio_advice(name)
        for name in (LINUX_PLATFORM_NAME, MACOS_PLATFORM_NAME, WINDOWS_PLATFORM_NAME, "freebsd14")
    }
    assert len(answers) == 4


# ---- the row itself -----------------------------------------------------


def test_a_denied_microphone_no_longer_ends_at_the_bare_word():
    detail = microphone_detail(
        "denied",
        snap_pending=False,
        no_portaudio=False,
        platform_name=MACOS_PLATFORM_NAME,
        advice=MacosPermissions().how_to_grant_microphone(),
    )
    assert detail != "denied"
    assert "Privacy_Microphone" in detail


def test_the_snap_answer_still_wins_over_the_os_remedy():
    """Inside the snap the cause is the un-connected interface, and that answer
    must not be displaced by a generic pane."""
    detail = microphone_detail(
        "denied",
        snap_pending=True,
        no_portaudio=True,
        platform_name=LINUX_PLATFORM_NAME,
        advice="GENERIC",
    )
    assert "snap connect" in detail
    assert "GENERIC" not in detail


def test_portaudio_still_wins_over_the_os_remedy():
    """A runtime that cannot load is not a permission; a settings pane cannot fix it."""
    detail = microphone_detail(
        "unknown",
        snap_pending=False,
        no_portaudio=True,
        platform_name=LINUX_PLATFORM_NAME,
        advice="GENERIC",
    )
    assert "libportaudio2" in detail
    assert "GENERIC" not in detail


def test_doctor_passes_both_new_arguments_at_the_call_site():
    """A pure helper improved in isolation changes no output. The previous version
    of this defect was exactly that shape: good advice, never reached."""
    source = (ROOT / "src" / "yazses" / "system" / "doctor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "microphone_detail"
    ]
    assert len(calls) == 1, calls
    kwargs = {kw.arg for kw in calls[0].keywords}
    assert {"platform_name", "advice"} <= kwargs, kwargs
    assert "perms.how_to_grant_microphone()" in source
