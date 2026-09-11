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
    """The handler shape from cli.py, tray/app.py and mcp/server.py, verbatim."""
    try:
        raise win_ipc.IpcUnreachableError(r"\\.\pipe\yazses-alice-daemon")
    except IpcUnreachableError as exc:
        assert "yazses-alice-daemon" in str(exc)
    else:  # pragma: no cover - the assertion above is the point
        pytest.fail("the shared handler did not catch the Windows transport's error")


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


def test_force_kill_signal_is_sigkill_on_posix():
    assert cli._force_kill_signal() is signal.SIGKILL


def test_force_kill_signal_is_none_where_the_attribute_is_absent(monkeypatch):
    """Simulate Windows by removing the attribute Windows does not have."""
    monkeypatch.delattr(signal, "SIGKILL", raising=True)
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
    monkeypatch.delattr(signal, "SIGKILL", raising=True)
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


def test_restart_still_force_kills_on_posix(monkeypatch):
    """The fix must not quietly weaken the Linux path it was protecting."""
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

    assert sent == [signal.SIGTERM, signal.SIGKILL]


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
    import yazses.ipc.client as shared

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
