"""Windows daemon lifecycle: #330 — the two bugs that made `start` and `restart` fail.

Both are cross-platform-testable on Linux, which matters: the defects lived only on
Windows but their *causes* are plain Python — an exception hierarchy and an argument
evaluated before the guard that was meant to protect it — so nothing here needs
Windows, pywin32, a named pipe or a daemon.

## Bug 1 — `yazses start` reported an IPC failure for a daemon that started fine

`cli._wait_until_ready` polls the daemon and swallows the one error it expects:

    except IpcUnreachableError:
        pass  # IPC socket not up yet — keep polling

That `except` never fired on Windows. There were **two different classes with the
same name** — `yazses.ipc.client.IpcUnreachableError` (imported by every caller)
and a second one declared in `yazses.platform.windows.ipc` (raised by the pipe
client) — with no inheritance between them. The raised error sailed past the
handler and out as a traceback, while the daemon came up a second later.

`cli.py` has fourteen `except IpcUnreachableError:` sites; `tray/app.py`,
`mcp/server.py` and `platform/windows/lifecycle.py` have more. Every one of them
was dead code on Windows, which is a good explanation for why Windows felt rougher
than Linux and macOS without anyone being able to say why.

## Bug 2 — `yazses restart` crashed on `signal.SIGKILL`

`_kill_yazses_daemons` has a `sys.platform != "linux"` guard, but the call site
read `_kill_yazses_daemons(signal.SIGKILL)` and Python evaluates the argument
first. `signal.SIGKILL` is POSIX-only and does not exist on Windows, so the
`AttributeError` was raised *before* the guard could return. The guard was
unreachable on Windows for its entire life.

The stale-hotkey symptom in #330 is a consequence of this one, not a third bug:
`restart` is the command that reloads the config, so a crashing `restart` leaves
the old daemon — and the old hotkey — in place.
"""
from __future__ import annotations

import signal

import pytest

import yazses.cli as cli
from yazses.ipc.client import IpcCallError, IpcUnreachableError
from yazses.ipc.protocol import NOT_REACHABLE
from yazses.platform.windows import ipc as win_ipc

# ---- Bug 1: one exception hierarchy, not two ------------------------------


def test_windows_unreachable_is_catchable_as_the_shared_one():
    """The single assertion that was False and is the whole of bug 1."""
    assert issubclass(win_ipc.IpcUnreachableError, IpcUnreachableError)


def test_windows_unreachable_is_also_an_ipc_call_error():
    """`except IpcCallError:` sites must catch it too — several only catch the base."""
    assert issubclass(win_ipc.IpcUnreachableError, IpcCallError)


def test_windows_module_does_not_redeclare_the_shared_call_error():
    """Re-declaring `IpcCallError` here is what split the hierarchy in the first place."""
    assert win_ipc.IpcCallError is IpcCallError


def test_catching_the_shared_name_catches_the_windows_error():
    """The handler shape from cli.py, tray/app.py and mcp/server.py, verbatim.

    No `else: pytest.fail(...)` here — CodeQL correctly flagged it as unreachable:
    the `try` unconditionally raises, so control either lands in `except` (and the
    assertion below runs) or the exception propagates uncaught (and pytest reports
    that failure on its own). There is no third path for an `else` to catch.
    """
    try:
        raise win_ipc.IpcUnreachableError(r"\\.\pipe\yazses-alice-daemon")
    except IpcUnreachableError as exc:
        assert "yazses-alice-daemon" in str(exc)


def test_windows_error_keeps_its_pipe_name_and_cause():
    """Subclassing must not cost the transport-specific detail callers log."""
    cause = OSError("WaitNamedPipe: The system cannot find the file specified.")
    exc = win_ipc.IpcUnreachableError(r"\\.\pipe\yazses-bob-daemon", cause=cause)
    assert exc.pipe_name == r"\\.\pipe\yazses-bob-daemon"
    assert exc.cause is cause
    assert exc.error.code == NOT_REACHABLE  # unchanged by the reparenting


