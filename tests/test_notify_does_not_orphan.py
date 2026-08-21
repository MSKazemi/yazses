"""An actionable toast must not outlive the process that raised it.

`notify()` runs the actionable path on a **daemon** thread, and its 120 s cap lives
inside that thread. A daemon thread is abandoned at interpreter exit without
unwinding, so in any process that exits sooner than the cap -- a CLI command,
`yazses verify`, one `pytest` run -- the cap never fires, nothing kills
`notify-send`, and a toast marked `--urgency critical` (which by spec never expires
on its own) is orphaned onto the user's desktop permanently.

That is not hypothetical: the suite leaked four per run and they accumulated for as
long as the desktop session lasted, at which point `yazses doctor` shares a machine
with dozens of stale "YazSes could not type that" pop-ups describing failures that
were never real.

Exercised through a real child process, because the bug *is* process lifetime:
nothing observable inside one interpreter distinguishes a tracked child from an
untracked one. The stand-in is a long `sleep` rather than `notify-send`, so the test
neither needs libnotify nor touches the developer's screen.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX orphan semantics; notify.py documents itself as the Linux path",
)

# Calls notify() exactly as the daemon does -- actionable, on the default daemon
# thread -- but with a spawner that starts a process which would outlive us by a
# long way. Prints the child's pid, gives the thread time to actually reach the
# spawn, then exits normally.
_CHILD = textwrap.dedent(
    """
    import subprocess, sys, time
    sys.path.insert(0, {src!r})
    from yazses.system.notify import notify, NotifyAction

    started = []

    def spawner(argv, **kwargs):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(600)"], **kwargs
        )
        started.append(proc)
        return proc

    notify(
        "T", "B",
        urgency="critical",
        actions=[NotifyAction("report", "Prepare a bug report")],
        on_action=lambda key: None,
        spawner=spawner,
        available=True,
        actions_supported=True,
    )
    for _ in range(100):          # wait for the worker thread to reach the spawn
        if started:
            break
        time.sleep(0.05)
    print(started[0].pid if started else -1, flush=True)
    """
)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def test_an_actionable_toast_dies_with_the_process_that_raised_it(tmp_path):
    src = str((__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
    script = tmp_path / "leaky.py"
    script.write_text(_CHILD.format(src=src), encoding="utf-8")

    done = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
    pid = int(done.stdout.strip())
    assert pid > 0, "the worker thread never spawned the toast — test is not exercising it"

    # The parent has exited. Nothing is left that would ever reap this on its own:
    # before the fix it sat in poll() until the desktop session ended.
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)

    if _alive(pid):
        os.kill(pid, 9)  # don't leak out of a test about leaking
        pytest.fail(
            f"notify-send stand-in {pid} outlived its parent: an actionable toast is "
            "orphaned onto the user's desktop whenever a short-lived process raises one"
        )
