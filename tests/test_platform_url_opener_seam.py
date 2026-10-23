"""`get_url_opener()` is how "send to" (ADR-031 §3) hands a URL to the desktop on this OS.

The `UrlOpener` Protocol sits in `platform/base.py` beside `FileOpener`, one
implementation per OS family in `platform/<os>/fileopen.py`, dispatched by
`platform/factory.py`. The URL it is given *is* the user's dictation, percent-encoded,
so this file pins, per backend and with every process and OS call faked:

* **the mechanism** -- Linux and the BSDs ask the desktop portal's `OpenURI` over the
  session bus first and, only when no portal received the URL, run `xdg-open` with it as
  one argv element and no shell; macOS calls `NSWorkspace` in-process and falls back to
  `open`; Windows calls `os.startfile` (`ShellExecuteW`, in-process);
* **no argv once the portal has it** -- a portal success, failure, cancel or late answer
  starts no process, so the URL is in no `/proc/<pid>/cmdline` of ours (the portal tests
  are at the bottom, with a fake jeepney connection);
* **refusal before anything starts** -- a web, file or script scheme, a URL without a
  scheme, or one with whitespace or control characters starts no process and calls no
  OS API (the deny-list behind `sendto`'s closed allow-list);
* **nothing carries the URL out** -- the child's stdout/stderr go to /dev/null, and no
  exception any backend raises quotes the URL;
* **the routing** -- the factory picks the right class per `sys.platform`, refuses an
  OS it has no backend for by name, and neither `sendto` package module reads
  `sys.platform` (AGENTS.md rule 6).

Not covered, and cannot be from here: that each OS really resolves `claude://` and
`codex://` to the installed client, and that a real xdg-desktop-portal answers `OpenURI`
for a custom scheme the way the fake below does. Nothing here has run on a real Mac or
Windows box, or against a real portal. `tests/conftest.py` refuses the session bus to every
test, so the `xdg-open` tests here are the fallback path and never reach a real desktop.
"""
from __future__ import annotations

import ast
import logging
import os
import subprocess
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import yazses.sendto as sendto_pkg
from yazses.platform import FileOpener, UrlOpener, get_url_opener
from yazses.platform.base import UrlOpenRefused, require_local_scheme, url_scheme
from yazses.platform.linux import fileopen as linux_fileopen
from yazses.platform.linux.fileopen import LinuxFileOpener, LinuxUrlOpener
from yazses.platform.macos import fileopen as macos_fileopen
from yazses.platform.macos.fileopen import MacosFileOpener, MacosUrlOpener
from yazses.platform.windows.fileopen import WindowsFileOpener, WindowsUrlOpener

#: Only RFC 3986 unreserved characters, so it appears verbatim inside a URL.
SECRET = "SECRET-PROMPT-zebra-7731"
URL = f"claude://claude.ai/new?q={SECRET}"

URL_OPENERS = [LinuxUrlOpener, MacosUrlOpener, WindowsUrlOpener]


# ---- the Protocol ------------------------------------------------------------------


@pytest.mark.parametrize("impl", URL_OPENERS)
def test_every_backend_satisfies_the_protocol(impl) -> None:
    assert isinstance(impl(), UrlOpener)


@pytest.mark.parametrize("impl", [LinuxFileOpener, MacosFileOpener, WindowsFileOpener])
def test_a_file_opener_is_not_mistaken_for_a_url_opener(impl) -> None:
    """`open_url`, not `open`: the two seams must not collapse into one structural type."""
    assert isinstance(impl(), FileOpener)
    assert not isinstance(impl(), UrlOpener)


# ---- the routing -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform_name", "expected"),
    [
        ("linux", LinuxUrlOpener),
        ("freebsd14", LinuxUrlOpener),
        ("openbsd7", LinuxUrlOpener),
        ("darwin", MacosUrlOpener),
        ("win32", WindowsUrlOpener),
    ],
)
def test_the_factory_dispatches_on_the_platform(platform_name, expected) -> None:
    with patch.object(sys, "platform", platform_name):
        assert type(get_url_opener()) is expected


