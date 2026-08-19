"""`yazses doctor` reported a broken login service and no way to fix it.

Two branches, on the page someone opens when the daemon is running the wrong build:

    [FAIL] systemd unit: ExecStart=… does not exist — the service crash-loops
           (status 203/EXEC) … Point the unit at your real binary or reinstall.

    [WARN] systemd unit: ExecStart=… differs from the yazses-daemon on PATH (…)
           — the service may run a different or older build

The first offers "reinstall", which is drastic and unnecessary. The second offers nothing.
And a repair already exists: `LinuxLifecycle.install_autostart` regenerates the unit from
`autostart.resolve_daemon_command()` whenever `autostart.needs_rewrite` says the recorded
path has moved — which is precisely both of these situations. `yazses autostart enable` is
the only command that reaches it.

## Why the message names *which* install

`resolve_daemon_command` prefers the console script next to the **running interpreter**, so
the unit ends up pointing at whichever install ran the command. That is right, and it is
also the one thing a user must know here, because this warning only fires when there is
more than one install — advising "run `yazses autostart enable`" without saying which one
would be a coin flip on the machine that produced the warning.

Same shape as three other fixes in this sweep: a diagnosis with no remedy, at the end of a
path the product itself sent you down. This one is narrower than those because the fault
was already named correctly; only the next step was missing.
"""

from __future__ import annotations

import pytest

from yazses.platform.linux import autostart


def test_the_repair_command_exists_and_rewrites_a_moved_unit() -> None:
    """The premise: there is something to recommend.

    `needs_rewrite` is what makes `yazses autostart enable` a repair rather than a no-op.
    """
    wanted = autostart.unit_text("/new/place/yazses-daemon")
    stale = autostart.unit_text("/old/place/yazses-daemon")
    assert autostart.needs_rewrite(stale, wanted) is True
    assert autostart.needs_rewrite(None, wanted) is True
    assert autostart.needs_rewrite(wanted, wanted) is False


def test_install_autostart_is_what_reaches_it() -> None:
    """If the repair moves, the advice below has to move with it."""
    import inspect

    from yazses.platform.linux.lifecycle import LinuxLifecycle

    source = inspect.getsource(LinuxLifecycle.install_autostart)
    assert "needs_rewrite" in source
    assert "write_text" in source


@pytest.mark.parametrize("status", ["FAIL", "WARN"])
def test_both_systemd_branches_name_the_repair(status: str) -> None:
    """Asserted on the source, because producing both rows needs a live systemd unit.

    Weaker than driving the function, and chosen deliberately over skipping the check on
    any machine without a user unit — which is every CI runner.
    """
    import inspect

    from yazses.system import doctor

    source = inspect.getsource(doctor)
    marker = {
        "FAIL": "does not exist — the service crash-loops",
        "WARN": "differs from the yazses-daemon on PATH",
    }[status]
    start = source.index(marker)
    window = source[start : start + 600]
    assert "yazses autostart enable" in window, (
        f"the {status} systemd branch names the fault and no remedy"
    )


def test_the_warning_says_which_install_the_unit_will_follow() -> None:
    """The one thing a user must know, and only relevant when this warning fires.

    `resolve_daemon_command` prefers the console script beside the running interpreter, so
    the unit follows whichever install runs the command — and this warning only appears
    when there is more than one.
    """
    import inspect

    from yazses.system import doctor

    source = inspect.getsource(doctor)
    start = source.index("differs from the yazses-daemon on PATH")
    window = source[start : start + 600]
    assert "run it from that install" in window


def test_the_fail_branch_no_longer_recommends_reinstalling() -> None:
    """Drastic, and unnecessary when one command rewrites the unit."""
    import inspect

    from yazses.system import doctor

    source = inspect.getsource(doctor)
    start = source.index("does not exist — the service crash-loops")
    window = source[start : start + 600]
    assert "reinstall" not in window


def test_resolve_daemon_command_prefers_this_install() -> None:
    """The behaviour the advice describes; if it changed, the advice is wrong."""
    import inspect

    source = inspect.getsource(autostart.resolve_daemon_command)
    assert "sys.executable" in source
    assert source.index("sibling") < source.index('shutil.which("yazses-daemon")')
