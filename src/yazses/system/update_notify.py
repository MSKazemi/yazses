"""Background "a newer YazSes is out" check — the policy, and its on-disk state.

Why this is opt-in
------------------
This is the only part of YazSes that reaches the network without being asked. The
project rule is that nothing leaves the machine, so ``[general] update_check``
defaults to ``false`` and this module stays completely dormant until someone turns
it on (``yazses features enable update-check``). What it sends when enabled is a
plain "what is the latest version" GET to github.com or PyPI — no voice, no text,
no config, no identifier — but it is still an outbound connection, which is a
choice the user makes rather than one made for them.

What it guarantees when it *is* on
----------------------------------
1. **It cannot break dictation.** It runs on its own thread, off the hot path, and
   every failure — no network, a firewall, a proxy, a rate limit, a bad payload —
   is swallowed. A blocked check is a no-op that retries later, never an error the
   user has to deal with. That is the whole point: someone who blocks YazSes at
   the firewall must keep a working dictation daemon.
2. **It notifies once per version, not once per check.** The state file remembers
   the last version announced, so a user who reads the toast and decides to update
   next month is not told again every day. A newer release re-arms it.
3. **It says how to update.** The toast carries the steps from
   ``updater.manual_update_steps`` — the same ones ``yazses update`` prints — so a
   Windows-installer user is not told "2.21.0 is out" with nothing to act on.

Everything except :func:`read_state`/:func:`write_state` is pure, so the policy is
testable with no clock, no filesystem and no network.
"""
from __future__ import annotations

import json
from pathlib import Path

__all__ = [
    "STATE_NAME",
    "UpdateState",
    "notification",
    "read_state",
    "should_check",
    "should_notify",
    "write_state",
]

STATE_NAME = "update-check.json"

# Floor on the check interval. A user who writes `update_check_interval_hours = 0`
# means "as often as possible", not "hammer the API in a tight loop" — and GitHub
# rate-limits unauthenticated requests, so a runaway check would get itself
# blocked and then report "could not reach github.com" forever.
MIN_INTERVAL_HOURS = 1.0


class UpdateState:
    """Last check time (epoch seconds) and last version already announced."""

    __slots__ = ("last_check", "notified_version")

    def __init__(self, last_check: float = 0.0, notified_version: str = "") -> None:
        self.last_check = last_check
        self.notified_version = notified_version

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, UpdateState):
            return NotImplemented
        return (
            self.last_check == other.last_check
            and self.notified_version == other.notified_version
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"UpdateState(last_check={self.last_check!r}, notified_version={self.notified_version!r})"


# ---- policy (pure) ---------------------------------------------------------

def should_check(now: float, last_check: float, interval_hours: float) -> bool:
    """True when the interval has elapsed since ``last_check``.

    A ``last_check`` in the future (a clock that moved backwards, a state file
    copied from another machine) counts as due rather than locking the check out
    until the clock catches up.
    """
    interval = max(float(interval_hours), MIN_INTERVAL_HOURS) * 3600.0
    if last_check <= 0 or last_check > now:
        return True
    return (now - last_check) >= interval


def should_notify(status, notified_version: str) -> bool:
    """True when there is an update the user has not already been told about."""
    if not getattr(status, "available", False):
        return False
    latest = getattr(status, "latest", None)
    if not latest:
        return False
    return latest != notified_version


def notification(status) -> tuple[str, str]:
    """``(summary, body)`` for the desktop toast announcing an available update."""
    from yazses import branding
    from yazses.system.updater import manual_update_steps

    summary = f"{branding.APP_NAME} {status.latest} is available"
    lines = [f"You're running {status.current}."]
    command = list(getattr(status, "command", None) or [])
    if command:
        lines.append(f"Update with:  {' '.join(command)}")
    else:
        steps = list(getattr(status, "steps", None) or []) or manual_update_steps(status.method)
        lines.append("How to update:")
        lines.extend(f"  {s}" for s in steps if s)
    return summary, "\n".join(lines)


# ---- state (I/O, never raises) ---------------------------------------------

def read_state(path: Path) -> UpdateState:
    """Load the state file; a missing, unreadable or corrupt one reads as empty.

    Never raises. A damaged state file must cost at most one extra check, not a
    crashed watcher thread.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return UpdateState()
    if not isinstance(payload, dict):
        return UpdateState()
    try:
        last = float(payload.get("last_check", 0) or 0)
    except (TypeError, ValueError):
        last = 0.0
    version = payload.get("notified_version") or ""
    return UpdateState(last, version if isinstance(version, str) else "")


def write_state(path: Path, state: UpdateState) -> bool:
    """Persist *state*; return False (never raise) if it could not be written."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {"last_check": state.last_check, "notified_version": state.notified_version},
                indent=2,
            ),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False