def test_an_os_with_no_backend_is_refused_by_name() -> None:
    with patch.object(sys, "platform", "aix7"), pytest.raises(NotImplementedError, match="aix7"):
        get_url_opener()


def test_the_sendto_package_never_reads_sys_platform() -> None:
    """Every OS difference is behind the seam; the caller only asks for an opener."""
    for path in sorted(Path(sendto_pkg.__file__).parent.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        reads = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr == "platform"
            and isinstance(node.value, ast.Name)
            and node.value.id == "sys"
        ]
        assert reads == [], f"sendto/{path.name} reads sys.platform at line(s) {reads}"


# ---- the pure guard ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "scheme"),
    [
        ("claude://claude.ai/new?q=x", "claude"),
        ("Codex://new?prompt=x", "codex"),
        ("x-scheme+v1.2://a", "x-scheme+v1.2"),
        ("no scheme here", ""),
        ("://nothing-before", ""),
        ("1abc://digits-first", ""),
        ("clä://non-ascii", ""),
        ("", ""),
    ],
)
def test_url_scheme(url, scheme) -> None:
    assert url_scheme(url) == scheme


@pytest.mark.parametrize(
    "url",
    [
        f"https://claude.ai/new?q={SECRET}",
        f"HTTP://claude.ai/new?q={SECRET}",
        f"ftp://example.test/{SECRET}",
        f"wss://example.test/{SECRET}",
        f"file:///tmp/{SECRET}",
        f"data:text/plain,{SECRET}",
        f"javascript:alert('{SECRET}')",
        f"about:{SECRET}",
        SECRET,
        f"claude://claude.ai/new?q={SECRET} --second-arg",
        f"claude://claude.ai/new?q={SECRET}\nsecond-line",
        f"claude://claude.ai/new?q={SECRET}\x00",
    ],
)
def test_require_local_scheme_refuses_without_quoting_the_url(url) -> None:
    with pytest.raises(UrlOpenRefused) as info:
        require_local_scheme(url)
    assert SECRET not in str(info.value)


def test_require_local_scheme_admits_the_send_to_schemes() -> None:
    require_local_scheme(URL)
    require_local_scheme(f"claude://code/new?q={SECRET}")
    require_local_scheme(f"codex://new?prompt={SECRET}")


# ---- refusal starts nothing, on every backend ----------------------------------------


@pytest.mark.parametrize("impl", URL_OPENERS)
@pytest.mark.parametrize("url", [f"https://claude.ai/new?q={SECRET}", f"file:///{SECRET}", ""])
def test_a_refused_url_starts_no_process_and_calls_no_os_api(impl, url, monkeypatch) -> None:
    started: list[object] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: started.append(a))
    monkeypatch.setattr(os, "startfile", started.append, raising=False)
    monkeypatch.setattr(macos_fileopen, "_workspace_opener",
                        lambda: (lambda u: bool(started.append(u)) or True))
    with pytest.raises(UrlOpenRefused) as info:
        impl().open_url(url)
    assert started == []
    assert SECRET not in str(info.value)


# ---- Linux and the BSDs: xdg-open ----------------------------------------------------


class _Proc:
    """A stand-in `Popen` result. `statuses` are what successive `wait` calls do."""

    def __init__(self, *statuses):
        self._statuses = list(statuses)
        self.waits: list[float | None] = []
        self.killed = False

    def wait(self, timeout=None):
        self.waits.append(timeout)
        status = self._statuses.pop(0) if self._statuses else 0
        if isinstance(status, BaseException):
            raise status
        return status

    def kill(self):  # pragma: no cover - must never be called
        self.killed = True

    terminate = kill


def _fake_popen(monkeypatch, proc: _Proc) -> list[tuple[list, dict]]:
    spawned: list[tuple[list, dict]] = []

    def fake(cmdline, **kwargs):
        spawned.append((list(cmdline), kwargs))
        return proc

    monkeypatch.setattr(linux_fileopen.subprocess, "Popen", fake)
    return spawned


