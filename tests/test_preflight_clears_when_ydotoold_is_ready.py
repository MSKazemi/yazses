"""A provisioned Wayland machine must stop being told to provision itself.

`build_plan().setup_ydotoold` answers "will `yazses setup` write the ydotoold unit?",
and on Wayland that is unconditionally true -- writing it is idempotent, so the planner
never probes. `preflight_hints` read the same flag as "ydotoold is missing", which made
`yazses start` print

    ACTION NEEDED
      Missing prerequisites: ydotoold (Wayland injection).

on EVERY start of a fully provisioned Wayland desktop, and nothing could ever clear it:
running the recommended `yazses setup` changed no input the check looked at.

Measured on a real machine (Ubuntu, GNOME Wayland): ydotoold installed at /usr/bin/ydotoold,
its user unit `enabled` + `active` and logging "accepted client", the udev rule byte-identical
to `UINPUT_UDEV_RULE`, `input` membership in effect -- `build_plan()` returned
`apt_packages=[]`, `add_to_input_group=False`, `install_udev_rule=False` and
`setup_ydotoold=True`, the lone True. The daemon chose `YdotoolInjector` while the warning
insisted the "Remote Desktop" portal would be used instead.

That is ADR-021's dismissed guard (rule 9: a guard is judged on how rarely it fires): one
that fires on 100% of a platform's starts trains the user to skip the whole block, including
the days it is telling the truth.
"""
from yazses.system.setup import SetupPlan, preflight_hints


def _wayland_plan(**kw) -> SetupPlan:
    plan = SetupPlan(session="wayland")
    plan.setup_ydotoold = True  # always true on Wayland -- a plan step, not a deficiency
    for k, v in kw.items():
        setattr(plan, k, v)
    return plan


def test_no_hint_when_ydotoold_is_actually_ready():
    """The regression: fully provisioned Wayland, nothing left to say."""
    hints = preflight_hints(
        {}, plan=_wayland_plan(), pending_relogin=False, ydotool_ready=lambda: True
    )
    assert hints == [], f"warned a fully provisioned machine: {hints!r}"


def test_hint_still_fires_when_ydotoold_is_not_ready():
    """The permissive direction is half the relationship -- prove it still warns."""
    hints = preflight_hints(
        {}, plan=_wayland_plan(), pending_relogin=False, ydotool_ready=lambda: False
    )
    assert len(hints) == 1
    assert "ydotoold (Wayland injection)" in hints[0]
    assert "yazses setup" in hints[0]
    assert "Remote Desktop" in hints[0]


def test_other_prerequisites_are_unaffected_by_a_ready_ydotoold():
    """A ready ydotoold must not silence a genuinely missing package or group."""
    plan = _wayland_plan(apt_packages=["wl-clipboard"], add_to_input_group=True)
    hints = preflight_hints(
        {}, plan=plan, pending_relogin=False, ydotool_ready=lambda: True
    )
    assert len(hints) == 1
    assert "wl-clipboard" in hints[0]
    assert "`input` group membership" in hints[0]
    # ...but it must no longer claim ydotoold is missing, nor threaten the portal.
    assert "ydotoold" not in hints[0]
    assert "Remote Desktop" not in hints[0]


def test_a_readiness_probe_that_raises_does_not_block_startup():
    """`preflight_hints` runs on the `yazses start` path; it may never raise."""
    def boom() -> bool:
        raise OSError("socket stat exploded")

    hints = preflight_hints(
        {}, plan=_wayland_plan(), pending_relogin=False, ydotool_ready=boom
    )
    # Falls back to the old conservative answer rather than crashing the daemon.
    assert len(hints) == 1
    assert "ydotoold (Wayland injection)" in hints[0]
