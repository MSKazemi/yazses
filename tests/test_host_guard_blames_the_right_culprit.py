"""The host-file guard must catch a test, and must not catch the owner.

`conftest.py::_no_test_may_write_the_users_real_config` watches the real config and
pid file around every test. It exists because two tests really did edit the developer's
machine, one of them `Daemon._shutdown()` deleting `~/.local/share/yazses/daemon.pid`
**out from under a running daemon**.

On 2026-08-21 it fired on a test that had done nothing. A full run reported
`9363 passed, 35 skipped, 1 error` in `test_injector_config_reaches_every_caller`,
which passes in isolation and passed again minutes later with no code change. What
happened is in the journal:

    00:01:25 yazses-daemon[4237]: Command mode: no command matched 19-char phrase
    00:01:34 systemd[1638]: Stopping yazses.service - YazSes voice dictation daemon...
    00:01:34 yazses.service: Consumed 12min 31.725s CPU time

The owner stopped his own daemon nine seconds after dictating. It exited cleanly and
took its pid file with it, and whichever test was executing at that instant was blamed.

Two things make that worse than a flake. The fixture asserts in **teardown**, so pytest
renders it as an ERROR rather than a FAILED — on an arbitrary innocent test. And the
fixture's own docstring already refuses to watch the data directory for exactly this
reason: *"a guard that fails because the owner dictated something would be turned off
within a day."* The pid file has the same property and had not been given the same
treatment.

The separating fact is whether the process that owned the file is still alive. That is
precisely the incident's own wording, so narrowing to it costs the guard nothing.
"""
from __future__ import annotations

import os

# `tests/` is a package, so the live conftest module — the one the fixture actually
# uses — is importable by name. Loading it by path instead would create a second
# module object and monkeypatching that would prove nothing about the real guard.
from tests import conftest


def _state(exists: bool, mtime: int = 1, size: int = 4) -> tuple:
    """A `(exists, mtime_ns, size)` triple in the shape `_host_state` produces."""
    return (exists, mtime, size) if exists else (False, 0, 0)


# --- the false positive that started this -------------------------------------------


def test_the_owners_daemon_exiting_is_not_blamed_on_a_test(monkeypatch):
    """The measured case: pid file vanishes, owning process is gone."""
    dead = _a_pid_that_is_not_running()
    monkeypatch.setattr(conftest, "_DAEMON_PID_AT_IMPORT", dead)

    assert conftest._pid_file_change_is_the_real_daemon(
        _state(True), _state(False)
    ), "a daemon that exited cleanly must not be reported as a test editing the host"


def test_the_owner_starting_a_daemon_mid_run_is_not_blamed_either(monkeypatch):
    """The same interference in the other direction, and the same answer."""
    monkeypatch.setattr(conftest, "_DAEMON_PID_AT_IMPORT", None)
    # A live process that is not this one: our own parent will do.
    monkeypatch.setattr(conftest, "_read_pid_file", lambda: os.getppid())

    assert conftest._pid_file_change_is_the_real_daemon(_state(False), _state(True))


# --- what it must still catch -------------------------------------------------------


def test_a_test_deleting_the_pid_file_under_a_live_daemon_still_fails(monkeypatch):
    """The original incident. This is the assertion the narrowing must not cost."""
    monkeypatch.setattr(conftest, "_DAEMON_PID_AT_IMPORT", os.getpid())

    assert not conftest._pid_file_change_is_the_real_daemon(
        _state(True), _state(False)
    ), "deleting the pid file out from under a running daemon must still be reported"


def test_a_test_writing_its_own_pid_still_fails(monkeypatch):
    """`lifecycle.write_pid()` writes `os.getpid()` — in a test, the pytest process."""
    monkeypatch.setattr(conftest, "_DAEMON_PID_AT_IMPORT", None)
    monkeypatch.setattr(conftest, "_read_pid_file", lambda: os.getpid())

    assert not conftest._pid_file_change_is_the_real_daemon(_state(False), _state(True))


def test_a_rewrite_naming_a_dead_process_still_fails(monkeypatch):
    """A file left naming nothing is not a daemon doing housekeeping."""
    monkeypatch.setattr(conftest, "_DAEMON_PID_AT_IMPORT", None)
    monkeypatch.setattr(conftest, "_read_pid_file", lambda: _a_pid_that_is_not_running())

    assert not conftest._pid_file_change_is_the_real_daemon(
        _state(True, mtime=1), _state(True, mtime=2)
    )


