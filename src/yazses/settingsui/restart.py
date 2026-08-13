"""Close the loop after Apply: restart the daemon and read the state back (#61).

Changing a feature writes config; the daemon reads config at startup. Until it is
restarted the window is showing settings that are not in effect, and the CLI's
answer — printing "run `yazses restart`" — is exactly the terminal round-trip the
settings app exists to remove.

All of the decisions live here with the IPC client and the restart command
injected, so the flow is unit-tested with fakes and the Qt dialog stays dumb.
That is the same split the rest of `settingsui/` uses.

## Honest state, not optimistic state

The window must never claim a restart worked because a command exited zero. A
daemon takes seconds to load a model, and "started" is not "ready" — so success
is defined as **`status` answering over IPC**, polled until it does or the
deadline passes. Anything else is reported as the failure it is, with the real
message.

Declining is a first-class outcome, not an error: the config is written either
way, so the window says the change is *pending a restart* and keeps saying it.
The one thing it may not do is go quiet and let the user believe a setting is
live when it is not.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class RestartState(Enum):
    """What the window should tell the user after Apply."""

    NOT_RUNNING = "not_running"      # nothing to restart; the change applies at next start
    PENDING = "pending"              # user declined; settings written but not in effect
    RESTARTED = "restarted"          # daemon is back and answering
    FAILED = "failed"                # it did not come back — say so


@dataclass(frozen=True)
class RestartOutcome:
    state: RestartState
    detail: str = ""

    @property
    def needs_restart_hint(self) -> bool:
        """True while the window should keep showing a 'restart pending' hint."""
        return self.state is RestartState.PENDING

    @property
    def message(self) -> str:
        if self.state is RestartState.RESTARTED:
            return f"Restarted. {self.detail}".strip()
        if self.state is RestartState.PENDING:
            return "Saved — your changes take effect when you restart YazSes."
        if self.state is RestartState.NOT_RUNNING:
            return "Saved. YazSes is not running; the changes apply when you start it."
        return f"Restart failed — {self.detail}"


def describe_status(status: dict | None) -> str:
    """One honest line about a running daemon, or "" when there is nothing to say."""
    if not status:
        return ""
    state = str(status.get("state") or "").strip()
    model = str(status.get("model") or "").strip()
    parts = [p for p in (f"state {state}" if state else "", f"model {model}" if model else "") if p]
    return f"Running ({', '.join(parts)})." if parts else "Running."


def apply_and_restart(
    *,
    is_running: Callable[[], bool],
    confirm: Callable[[], bool],
    restart: Callable[[], tuple[bool, str]],
    status: Callable[[], dict | None],
    ready_timeout_s: float = 30.0,
    poll_interval_s: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> RestartOutcome:
    """Offer a restart, perform it, and confirm the daemon really came back.

    Every effect is injected: `is_running`/`status` come from the IPC client,
    `restart` runs the same path as `yazses restart`, and `confirm` is the Qt
    dialog. Nothing here imports Qt.
    """
    if not is_running():
        # Nothing to restart. Prompting anyway would be a dialog whose only honest
        # answer is "there was nothing to do".
        return RestartOutcome(RestartState.NOT_RUNNING)

    if not confirm():
        return RestartOutcome(RestartState.PENDING)

    try:
        ok, detail = restart()
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, never raised at Qt
        return RestartOutcome(RestartState.FAILED, str(exc))
    if not ok:
        return RestartOutcome(RestartState.FAILED, detail or "the restart command failed")

    # "Started" is not "ready": the daemon still has to load a model. Success is
    # `status` answering, not a zero exit code.
    deadline = now() + ready_timeout_s
    last_error = ""
    while now() < deadline:
        try:
            reported = status()
        except Exception as exc:  # noqa: BLE001 - keep polling; it may still be starting
            last_error, reported = str(exc), None
        if reported:
            return RestartOutcome(RestartState.RESTARTED, describe_status(reported))
        sleep(poll_interval_s)

    return RestartOutcome(
        RestartState.FAILED,
        f"it did not answer within {ready_timeout_s:.0f}s"
        + (f" ({last_error})" if last_error else ""),
    )
