"""A monotonic clock that keeps counting while the machine is asleep.

``time.monotonic()`` is the right clock for measuring how long something took: it
cannot be dragged backwards by an NTP correction or a timezone change. It is the
wrong clock for measuring *how long a process has existed*, because on Linux it maps
to ``CLOCK_MONOTONIC``, which stops ticking across a suspend.

Measured on a laptop, 2026-08-20: the daemon had been running for 9 h 25 m by ``ps``
with ``NRestarts=0``, and ``yazses status`` reported 5 h 29 m. The difference was
3 h 55 m 43 s, exactly ``CLOCK_BOOTTIME - CLOCK_MONOTONIC`` on that machine — the time
the lid had been shut.

That matters because of what the field is *for*. ``cli._format_uptime`` says it: "a
long uptime is how you notice a daemon that predates the upgrade". A daemon keeps
running the build it started with until it is restarted, so uptime is the surface that
reveals a stale process — and it read low on precisely the device class where a process
is most likely to be stale, a laptop that sleeps every night. Over a week of nightly
suspends the two answers diverge by most of a day.

Deliberately **not** used for durations. Anything measuring an interval that happens
while the machine is awake — a decode, a hold, a recording's elapsed time, a
continuation window — keeps ``time.monotonic()``: those want the wake-time answer, and
a suspend in the middle of one is either impossible or a reason to stop, not to count.
"""
from __future__ import annotations

import time

#: ``CLOCK_BOOTTIME`` is Linux-only and absent on macOS and Windows, so it is probed
#: rather than assumed. Resolved once at import: the constant cannot appear later.
_BOOTTIME = getattr(time, "CLOCK_BOOTTIME", None)


def monotonic_including_suspend() -> float:
    """Seconds from an arbitrary epoch, counting time spent suspended.

    Falls back to :func:`time.monotonic` where ``CLOCK_BOOTTIME`` does not exist. Both
    ends of a measurement must come from this function — mixing the two clocks yields
    a difference that is neither.

    The fallback is not equivalent everywhere, and this docstring is the honest record
    of what was actually verified: on Linux the two clocks were measured to differ by
    the suspend time. On other platforms ``time.monotonic()`` is used unchanged, which
    is no worse than the behaviour this replaced.
    """
    if _BOOTTIME is not None:
        try:
            return time.clock_gettime(_BOOTTIME)
        except (OSError, AttributeError, ValueError):
            # A kernel or libc that names the constant and refuses the call. Falling
            # back is always safe: it is the clock this code used before.
            pass
    return time.monotonic()


def counts_suspend() -> bool:
    """Whether :func:`monotonic_including_suspend` is actually suspend-aware here.

    For diagnostics and for the test suite, which must not assert Linux behaviour on a
    CI runner that has no ``CLOCK_BOOTTIME``.
    """
    return _BOOTTIME is not None