def test_linux_runs_xdg_open_with_the_url_as_one_argument_and_no_shell(monkeypatch) -> None:
    spawned = _fake_popen(monkeypatch, _Proc(0))
    LinuxUrlOpener().open_url(URL)
    assert len(spawned) == 1
    argv, kwargs = spawned[0]
    assert argv == ["xdg-open", URL]
    assert not kwargs.get("shell")


def test_linux_discards_the_child_s_output_and_detaches_it(monkeypatch) -> None:
    """`xdg-open` quotes its argument in its error messages; the daemon's stderr is its log."""
    spawned = _fake_popen(monkeypatch, _Proc(0))
    LinuxUrlOpener().open_url(URL)
    _argv, kwargs = spawned[0]
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["start_new_session"] is True


def test_linux_waits_a_bounded_time_for_xdg_open(monkeypatch) -> None:
    proc = _Proc(0)
    _fake_popen(monkeypatch, proc)
    LinuxUrlOpener().open_url(URL)
    assert proc.waits == [linux_fileopen.XDG_OPEN_WAIT_S]
    assert 0 < linux_fileopen.XDG_OPEN_WAIT_S <= 10


@pytest.mark.parametrize("status", [1, 2, 3, 4])
def test_linux_reports_a_failure_status_without_the_url(monkeypatch, status) -> None:
    """4 is what xdg-open returns when no program is registered for the scheme."""
    _fake_popen(monkeypatch, _Proc(status))
    with pytest.raises(OSError) as info:
        LinuxUrlOpener().open_url(URL)
    assert str(status) in str(info.value)
    assert SECRET not in str(info.value)
    assert not isinstance(info.value, subprocess.CalledProcessError)


def test_linux_leaves_a_still_running_xdg_open_alone(monkeypatch) -> None:
    """Some desktops' fallbacks run the client in the foreground; killing xdg-open could
    kill the client. It counts as handed off, and is reaped in the background."""
    proc = _Proc(subprocess.TimeoutExpired(["xdg-open", URL], 5.0), 0)
    _fake_popen(monkeypatch, proc)
    reapers: list[dict] = []

    class _Thread:
        def __init__(self, **kwargs):
            reapers.append(kwargs)

        def start(self):
            reapers[-1]["started"] = True

    monkeypatch.setattr(linux_fileopen.threading, "Thread", _Thread)
    LinuxUrlOpener().open_url(URL)  # no exception: handed off
    assert proc.killed is False
    assert len(reapers) == 1 and reapers[0]["started"] is True
    assert reapers[0]["target"] == proc.wait
    assert reapers[0]["daemon"] is True


def test_linux_without_xdg_open_raises_an_oserror_that_names_no_url(monkeypatch) -> None:
    def missing(cmdline, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "xdg-open")

    monkeypatch.setattr(linux_fileopen.subprocess, "Popen", missing)
    with pytest.raises(OSError) as info:
        LinuxUrlOpener().open_url(URL)
    assert SECRET not in str(info.value)


def test_the_bsds_get_the_same_xdg_open_path(monkeypatch) -> None:
    spawned = _fake_popen(monkeypatch, _Proc(0))
    with patch.object(sys, "platform", "freebsd14"):
        get_url_opener().open_url(URL)
    assert spawned[0][0] == ["xdg-open", URL]


# ---- macOS: NSWorkspace, then `open` ----------------------------------------------------


def _fake_pyobjc(monkeypatch, *, opened: bool = True, parsed: bool = True) -> list[object]:
    """Fake `AppKit` and `Foundation` modules; returns what `openURL_` received."""
    received: list[object] = []

    class _NSURL:
        @staticmethod
        def URLWithString_(url):
            return SimpleNamespace(url=url) if parsed else None

    class _Workspace:
        def openURL_(self, nsurl):
            received.append(nsurl)
            return opened

    appkit = SimpleNamespace(
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: _Workspace())
    )
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(NSURL=_NSURL))
    return received


