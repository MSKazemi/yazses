"""`get_url_opener()` is how "send to" (ADR-031 §3) hands a URL to the desktop on this OS.

The `UrlOpener` Protocol sits in `platform/base.py` beside `FileOpener`, one
implementation per OS family in `platform/<os>/fileopen.py`, dispatched by
`platform/factory.py`. The URL it is given *is* the user's dictation, percent-encoded,
so this file pins, per backend and with every process and OS call faked:

* **the mechanism** -- Linux and the BSDs run `xdg-open` with the URL as one argv
  element and no shell; macOS calls `NSWorkspace` in-process and falls back to `open`;
  Windows calls `os.startfile` (`ShellExecuteW`, in-process);
* **refusal before anything starts** -- a web, file or script scheme, a URL without a
  scheme, or one with whitespace or control characters starts no process and calls no
  OS API (the deny-list behind `sendto`'s closed allow-list);
* **nothing carries the URL out** -- the child's stdout/stderr go to /dev/null, and no
  exception any backend raises quotes the URL;
* **the routing** -- the factory picks the right class per `sys.platform`, refuses an
  OS it has no backend for by name, and neither `sendto` package module reads
  `sys.platform` (AGENTS.md rule 6).

Not covered, and cannot be from here: that each OS really resolves `claude://` and
`codex://` to the installed client. Nothing here has run on a real Mac or Windows box.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
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
