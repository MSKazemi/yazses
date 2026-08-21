"""Keep the tray icon on screen for the whole session, not just the first minute.

The daemon launches the tray once at startup and then forgets it. If that process dies —
a Qt crash, an OOM kill, a desktop-shell restart taking its tray with it, or the user
choosing "Quit tray" from its own menu — the icon is simply gone until the *daemon* is
restarted. Dictation keeps working, which is what makes it insidious: the only thing that
tells you whether YazSes is listening, muted, in command mode, or has nowhere to type has
vanished, and nothing anywhere says so.

Liveness is read from the tray's own single-instance lock rather than from a child PID.
That is deliberate: the lock is held by whichever tray is actually running, so it stays
correct when the tray was started by hand, survived a daemon restart, or was replaced —
all states a remembered ``Popen`` handle gets wrong. It is also the exact condition a new
tray would test, so this cannot fight the lock and spawn a process that immediately exits.

The policy is pure and lives here; the thread and the spawning live in the daemon.
"""
from __future__ import annotations

from dataclasses import dataclass

# A tray that dies immediately, over and over, is broken in a way relaunching cannot fix
# (no display, a missing Qt platform plugin). Try a bounded number of times, then stop and
# say so, rather than spawning a process every few seconds for the rest of the session.
DEFAULT_MAX_RELAUNCHES = 5
# Long enough that a user who deliberately quit the tray is not fighting a daemon that
# keeps resurrecting it within the same breath; short enough that a crash is invisible.
DEFAULT_INTERVAL_S = 20.0


@dataclass(frozen=True)
class RelaunchDecision:
    """Whether to relaunch, and what to say about it."""

    relaunch: bool
    give_up: bool = False
    reason: str = ""


def decide(*, alive: bool, relaunches_so_far: int,
           max_relaunches: int = DEFAULT_MAX_RELAUNCHES) -> RelaunchDecision:
    """Decide what to do about the tray, given whether one is currently running.

    ``alive`` should come from the tray lock being held, not from a process handle.
    """
    if alive:
        return RelaunchDecision(relaunch=False)
    if relaunches_so_far >= max_relaunches:
        return RelaunchDecision(
            relaunch=False,
            give_up=True,
            reason=(
                f"tray died {relaunches_so_far} times; not relaunching again. "
                "Start it manually with `yazses tray` to see the error it prints."
            ),
        )
    return RelaunchDecision(relaunch=True, reason="tray is not running — relaunching")


#: Cap on what a dead tray's stderr may contribute to the daemon log. A Qt plugin
#: failure is a few lines; a traceback with a loop in it is not, and the daemon log is
#: also what `yazses report` attaches to an issue.
STDERR_TAIL_LINES = 12


def describe_exit(stderr_text: str) -> str:
    """One-line-per-line summary of why a tray process died, or "" if it said nothing.

    The supervisor used to launch the tray with ``stderr=DEVNULL`` and then, on giving
    up, advise *"start it manually with `yazses tray` to see the error it prints"* — an
    instruction that only exists because the error was thrown away. Observed on a real
    machine: five relaunches across an evening and not one word about the cause.

    Blank lines and Python's ``Traceback (most recent call last):`` banner are dropped;
    the banner costs a line of the budget and carries nothing the frames below it do not.
    """
    lines = [ln.rstrip() for ln in stderr_text.splitlines()]
    lines = [
        ln for ln in lines
        if ln.strip() and not ln.startswith("Traceback (most recent call last)")
    ]
    if not lines:
        return ""
    # The tail, not the head: the exception type and message are the last thing printed,
    # and they are what names the cause. A head-first cut keeps the frames and drops it.
    return "\n".join(lines[-STDERR_TAIL_LINES:])