def test_wait_until_ready_keeps_polling_through_a_windows_pipe_error():
    """End-to-end on the code path from the report: `start` must not raise.

    Before the fix this propagated out of `_wait_until_ready` as the traceback
    users saw, instead of being swallowed as "not up yet".
    """

    class _Lifecycle:
        def __init__(self):
            self._running = [True, True]

        def is_running(self):
            return self._running.pop(0) if self._running else True

    class _Client:
        def __init__(self):
            self._responses = [
                win_ipc.IpcUnreachableError(r"\\.\pipe\yazses-carol-daemon"),
                {"state": "idle", "ready": True},
            ]

        def call(self, _method, **_params):
            item = self._responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    class _Paths:
        ipc_socket = "ignored"

    class _Platform:
        def __init__(self):
            self.lifecycle = _Lifecycle()
            self.paths = _Paths()
            self._client = _Client()

        def ipc_client_factory(self, _socket):
            return self._client

    outcome, info = cli._wait_until_ready(_Platform(), timeout=5.0)
    assert outcome == "ready"
    assert info["ready"] is True


# ---- Bug 2: no SIGKILL where there is no SIGKILL --------------------------


# Both directions inject the attribute rather than reading the host's, because the
# host is the one thing these tests must not depend on. Reading `signal.SIGKILL`
# inside the assertion made the *test* raise `AttributeError` on Windows -- the one
# platform this whole file is about -- and `delattr(..., raising=True)` failed there
# for the opposite reason: the attribute is already gone. Injecting also makes the
# assertion stronger, since it proves `_force_kill_signal` returns whatever `getattr`
# found rather than a constant that happens to match.
_SENTINEL_SIGKILL = 9


def test_force_kill_signal_returns_the_signal_where_one_exists(monkeypatch):
    monkeypatch.setattr(signal, "SIGKILL", _SENTINEL_SIGKILL, raising=False)
    assert cli._force_kill_signal() == _SENTINEL_SIGKILL


def test_force_kill_signal_is_none_where_the_attribute_is_absent(monkeypatch):
    """Windows has no `SIGKILL`; `raising=False` so this also holds *on* Windows."""
    monkeypatch.delattr(signal, "SIGKILL", raising=False)
    assert cli._force_kill_signal() is None


def test_kill_yazses_daemons_treats_none_as_a_no_op(monkeypatch):
    """So the caller never has to branch on the platform."""
    import subprocess

    def _boom(*_a, **_k):  # pragma: no cover - must not be reached
        pytest.fail("a None signal must not reach pgrep")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert cli._kill_yazses_daemons(None) == 0


def test_restart_does_not_touch_sigkill_on_a_platform_without_it(monkeypatch):
    """The regression test for the traceback in #330.

    With `signal.SIGKILL` absent, `_restart_daemon` previously raised
    `AttributeError: module 'signal' has no attribute 'SIGKILL'` at the call
    site, before its own platform guard could return — so `restart` crashed and
    the daemon was left running with the *old* config, which is the stale
    `right_ctrl` hotkey the reporter saw.
    """
    monkeypatch.delattr(signal, "SIGKILL", raising=False)
    monkeypatch.setattr(cli, "_systemd_managed", lambda: False)
    monkeypatch.setattr(cli, "_kill_yazses_daemons", lambda _sig: 0)

    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda *_: None)

    spawned = []
    monkeypatch.setattr(cli, "_spawn_daemon", lambda plat: spawned.append(plat))

    class _Paths:
        def __init__(self, tmp):
            self.data_dir = tmp

    class _Lifecycle:
        def __init__(self):
            self.cleared = 0

        def read_pid(self):
            return None

        def clear_pid(self):
            self.cleared += 1

    class _Platform:
        def __init__(self, tmp):
            self.lifecycle = _Lifecycle()
            self.paths = _Paths(tmp)

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        plat = _Platform(Path(tmp))
        cli._restart_daemon(plat)  # must not raise

    assert plat.lifecycle.cleared == 1
    assert spawned == [plat], "restart must still end with exactly one daemon spawned"


def test_restart_still_force_kills_where_a_kill_signal_exists(monkeypatch):
    """The fix must not quietly weaken the Linux path it was protecting.

    The signal is injected for the same reason as above: this assertion used to
    name `signal.SIGKILL` directly and therefore could not run on Windows.
    """
    monkeypatch.setattr(signal, "SIGKILL", _SENTINEL_SIGKILL, raising=False)
    monkeypatch.setattr(cli, "_systemd_managed", lambda: False)
    sent = []
    monkeypatch.setattr(cli, "_kill_yazses_daemons", lambda sig: sent.append(sig) or 0)

    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda *_: None)
    monkeypatch.setattr(cli, "_spawn_daemon", lambda _plat: None)

    class _Paths:
        def __init__(self, tmp):
            self.data_dir = tmp

    class _Lifecycle:
        def read_pid(self):
            return None

        def clear_pid(self):
            return None

    class _Platform:
        def __init__(self, tmp):
            self.lifecycle = _Lifecycle()
            self.paths = _Paths(tmp)

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        cli._restart_daemon(_Platform(Path(tmp)))

    assert sent == [signal.SIGTERM, _SENTINEL_SIGKILL]