def test_a_vanished_file_with_no_daemon_at_session_start_still_fails(monkeypatch):
    """Nothing owned it, so nothing but a test can have removed it."""
    monkeypatch.setattr(conftest, "_DAEMON_PID_AT_IMPORT", None)

    assert not conftest._pid_file_change_is_the_real_daemon(_state(True), _state(False))


# --- the config half is untouched, and must stay that way ---------------------------


def test_the_config_file_has_no_exemption():
    """No daemon rewrites the config, so there is no interference to forgive.

    Read from the fixture's source rather than asserted about behaviour, because the
    exemption is applied by key name and a widened key would be invisible otherwise.
    """
    import inspect

    source = inspect.getsource(conftest._no_test_may_write_the_users_real_config)
    assert '"pid file" in changed' in source, source
    assert "config" not in source.split("changed = ")[-1].split("assert")[0], (
        "the exemption must apply to the pid file only"
    )


# --- helpers ------------------------------------------------------------------------


def _a_pid_that_is_not_running() -> int:
    """A pid nothing holds.

    Searched downward from the max rather than hardcoded: any fixed number is a real
    process on someone's machine, and a guard test that depends on which is the kind
    of host-dependence this whole file is about.
    """
    for candidate in range(4_194_303, 4_194_000, -1):
        if not conftest._alive(candidate):
            return candidate
    raise AssertionError("found no free pid to test with")


def test_the_liveness_probe_is_not_trivially_true_or_false():
    """Prove the helper both ways, or every test above could be passing on a stub."""
    assert conftest._alive(os.getpid()) is True
    assert conftest._alive(_a_pid_that_is_not_running()) is False
    assert conftest._alive(None) is False
    assert conftest._alive(0) is False
    assert conftest._alive(-1) is False


# --- the fixture body itself, not just the predicate --------------------------------


def _drive_the_guard(tmp_path, *, before_exists: bool, after_exists: bool):
    """Run the real fixture around a simulated pid-file change. Returns the error.

    The fixture is driven by hand because its `before` snapshot is taken during
    *setup* — before any test body could redirect the watched path. Pointing
    `_WATCHED_HOST_FILES` at `tmp_path` between the two `next()` calls is the only way
    to control both snapshots, and it keeps the whole thing off the real machine,
    which is the point of the guard being tested.

    The redirect is restored in a `finally` rather than by `monkeypatch`, and the first
    draft got that wrong in an instructive way: this same fixture is autouse, so it is
    also wrapping *this* test, and `monkeypatch` undid the global only after the outer
    copy had taken its own `after` snapshot. Its before- and after-readings then pointed
    at two different files and it reported "this test modified the real config file" —
    the exact trap `_resolve_watched_host_files` documents. The global must be back
    before this function returns.
    """
    fixture = conftest._no_test_may_write_the_users_real_config
    fn = getattr(fixture, "__wrapped__", fixture)

    pid_file = tmp_path / "daemon.pid"
    config = tmp_path / "config.toml"
    config.write_text("x", encoding="utf-8")
    if before_exists:
        pid_file.write_text("4237", encoding="utf-8")

    real = conftest._WATCHED_HOST_FILES
    try:
        conftest._WATCHED_HOST_FILES = {"config file": config, "pid file": pid_file}
        gen = fn()
        next(gen)                       # setup: snapshot `before`

        if after_exists and not before_exists:
            pid_file.write_text("4237", encoding="utf-8")
        elif before_exists and not after_exists:
            pid_file.unlink()

        try:
            next(gen)                   # teardown: snapshot `after`, then assert
        except StopIteration:
            return None                 # the guard was satisfied
        except AssertionError as exc:
            return str(exc)
        raise AssertionError("the fixture yielded twice")
    finally:
        conftest._WATCHED_HOST_FILES = real


def test_the_real_fixture_forgives_a_daemon_that_exited(tmp_path, monkeypatch):
    """End to end: the exact 2026-08-21 sequence must no longer error."""
    monkeypatch.setattr(
        conftest, "_DAEMON_PID_AT_IMPORT", _a_pid_that_is_not_running()
    )
    err = _drive_the_guard(tmp_path, before_exists=True, after_exists=False)
    assert err is None, f"the owner's own daemon exiting still blames a test: {err}"


def test_the_real_fixture_still_catches_the_original_incident(tmp_path, monkeypatch):
    """And the deletion under a live daemon must still raise, with its own wording."""
    monkeypatch.setattr(conftest, "_DAEMON_PID_AT_IMPORT", os.getpid())
    err = _drive_the_guard(tmp_path, before_exists=True, after_exists=False)
    assert err is not None, "the incident this guard exists for stopped being caught"
    assert "pid file" in err, err
