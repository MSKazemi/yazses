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
# A daemon that dies mid-session used to stay dead. On Linux systemd restarts it
# (`Restart=on-failure`) and on macOS launchd does (`KeepAlive`), but Windows
# autostart is a one-shot `HKCU\Run` value that fires at login and never again —
# so a crash at 10am meant no dictation until the user logged out and back in.
# The tray is already polling, already holds the lifecycle handle, and already
# spawns the daemon once at startup; it just never used any of that for recovery.
MAX_DAEMON_RELAUNCHES = 5
# Give a relaunched daemon time to boot and answer before trying again — model
# loading takes seconds, and the poll loop ticks every second.
RELAUNCH_COOLDOWN_S = 15.0


@dataclass(frozen=True)
class PollDecision:
    """What the poll loop should do about an unreachable daemon."""

    give_up: bool
    state: TrayState = TrayState.IDLE
    last_error: str | None = None
    # Spawn a replacement daemon. Only ever true when the daemon is genuinely
    # gone — a wedged one still holds its single-instance lock, so a replacement
    # would exit as a duplicate and achieve nothing but noise.
    relaunch: bool = False


def unreachable_decision(
    ever_connected: bool,
    waiting_s: float,
    *,
    daemon_running: bool = True,
    relaunches: int = 0,
    since_relaunch_s: float | None = None,
    max_relaunches: int = MAX_DAEMON_RELAUNCHES,
) -> PollDecision:
    """Decide how to react to an unreachable daemon. Pure, so it unit-tests directly.

    ``waiting_s`` is how long we have been waiting: since the tray started when we have
    never reached the daemon, since it went away when we had.

    Giving up is only ever right for a daemon that never came up at all — the tray
    spawned one and it failed to boot, so there is nothing to poll. Once the daemon HAS
    answered, an outage means a restart (routine) or a crash, and in both cases the poll
    loop has to survive: it owns the single-instance lock, so a tray that stops polling
    doesn't just freeze its own icon on whatever it last drew — it also makes every tray
    launched afterwards exit as a duplicate, leaving no way back short of killing it by
    hand.

    Past the grace period a crash is answered by **relaunching** the daemon rather than
    only turning the icon red. ``daemon_running`` distinguishes the two ways IPC can go
    quiet, and they need opposite responses: a *dead* daemon should be replaced, while a
    *wedged* one still holds the single-instance lock, so a replacement would exit
    immediately as a duplicate — there, red is all we honestly have. Relaunches are
    bounded and spaced by ``since_relaunch_s`` for the same reason the tray supervisor
    bounds its own: a daemon that dies on boot every time is broken in a way respawning
    cannot fix, and hammering it would just bury the real error.
    """
    if not ever_connected:
        if waiting_s > _DAEMON_BOOT_TIMEOUT_S:
            return PollDecision(give_up=True)
        # The tray already spawned one at startup; let it finish booting.
        return PollDecision(give_up=False, last_error="daemon starting")
    if waiting_s <= _RECONNECT_GRACE_S:
        return PollDecision(give_up=False, last_error="daemon restarting")

    if daemon_running:
        # Alive but not answering: replacing it is impossible (it holds the lock)
        # and would be wrong anyway — say so instead of pretending to act.
        return PollDecision(
            give_up=False, state=TrayState.ERROR, last_error="daemon not responding"
        )
    if relaunches >= max_relaunches:
        return PollDecision(
            give_up=False,
            state=TrayState.ERROR,
            last_error=(
                f"daemon died {relaunches} times; not restarting again — "
                "run `yazses start` to see the error it prints"
            ),
        )
    if since_relaunch_s is not None and since_relaunch_s < RELAUNCH_COOLDOWN_S:
        return PollDecision(
            give_up=False, state=TrayState.ERROR, last_error="daemon restarting"
        )
    return PollDecision(
        give_up=False,
        state=TrayState.ERROR,
        last_error="daemon stopped — restarting it",
        relaunch=True,
    )