# ---- The general form: no platform transport may shadow a shared IPC name ----
#
# The two assertions above name `platform.windows.ipc` explicitly, which locks
# the bug that was reported and nothing else. But the defect was never really
# "Windows declared a class"; it was that **an exception is caught by identity**,
# so any transport that re-declares a name its callers import from
# `yazses.ipc.client` silently disables every `except` site for that platform —
# with no import error, no lint warning and no failing test to say so.
#
# `platform/linux/ipc.py` and `platform/macos/ipc.py` cannot hit this today
# because they reuse `JsonRpcClient` and therefore raise the shared errors by
# construction. That is a property of how they happen to be written, not a rule
# anything enforces, and the next transport (a BSD one, a socket-activated one,
# a test double) gets no warning at all.
#
# So derive the region rather than listing it: every `ipc.py` under
# `platform/`, discovered by glob, is checked against every public name in
# `yazses.ipc.client`. A new OS is covered the day its module appears.


def _platform_ipc_modules():
    """Every platform IPC module, found by globbing rather than by memory."""
    import importlib
    from pathlib import Path

    import yazses.platform as platform_pkg

    root = Path(platform_pkg.__file__).parent
    found = {}
    for path in sorted(root.glob("*/ipc.py")):
        name = f"yazses.platform.{path.parent.name}.ipc"
        found[name] = importlib.import_module(name)
    return found


def test_the_platform_ipc_module_scan_finds_something():
    """A guard that iterates is green on an empty collection.

    If the glob ever stops matching -- a rename, a package move, a layout
    change -- the shadowing test below would pass by checking nothing. Fail
    here instead, loudly, rather than reporting compliance we did not verify.
    """
    modules = _platform_ipc_modules()
    assert len(modules) >= 3, f"expected linux/macos/windows IPC modules, found {sorted(modules)}"


def test_no_platform_transport_shadows_a_shared_ipc_name():
    """A platform module may subclass a shared IPC name, never redeclare it.

    This is the generalisation of #330: `windows.ipc` declared its own
    `IpcUnreachableError`, unrelated by inheritance to the one all fourteen
    `except` sites in `cli.py` import, so those handlers were dead code on
    Windows while behaving correctly on Linux and macOS.
    """
    from yazses.ipc import client as shared

    shared_names = {
        name: obj for name, obj in vars(shared).items() if not name.startswith("_") and isinstance(obj, type)
    }
    offenders = []
    for mod_name, mod in _platform_ipc_modules().items():
        for name, shared_obj in shared_names.items():
            local = getattr(mod, name, None)
            if local is None or local is shared_obj:
                continue  # absent, or the shared class re-exported -- both fine
            if not (isinstance(local, type) and issubclass(local, shared_obj)):
                offenders.append(f"{mod_name}.{name} shadows yazses.ipc.client.{name} without subclassing it")
    assert not offenders, "\n".join(
        [
            "A platform transport redeclared a name its callers catch by identity.",
            "Subclass the shared class instead of declaring a new one:",
            *offenders,
        ]
    )


# ---- The reopened half of #330: `restart` replaced a daemon it had not ----
# seen leave, and `start` opened a blank console window.
#
# Both live in `WindowsLifecycle`, and both are testable here because their
# causes are plain control flow: a method that returns at an *acknowledgement*
# instead of at an *exit*, and a creation-flag set where one flag contradicted
# the other. The reporter's evidence was real-Windows PIDs and a window that
# stayed open; the assertions below are what would have caught either from
# Linux, so the suite keeps guarding them on every run rather than on the next
# Windows machine someone borrows.

from yazses.platform import windows as _windows_pkg
from yazses.platform.base import Paths as _Paths
from yazses.platform.windows import lifecycle as _win_lifecycle