def test_macos_hands_the_url_to_nsworkspace_and_starts_no_process(monkeypatch) -> None:
    received = _fake_pyobjc(monkeypatch)
    started: list[object] = []
    monkeypatch.setattr(macos_fileopen.subprocess, "run", lambda *a, **k: started.append(a))
    MacosUrlOpener().open_url(URL)
    assert [n.url for n in received] == [URL]
    assert started == [], "with NSWorkspace available, no argv ever holds the URL"


def test_macos_reports_nsworkspace_declining_without_the_url(monkeypatch) -> None:
    _fake_pyobjc(monkeypatch, opened=False)
    with pytest.raises(OSError) as info:
        MacosUrlOpener().open_url(URL)
    assert SECRET not in str(info.value)


def test_macos_reports_an_unparsable_url_without_the_url(monkeypatch) -> None:
    received = _fake_pyobjc(monkeypatch, parsed=False)
    with pytest.raises(OSError) as info:
        MacosUrlOpener().open_url(URL)
    assert received == []
    assert SECRET not in str(info.value)


def _no_pyobjc(monkeypatch) -> None:
    # A None entry in sys.modules makes `import AppKit` raise ImportError.
    monkeypatch.setitem(sys.modules, "AppKit", None)
    monkeypatch.setitem(sys.modules, "Foundation", None)


