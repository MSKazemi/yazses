"""Sample how busy this machine is, for the Adaptive Latency Governor (ADR-v2-073).

The governor's policy is pure (:mod:`yazses.latency.governor`); this is the one impure
half, kept small enough to read in a sitting.

**No new dependency.** psutil would give a per-interval CPU percentage, but it is not in
this project's dependency set and adding a runtime dep to pick a beam width is the wrong
trade. ``os.getloadavg`` is stdlib, costs a read of ``/proc/loadavg``, and answers the
question the governor actually asks — *is this machine under load right now* — rather than
the instantaneous one.

**It does not exist on Windows.** ``os.getloadavg`` is POSIX-only, so :func:`cpu_percent`
returns ``None`` there and the governor stays dormant rather than guessing. The daemon
says so once through ``_warn_feature_inert`` instead of leaving an enabled feature silent.

**Why the 1-minute average rather than the 5- or 15-minute one.** The governor decides
what to do with the *next* utterance. A 15-minute average would still be reporting a build
that finished ten minutes ago.
"""
from __future__ import annotations

import os


def cpu_percent() -> float | None:
    """Recent system load as a percentage of total CPU capacity, or ``None``.

    ``None`` means "this platform cannot answer" — never 0.0, which the governor
    would read as an idle machine and act on.

    A load average is a count of runnable processes, so it is normalised by the core
    count and is not capped at 100: a load of 16 on 8 cores is 200%, which is exactly
    the state the high-load policy exists for.
    """
    try:
        one_minute = os.getloadavg()[0]
    except (OSError, AttributeError):  # Windows, or a kernel without /proc/loadavg
        return None
    cores = os.cpu_count() or 1
    return (one_minute / cores) * 100.0


def unavailable_reason() -> str | None:
    """Why the governor cannot run here, or ``None`` when it can. For the log line."""
    if cpu_percent() is None:
        return (
            "this platform exposes no load average (os.getloadavg is POSIX-only), so "
            "the governor has nothing to decide on"
        )
    return None
