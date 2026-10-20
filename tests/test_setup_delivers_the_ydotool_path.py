"""`yazses setup` must be able to actually deliver the ydotool path on Wayland.

It could not. Two independent gaps, both verified on a stock Ubuntu 24.04:

1. `APT_PACKAGES` installed the `ydotool` client but not `ydotoold` — a *separate*
   package on Debian/Ubuntu (`dpkg -L ydotool` lists one binary). So setup wrote a
   systemd unit whose `ExecStart=/usr/bin/ydotoold` pointed at nothing, the socket
   never appeared, and `preflight_hints` reported "Missing prerequisites: ydotoold"
   forever — telling the user to run the command that could never fix it.
2. No udev rule existed anywhere in the repo. `/dev/uinput` is `0600 root:root`, so
   even a member of `input` cannot open it, and a user-level ydotoold fails.

Together they made the RemoteDesktop portal the de-facto default on Ubuntu Wayland,
which is what puts a permanent screen-sharing indicator on an offline-first app.
"""

from __future__ import annotations

import pytest

from yazses.system import setup

# What a machine with nothing installed looks like to `which`.
NOTHING = None


def _plan(session="wayland", *, installed=(), rule=None, in_group=True):
    return setup.build_plan(
        {"WAYLAND_DISPLAY": "wayland-0"} if session == "wayland" else {"DISPLAY": ":0"},
        which=lambda name: f"/usr/bin/{name}" if name in installed else NOTHING,
        portaudio_present=lambda: True,
        user="tester",
        user_in_input_group=lambda _u: in_group,
        read_udev_rule=lambda: rule,
    )


# ---------------------------------------------------------------- the daemon


def test_the_daemon_package_is_installed_not_just_the_client():
    """The bug: the unit pointed at a binary the plan never installed."""
    plan = _plan()
    assert "ydotoold" in plan.apt_packages


def test_the_daemon_is_not_reinstalled_when_present():
    plan = _plan(installed=("ydotoold",))
    assert "ydotoold" not in plan.apt_packages


# ------------------------------------------------------------------ the rule


def test_a_wayland_machine_with_no_rule_plans_to_install_one():
    plan = _plan(rule=None)
    assert plan.install_udev_rule is True


def test_a_machine_that_already_has_our_rule_plans_nothing():
    plan = _plan(rule=setup.UINPUT_UDEV_RULE)
    assert plan.install_udev_rule is False


def test_a_drifted_rule_is_repaired_rather_than_trusted():
    """A hand-edited or superseded copy must not be left in place — it is the file
    that decides whether the device can be opened at all."""
    plan = _plan(rule='KERNEL=="uinput", MODE="0666"\n')
    assert plan.install_udev_rule is True


def test_x11_needs_no_rule():
    """xdotool goes through the X server and never touches /dev/uinput."""
    plan = _plan(session="x11", rule=None)
    assert plan.install_udev_rule is False
    assert plan.setup_ydotoold is False


def test_the_rule_counts_towards_there_being_work_to_do():
    """`is_noop` drives the 'nothing to do' message; a missing rule is work."""
    plan = setup.SetupPlan(install_udev_rule=True)
    assert plan.is_noop is False


def test_the_plan_warns_that_a_relogin_is_required():
    """The rule only reaches a new session. Saying so is the difference between a
    user who succeeds and one who re-runs setup and sees nothing change."""
    plan = _plan(rule=None)
    assert any("log out" in note for note in plan.notes)


# ------------------------------------------------------- applying it safely


class _Runner:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        assert kwargs.get("check") is False, "apply_plan must never let a non-zero exit raise"
        return type("R", (), {"returncode": 0})()


def test_installing_the_rule_never_goes_through_a_shell(tmp_path):
    """Our rule text contains `==` and quotes. A `sudo sh -c 'echo ... >'` would put
    it through a shell; this module has never used shell=True and must not start."""
    runner = _Runner()
    plan = setup.SetupPlan(session="wayland", install_udev_rule=True)

    setup.apply_plan(plan, runner=runner, echo=lambda *_a: None, has_apt=lambda: True)

    assert runner.calls, "nothing was run"
    for argv in runner.calls:
        assert all(isinstance(part, str) for part in argv)
        assert "sh" not in argv and "bash" not in argv
        assert not any(">" in part for part in argv)


def test_the_rule_is_copied_reloaded_and_triggered():
    runner = _Runner()
    plan = setup.SetupPlan(session="wayland", install_udev_rule=True)

    setup.apply_plan(plan, runner=runner, echo=lambda *_a: None, has_apt=lambda: True)

    joined = [" ".join(c) for c in runner.calls]
    assert any(c.startswith("sudo cp ") and c.endswith(setup.UDEV_RULE_PATH) for c in joined)
    assert any("udevadm control --reload-rules" in c for c in joined)
    assert any("udevadm trigger" in c for c in joined)


def test_a_refused_sudo_is_absorbed_and_explained():
    """A confined or sudo-less machine must get the manual command, not a traceback."""
    said: list[str] = []

    def _boom(argv, **_kw):
        raise PermissionError(13, "Permission denied", "sudo")

    plan = setup.SetupPlan(session="wayland", install_udev_rule=True)
    ok = setup.apply_plan(plan, runner=_boom, echo=said.append, has_apt=lambda: True)

    assert ok is False
    assert any("udev" in line for line in said)


def test_a_confined_snap_never_plans_a_rule_it_cannot_install():
    """A strict snap has no package manager and cannot write /etc/udev — the portal
    is genuinely its only route, and advice it cannot follow is worse than none."""
    plan = setup.build_plan(
        {"WAYLAND_DISPLAY": "wayland-0", "SNAP": "/snap/yazses/1", "SNAP_NAME": "yazses"},
        which=lambda _n: NOTHING,
        portaudio_present=lambda: True,
        user="tester",
        user_in_input_group=lambda _u: False,
        read_udev_rule=lambda: None,
    )
    assert plan.confined is True
    assert plan.install_udev_rule is False
    assert plan.setup_ydotoold is False


# --------------------------------------------------------------- the enum bug


def test_the_documented_ydotool_backend_is_actually_accepted():
    """`config.py` documented `backend = "ydotool"` and `get_injector` honours it,
    but the validator's enum omitted it — so the loader reverted the user's
    documented choice to "auto" and said it "is not one of ..."."""
    from yazses.config import InjectionConfig
    from yazses.configcheck import build_section, enum_values

    assert "ydotool" in (enum_values("injection", "backend") or ())

    problems: list = []
    cfg = build_section(InjectionConfig, {"backend": "ydotool"}, "injection", problems)
    assert cfg.backend == "ydotool"
    assert not problems


@pytest.mark.parametrize("value", ["auto", "type", "ydotool", "clipboard", "wtype", "portal", "unicode"])
def test_every_documented_backend_survives_a_round_trip(value):
    from yazses.config import InjectionConfig
    from yazses.configcheck import build_section

    problems: list = []
    cfg = build_section(InjectionConfig, {"backend": value}, "injection", problems)
    assert cfg.backend == value, f"{value} was rejected: {problems}"
