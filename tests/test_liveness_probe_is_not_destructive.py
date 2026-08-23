"""`os.kill(pid, 0)` asks a question on Unix and pulls a trigger on Windows.

Found by running the suite on a real Windows Server 2022 box: it died silently a little
under halfway through, with exit code 0, no traceback and no summary line. The killer was
`tests/test_host_guard_blames_the_right_culprit.py::test_the_liveness_probe_is_not_trivially_true_or_false`
— the test whose whole job is to prove the probe answers both ways, and which does that by
asking whether *this* process is alive. On Windows that call is
`TerminateProcess(handle, 0)`, so the runner shot itself and every test after it never ran.

Three things make this worth a guard of its own rather than a one-line fix:

* **The knowledge was already in the tree and did not travel.** `platform/windows/lifecycle.py`
  carried the explanation and the `OpenProcess`/`GetExitCodeProcess` replacement, written
  after the same idiom was caught killing the daemon `yazses status` was asked about. Two
  other call sites kept the destructive spelling anyway.
* **The existing guard could not see them.** `test_is_running_never_calls_os_kill` names one
  class, and hands it `alive_probe=lambda pid: False` so the real probe never runs. It was
  green throughout.
* **The failure signature is silence.** Exit code 0 and no output is indistinguishable from
  a pass to anything reading a status code.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

from tests import conftest
from yazses.system import pid as pid_module
from yazses.system.proc import process_alive

REPO = Path(__file__).resolve().parent.parent

#: The only two files allowed to spell it. `system/proc.py` is the implementation and
#: reaches it solely through a `sys.platform` branch; `platform/macos/lifecycle.py` is
#: selected by `platform/factory.py` on Darwin and cannot execute on Windows at all.
ALLOWED = {
    Path("src/yazses/system/proc.py"),
    Path("src/yazses/platform/macos/lifecycle.py"),
}


def _liveness_probes(tree: ast.AST) -> list[int]:
    """Line numbers of `os.kill(<anything>, 0)` calls."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) != 2:
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "kill"):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "os"):
            continue
        sig = node.args[1]
        if isinstance(sig, ast.Constant) and sig.value == 0:
            out.append(node.lineno)
    return out


def _python_files() -> list[Path]:
    files = []
    for root in ("src", "tests", "paper", "scripts", "hooks"):
        files.extend(sorted((REPO / root).rglob("*.py")))
    return files


def test_no_module_uses_the_posix_liveness_idiom():
    """The scan is over every tracked source root, not over a list of usual suspects.

    A hand-written list of files to check is the defect this is guarding against: the
    previous guard named `WindowsLifecycle` and both surviving call sites were elsewhere.
    """
    offenders = {}
    for path in _python_files():
        rel = path.relative_to(REPO)
        if rel in ALLOWED:
            continue
        lines = _liveness_probes(ast.parse(path.read_text(encoding="utf-8")))
        if lines:
            offenders[str(rel)] = lines
    assert not offenders, (
        "os.kill(pid, 0) terminates the process on Windows; call "
        f"yazses.system.proc.process_alive instead. Found: {offenders}"
    )


def test_the_scan_would_actually_catch_one():
    """Prove the matcher, or the test above passes on any repository at all."""
    assert _liveness_probes(ast.parse("import os\nos.kill(p, 0)\n")) == [2]
    assert _liveness_probes(ast.parse("import os, signal\nos.kill(p, signal.SIGTERM)\n")) == []
    assert _liveness_probes(ast.parse("os.killpg(p, 0)\n")) == []


def test_the_allowed_implementation_is_behind_a_platform_branch():
    """`system/proc.py` may spell it, but only where Windows cannot reach it."""
    src = (REPO / "src/yazses/system/proc.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    holders = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and _liveness_probes(node)
    ]
    assert holders == ["_posix_alive"], holders


def test_process_alive_is_true_for_this_process():
    assert process_alive(os.getpid()) is True


def test_process_alive_is_false_for_a_pid_nothing_holds():
    for candidate in range(4_194_303, 4_194_000, -1):
        if not process_alive(candidate):
            return
    pytest.fail("found no free pid to test with")


@pytest.mark.parametrize("pid", [None, 0, -1, -12345])
def test_no_pid_process_group_or_negative_is_ever_alive(pid):
    # These are also os.kill's "signal a process group" spellings, which is not a
    # question anything here means to ask.
    assert process_alive(pid) is False


def test_windows_dispatches_away_from_os_kill(monkeypatch):
    """The branch itself, testable off Windows — the real ctypes path is not.

    Without this, the guard above proves only that the string is absent; this proves the
    Windows *path* never reaches the call.
    """
    def _boom(*args, **kwargs):
        raise AssertionError("os.kill must never run on the Windows path")

    monkeypatch.setattr(os, "kill", _boom)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("yazses.system.proc._windows_alive", lambda pid: "windows-probe")
    assert process_alive(1234) == "windows-probe"


def _on_windows(monkeypatch, message: str) -> None:
    """Make this process answer as Windows, and make `os.kill` fatal if anything calls it.

    The POSIX spelling is correct *on POSIX*, so a guard that simply forbids `os.kill`
    fails on the platform where it is the right answer. What has to be proved is that the
    Windows path never arrives there.
    """
    def _boom(*args, **kwargs):
        raise AssertionError(message)

    monkeypatch.setattr(os, "kill", _boom)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("yazses.system.proc._windows_alive", lambda pid: True)


def test_is_running_never_reaches_os_kill_on_windows(tmp_path, monkeypatch):
    """`status`, `doctor` and the tray poll all land here with a real PID.

    The PID file is present and the lock file absent, which is the branch that used to
    reach the probe: an install whose daemon died without cleaning up, or one predating
    the lock file entirely.
    """
    _on_windows(monkeypatch, "is_running must not use os.kill as a probe")
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setattr(pid_module, "_PID_FILE", pid_file)
    monkeypatch.setattr(pid_module, "_LOCK_FILE", tmp_path / "absent.lock")
    pid_module.is_running()  # must not raise, and must not have killed this process


def test_the_conftest_guard_probe_never_reaches_os_kill_on_windows(monkeypatch):
    """The exact call that killed the Windows run: `_alive(os.getpid())`."""
    _on_windows(monkeypatch, "the host guard's probe must not use os.kill")
    assert conftest._alive(os.getpid()) is True
    assert conftest._alive(None) is False
