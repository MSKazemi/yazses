"""`yazses restart`/`start` may signal only YazSes daemons that are its own to stop.

The hunt used to be ``pgrep -f yazses[.]main`` across every user, excluding only its own
pid and its direct parent. A bystander whose argv merely *contained* the text (``tail -f
yazses.main.log``) was sent SIGTERM; a match owned by another user raised PermissionError
out of ``restart``; and ``_restart_daemon`` unlinked ``daemon.lock`` even when the old
daemon survived, so a second instance created a fresh file, locked that, and both ran --
every dictation typed twice.

Nothing here signals by pattern. The process table is a fake, and the one real subprocess
(the lock holder) is signalled by its exact pid only.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

import yazses.cli as cli

ME = 1000
OTHER = 1001
SELF_PID = 500


def _table(*rows):
    """Rows are (pid, ppid, uid, argv); returns the injectable table callable."""
    return lambda: list(rows)


def _hunt(rows, sig=signal.SIGTERM, monkeypatch=None, kill=None):
    sent = []
    real_kill = os.kill

    def fake_kill(pid, s):
        sent.append((pid, s))
        if kill is not None:
            kill(pid, s)

    assert monkeypatch is not None
    monkeypatch.setattr(os, "kill", fake_kill)
    monkeypatch.setattr(sys, "platform", "linux")
    count = cli._kill_yazses_daemons(sig, _table(*rows), uid=ME, pid=SELF_PID)
    monkeypatch.setattr(os, "kill", real_kill)
    return count, sent


DAEMON = ["/home/u/.local/bin/yazses-daemon"]
MODULE = ["/home/u/.venv/bin/python3.12", "-m", "yazses.main"]
SHEBANG = ["/usr/bin/python3", "/home/u/.local/bin/yazses-daemon"]
SELF = (SELF_PID, 400, ME, ["python", "-m", "yazses.cli", "restart"])


# ---- argv shape ---------------------------------------------------------------


@pytest.mark.parametrize("argv", [DAEMON, MODULE, SHEBANG, ["python", "-X", "dev", "-m", "yazses.main"]])
def test_real_daemon_shapes_match(argv):
    assert cli._is_daemon_argv(argv)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["tail", "-f", "/var/log/yazses.main.log"],
        ["python", "-c", "import time; time.sleep(60)", "tail-of-yazses.main.log"],
        ["vim", "src/yazses/main.py", "yazses.main"],
        ["python", "-m", "yazses.main", "--extra"],  # the daemon is launched with no arguments
        ["python", "-m", "yazses.cli", "restart"],
        ["python", "-m", "pytest", "-k", "yazses.main"],
        ["/usr/bin/yazses-daemon", "--help"],
        ["bash", "-c", "exec /home/u/.local/bin/yazses-daemon"],
        ["python", "/home/u/.local/bin/yazses-daemon", "x"],
    ],
)
def test_bystanders_do_not_match(argv):
    assert not cli._is_daemon_argv(argv)


# ---- who gets signalled -------------------------------------------------------


def test_bystander_with_yazses_main_in_a_quoted_argument_is_not_signalled(monkeypatch):
    bystander = (900, 1, ME, ["python", "-c", "import time; time.sleep(60)", "tail-of-yazses.main.log"])
    count, sent = _hunt([SELF, bystander], monkeypatch=monkeypatch)
    assert (count, sent) == (0, [])


def test_real_daemon_of_the_same_uid_is_signalled(monkeypatch):
    count, sent = _hunt(
        [SELF, (901, 1, ME, DAEMON), (902, 1, ME, MODULE)], monkeypatch=monkeypatch
    )
    assert count == 2
    assert sent == [(901, signal.SIGTERM), (902, signal.SIGTERM)]


def test_daemon_of_another_uid_is_skipped_without_raising(monkeypatch):
    count, sent = _hunt([SELF, (903, 1, OTHER, DAEMON)], monkeypatch=monkeypatch)
    assert (count, sent) == (0, [])


def test_whole_ancestor_chain_is_excluded_not_just_the_parent(monkeypatch):
    # restart <- settings <- tray <- daemon-shaped grandparent: none of them may be hit.
    rows = [
        (SELF_PID, 400, ME, ["python", "-m", "yazses.cli", "restart"]),
        (400, 300, ME, ["python", "-m", "yazses.main"]),
        (300, 200, ME, DAEMON),
        (200, 1, ME, MODULE),
        (904, 1, ME, DAEMON),  # an unrelated stray: this one is fair game
    ]
    count, sent = _hunt(rows, monkeypatch=monkeypatch)
    assert sent == [(904, signal.SIGTERM)]
    assert count == 1


def test_own_pid_is_never_signalled_even_when_it_looks_like_a_daemon(monkeypatch):
    count, sent = _hunt([(SELF_PID, 1, ME, MODULE)], monkeypatch=monkeypatch)
    assert (count, sent) == (0, [])


def test_permission_error_is_swallowed_and_the_hunt_continues(monkeypatch):
    def deny_first(pid, _sig):
        if pid == 905:
            raise PermissionError(1, "Operation not permitted")

    count, sent = _hunt(
        [SELF, (905, 1, ME, DAEMON), (906, 1, ME, MODULE)],
        monkeypatch=monkeypatch,
        kill=deny_first,
    )
    assert [p for p, _ in sent] == [905, 906]
    assert count == 1, "only the signal that was delivered is counted"


def test_vanished_process_is_not_an_error(monkeypatch):
    def gone(_pid, _sig):
        raise ProcessLookupError

    count, _sent = _hunt([SELF, (907, 1, ME, DAEMON)], monkeypatch=monkeypatch, kill=gone)
    assert count == 0


def test_none_signal_still_a_no_op_even_with_a_table(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert cli._kill_yazses_daemons(None, _table((901, 1, ME, DAEMON)), uid=ME, pid=SELF_PID) == 0


def test_the_live_proc_reader_sees_this_process_and_its_parent():
    if not sys.platform.startswith("linux"):
        pytest.skip("reads /proc")
    rows = {r[0]: r for r in cli._read_proc_table()}
    me = rows[os.getpid()]
    assert me[1] == os.getppid()
    assert me[2] == os.getuid()
    assert any("python" in a or "pytest" in a for a in me[3])


# ---- restart and the lock -----------------------------------------------------


class _Lifecycle:
    def __init__(self):
        self.cleared = 0

    def read_pid(self):
        return None

    def clear_pid(self):
        self.cleared += 1


class _Platform:
    def __init__(self, data_dir: Path):
        self.lifecycle = _Lifecycle()
        self.paths = type("P", (), {"data_dir": data_dir})()


@pytest.fixture
def quiet_restart(monkeypatch):
    import time

    monkeypatch.setattr(cli, "_systemd_managed", lambda: False)
    monkeypatch.setattr(cli, "_kill_yazses_daemons", lambda _sig: 0)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    spawned = []
    monkeypatch.setattr(cli, "_spawn_daemon", lambda plat: spawned.append(plat))
    return spawned


_HOLDER = (
    "import sys, time\n"
    "from yazses.system.single_instance import SingleInstanceLock\n"
    "lock = SingleInstanceLock(sys.argv[1])\n"
    "import os\n"
    "print(lock.acquire(), os.getpid(), flush=True)\n"
    "time.sleep(60)\n"
)


def _spawn_holder(lock: Path) -> tuple[subprocess.Popen, int]:
    """Start a process that holds ``lock``; return it with the pid that holds it.

    The pid that holds the lock is the one the helper reports from inside, not
    ``Popen.pid``: inside a Windows venv ``sys.executable`` is a launcher stub
    that starts the real interpreter as a child, so the two differ there.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(lock)], stdout=subprocess.PIPE, text=True
    )
    assert proc.stdout is not None
    acquired, _, pid = proc.stdout.readline().strip().partition(" ")
    assert acquired == "True", "helper must take the lock"
    return proc, int(pid)


