"""`build_plan` is the first thing `yazses setup` and `yazses quickstart` do, and it
raised `KeyError` for any uid with no `/etc/passwd` entry.

That is not an exotic machine. It is what `docker run --user 4242:4242` produces, and
what Kubernetes produces whenever `runAsUser` is an arbitrary uid -- and YazSes ships a
Docker image, so the path is reachable by design. `_current_user()` ended at
`pwd.getpwuid(os.getuid()).pw_name` with nothing after it.

The two commands failed *differently*, which is why it stayed hidden:

* `yazses setup` did not guard the call and exited with a raw traceback -- on the one
  command whose entire job is to fix a machine's prerequisites;
* `yazses quickstart` guarded it with `except Exception: needs_setup = False` and printed
  **"Prerequisites -- already set up ✓"**. A swallowed probe became a positive claim, on
  the first screen a new user meets, and it was wrong precisely where it mattered: inside
  a fresh container almost nothing is set up.

So this file pins both halves -- the probe is total, and "we could not find out" never
renders as a tick.
"""

from __future__ import annotations

import os
import sys

import pytest
from typer.testing import CliRunner

from yazses.cli import app
from yazses.system import setup

# `pwd` is POSIX-only. It was imported at module scope, so on Windows this file
# raised `ModuleNotFoundError` during *collection* -- which is not one red test,
# it is the whole module erroring and both Windows jobs failing with it. The
# subject here is the passwd database, which Windows does not have, so skipping
# is the honest answer rather than a workaround.
pwd = pytest.importorskip("pwd", reason="POSIX passwd database; absent on Windows")

runner = CliRunner()


@pytest.fixture
def linux_quickstart(monkeypatch):
    """Force `quickstart`'s Linux branch, whatever host the tests run on.

    The prerequisites step only renders a tick on Linux -- every other platform
    prints "Check prerequisites" unconditionally, because the `input` group and
    the system packages are a Linux concern. So both quickstart tests below were
    platform-dependent without saying so:

    * the "still ticks" one **could not pass** off Linux and took both macOS jobs
      red;
    * the "does not tick" one **passed off Linux for the wrong reason** -- it
      asserts a string is absent, and on macOS it is absent because the branch
      that could print it never runs. Green, and proving nothing.

    Pinning the platform fixes the first and gives the second its meaning back,
    which a `skipif` would not have done.
    """
    monkeypatch.setattr(sys, "platform", "linux")


@pytest.fixture
def passwdless_uid(monkeypatch):
    """A uid the system has no account for, and no name in the environment."""
    for var in ("SUDO_USER", "USER", "LOGNAME"):
        monkeypatch.delenv(var, raising=False)

    def _boom(uid):
        raise KeyError(f"getpwuid(): uid not found: {uid}")

    monkeypatch.setattr(pwd, "getpwuid", _boom)
    monkeypatch.setattr(os, "getuid", lambda: 4242)


def test_the_passwd_database_is_consulted_before_the_uid(monkeypatch):
    """Guard the guard.

    Every assertion below turns on the numeric fallback being a *last* resort. If
    `_current_user` stopped consulting `/etc/passwd` at all, it would return a uid string
    on every machine, the fixture would prove nothing, and the tests would still be green
    -- so pin the ordinary path too, hermetically rather than off this host.
    """
    for var in ("SUDO_USER", "USER", "LOGNAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(os, "getuid", lambda: 4242)
    monkeypatch.setattr(
        pwd, "getpwuid", lambda uid: type("E", (), {"pw_name": f"account-for-{uid}"})()
    )
    assert setup._current_user() == "account-for-4242"


def test_current_user_is_total(passwdless_uid):
    assert setup._current_user() == "4242", "must fall back to the uid, not raise"


def test_build_plan_does_not_raise_for_a_passwdless_uid(passwdless_uid):
    plan = setup.build_plan()
    assert plan.is_noop is False, (
        "a container with no account for its uid is not in the `input` group, so the "
        "honest plan is a non-empty one"
    )


def test_input_group_pending_relogin_does_not_raise(passwdless_uid):
    assert setup.input_group_pending_relogin() is False


@pytest.mark.parametrize(
    "env,expected",
    [
        ({"SUDO_USER": "mohsen", "USER": "root", "LOGNAME": "x"}, "mohsen"),
        ({"USER": "mohsen", "LOGNAME": "x"}, "mohsen"),
        ({"LOGNAME": "mohsen"}, "mohsen"),
    ],
)
def test_a_named_user_still_wins_over_the_uid(passwdless_uid, monkeypatch, env, expected):
    """The fallback is a last resort. `sudo yazses setup` must still provision the
    invoking user, not root and not a number."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert setup._current_user() == expected


def test_an_unnamed_group_membership_is_false_not_an_error(passwdless_uid):
    """The numeric fallback has to be *answerable*, not merely non-raising.

    Group members are stored by name, so a uid with no account is not a member of
    anything -- which is the true answer, and the one that makes `setup` offer to fix it.
    """
    assert setup._user_in_input_group("4242") is False


def test_quickstart_does_not_tick_a_check_it_could_not_run(monkeypatch, linux_quickstart):
    """The false statement, pinned directly."""
    def _boom(*a, **k):
        raise KeyError("getpwuid(): uid not found: 4242")

    monkeypatch.setattr(setup, "build_plan", _boom)
    result = runner.invoke(app, ["quickstart"])
    assert result.exit_code == 0, result.output
    assert "already set up ✓" not in result.output, (
        "quickstart claimed the prerequisites were fine after the probe failed:\n"
        + result.output
    )
    assert "yazses doctor" in result.output, (
        "when it cannot tell, it must send the user somewhere that can"
    )


def test_quickstart_still_ticks_when_the_probe_says_so(monkeypatch, linux_quickstart):
    """The counterpart -- the fix must not turn a real ✓ into a shrug."""
    monkeypatch.setattr(setup, "build_plan", lambda *a, **k: setup.SetupPlan(session="x11"))
    result = runner.invoke(app, ["quickstart"])
    assert result.exit_code == 0, result.output
    assert "already set up ✓" in result.output, result.output