def test_macos_without_pyobjc_falls_back_to_open_as_one_argument(monkeypatch) -> None:
    _no_pyobjc(monkeypatch)
    calls: list[tuple[list, dict]] = []

    def fake_run(cmdline, **kwargs):
        calls.append((list(cmdline), kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(macos_fileopen.subprocess, "run", fake_run)
    MacosUrlOpener().open_url(URL)
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == ["open", URL]
    assert not kwargs.get("shell")
    assert kwargs["stdout"] is subprocess.DEVNULL and kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["check"] is False, "a CalledProcessError would carry the argv, i.e. the URL"


def test_macos_open_failing_is_reported_without_the_url(monkeypatch) -> None:
    _no_pyobjc(monkeypatch)
    monkeypatch.setattr(macos_fileopen.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(OSError) as info:
        MacosUrlOpener().open_url(URL)
    assert "1" in str(info.value)
    assert SECRET not in str(info.value)


# ---- Windows: os.startfile ------------------------------------------------------------


def test_windows_hands_the_url_to_startfile(monkeypatch) -> None:
    """`os.startfile` exists only on Windows, so it is replaced, not merely patched."""
    calls: list[str] = []
    monkeypatch.setattr(os, "startfile", calls.append, raising=False)
    WindowsUrlOpener().open_url(URL)
    assert calls == [URL]


def test_windows_strips_the_url_from_the_startfile_error(monkeypatch) -> None:
    """ShellExecuteW's OSError names the "file" it was given -- here, the URL."""

    def no_handler(target):
        raise OSError(22, "No application is associated with this operation", target)

    monkeypatch.setattr(os, "startfile", no_handler, raising=False)
    with pytest.raises(OSError) as info:
        WindowsUrlOpener().open_url(URL)
    assert SECRET not in str(info.value)
    assert info.value.filename is None
    assert info.value.__context__ is None or info.value.__suppress_context__
    assert info.value.errno == 22


# ---- Linux and the BSDs: the desktop portal's OpenURI, before xdg-open --------------------
#
# The D-Bus layer is replaced at one seam, `fileopen._open_session_bus`, by `_FakeBus`: a
# stand-in for jeepney's blocking connection that opens nothing and answers with *real*
# jeepney messages (`new_method_return`, `new_error`, `new_signal`), so the message the
# opener builds is serialised and its match rule is tested against a real `Response`.
# Hence `jeepney` is needed, as `test_pointer_portal.py`'s one serialising test needs it;
# off Linux and the BSDs it is not installed and these skip.

SENDER = ":1.42"
REQUEST_PREFIX = f"{linux_fileopen.PORTAL_PATH}/request/1_42/"


@pytest.fixture
def jeepney():
    return pytest.importorskip("jeepney", reason="the D-Bus client is a Linux/BSD dependency")


class _FakeBus:
    """A jeepney session-bus connection that records instead of writing to a socket.

    ``openuri`` is what the portal does with the call: ``"handle"`` returns the predicted
    Request handle, ``"other-handle"`` an unpredicted one, an error name returns that D-Bus
    error (whose text quotes the URI, as a real portal's may), and an exception is raised.
    ``responses`` are what successive waits for the Request's ``Response`` get: a code, or
    an exception (``TimeoutError`` = no answer yet).
    """

    unique_name = SENDER

    def __init__(self, *, openuri: object = "handle", responses: list | None = None,
                 refuse_match: bool = False) -> None:
        self.openuri = openuri
        self.responses = list(responses if responses is not None else [0])
        self.refuse_match = refuse_match
        self.sent: list = []
        self.filters: list = []
        self.waits: list[float | None] = []
        self.closed = 0
        self.request_path = ""

    def members(self) -> list[str]:
        from jeepney import HeaderFields

        return [m.header.fields[HeaderFields.member] for m in self.sent]

    def openuri_calls(self) -> list:
        from jeepney import HeaderFields

        return [m for m in self.sent if m.header.fields[HeaderFields.member] == "OpenURI"]

    def send_and_get_reply(self, msg, timeout=None):
        from jeepney import HeaderFields, new_error, new_method_return

        self.sent.append(msg)
        member = msg.header.fields[HeaderFields.member]
        if member in ("AddMatch", "RemoveMatch"):
            if self.refuse_match:
                return new_error(msg, "org.freedesktop.DBus.Error.LimitsExceeded")
            return new_method_return(msg)
        assert member == "OpenURI", member
        token = msg.body[2]["handle_token"][1]
        self.request_path = REQUEST_PREFIX + token
        if isinstance(self.openuri, BaseException):
            raise self.openuri
        if self.openuri == "handle":
            return new_method_return(msg, "o", (self.request_path,))
        if self.openuri == "other-handle":
            return new_method_return(msg, "o", (REQUEST_PREFIX + "somethingelse",))
        return new_error(msg, self.openuri, "s", (f"could not open {msg.body[1]}",))

    def filter(self, rule):
        handle = SimpleNamespace(rule=rule, queue=deque(), close=lambda: None)
        self.filters.append(handle)
        return handle

    def recv_until_filtered(self, queue, timeout=None):
        from jeepney import DBusAddress, new_signal

        self.waits.append(timeout)
        outcome = self.responses.pop(0) if self.responses else TimeoutError()
        if isinstance(outcome, BaseException):
            raise outcome
        signal = new_signal(
            DBusAddress(self.request_path, interface=linux_fileopen.REQUEST_IFACE),
            "Response", "ua{sv}", (outcome, {}),
        )
        assert self.filters and self.filters[-1].rule.matches(signal), (
            "the opener's match rule must catch the portal's real Response signal"
        )
        assert self.filters[-1].queue is queue
        return signal

    def close(self) -> None:
        self.closed += 1


def _use_bus(monkeypatch, bus: _FakeBus) -> list[int]:
    """Route the opener to *bus*; returns a list that counts connections opened."""
    opened: list[int] = []

    def connect():
        opened.append(1)
        return bus

    monkeypatch.setattr(linux_fileopen, "_open_session_bus", connect)
    return opened


def _record_spawns(monkeypatch) -> list[list]:
    spawned: list[list] = []

    def fake_popen(cmdline, **kwargs):
        spawned.append(list(cmdline))
        return _Proc(0)

    monkeypatch.setattr(linux_fileopen.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(linux_fileopen.subprocess, "run",
                        lambda cmdline, **k: spawned.append(list(cmdline)))
    return spawned


def _record_threads(monkeypatch) -> list[dict]:
    """Replace `threading.Thread` in the opener; each entry is one thread's kwargs."""
    threads: list[dict] = []

    class _Thread:
        def __init__(self, **kwargs):
            threads.append(kwargs)

        def start(self):
            threads[-1]["started"] = True

    monkeypatch.setattr(linux_fileopen.threading, "Thread", _Thread)
    return threads


def test_portal_success_starts_no_process(jeepney, monkeypatch) -> None:
    """The point of the portal path: the URL reaches the desktop and no argv holds it."""
    bus = _FakeBus(responses=[0])
    opened = _use_bus(monkeypatch, bus)
    spawned = _record_spawns(monkeypatch)
    LinuxUrlOpener().open_url(URL)
    assert spawned == [], "with the portal answering, no process may be started with the URL"
    assert opened == [1]
    assert len(bus.openuri_calls()) == 1
    assert bus.waits == [linux_fileopen.PORTAL_RESPONSE_WAIT_S]
    assert bus.closed == 1


def test_portal_call_is_openuri_with_the_url_in_the_body(jeepney, monkeypatch) -> None:
    from jeepney import HeaderFields

    bus = _FakeBus()
    _use_bus(monkeypatch, bus)
    _record_spawns(monkeypatch)
    LinuxUrlOpener().open_url(URL)
    (msg,) = bus.openuri_calls()
    fields = msg.header.fields
    assert fields[HeaderFields.destination] == "org.freedesktop.portal.Desktop"
    assert fields[HeaderFields.path] == "/org/freedesktop/portal/desktop"
    assert fields[HeaderFields.interface] == "org.freedesktop.portal.OpenURI"
    assert fields[HeaderFields.signature] == "ssa{sv}"
    parent_window, uri, options = msg.body
    assert parent_window == ""
    assert uri == URL
    assert set(options) == {"handle_token"}
    kind, token = options["handle_token"]
    assert kind == "s" and token.startswith("yazses") and token.isalnum()
    assert msg.serialise(serial=1), "a signature/body mismatch would raise here"


def test_portal_match_rule_is_installed_before_the_call(jeepney, monkeypatch) -> None:
    """The portal may answer before its method reply lands; subscribe-after-send loses it."""
    bus = _FakeBus()
    _use_bus(monkeypatch, bus)
    _record_spawns(monkeypatch)
    LinuxUrlOpener().open_url(URL)
    assert bus.members() == ["AddMatch", "OpenURI"]
    assert len(bus.filters) == 1


def test_each_call_uses_a_fresh_handle_token(jeepney, monkeypatch) -> None:
    paths = []
    for _ in range(2):
        bus = _FakeBus()
        _use_bus(monkeypatch, bus)
        _record_spawns(monkeypatch)
        LinuxUrlOpener().open_url(URL)
        paths.append(bus.request_path)
    assert paths[0] != paths[1]


# -- unavailable: nothing received the URL, so xdg-open is the fallback ------------------


def test_no_session_bus_falls_back_to_xdg_open(monkeypatch) -> None:
    """conftest's default: the bus is refused, exactly as on a machine without one."""
    spawned = _record_spawns(monkeypatch)
    LinuxUrlOpener().open_url(URL)
    assert spawned == [["xdg-open", URL]]


def test_without_jeepney_the_bus_is_never_opened_and_xdg_open_is_used(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "jeepney", None)  # `import jeepney` -> ImportError
    opened = _use_bus(monkeypatch, _FakeBus())
    spawned = _record_spawns(monkeypatch)
    LinuxUrlOpener().open_url(URL)
    assert opened == []
    assert spawned == [["xdg-open", URL]]


@pytest.mark.parametrize(
    "error_name",
    [
        "org.freedesktop.DBus.Error.ServiceUnknown",
        "org.freedesktop.DBus.Error.NameHasNoOwner",
        "org.freedesktop.DBus.Error.UnknownMethod",
        "org.freedesktop.DBus.Error.UnknownInterface",
        "org.freedesktop.DBus.Error.UnknownObject",
        "org.freedesktop.DBus.Error.Spawn.ExecFailed",
        "org.freedesktop.DBus.Error.Spawn.ServiceNotFound",
    ],
)
def test_no_portal_service_or_method_falls_back_to_xdg_open(jeepney, monkeypatch,
                                                            error_name) -> None:
    bus = _FakeBus(openuri=error_name)
    _use_bus(monkeypatch, bus)
    spawned = _record_spawns(monkeypatch)
    LinuxUrlOpener().open_url(URL)
    assert spawned == [["xdg-open", URL]]
    assert bus.waits == [], "no Request exists to wait on"
    assert bus.closed == 1


def test_a_refused_match_rule_falls_back_before_the_url_is_sent(jeepney, monkeypatch) -> None:
    bus = _FakeBus(refuse_match=True)
    _use_bus(monkeypatch, bus)
    spawned = _record_spawns(monkeypatch)
    LinuxUrlOpener().open_url(URL)
    assert bus.openuri_calls() == [], "the URL never left for the bus"
    assert spawned == [["xdg-open", URL]]


# -- the portal had the URL: a failure is a failed hand-off, never a second one -----------


@pytest.mark.parametrize(
    "error_name",
    [
        "org.freedesktop.portal.Error.NotAllowed",
        "org.freedesktop.portal.Error.InvalidArgument",
        "org.freedesktop.portal.Error.Failed",
        "org.freedesktop.DBus.Error.NoReply",
        "org.freedesktop.DBus.Error.AccessDenied",
    ],
)
def test_a_portal_error_is_refused_without_xdg_open_or_the_url(jeepney, monkeypatch,
                                                               error_name) -> None:
    """The error's *text* quotes the URI (the fake does, as a real portal may); only the
    error's *name* may reach the exception."""
    bus = _FakeBus(openuri=error_name)
    _use_bus(monkeypatch, bus)
    spawned = _record_spawns(monkeypatch)
    with pytest.raises(OSError) as info:
        LinuxUrlOpener().open_url(URL)
    assert spawned == []
    assert error_name in str(info.value)
    assert SECRET not in str(info.value)
    assert info.value.__cause__ is None
    assert bus.closed == 1


@pytest.mark.parametrize(("code", "word"), [(1, "cancelled"), (2, "2")])
def test_a_cancelled_or_failed_response_is_refused_without_xdg_open(jeepney, monkeypatch,
                                                                    code, word) -> None:
    """1 is the user pressing Cancel on the app chooser: a fallback would overrule them."""
    bus = _FakeBus(responses=[code])
    _use_bus(monkeypatch, bus)
    spawned = _record_spawns(monkeypatch)
    with pytest.raises(OSError) as info:
        LinuxUrlOpener().open_url(URL)
    assert spawned == []
    assert word in str(info.value)
    assert SECRET not in str(info.value)


@pytest.mark.parametrize("exc", [TimeoutError(), ConnectionResetError(104, f"reset {URL}")])
def test_no_reply_to_the_call_is_refused_without_xdg_open(jeepney, monkeypatch, exc) -> None:
    """The portal may already have the URL; a fallback could open the client twice."""
    bus = _FakeBus(openuri=exc)
    _use_bus(monkeypatch, bus)
    spawned = _record_spawns(monkeypatch)
    with pytest.raises(OSError) as info:
        LinuxUrlOpener().open_url(URL)
    assert spawned == []
    assert SECRET not in str(info.value)
    assert info.value.__context__ is None or info.value.__suppress_context__
    assert bus.closed == 1


def test_a_bus_failure_while_waiting_is_refused_without_xdg_open(jeepney, monkeypatch) -> None:
    bus = _FakeBus(responses=[ConnectionResetError(104, f"reset {URL}")])
    _use_bus(monkeypatch, bus)
    spawned = _record_spawns(monkeypatch)
    with pytest.raises(OSError) as info:
        LinuxUrlOpener().open_url(URL)
    assert spawned == []
    assert SECRET not in str(info.value)


def test_an_unpredicted_request_handle_counts_as_accepted(jeepney, monkeypatch) -> None:
    """A portal older than `handle_token` names its own Request path; its Response cannot
    be matched safely, but the call succeeded, so the portal has the URL."""
    bus = _FakeBus(openuri="other-handle")
    _use_bus(monkeypatch, bus)
    spawned = _record_spawns(monkeypatch)
    LinuxUrlOpener().open_url(URL)
    assert spawned == []
    assert bus.waits == []
    assert bus.closed == 1


def test_no_response_yet_is_a_hand_off_and_the_connection_is_kept(jeepney, monkeypatch) -> None:
    """An app chooser may be on screen. Closing the connection could close it, so a
    background thread keeps it open for the late answer, then closes it."""
    bus = _FakeBus(responses=[TimeoutError(), 0])
    _use_bus(monkeypatch, bus)
    spawned = _record_spawns(monkeypatch)
    threads = _record_threads(monkeypatch)
    LinuxUrlOpener().open_url(URL)  # no exception: handed off
    assert spawned == []
    assert len(threads) == 1 and threads[0]["started"] is True and threads[0]["daemon"] is True
    assert bus.closed == 0, "the connection belongs to the waiting thread now"

    threads[0]["target"]()  # what the thread does
    assert bus.waits == [linux_fileopen.PORTAL_RESPONSE_WAIT_S, linux_fileopen.PORTAL_LINGER_S]
    assert bus.closed == 1


def test_the_linger_thread_closes_the_connection_with_no_answer(jeepney, monkeypatch) -> None:
    bus = _FakeBus(responses=[TimeoutError(), TimeoutError()])
    _use_bus(monkeypatch, bus)
    _record_spawns(monkeypatch)
    threads = _record_threads(monkeypatch)
    LinuxUrlOpener().open_url(URL)
    threads[0]["target"]()
    assert bus.closed == 1


def test_a_refused_scheme_never_opens_the_bus(monkeypatch) -> None:
    opened = _use_bus(monkeypatch, _FakeBus())
    with pytest.raises(UrlOpenRefused):
        LinuxUrlOpener().open_url(f"https://claude.ai/new?q={SECRET}")
    assert opened == []


# -- never the URL in a log, on any path ----------------------------------------------------


_SCENARIOS: dict[str, dict] = {
    "portal-opened": {"responses": [0]},
    "portal-cancelled": {"responses": [1]},
    "portal-failed": {"responses": [2]},
    "portal-pending": {"responses": [TimeoutError(), TimeoutError()]},
    "portal-refused": {"openuri": "org.freedesktop.portal.Error.NotAllowed"},
    "portal-absent": {"openuri": "org.freedesktop.DBus.Error.ServiceUnknown"},
    "portal-no-reply": {"openuri": TimeoutError()},
}


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_no_log_record_or_exception_carries_the_url(jeepney, monkeypatch, caplog,
                                                    scenario) -> None:
    caplog.set_level(logging.DEBUG)
    bus = _FakeBus(**_SCENARIOS[scenario])
    _use_bus(monkeypatch, bus)
    _record_spawns(monkeypatch)
    threads = _record_threads(monkeypatch)
    raised = ""
    try:
        LinuxUrlOpener().open_url(URL)
    except OSError as exc:
        raised = f"{exc!s} {exc!r} {exc.__cause__!r}"
    for thread in threads:
        thread["target"]()  # the late-answer path logs too
    assert SECRET not in raised
    for record in caplog.records:
        assert SECRET not in record.getMessage(), record.getMessage()
        assert SECRET not in repr(record.args)


def test_the_log_names_the_path_taken(jeepney, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO, logger=linux_fileopen.logger.name)
    _use_bus(monkeypatch, _FakeBus(responses=[0]))
    _record_spawns(monkeypatch)
    LinuxUrlOpener().open_url(URL)
    assert "desktop portal (OpenURI, opened)" in caplog.text

    caplog.clear()
    _use_bus(monkeypatch, _FakeBus(openuri="org.freedesktop.DBus.Error.ServiceUnknown"))
    LinuxUrlOpener().open_url(URL)
    assert "with xdg-open" in caplog.text
    assert "org.freedesktop.DBus.Error.ServiceUnknown" in caplog.text


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("org.freedesktop.portal.Error.NotAllowed", "org.freedesktop.portal.Error.NotAllowed"),
        (f"not a name {SECRET} claude://x", "unnamed D-Bus error"),
        (None, "unnamed D-Bus error"),
        ("x" * 256, "unnamed D-Bus error"),
    ],
)
def test_only_a_well_formed_error_name_is_ever_reported(name, shown) -> None:
    assert linux_fileopen._safe_error_name(name) == shown
