"""macOS needs TWO grants for the dictation key, and YazSes only ever asked for one.

Reported on #182 by the first humans to run the macOS build (an M2 on Tahoe
26.6.x, and an M4 via the Homebrew cask). The state they described:

* **Accessibility** granted to YazSes and visible as an enabled toggle;
* `yazses doctor` reporting `[OK] Microphone` and one `[FAIL]` about
  Accessibility -- the permission that was already on;
* the dictation key doing **nothing**, in any application;
* **YazSes absent from Privacy -> Microphone entirely**, with no way to add it.

That reads as three unrelated bugs and is one. `MacosHotkey` observes the key
with a ``CGEventTap``, and since macOS 10.15 an observing keyboard tap requires
user approval of **Input Monitoring** in addition to Accessibility. YazSes never
checked that service, never requested it, and the bundle declared no
``NSInputMonitoringUsageDescription`` -- so the tap returned NULL, the hotkey
never fired, nothing ever opened the microphone, and macOS therefore never
showed the one-time microphone prompt that is what puts an app in that pane.

These tests pin the parts that are decidable without a Mac: that the service is
checked separately, that a missing IOKit answers UNKNOWN rather than a refusal
we cannot substantiate, that `doctor` grows a row for it on macOS and only on
macOS, that the remedy names the right pane, and that the bundle ships the usage
string. What they cannot prove is the fix on hardware -- that needs #182.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from yazses.platform.base import (
    LINUX_PLATFORM_NAME,
    MACOS_PLATFORM_NAME,
    WINDOWS_PLATFORM_NAME,
    PermissionState,
)
from yazses.platform.macos import permissions as perms_mod
from yazses.platform.macos.hotkey import tap_failure_message
from yazses.platform.macos.permissions import _BUNDLE_ID, MacosPermissions
from yazses.system.doctor import _input_monitoring_check

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "packaging" / "macos" / "yazses.spec"


class _FakeIOKit:
    """Stands in for the IOKit handle so the mapping is testable off a Mac."""

    def __init__(self, check: int | None = None, request: bool = False) -> None:
        self._check = check
        self._request = request
        self.asked_with: list[int] = []
        if check is None:  # emulate a pre-10.15 IOKit with no such symbol
            return
        self.IOHIDCheckAccess = self._make(lambda t: self._check)
        self.IOHIDRequestAccess = self._make(lambda t: self._request)

    def _make(self, fn):
        class _Fn:
            restype = None
            argtypes: list = []

            def __call__(_s, value):  # noqa: N805
                self.asked_with.append(int(value))
                return fn(value)

        return _Fn()

    def __getattr__(self, name: str):  # only reached when check is None
        raise AttributeError(name)


# ---- the service is read, and read correctly ----------------------------


@pytest.mark.parametrize(
    ("hid_status", "expected"),
    [
        (perms_mod._HID_ACCESS_GRANTED, PermissionState.OK),
        (perms_mod._HID_ACCESS_DENIED, PermissionState.DENIED),
        (perms_mod._HID_ACCESS_UNKNOWN, PermissionState.UNKNOWN),
    ],
)
def test_it_maps_every_iohid_access_value(
    monkeypatch: pytest.MonkeyPatch, hid_status: int, expected: PermissionState
) -> None:
    monkeypatch.setattr(perms_mod, "_iokit", lambda: _FakeIOKit(check=hid_status))
    assert MacosPermissions().check_input_monitoring() is expected


def test_it_asks_about_listening_not_posting(monkeypatch: pytest.MonkeyPatch) -> None:
    """`kIOHIDRequestTypePostEvent` is a different grant and would answer the
    wrong question -- the tap observes input, it does not synthesise it."""
    fake = _FakeIOKit(check=perms_mod._HID_ACCESS_GRANTED)
    monkeypatch.setattr(perms_mod, "_iokit", lambda: fake)
    MacosPermissions().check_input_monitoring()
    assert fake.asked_with == [perms_mod._HID_REQUEST_LISTEN_EVENT]
    assert perms_mod._HID_REQUEST_LISTEN_EVENT != 0, "post-event is 0; listen is 1"


def test_no_iokit_is_unknown_never_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """We could not ask. Reporting a refusal would send the reader to a pane to
    fix something we have no evidence is wrong."""
    monkeypatch.setattr(perms_mod, "_iokit", lambda: None)
    assert MacosPermissions().check_input_monitoring() is PermissionState.UNKNOWN
    assert MacosPermissions().request_input_monitoring() is False


def test_a_pre_1015_iokit_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(perms_mod, "_iokit", lambda: _FakeIOKit(check=None))
    assert MacosPermissions().check_input_monitoring() is PermissionState.UNKNOWN


def test_request_triggers_the_prompt_and_reports_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requesting is what puts the app in the list at all. An app that never
    asks does not appear there -- which is why "enable it in Settings" was not
    advice #182's reporter could act on."""
    fake = _FakeIOKit(check=perms_mod._HID_ACCESS_UNKNOWN, request=True)
    monkeypatch.setattr(perms_mod, "_iokit", lambda: fake)
    assert MacosPermissions().request_input_monitoring() is True
    assert fake.asked_with == [perms_mod._HID_REQUEST_LISTEN_EVENT]


