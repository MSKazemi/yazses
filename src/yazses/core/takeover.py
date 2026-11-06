"""Should a starting daemon replace the one that already holds the lock?

Pure, so the rule is tested directly. The rule is deliberately narrow: replace only a
daemon that is **strictly older** than this one. Two equal versions are two copies of the
same program (a duplicate start, which the lock exists to refuse), and a newer incumbent
must never be displaced by an older launcher, or two installs would take the lock from
each other in a loop.

Why it exists at all: a daemon reads its permissions, its config and its code once, when
it starts. After an upgrade the previous daemon keeps running, the new app exits as a
duplicate, and the user is left with the old answer -- on macOS that is the keyboard
permission read before it was granted (#562, #578).
"""

from __future__ import annotations

import re

_NUMERIC_HEAD = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)")


def _head(version: object) -> tuple[int, int, int] | None:
    if not isinstance(version, str):
        return None
    m = _NUMERIC_HEAD.match(version)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def is_older(incumbent: object, mine: object) -> bool:
    """True only when both versions parse and ``incumbent`` is strictly lower.

    Anything unreadable answers False: an incumbent that did not report a version (an
    old daemon, a failed call) is left alone, which is today's behaviour. Pre-release and
    dev suffixes are ignored -- ``2.43.0.dev1`` and ``2.43.0`` compare equal -- because a
    takeover on a suffix difference would be a guess.
    """
    theirs, ours = _head(incumbent), _head(mine)
    return theirs is not None and ours is not None and theirs < ours


# ---- replacing a running daemon from outside it (the tray, #578) ---------------------------
#
# `is_older` above is asked by a *starting daemon*. The tray never starts one while a daemon
# is running, so a user who reopens the upgraded app, or reopens it after granting a
# permission, got a new tray talking to the old daemon. These are asked by the tray instead,
# from the `status` reply it already polls.

#: The states in which a running daemon may be replaced from outside. Idle and error only:
#: every other state is either doing work the user asked for (a recording, a transcription,
#: a meeting, a read-back, an enrolment) or on its way somewhere (loading), and `paused` is
#: a choice the user made that a fresh daemon would not remember.
REPLACEABLE_STATES = frozenset({"idle", "error"})

#: How long after one hand-off the same reason may trigger another, across processes. A
#: daemon closes the tray it launched, so a tray that restarts its own parent is followed
#: by a fresh tray with no memory; only a record on disk stops that from becoming a loop
#: when a restart does not clear the reason (a permission probe that flaps).
REPLACE_SILENCE_S = 60.0 * 60.0


def _stale_grants(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v]


def replacement_reason(status: object, mine: object) -> str | None:
    """Why the daemon that sent ``status`` should be replaced by a fresh start, or None.

    ``"older"`` when it is strictly older than ``mine`` (:func:`is_older`), and
    ``"permissions"`` when it reports ``stale_permissions`` -- grants given after it
    started, which its keyboard tap cannot see (#578). Both are the daemon's own report,
    a specific and checkable signal rather than a heuristic (ADR-021).

    None for anything else: a daemon that is busy (see :data:`REPLACEABLE_STATES`) or in a
    meeting, a current one, and any reply of the wrong shape.
    """
    if not isinstance(status, dict):
        return None
    state = status.get("state")
    if not isinstance(state, str) or state not in REPLACEABLE_STATES:
        return None
    # Both flags reach `status` from v2.25.0; `version` from v2.24.0. A v2.24.x daemon
    # finalizing a meeting reports `transcribing`, which the state rule above refuses.
    if status.get("meeting_active") or status.get("meeting_finalizing"):
        return None
    if is_older(status.get("version"), mine):
        return "older"
    if _stale_grants(status.get("stale_permissions")):
        return "permissions"
    return None


def may_replace_again(
    last: float | None, now: float, *, silence_s: float = REPLACE_SILENCE_S
) -> bool:
    """Whether a hand-off recorded at ``last`` (epoch seconds, or None) allows one ``now``.

    A record from the future (a clock set back) counts as stale rather than as a block
    that could last for as long as the clock is wrong.
    """
    return last is None or not (0.0 <= now - last < silence_s)
