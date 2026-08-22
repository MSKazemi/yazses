"""The toast queue is one-shot, and fourteen callers were racing for it.

On Windows and macOS there is no `notify-send`, so `core/daemon.py::run` registers
`_queue_notification` as `system.notify.set_fallback_sink` and every toast the daemon
wants to show goes into a list instead. The tray collects that list from the `status`
reply and displays it natively. `_handle_status` ended with:

    "notifications": self._drain_notifications(),

and the comment beside it was right about the intent — *"DRAINED by this read, so each
one is delivered once"* — while assuming a fact that was not true: that the tray is the
only reader.

`status` has fourteen call sites in `src/`. One of them displays notifications
(`tray/app.py`, which passes the list to `_show_notifications`). The other thirteen
include **`overlay/poller.py`**, which polls continuously on the same machine as the
tray and renders no notifications at all — so whichever poll landed first took the
toast and it was gone. The tray's *own* menu controller was another: opening the menu
read `status` and swallowed whatever was pending.

Not a duplicate suppressed. On those two platforms this queue is the only notification
channel that exists, so a swallowed toast is a message the user never sees.

The fix is a flag, and its **default** is the load-bearing part. `status` still drains
unless the caller opts out, because the daemon keeps running the build it started with
until `yazses restart`: an older tray polling a newer daemon sends no flag, and a
default of "do not drain" would have it re-show the same toast on every poll — the tray
displays everything it receives, once per second. Defaulting to drain leaves every
version-skew combination no worse than it is today.
"""
from __future__ import annotations

import ast
import pathlib

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request
from yazses.platform import get_platform

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "yazses"

#: The only readers allowed to consume the queue: they display what they take.
#: Repo-relative, POSIX-spelled so the guard reads the same on Windows CI.
_DISPLAYERS = frozenset({"tray/app.py"})


def _status_call_sites() -> list[tuple[str, int, bool]]:
    """Every `…call("status", …)` in `src/`, with whether it opts out.

    Matched on the *first positional argument of a `.call()`* rather than on the string
    "status" appearing anywhere, because `cli.py` also has `_staged_call("status")` —
    which talks to the `staged` method with `action="status"` and has nothing to do with
    this queue. A grep-shaped guard would have demanded a flag on it.
    """
    sites: list[tuple[str, int, bool]] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "call"):
                continue
            if not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and first.value == "status"):
                continue
            opts_out = any(
                kw.arg == "consume_notifications"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is False
                for kw in node.keywords
            )
            sites.append((path.relative_to(SRC).as_posix(), node.lineno, opts_out))
    return sites


def test_the_scan_finds_the_call_sites():
    """A guard that iterates is green over an empty list. Prove it is not empty."""
    sites = _status_call_sites()
    assert len(sites) >= 12, sites
    files = {f for f, _, _ in sites}
    assert "tray/app.py" in files, files
    assert "overlay/poller.py" in files, "the reader this whole file is about"


def test_the_scan_does_not_confuse_the_staged_status_action():
    """`_staged_call("status")` is the `staged` method with `action="status"`.

    Asserted by reading the matched source lines rather than by naming a line number:
    a hardcoded location goes stale on the next edit to `cli.py` and the guard then
    passes for the wrong reason. This is what the scan must never pick up:

        return client.call("staged", action=action)   # via _staged_call("status")
    """
    lines = (SRC / "cli.py").read_text(encoding="utf-8").splitlines()
    matched = [lines[line - 1] for f, line, _ in _status_call_sites() if f == "cli.py"]

    assert matched, "no cli.py status calls found at all — the scan is broken"
    offenders = [ln.strip() for ln in matched if "_staged_call" in ln]
    assert not offenders, (
        f"{offenders} was matched, but its method is `staged`, not `status` — the guard "
        "would demand a flag on a call that has nothing to do with the toast queue"
    )


def test_every_status_reader_that_cannot_display_a_toast_opts_out():
    offenders = [
        f"{f}:{line}" for f, line, opts_out in _status_call_sites()
        if not opts_out and f not in _DISPLAYERS
    ]
    assert not offenders, (
        f"{offenders} read the daemon's status without "
        "`consume_notifications=False`, so they drain the queued toasts. On Windows and "
        "macOS that queue is the only notification channel, and these callers do not "
        "show what they take. Pass the flag, or — if this reader really does display "
        "them — add it to `_DISPLAYERS` here."
    )


def test_the_approved_displayer_actually_displays():
    """`_DISPLAYERS` is an exemption; it has to be earned, not asserted."""
    for name in _DISPLAYERS:
        source = (SRC / name).read_text(encoding="utf-8")
        assert "_show_notifications" in source, (
            f"{name} is exempted from opting out but never shows a notification"
        )


# --- the daemon's behaviour ---------------------------------------------------------


def _daemon():
    d = Daemon(config=Config(), platform=get_platform())
    d._queue_notification("YazSes", "Switched back to your USB microphone")
    return d


def _status(d, **params):
    return d._handle_status(Request(method="status", params=params) if params else None)


def test_a_reader_that_cannot_display_leaves_the_toast_for_the_tray():
    """The bug, in one assertion: the overlay reads, the tray still gets it."""
    d = _daemon()

    overlay = _status(d, consume_notifications=False)
    tray = _status(d)

    assert len(overlay["notifications"]) == 1, overlay["notifications"]
    assert len(tray["notifications"]) == 1, (
        "the overlay's poll swallowed the toast — on Windows and macOS the user would "
        "never see it"
    )


def test_the_displaying_reader_still_gets_each_toast_once():
    """Draining is the right behaviour for the consumer; it must not regress."""
    d = _daemon()

    assert len(_status(d)["notifications"]) == 1
    assert _status(d)["notifications"] == [], "a toast was delivered twice"


def test_an_unaware_caller_still_drains():
    """Version skew: an older tray sends no flag and must behave as it does today."""
    d = _daemon()
    assert len(d._handle_status(None)["notifications"]) == 1
    assert d._handle_status(None)["notifications"] == []


def test_a_request_with_no_params_still_drains():
    d = _daemon()
    assert len(d._handle_status(Request(method="status"))["notifications"]) == 1


def test_peeking_hands_out_a_copy():
    """The audio thread appends to that list while the caller serialises it."""
    d = _daemon()
    peeked = _status(d, consume_notifications=False)["notifications"]
    peeked.clear()
    assert len(_status(d)["notifications"]) == 1, "the peek handed out the live list"


def test_preparing_a_bug_report_does_not_eat_the_toast():
    """The daemon's own report build reads status; it is not a displayer.

    Source-level because the surrounding method opens a browser. The toast that
    prompted the user to click "prepare a report" is the last one to lose.
    """
    import inspect

    source = inspect.getsource(Daemon._prepare_bug_report)
    assert '"consume_notifications": False' in source, (
        "the diagnostic bundle drains the queue that produced it"
    )