class _Probe:
    """A liveness probe with a scripted answer; raises once the script runs out."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.asked = 0

    def __call__(self, _pid):
        self.asked += 1
        if not self._answers:
            raise AssertionError("stop_daemon kept probing after its script ended")
        return self._answers.pop(0)


class _RecordingPipeClient:
    """Stand-in for NamedPipeIpcClient: scripted result, recorded calls."""

    instances: list = []

    def __init__(self, socket, timeout_s=None):
        self.socket = socket
        self.timeout_s = timeout_s
        self.calls: list = []
        type(self).instances.append(self)

    def call(self, method, **_params):
        self.calls.append(method)
        return {"ok": True}


class _UnreachablePipeClient(_RecordingPipeClient):
    def call(self, method, **_params):
        self.calls.append(method)
        from yazses.ipc.client import IpcUnreachableError

        raise IpcUnreachableError(r"\\.\pipe\yazses-dead-daemon")


def _windows_lifecycle(tmp_path, probe, monkeypatch, client_cls=_RecordingPipeClient):
    paths = _Paths(
        config_dir=tmp_path,
        state_dir=tmp_path,
        cache_dir=tmp_path,
        log_dir=tmp_path,
        data_dir=tmp_path,
    )
    monkeypatch.setattr(_windows_pkg.ipc, "NamedPipeIpcClient", client_cls)
    return _win_lifecycle.WindowsLifecycle(paths, alive_probe=probe)


def _record_kills(monkeypatch):
    kills = []
    monkeypatch.setattr(_win_lifecycle.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    return kills


def _fast_waits(monkeypatch, grace=0.2, poll=0.01):
    """Shrink the #330 wait windows so the suite feels them, not their length."""
    monkeypatch.setattr(_win_lifecycle, "_SHUTDOWN_GRACE_S", grace)
    monkeypatch.setattr(_win_lifecycle, "_FORCE_GRACE_S", grace)
    monkeypatch.setattr(_win_lifecycle, "_SHUTDOWN_POLL_S", poll)


def test_stop_daemon_waits_for_the_acknowledged_process_to_exit(tmp_path, monkeypatch):
    """The ack is not an exit: `stop_daemon` must watch the PID die before returning.

    The reopened finding behind #330: `WindowsLifecycle.stop_daemon` returned at
    the RPC *acknowledgement*, so `restart` spawned the successor while the old
    daemon still held a live IPC server on the same pipe (8 may coexist), and
    `status` answered with the old daemon's hotkey. The fix's substance is this
    ordering: acknowledged -> *observed gone* -> return, with no signal at all
    on the graceful path.
    """
    probe = _Probe([True, True, False])  # alive across two polls, then gone
    kills = _record_kills(monkeypatch)
    _fast_waits(monkeypatch)
    _RecordingPipeClient.instances.clear()
    lc = _windows_lifecycle(tmp_path, probe, monkeypatch)

    lc.stop_daemon(4242)

    assert _RecordingPipeClient.instances[-1].calls == ["shutdown"], "the graceful path is attempted first"
    assert kills == [], "an acknowledged shutdown that completes must never escalate to a signal"
    assert probe.asked == 3, "returned only after observing the exit it was promised"


def test_stop_daemon_terminates_when_the_acknowledged_process_never_leaves(tmp_path, monkeypatch):
    """Acknowledged but not exiting: bounded patience, then SIGTERM.

    The grace constants are module-level so this test can shrink them instead
    of the suite sleeping through the real 10 seconds.
    """
    probe = _Probe([True] * 10_000)  # never exits on its own
    kills = _record_kills(monkeypatch)
    _fast_waits(monkeypatch, grace=0.05, poll=0.005)
    lc = _windows_lifecycle(tmp_path, probe, monkeypatch)

    lc.stop_daemon(4242)  # must return, not hang

    assert kills == [(4242, signal.SIGTERM)], "a survivor of the graceful window is terminated"


def test_stop_daemon_terminates_immediately_when_the_pipe_is_unreachable(tmp_path, monkeypatch):
    """Unreachable pipe: no graceful wait to sit through; signal, then wait for the exit."""
    probe = _Probe([True, False])
    kills = _record_kills(monkeypatch)
    _fast_waits(monkeypatch)
    lc = _windows_lifecycle(tmp_path, probe, monkeypatch, client_cls=_UnreachablePipeClient)

    lc.stop_daemon(4242)

    assert _UnreachablePipeClient.instances[-1].calls == ["shutdown"]
    assert kills == [(4242, signal.SIGTERM)]
    assert probe.asked == 2, "after signalling, the method still waits for the exit it caused"


def test_stop_daemon_stops_asking_once_the_pid_is_gone(tmp_path, monkeypatch):
    """A dead PID is not probed again — `_Probe` raises if the wait keeps polling."""
    probe = _Probe([False])  # gone on the first question
    kills = _record_kills(monkeypatch)
    _fast_waits(monkeypatch)
    lc = _windows_lifecycle(tmp_path, probe, monkeypatch)

    lc.stop_daemon(4242)

    assert probe.asked == 1
    assert kills == []


