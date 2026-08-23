"""A daemon's uptime must not shrink because the laptop slept.

Measured on the machine that found this, 2026-08-20 23:1x:

    $ ps -o lstart,etime -p 4237
    Thu Aug 20 13:51:43 2026    09:25:51
    $ systemctl --user show yazses -p NRestarts
    NRestarts=0
    $ yazses status
      uptime:   5h 29m

    >>> time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()
    14142.67          # 3 h 55 m 43 s

The process had not restarted. The gap between the reported uptime and the real one
was exactly the time the lid had been shut, because `time.monotonic()` maps to
`CLOCK_MONOTONIC` on Linux and that clock stops while the machine is suspended.

Why it is worth a clock swap rather than a shrug: `cli._format_uptime` states the
field's purpose — "a long uptime is how you notice a daemon that predates the
upgrade". A daemon keeps running the build it started with until restarted, so uptime
is the surface that reveals a stale process, and it read low on exactly the device
class where a process is most likely to be stale. Over a week of nightly suspends the
error grows to most of a day, which is the difference between "this daemon is from
before the upgrade" and "this daemon looks current".
"""
from __future__ import annotations

import inspect
import re
import time

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.system import uptime as uptime_mod

# --- the clock itself ---------------------------------------------------------------


def test_it_returns_a_float_that_advances():
    first = uptime_mod.monotonic_including_suspend()
    assert isinstance(first, float)
    assert uptime_mod.monotonic_including_suspend() >= first


def test_on_linux_it_tracks_boottime_not_monotonic():
    """The whole point, asserted only where the clock exists."""
    if not uptime_mod.counts_suspend():
        return  # macOS/Windows: no CLOCK_BOOTTIME, nothing to compare against.
    ours = uptime_mod.monotonic_including_suspend()
    boot = time.clock_gettime(time.CLOCK_BOOTTIME)
    mono = time.monotonic()
    # Same clock as BOOTTIME (sampled microseconds apart), and never the shorter one.
    assert abs(ours - boot) < 1.0, (ours, boot)
    assert ours >= mono - 1.0, (ours, mono)


def test_it_falls_back_when_the_constant_is_absent(monkeypatch):
    """macOS and Windows have no CLOCK_BOOTTIME; the probe must not raise there."""
    monkeypatch.setattr(uptime_mod, "_BOOTTIME", None)
    value = uptime_mod.monotonic_including_suspend()
    assert isinstance(value, float)
    assert abs(value - time.monotonic()) < 1.0


def test_it_falls_back_when_the_call_is_refused(monkeypatch):
    """A kernel that names the constant and rejects the call must not kill status.

    ``raising=False`` because Windows has no ``time.clock_gettime`` at all, and
    without it this test raised ``AttributeError`` during *setup* on every Windows
    runner -- red CI for the one platform where the fallback is not a hypothetical.
    """
    monkeypatch.setattr(uptime_mod, "_BOOTTIME", 7)

    def _refuse(_clock):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(time, "clock_gettime", _refuse, raising=False)
    assert isinstance(uptime_mod.monotonic_including_suspend(), float)


# --- the daemon actually using it ---------------------------------------------------


def _daemon():
    d = Daemon(config=Config(), platform=get_platform())
    return d


def test_status_reports_the_suspend_as_uptime(monkeypatch):
    """Replay the measured numbers: 9 h 25 m real, of which 3 h 55 m was asleep."""
    import yazses.core.daemon as daemon_mod

    awake = 19808.0          # 5 h 30 m of CLOCK_MONOTONIC
    suspended = 14142.67     # 3 h 55 m 43 s the lid was shut
    started = 1000.0

    d = _daemon()
    d._state.started_at = started
    monkeypatch.setattr(
        daemon_mod, "monotonic_including_suspend", lambda: started + awake + suspended
    )

    info = d._handle_status(None)

    assert info["uptime_s"] == round(awake + suspended, 2), (
        "status dropped the suspended time — the old CLOCK_MONOTONIC behaviour"
    )
    assert info["uptime_s"] > 9 * 3600, "9 h 25 m of real uptime must read as over 9 h"


def test_status_still_reports_zero_before_the_stamp_is_set():
    d = _daemon()
    d._state.started_at = 0.0
    assert d._handle_status(None)["uptime_s"] == 0.0


def test_both_ends_read_the_same_clock():
    """Stamp and read must agree, or the difference is meaningless.

    Source-level on purpose: a functional test can pin the *read* (above) but the
    stamp happens inside `run()`, behind IPC, hotkeys and a model load. This is the
    cheap way to prove the pair moved together — and the pair is the whole bug.
    """
    stamp = inspect.getsource(Daemon.run)
    read = inspect.getsource(Daemon._handle_status)

    assert re.search(r"started_at\s*=\s*monotonic_including_suspend\(\)", stamp), (
        "run() no longer stamps started_at with the suspend-aware clock"
    )
    assert "monotonic_including_suspend()" in read, (
        "_handle_status no longer reads the suspend-aware clock"
    )
    assert not re.search(r"started_at\s*=\s*time\.monotonic\(\)", stamp), (
        "run() stamps started_at with time.monotonic() again — that clock stops "
        "across a suspend and the reported uptime shrinks by the time slept"
    )
    assert not re.search(r"time\.monotonic\(\)\s*-\s*self\._state\.started_at", read), (
        "_handle_status measures uptime with time.monotonic() again"
    )


def test_durations_keep_the_wake_time_clock():
    """The swap must not leak into interval measurement.

    A meeting's elapsed time drives the `max_minutes` auto-stop and measures audio
    that only exists while the machine is awake. `time.monotonic()` is correct there,
    and staying correct is worth a line here because the two calls look alike.
    """
    source = inspect.getsource(Daemon._handle_meeting_start)
    assert "started_at=time.monotonic()" in source, (
        "the meeting controller's elapsed clock should stay on time.monotonic()"
    )
