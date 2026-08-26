"""`yazses setup` inside a strictly confined snap.

Three defects, reported from a real `snap install yazses` on Ubuntu, all with the
same root: `system/setup.py` provisions the machine as if it owned it, and inside
strict confinement it owns nothing.

1. `apply_plan` crashed with a raw `PermissionError` traceback. `check=False`
   suppresses a non-zero *exit*; it does nothing about a binary that cannot be
   *exec'd*, and AppArmor denies `sudo` to a confined snap. The same module already
   guards `snapctl` with `except (FileNotFoundError, OSError)` — the guard existed
   in one place and not the one that runs commands.
2. `build_plan` proposed `usermod -aG input`, the single piece of advice
   `system/snap.py` was written to eliminate (issue #44): inside confinement the
   barrier is snapd, not the group, so the user joins it, logs out, logs back in,
   and gets the identical `denied`. It also proposed host packages a snap can
   neither install nor see.
3. `next_steps` — the "things you must do yourself" checklist, i.e. the one place
   that *should* have carried it — never mentioned `snap connect yazses:raw-input`
   at all, while `preflight_hints` had known about it all along.
"""

from __future__ import annotations

import os

import pytest

# `apply_plan`'s `input`-group step resolves the login name through `_current_user`,
# which imports the Unix-only `pwd`. The module is deliberately importable on Windows
# (`yazses setup` returns early there), so the step itself is POSIX-only -- the same
# split `tests/test_setup.py` already draws.
posix_only = pytest.mark.skipif(
    os.name != "posix",
    reason="the `input`-group step resolves a POSIX login name (`pwd`)",
)

from yazses.system import setup

SNAP_ENV = {
    "SNAP_NAME": "yazses",
    "SNAP": "/snap/yazses/348",
    "SNAP_CONFINEMENT": "strict",
    "WAYLAND_DISPLAY": "wayland-0",
}


def _bare_plan(env, **kw):
    """The plan for a machine where nothing is provisioned — the worst case."""
    return setup.build_plan(
        env,
        which=lambda cmd: None,
        portaudio_present=lambda: False,
        user="mohsen",
        user_in_input_group=lambda u: False,
        **kw,
    )


# --- 1. an un-exec'able command must not escape as a traceback ----------------

@pytest.mark.parametrize(
    "exc",
    [
        PermissionError(13, "Permission denied", "sudo"),   # AppArmor denies exec
        FileNotFoundError(2, "No such file or directory", "sudo"),  # no sudo at all
        OSError(8, "Exec format error", "sudo"),
    ],
    ids=["denied", "absent", "unexecutable"],
)
def test_apply_plan_survives_a_command_it_cannot_execute(exc):
    def runner(argv, **kw):
        raise exc

    said: list[str] = []
    plan = setup.SetupPlan(apt_packages=["libportaudio2"], session="x11")
    ok = setup.apply_plan(
        plan, runner=runner, echo=said.append, has_apt=lambda: True
    )

    assert ok is False, "a step that could not run is not a success"
    assert any("apt-get" in line for line in said), (
        f"the failure must name the command that could not run: {said}"
    )


@posix_only
def test_apply_plan_reports_every_failed_step_not_just_the_first():
    """A plan is best-effort: one un-exec'able command must not abort the rest."""
    attempted: list[str] = []

    def runner(argv, **kw):
        attempted.append(argv[0])
        raise PermissionError(13, "Permission denied", argv[0])

    plan = setup.SetupPlan(
        apt_packages=["libportaudio2"],
        add_to_input_group=True,
        session="x11",
    )
    ok = setup.apply_plan(plan, runner=runner, echo=lambda *a: None, has_apt=lambda: True)

    assert ok is False
    assert "sudo" in attempted, "usermod step must still be attempted after apt failed"


# --- 2. confinement must not be handed advice that cannot work ----------------

def test_confined_snap_is_never_told_to_join_the_input_group():
    """Issue #44: the barrier is snapd, not the group. `system/snap.py` exists to
    say so, and the planner never asked it."""
    plan = _bare_plan(SNAP_ENV)
    assert plan.add_to_input_group is False