def test_start_daemon_detached_has_no_visible_console_and_no_contradiction(monkeypatch, tmp_path):
    """The spawn flags say exactly one thing about consoles: make it invisible.

    The blank window in #330 came from `DETACHED_PROCESS | CREATE_NO_WINDOW`:
    a parent with *no* console handing the pipx/venv redirector the job of
    starting a console-subsystem interpreter, which then allocates a brand-new
    *visible* console of its own. Dropping DETACHED_PROCESS leaves the daemon
    an invisible console (CREATE_NO_WINDOW) that the redirector's child
    inherits — nothing for anyone to draw. stdin joins stdout/stderr at
    DEVNULL so nothing ever reads the terminal the CLI came from.
    """
    captured = {}

    def _fake_popen(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return object()

    monkeypatch.setattr(_win_lifecycle.subprocess, "Popen", _fake_popen)
    paths = _Paths(
        config_dir=tmp_path,
        state_dir=tmp_path,
        cache_dir=tmp_path,
        log_dir=tmp_path,
        data_dir=tmp_path,
    )
    _win_lifecycle.WindowsLifecycle(paths, alive_probe=_Probe([False])).start_daemon_detached()

    flags = captured["creationflags"]
    assert flags & _win_lifecycle._DETACHED_PROCESS == 0, (
        "DETACHED_PROCESS gives the redirector a console-less parent and the "
        "interpreter a visible console of its own — the #330 blank window"
    )
    assert flags & _win_lifecycle._CREATE_NO_WINDOW, "the daemon's console must be invisible"
    assert flags & _win_lifecycle._CREATE_NEW_PROCESS_GROUP, "graceful CTRL_BREAK stop depends on this"
    assert captured["stdin"] is _win_lifecycle.subprocess.DEVNULL
    assert captured["stdout"] is _win_lifecycle.subprocess.DEVNULL
    assert captured["stderr"] is _win_lifecycle.subprocess.DEVNULL
    assert captured["argv"][1:] == ["-m", "yazses.main"], "the non-frozen spawn still runs the module"


def test_restart_waits_for_the_old_daemon_to_exit_before_spawning(tmp_path, monkeypatch):
    """cli-level ordering: observe the recorded PID gone, *then* spawn exactly one.

    The lifecycle wait is one half of the fix; this asserts `_restart_daemon`
    actually consults it. The previous code slept one fixed second and spawned
    into whatever state that left behind, which is precisely what the reporter
    measured with two simultaneous `yazses.main` processes.
    """
    import time as _time

    order = []
    monkeypatch.setattr(cli, "_systemd_managed", lambda: False)
    monkeypatch.setattr(cli, "_kill_yazses_daemons", lambda _sig: 0)
    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    monkeypatch.setattr(cli, "_wait_for_daemon_exit", lambda pid, **_kw: order.append(("wait", pid)) or True)
    monkeypatch.setattr(cli, "_spawn_daemon", lambda _plat: order.append(("spawn", None)))

    class _Lifecycle:
        def read_pid(self):
            return 4242

        def stop_daemon(self, pid):
            order.append(("stop", pid))

        def clear_pid(self):
            order.append(("clear", None))

    class _Platform:
        lifecycle = _Lifecycle()
        paths = type("P", (), {"data_dir": tmp_path})()

    cli._restart_daemon(_Platform())

    assert order == [
        ("stop", 4242),
        ("wait", 4242),
        ("clear", None),
        ("spawn", None),
    ], "the successor must not exist before the predecessor is observed gone"


def test_wait_for_daemon_exit_is_true_for_a_pid_already_gone(monkeypatch):
    """A dead PID answers on the first probe — no sleeps, no grace spent."""
    import yazses.system.proc as _proc

    monkeypatch.setattr(_proc, "process_alive", lambda _pid: False)
    assert cli._wait_for_daemon_exit(4242, grace_s=5.0, poll_s=0.0) is True


def test_wait_for_daemon_exit_gives_up_bounded_rather_than_hanging(monkeypatch):
    """Bounded by clock, not by hope: a PID that never dies fails the wait.

    Downstream guards (is_running, the instance lock) own what happens next;
    this function's contract is only to stop asking in time.
    """
    import yazses.system.proc as _proc

    monkeypatch.setattr(_proc, "process_alive", lambda _pid: True)
    assert cli._wait_for_daemon_exit(4242, grace_s=0.0, poll_s=0.0) is False
