"""Snap-confinement detection and the advice it drives (issue #44).

The bug being pinned here is not a crash: it is *impossible advice*. Inside a
strictly confined snap, `yazses doctor` told users to join the `input` group,
which can never grant `/dev/input` access because snapd — not the group — is
what blocks it. Users followed it in circles.
"""

from __future__ import annotations

from yazses.platform import PermissionState
from yazses.platform.linux.permissions import LinuxPermissions
from yazses.system import doctor
from yazses.system.snap import in_snap, in_strict_snap, keyboard_capture_advice

# ---- detection -------------------------------------------------------------


def test_not_in_snap_when_no_snap_env():
    assert in_snap({}) is False
    assert in_strict_snap({}) is False


def test_in_snap_via_snap_name_or_snap():
    assert in_snap({"SNAP_NAME": "yazses"}) is True
    assert in_snap({"SNAP": "/snap/yazses/42"}) is True


def test_strict_is_assumed_when_confinement_unset():
    # snapd normally sets SNAP_CONFINEMENT; if it is missing we must not guess
    # "unconfined", because that would restore the impossible advice.
    assert in_strict_snap({"SNAP_NAME": "yazses"}) is True


def test_strict_confinement_is_detected():
    assert in_strict_snap({"SNAP_NAME": "yazses", "SNAP_CONFINEMENT": "strict"}) is True


def test_classic_and_devmode_are_not_strict():
    # These do get raw device access, so the group advice is fine there.
    assert in_strict_snap({"SNAP_NAME": "yazses", "SNAP_CONFINEMENT": "classic"}) is False
    assert in_strict_snap({"SNAP_NAME": "yazses", "SNAP_CONFINEMENT": "devmode"}) is False
    assert in_strict_snap({"SNAP_NAME": "yazses", "SNAP_CONFINEMENT": "Classic"}) is False


# ---- the advice itself -----------------------------------------------------


def test_advice_names_the_interface_not_the_group():
    advice = keyboard_capture_advice({"SNAP_NAME": "yazses"})
    assert "snap connect yazses:raw-input" in advice
    assert "raw-input" in advice
    # The whole point: the group fix must not be offered here.
    assert "usermod" not in advice


def test_advice_uses_the_instance_name_for_parallel_installs():
    advice = keyboard_capture_advice(
        {"SNAP_NAME": "yazses", "SNAP_INSTANCE_NAME": "yazses_beta"}
    )
    assert "snap connect yazses_beta:raw-input" in advice


def test_advice_offers_an_unconfined_escape_hatch():
    advice = keyboard_capture_advice({"SNAP_NAME": "yazses"})
    assert "pipx install yazses" in advice


# ---- doctor wiring ---------------------------------------------------------


def _denied_perms(monkeypatch):
    perms = LinuxPermissions()
    monkeypatch.setattr(perms, "check_keyboard_capture", lambda: PermissionState.DENIED)
    monkeypatch.setattr(perms, "how_to_grant", lambda: "Ask an administrator.")
    return perms


def test_doctor_gives_snap_advice_instead_of_the_group_advice(monkeypatch):
    perms = _denied_perms(monkeypatch)
    monkeypatch.setattr(doctor, "in_strict_snap", lambda: True)

    name, status, detail = doctor._keyboard_capture_check(perms, "linux")
    rendered = doctor._format_check(name, status, detail)

    assert status == "FAIL"
    assert "raw-input" in rendered
    assert "usermod" not in rendered


def test_snap_branch_wins_over_pending_relogin(monkeypatch):
    # Being mid-relogin is irrelevant inside a snap; the group was never the
    # barrier, so that message would still send the user in a circle.
    perms = _denied_perms(monkeypatch)
    monkeypatch.setattr(doctor, "in_strict_snap", lambda: True)
    monkeypatch.setattr(doctor, "_input_group_pending_relogin", lambda: True)

    _name, _status, detail = doctor._keyboard_capture_check(perms, "linux")
    assert "raw-input" in detail
    # The advice may *name* the group to explain why it is not the fix; what it
    # must not do is tell the user to log out and back in.
    assert "log out and back in" not in detail.lower()
    assert "session started before" not in detail.lower()


def test_outside_a_snap_the_group_advice_is_unchanged(monkeypatch):
    perms = _denied_perms(monkeypatch)
    monkeypatch.setattr(doctor, "in_strict_snap", lambda: False)
    monkeypatch.setattr(doctor, "_input_group_pending_relogin", lambda: False)

    _name, _status, detail = doctor._keyboard_capture_check(perms, "linux")
    assert "sudo usermod -aG input $USER" in detail
    assert "raw-input" not in detail


def test_granted_capture_never_mentions_snap(monkeypatch):
    perms = LinuxPermissions()
    monkeypatch.setattr(perms, "check_keyboard_capture", lambda: PermissionState.OK)
    monkeypatch.setattr(doctor, "in_strict_snap", lambda: True)

    _name, status, detail = doctor._keyboard_capture_check(perms, "linux")
    assert status == "OK"
    assert "raw-input" not in detail
