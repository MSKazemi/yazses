"""Opt-in "a newer YazSes is out" watcher: policy, state, and the privacy default.

The check is the only outbound connection YazSes makes, so the first thing tested
here is that it is off unless asked for. After that: it must announce a version
once rather than nag, and a blocked network must be a silent no-op rather than
anything the user has to deal with.
"""
from __future__ import annotations

from yazses.config import GeneralConfig
from yazses.system import update_notify as un
from yazses.system.updater import UpdateStatus, manual_update_steps

_HOUR = 3600.0


def _status(available=True, latest="2.0.0", method="pip", command=None, current="1.0.0"):
    return UpdateStatus(
        method=method, current=current, latest=latest, available=available,
        command=command, steps=manual_update_steps(method) if available else [],
    )


# ---- the privacy default ---------------------------------------------------

def test_update_check_is_off_by_default():
    # "Nothing leaves the machine" is the product. A background check that shipped
    # on would contact github.com/PyPI from a fresh install with no one asking.
    assert GeneralConfig().update_check is False


# ---- when to check ---------------------------------------------------------

def test_first_run_checks_immediately():
    assert un.should_check(now=1000.0, last_check=0.0, interval_hours=24) is True


def test_waits_for_the_interval():
    now = 100 * _HOUR
    assert un.should_check(now, last_check=now - 2 * _HOUR, interval_hours=24) is False
    assert un.should_check(now, last_check=now - 25 * _HOUR, interval_hours=24) is True


def test_a_zero_interval_is_floored_not_a_tight_loop():
    # `interval_hours = 0` means "as often as possible", not "hammer the API until
    # GitHub rate-limits us and every check then reports failure".
    now = 100 * _HOUR
    assert un.should_check(now, last_check=now - 60.0, interval_hours=0) is False
    assert un.should_check(now, last_check=now - 2 * _HOUR, interval_hours=0) is True


def test_a_clock_that_moved_backwards_does_not_lock_the_check_out():
    # last_check in the future (suspend/resume, a copied state file) would
    # otherwise disable checking until the clock caught up.
    assert un.should_check(now=1000.0, last_check=999_000.0, interval_hours=24) is True


# ---- when to notify --------------------------------------------------------

def test_notifies_once_per_version_not_once_per_check():
    st = _status(latest="2.0.0")
    assert un.should_notify(st, notified_version="") is True
    assert un.should_notify(st, notified_version="2.0.0") is False
    # A newer release re-arms it.
    assert un.should_notify(_status(latest="2.1.0"), notified_version="2.0.0") is True


def test_never_notifies_when_there_is_no_update():
    assert un.should_notify(_status(available=False, latest="1.0.0"), "") is False
    assert un.should_notify(_status(available=True, latest=None), "") is False


# ---- what the toast says ---------------------------------------------------

def test_notification_carries_the_upgrade_command():
    summary, body = un.notification(_status(command=["pipx", "upgrade", "yazses"]))
    assert "2.0.0" in summary
    assert "pipx upgrade yazses" in body
    assert "1.0.0" in body  # what they're running now


def test_notification_for_a_windows_install_gives_steps_not_a_dead_end():
    # There is no command for a .exe install, and "2.0.0 is available" with nothing
    # to act on is worse than saying nothing at all.
    _, body = un.notification(_status(method="windows-installer"))
    assert "releases" in body
    assert "Download" in body


# ---- state file ------------------------------------------------------------

def test_state_round_trips(tmp_path):
    path = tmp_path / un.STATE_NAME
    assert un.write_state(path, un.UpdateState(123.5, "2.0.0")) is True
    assert un.read_state(path) == un.UpdateState(123.5, "2.0.0")


def test_missing_or_corrupt_state_reads_as_empty(tmp_path):
    assert un.read_state(tmp_path / "nope.json") == un.UpdateState()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert un.read_state(bad) == un.UpdateState()  # costs one extra check, not a crash


def test_write_state_returns_false_instead_of_raising(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    # A path whose parent is a regular file cannot be created.
    assert un.write_state(blocker / "sub" / un.STATE_NAME, un.UpdateState(1.0, "")) is False