# ---- doctor grows a row, on macOS and nowhere else -----------------------


class _Perms:
    def __init__(self, state: PermissionState) -> None:
        self._state = state

    def check_input_monitoring(self) -> PermissionState:
        return self._state

    def how_to_grant_input_monitoring(self) -> str:
        return "REMEDY-TEXT"


@pytest.mark.parametrize("other", [LINUX_PLATFORM_NAME, WINDOWS_PLATFORM_NAME])
def test_the_row_is_absent_off_macos(other: str) -> None:
    assert _input_monitoring_check(_Perms(PermissionState.DENIED), other) is None


@pytest.mark.parametrize(
    ("state", "status"),
    [
        (PermissionState.OK, "OK"),
        (PermissionState.DENIED, "FAIL"),
        # "never asked" and "refused" are one return value to a process that has
        # not asked yet. A red line in front of every new user would be wrong.
        (PermissionState.UNKNOWN, "WARN"),
    ],
)
def test_the_row_grades_each_state(state: PermissionState, status: str) -> None:
    row = _input_monitoring_check(_Perms(state), MACOS_PLATFORM_NAME)
    assert row is not None
    name, got, detail = row
    assert name == "Input monitoring"
    assert got == status
    if state is not PermissionState.OK:
        assert "REMEDY-TEXT" in detail


def test_a_backend_without_the_method_is_skipped_not_crashed() -> None:
    """`PermissionsBackend` is a runtime-checkable Protocol; this row uses
    `getattr` so an older or third-party backend is absent, not an exception."""

    class _Old:
        pass

    assert _input_monitoring_check(_Old(), MACOS_PLATFORM_NAME) is None


# ---- the remedies send the reader to the right place --------------------


def test_the_remedy_names_the_input_monitoring_pane() -> None:
    text = MacosPermissions().how_to_grant_input_monitoring()
    assert "Input Monitoring" in text
    assert "Privacy_ListenEvent" in text, "must open the pane it is talking about"
    assert f"tccutil reset ListenEvent {_BUNDLE_ID}" in text, (
        "a bare reset clears every app's grant on the Mac"
    )
    assert "not listed at all" in text.lower(), (
        "the reported state was an app absent from the pane, not a toggle turned off"
    )


def test_the_accessibility_remedy_points_at_the_second_switch() -> None:
    """The exact loop #182 was stuck in: re-toggling the permission that was
    already on, because nothing said there was another one."""
    text = MacosPermissions().how_to_grant()
    assert "Input Monitoring" in text


@pytest.mark.parametrize("granted", [True, False])
def test_a_null_tap_names_a_grant_we_actually_determined(granted: bool) -> None:
    msg = tap_failure_message(input_monitoring_granted=granted)
    assert "Input Monitoring" in msg
    if granted:
        # Do not repeat advice we know is not the problem.
        assert "Accessibility" in msg
        assert "enable YazSes" in msg
    else:
        assert "BOTH" in msg


# ---- the bundle declares the usage string -------------------------------


def _info_plist_keys() -> set[str]:
    """Read the spec's `info_plist=` dict out of the source, not by importing it
    (the spec runs under PyInstaller and pulls in the whole app to do it)."""
    tree = ast.parse(SPEC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "info_plist":
            assert isinstance(node.value, ast.Dict)
            return {
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    raise AssertionError("no info_plist= in the macOS spec")


def test_the_bundle_declares_an_input_monitoring_usage_string() -> None:
    """Without the string macOS may refuse the service without ever prompting --
    the spec's own comment says exactly this about the microphone, and the same
    trap was live for Input Monitoring."""
    keys = _info_plist_keys()
    assert "NSInputMonitoringUsageDescription" in keys
    # The two it already had, so this test fails a regression in either.
    assert "NSMicrophoneUsageDescription" in keys