def run() -> None:
    """Entry point — the `yazses-tray` GUI script."""
    # A GUI script has no console on Windows, so sys.stderr is None and
    # basicConfig's StreamHandler would raise on its first log line. Must come
    # before basicConfig, which binds the stream at construction time.
    from yazses.system.wincon import ensure_streams

    ensure_streams()
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
        relaunches = 0
        last_relaunch: float | None = None
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
                        audio_level=float(info.get("audio_level") or 0.0),
                        vad_threshold=float(info.get("vad_threshold") or 0.0),
                        # The daemon has always sent this; nothing carried it, so the
                        # tooltip said "Mic: default" however the device was pinned or
                        # auto-healed. Declaring the field without reading it here would
                        # just move the wrong answer one layer down.
                        input_device=info.get("input_device"),
                        # Meeting Mode's Start/Stop entries. `.get` with no default
                        # rather than `bool(...)` for the first one: None means an
                        # older daemon that never sent the key, and that is a
                        # different answer from "the feature is off".
                        meeting_enabled=info.get("meeting_enabled"),
                        meeting_active=bool(info.get("meeting_active")),
                        meeting_finalizing=bool(info.get("meeting_finalizing")),
                    )
                )
                # Toasts the daemon could not show itself (no libnotify — Windows,
                # macOS). The status read drains them, so a failure to display one
                # loses it; that is the right trade for a transient status message,
                # and far better than the log-only silence it replaces.
                _show_notifications(tray, info.get("notifications"))
                if str(info.get("state") or "") in _RECORDING_STATES:
                    interval = _FAST_POLL_INTERVAL_S  # keep the icon live during a burst
            except IpcUnreachableError:
                now = time.monotonic()
                if unreachable_since is None:
                    unreachable_since = now
                since = unreachable_since if ever_connected else started
                decision = unreachable_decision(
                    ever_connected,
                    now - since,
                    # Ask the lifecycle, not the socket: a daemon can be alive and
                    # wedged, and that must not be answered by spawning another.
                    daemon_running=_daemon_running(platform),
                    relaunches=relaunches,
                    since_relaunch_s=(None if last_relaunch is None else now - last_relaunch),
                )
                if decision.give_up:
                    log.warning("Daemon never became reachable; stopping poll.")
                    return
                tray.set_state(
                    TrayModel(state=decision.state, last_error=decision.last_error)
                )
                if decision.relaunch:
                    relaunches += 1
                    last_relaunch = now
                    log.warning(
                        "Daemon is gone; restarting it (attempt %d/%d).",
                        relaunches,
                        MAX_DAEMON_RELAUNCHES,
                    )
                    try:
                        platform.lifecycle.start_daemon_detached()
                    except Exception:
                        # Never let a failed respawn kill the poll loop: the tray
                        # holds the single-instance lock, so it dying strands the
                        # user with no icon and no way to start a new one.
                        log.exception("Restarting the daemon failed")
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


def _show_notifications(tray: object, raw: object) -> None:
    """Display toasts relayed from the daemon. Never raises into the poll loop.

    Tolerant of shape because this crosses an IPC boundary: an older daemon sends
    no `notifications` key at all, and a malformed entry must not cost the caller
    its status update.
    """
    if not isinstance(raw, list):
        return
    show = getattr(tray, "notify", None)
    if not callable(show):
        return
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "YazSes")
        body = str(item.get("body") or "")
        if not body:
            continue
        try:
            show(title, body)
        except Exception:
            log.debug("relayed notification failed", exc_info=True)


def _daemon_running(platform) -> bool:  # noqa: ANN001 - the Platform bundle
    """Is a daemon process alive, regardless of whether it is answering IPC?

    Never raises: this only informs *how* to react to an outage, so a probe that
    fails must not be the thing that stops the poll loop. On the safe side —
    "still running" means the tray reports the problem instead of respawning.
    """
    try:
        return bool(platform.lifecycle.is_running())
    except Exception:
        log.debug("daemon liveness probe failed", exc_info=True)
        return True


def _state_from_string(s: object) -> TrayState:
    if not isinstance(s, str):
        return TrayState.IDLE
    try:
        return TrayState(s)
    except ValueError:
        return TrayState.IDLE


if __name__ == "__main__":
    run()