def test_confined_snap_is_not_told_to_install_host_packages():
    """A snap has its own read-only rootfs: it can neither run the package manager
    nor benefit from a host install, and `shutil.which` inside its mount namespace
    is not answering about the host in the first place."""
    plan = _bare_plan(SNAP_ENV)
    assert plan.apt_packages == []


def test_confined_snap_does_not_write_a_ydotoold_unit_systemd_cannot_read():
    """XDG_CONFIG_HOME inside a snap points at ~/snap/yazses/<rev>/.config, which
    the user's systemd never scans — the unit would be written nowhere."""
    plan = _bare_plan(SNAP_ENV)
    assert plan.setup_ydotoold is False


def test_confined_plan_says_why_rather_than_claiming_the_machine_is_ready():
    """Emptying the plan must not silently become 'all requirements satisfied' —
    that is a false statement on the one command whose job is prerequisites."""
    plan = _bare_plan(SNAP_ENV)
    assert plan.confined is True
    assert plan.notes, "a confined plan must explain why it is empty"
    assert any("snap" in n.lower() for n in plan.notes)


def test_a_classic_snap_is_provisioned_normally():
    """Classic confinement has the host's filesystem and no AppArmor sandbox, so
    the ordinary plan is correct there. Only *strict* is the special case."""
    plan = _bare_plan({**SNAP_ENV, "SNAP_CONFINEMENT": "classic"})
    assert plan.confined is False
    assert plan.add_to_input_group is True
    assert plan.apt_packages


def test_an_ordinary_install_is_unaffected():
    plan = _bare_plan({"WAYLAND_DISPLAY": "wayland-0"})
    assert plan.confined is False
    assert plan.add_to_input_group is True
    assert plan.setup_ydotoold is True
    assert "libportaudio2" in plan.apt_packages


# --- 3. the checklist must carry the step that actually works -----------------

def test_next_steps_tells_a_confined_snap_to_connect_raw_input():
    plan = _bare_plan(SNAP_ENV)
    steps = setup.next_steps(
        SNAP_ENV, plan=plan, mic_pending=True, rawinput_pending=True, pending_relogin=False
    )
    commands = [s.command for s in steps]
    assert "sudo snap connect yazses:raw-input" in commands


def test_next_steps_never_tells_a_confined_snap_to_run_usermod():
    plan = _bare_plan(SNAP_ENV)
    steps = setup.next_steps(
        SNAP_ENV, plan=plan, mic_pending=True, rawinput_pending=True, pending_relogin=True
    )
    commands = " ".join(s.command for s in steps)
    assert "usermod" not in commands, (
        "the loop that can never succeed (issue #44) must not be in the checklist"
    )


def test_next_steps_connects_the_mic_before_the_hotkey():
    """Both interfaces are one-time connects; order them the way install reads."""
    plan = _bare_plan(SNAP_ENV)
    steps = setup.next_steps(
        SNAP_ENV, plan=plan, mic_pending=True, rawinput_pending=True, pending_relogin=False
    )
    commands = [s.command for s in steps]
    assert commands.index("sudo snap connect yazses:audio-record") < commands.index(
        "sudo snap connect yazses:raw-input"
    )


def test_connected_interfaces_produce_no_connect_steps():
    plan = _bare_plan(SNAP_ENV)
    steps = setup.next_steps(
        SNAP_ENV, plan=plan, mic_pending=False, rawinput_pending=False, pending_relogin=False
    )
    assert not any("snap connect" in s.command for s in steps)


def test_an_ordinary_install_still_gets_the_usermod_step():
    """The #44 suppression is scoped to confinement — it must not disarm the real
    advice everywhere else."""
    env = {"WAYLAND_DISPLAY": "wayland-0"}
    plan = _bare_plan(env)
    steps = setup.next_steps(
        env, plan=plan, mic_pending=False, rawinput_pending=False, pending_relogin=False
    )
    assert any("usermod -aG input" in s.command for s in steps)
