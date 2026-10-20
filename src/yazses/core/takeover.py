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
