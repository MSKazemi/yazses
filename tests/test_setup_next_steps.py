"""`setup.next_steps()` — the ordered install checklist of manual actions.

Everything a fresh install still needs the user to do themselves must be surfaced
in order: connect the mic (snap), join `input`, re-login, calibrate the voice, and
start dictating. This locks that contract so no step can silently go missing.
"""
from __future__ import annotations

from yazses.system import setup


def _titles(steps):
    return [s.title for s in steps]


def _commands(steps):
    return [s.command for s in steps]


def test_snap_bare_machine_lists_every_manual_step_in_order():
    plan = setup.SetupPlan(add_to_input_group=True, session="wayland")
    steps = setup.next_steps(
        {"SNAP_NAME": "yazses"}, plan=plan, mic_pending=True, pending_relogin=False
    )
    cmds = _commands(steps)
    # Ordered: mic connect → usermod → re-login → calibrate → start.
    assert "sudo snap connect yazses:audio-record" in cmds
    assert "sudo usermod -aG input $USER" in cmds
    assert "" in cmds  # the log-out/in action has no command
    assert "yazses mic-level --set" in cmds
    assert "yazses start" in cmds
    assert cmds.index("sudo snap connect yazses:audio-record") < cmds.index(
        "sudo usermod -aG input $USER"
    )
    assert cmds.index("yazses mic-level --set") < cmds.index("yazses start")


def test_apt_install_omits_snap_mic_step():
    # Not a snap → no audio-record connect; mic access is granted by apt directly.
    plan = setup.SetupPlan(add_to_input_group=True, session="x11")
    steps = setup.next_steps({}, plan=plan, mic_pending=False, pending_relogin=False)
    assert not any("snap connect" in c for c in _commands(steps))
    assert "sudo usermod -aG input $USER" in _commands(steps)


def test_relogin_step_when_membership_pending_even_without_usermod():
    # Already in the group per /etc/group but this session predates it → must re-login.
    plan = setup.SetupPlan(add_to_input_group=False, session="x11")
    steps = setup.next_steps({}, plan=plan, mic_pending=False, pending_relogin=True)
    assert any(s.command == "" for s in steps)  # the re-login action
    assert any("log out" in s.title.lower() for s in steps)


def test_calibrate_and_start_always_present():
    # Even a fully provisioned machine should be told to calibrate + start.
    plan = setup.SetupPlan(session="x11")
    steps = setup.next_steps({}, plan=plan, mic_pending=False, pending_relogin=False)
    assert "yazses mic-level --set" in _commands(steps)
    assert "yazses start" in _commands(steps)


def test_every_step_has_a_reason():
    plan = setup.SetupPlan(add_to_input_group=True, session="wayland")
    steps = setup.next_steps(
        {"SNAP_NAME": "yazses"}, plan=plan, mic_pending=True, pending_relogin=True
    )
    assert steps and all(s.title and s.why for s in steps)