def _stop_holder(proc: subprocess.Popen, holder_pid: int) -> None:
    """Kill exactly the processes this test spawned (the stub and the holder)."""
    import contextlib

    proc.kill()
    if holder_pid != proc.pid:
        with contextlib.suppress(OSError):
            os.kill(holder_pid, signal.SIGTERM)
    proc.wait(timeout=10)


def test_restart_aborts_and_leaves_the_lock_when_a_live_holder_survives(
    tmp_path, quiet_restart
):
    import typer

    lock = tmp_path / "daemon.lock"
    holder, holder_real_pid = _spawn_holder(lock)
    try:
        plat = _Platform(tmp_path)
        with pytest.raises(typer.Exit) as exc:
            cli._restart_daemon(plat)
        assert exc.value.exit_code == 1
        assert lock.exists(), "a held lock file must not be unlinked"
        assert quiet_restart == [], "no second daemon may be spawned"
        assert plat.lifecycle.cleared == 0
        # and the holder really does still own it
        from yazses.system.single_instance import SingleInstanceLock, holder_pid

        assert holder_pid(lock) == holder_real_pid
        assert SingleInstanceLock(lock).acquire() is False
    finally:
        _stop_holder(holder, holder_real_pid)


def test_restart_unlinks_an_unheld_lock_and_spawns_one_daemon(tmp_path, quiet_restart):
    lock = tmp_path / "daemon.lock"
    lock.write_text("99999", encoding="utf-8")  # stale file, nobody holds it
    plat = _Platform(tmp_path)
    cli._restart_daemon(plat)
    assert not lock.exists()
    assert plat.lifecycle.cleared == 1
    assert quiet_restart == [plat]


def test_restart_with_no_lock_file_still_spawns(tmp_path, quiet_restart):
    plat = _Platform(tmp_path)
    cli._restart_daemon(plat)
    assert quiet_restart == [plat]


def test_a_lock_released_during_the_grace_wait_lets_restart_proceed(
    tmp_path, quiet_restart, monkeypatch
):
    """The holder was SIGKILLed a moment ago: it is gone by the re-check, so restart goes on."""
    import yazses.system.single_instance as si

    lock = tmp_path / "daemon.lock"
    lock.write_text("4242", encoding="utf-8")
    answers = iter([4242, None])
    monkeypatch.setattr(si, "holder_pid", lambda _p: next(answers))
    monkeypatch.setattr(cli, "_wait_for_daemon_exit", lambda _pid, **_kw: True)
    plat = _Platform(tmp_path)
    cli._restart_daemon(plat)
    assert not lock.exists()
    assert quiet_restart == [plat]
