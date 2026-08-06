"""Cross-platform tray application.

The tray is a thin status / control layer that talks to the daemon over IPC.
It does NOT drive the dictation pipeline itself — the daemon does. On launch:

1. If the daemon isn't reachable, spawn it via :meth:`Lifecycle.start_daemon_detached`.
2. Poll the daemon's ``status`` RPC every second; map state → tray glyph.
3. On quit, send ``shutdown`` over IPC.

The tray's ``run()`` blocks the main thread (it owns the OS runloop on macOS,
the message pump on Windows). Polling happens on a worker thread.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass

from yazses.ipc.client import IpcCallError, IpcUnreachableError
from yazses.platform import TrayModel, TrayState, get_platform

log = logging.getLogger(__name__)


_POLL_INTERVAL_S = 1.0
# Poll faster while recording so the icon reflects the burst (green ↔ yellow when there's
# no text target) during a short hold, instead of lagging a full second behind.
_FAST_POLL_INTERVAL_S = 0.15
_RECORDING_STATES = frozenset({"recording", "transcribing", "injecting", "meeting"})
_DAEMON_BOOT_TIMEOUT_S = 30.0
# How long the daemon may be away, after we have already talked to it, before the icon
# stops claiming everything is fine. `yazses restart` takes the socket down for a second
# or two; flashing red for that would be noise, staying blue for a dead daemon would be
# a lie. Short grace, then say so.
_RECONNECT_GRACE_S = 5.0


@dataclass(frozen=True)
class PollDecision:
    """What the poll loop should do about an unreachable daemon."""

    give_up: bool
    state: TrayState = TrayState.IDLE
    last_error: str | None = None


def unreachable_decision(ever_connected: bool, waiting_s: float) -> PollDecision:
    """Decide how to react to an unreachable daemon. Pure, so it unit-tests directly.

    ``waiting_s`` is how long we have been waiting: since the tray started when we have
    never reached the daemon, since it went away when we had.

    Giving up is only ever right for a daemon that never came up at all — the tray
    spawned one and it failed to boot, so there is nothing to poll. Once the daemon HAS
    answered, an outage means a restart (routine) or a crash (the user will restart it),
    and in both cases the poll loop has to survive: it owns the single-instance lock, so
    a tray that stops polling doesn't just freeze its own icon on whatever it last drew —
    it also makes every tray launched afterwards exit as a duplicate, leaving no way back
    short of killing it by hand.
    """
    if not ever_connected:
        if waiting_s > _DAEMON_BOOT_TIMEOUT_S:
            return PollDecision(give_up=True)
        return PollDecision(give_up=False, last_error="daemon starting")
    if waiting_s > _RECONNECT_GRACE_S:
        return PollDecision(
            give_up=False, state=TrayState.ERROR, last_error="daemon not responding"
        )
    return PollDecision(give_up=False, last_error="daemon restarting")


def run() -> None:
    """Entry point — `yazses-tray` console script."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    platform = get_platform()
    if platform.tray_factory is None:
        log.error("Platform %r has no tray backend; nothing to do.", platform.name)
        sys.exit(1)

    # One tray only: the daemon auto-launches it, and `yazses restart` would spawn a
    # second. An exclusive lock (freed by the OS on exit) makes a duplicate exit quietly.
    from yazses.system.single_instance import SingleInstanceLock

    lock = SingleInstanceLock(platform.paths.data_dir / "tray.lock")
    if not lock.acquire():
        log.info("A YazSes tray is already running; exiting.")
        return

    tray = platform.tray_factory()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)

    if not platform.lifecycle.is_running():
        log.info("Daemon not running; spawning.")
        platform.lifecycle.start_daemon_detached()

    stop_event = threading.Event()

    def _poller() -> None:
        started = time.monotonic()
        ever_connected = False
        unreachable_since: float | None = None
        while not stop_event.is_set():
            interval = _POLL_INTERVAL_S
            try:
                info = client.call("status")
                ever_connected = True
                unreachable_since = None
                state = _state_from_string(info.get("state"))
                tray.set_state(
                    TrayModel(
                        state=state,
                        hotkey=str(info.get("hotkey", "auto")),
                        model=str(info.get("model", "")),
                        last_error=info.get("last_error"),
                        uptime_s=float(info.get("uptime_s", 0.0)),
                        silent_streak=int(info.get("silent_streak") or 0),
                        target_ok=info.get("target_ok"),
                        command_mode=bool(info.get("command_mode")),
                    )
                )
                if str(info.get("state") or "") in _RECORDING_STATES:
                    interval = _FAST_POLL_INTERVAL_S  # keep the icon live during a burst
            except IpcUnreachableError:
                if unreachable_since is None:
                    unreachable_since = time.monotonic()
                since = unreachable_since if ever_connected else started
                decision = unreachable_decision(ever_connected, time.monotonic() - since)
                if decision.give_up:
                    log.warning("Daemon never became reachable; stopping poll.")
                    return
                tray.set_state(
                    TrayModel(state=decision.state, last_error=decision.last_error)
                )
            except IpcCallError as exc:
                log.warning("status RPC failed: %s", exc)
                tray.set_state(TrayModel(state=TrayState.ERROR, last_error=str(exc)))
            except Exception:
                log.exception("Tray poller crashed")
                return
            stop_event.wait(interval)

    poll_thread = threading.Thread(target=_poller, name="tray-poller", daemon=True)
    poll_thread.start()

    def _on_quit() -> None:
        stop_event.set()
        try:
            client.call("shutdown")
        except IpcUnreachableError:
            pass
        except Exception:
            log.exception("Sending shutdown to daemon failed")

    try:
        tray.run(_on_quit)
    finally:
        stop_event.set()


def _state_from_string(s: object) -> TrayState:
    if not isinstance(s, str):
        return TrayState.IDLE
    try:
        return TrayState(s)
    except ValueError:
        return TrayState.IDLE


if __name__ == "__main__":
    run()
