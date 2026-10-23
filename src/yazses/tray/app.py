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
from yazses.tray.menu import _RECORDING_STATES

log = logging.getLogger(__name__)


# 0.25 s, not 1.0 s. This is the rate at which a *transition* is caught, not the rate
# at which a steady state is refreshed, and hold-to-talk bursts are 1-2 s long: at 1.0 s
# a short burst could begin and end between two samples and never be observed at all,
# so the icon stayed blue through a dictation that worked. Reported first-hand from
# Windows as "the colour does not change". The overlay -- the other process polling the
# same status RPC for the same transition -- already used 0.25 s for exactly this
# reason; the tray was deciding it independently and getting it wrong.
_POLL_INTERVAL_S = 0.25
# Poll faster once recording is observed so the icon tracks changes *within* the burst
# (green ↔ yellow when there's no text target). This rate can only ever refine what the
# rate above has already caught, which is why the one above is the load-bearing one.
_FAST_POLL_INTERVAL_S = 0.15
# Imported, not restated. This file and `tray/menu.py` each held an identical
# four-element copy, and the two decide the same thing: `menu.py` picks the icon
# colour for a state, this file decides whether to poll faster during it. A state
# added to one and not the other gives an icon that is the right colour and a
# second behind, or vice versa -- a divergence nothing would report.
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
    # Close the tray: the user ran `yazses stop`, which means all of YazSes.
    close_tray: bool = False


def unreachable_decision(
    ever_connected: bool,
    waiting_s: float,
    *,
    daemon_running: bool = True,
    relaunches: int = 0,
    since_relaunch_s: float | None = None,
    max_relaunches: int = MAX_DAEMON_RELAUNCHES,
    stop_requested: bool = False,
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

    ``stop_requested`` comes first: `yazses stop` left a note after this tray started
    (``system/stop_request.py``), so the daemon is gone on purpose and the tray goes
    with it. Restarting it, as this used to, undid the stop within seconds. A daemon
    still shutting down is waited for, not answered.
    """
    if stop_requested:
        if daemon_running:
            return PollDecision(give_up=False, last_error="daemon stopping")
        return PollDecision(give_up=True, close_tray=True)
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


#: How often the tray looks for a one-click update started by another process. A stat
#: and a small JSON read; the job waits minutes for the tray, so a second is plenty.
_UPDATE_WATCH_INTERVAL_S = 1.0


class UpdateHandoffWatch:
    """Whether this tray must close for a one-click update another process started.

    Inert where the platform has no ``UpdateLauncher`` (everything but Windows). Never
    raises: a check that fails answers "no", and the tray keeps running.
    """

    def __init__(self, launcher, *, clock=time.monotonic, wall=time.time, own_pid=None,
                 interval_s: float = _UPDATE_WATCH_INTERVAL_S) -> None:  # noqa: ANN001
        import os

        self._launcher = launcher
        self._clock = clock
        self._since = wall()
        self._own_pid = os.getpid() if own_pid is None else own_pid
        self._interval = interval_s
        self._next = clock()

    def should_close(self) -> bool:
        if self._launcher is None:
            return False
        now = self._clock()
        if now < self._next:
            return False
        self._next = now + self._interval
        try:
            from yazses.system.installer_update import handoff_started_elsewhere

            return handoff_started_elsewhere(
                self._launcher.staging_dir(), since=self._since, own_pid=self._own_pid
            )
        except Exception:
            log.debug("could not check for an update hand-off", exc_info=True)
            return False


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

    # Wall clock, because `yazses stop` writes its note from another process: only a
    # note left after this moment can close this tray (see system/stop_request.py).
    tray_started_wall = time.time()
    from yazses.system.stop_request import stop_requested_since

    if not platform.lifecycle.is_running():
        log.info("Daemon not running; spawning.")
        platform.lifecycle.start_daemon_detached()

    stop_event = threading.Event()
    update_watch = UpdateHandoffWatch(getattr(platform, "update_launcher", None))

    def _poller() -> None:
        started = time.monotonic()
        ever_connected = False
        unreachable_since: float | None = None
        relaunches = 0
        last_relaunch: float | None = None
        while not stop_event.is_set():
            interval = _POLL_INTERVAL_S
            if update_watch.should_close():
                # `yazses update` (or another surface) handed off a one-click update and
                # its job is waiting for this process to exit (ADR-027). Closing runs
                # `_on_quit`, which stops the poll *before* it asks the daemon to shut
                # down, so the daemon is not respawned behind the installer's back.
                log.info("A YazSes update was started elsewhere; closing the tray for it.")
                tray.stop()
                return
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
                        # `[stt] idle_unload_s` (ADR-029): None at the default and on
                        # an older daemon; `residency_line` ignores any other shape.
                        stt_residency=(
                            info.get("stt_residency")
                            if isinstance(info.get("stt_residency"), dict)
                            else None
                        ),
                        # The decoder that actually came up (#644), for the menus'
                        # status line. Never filled in from `model`: a status that
                        # repeats the config is what hid a failed Parakeet load.
                        engine=(
                            str(info["engine"]) if info.get("engine") else None
                        ),
                        engine_model=(
                            str(info["engine_model"]) if info.get("engine_model") else None
                        ),
                        engine_fallback=(
                            info.get("engine_fallback")
                            if isinstance(info.get("engine_fallback"), dict)
                            else None
                        ),
                    )
                )
                # Toasts the daemon could not show itself (no libnotify — Windows,
                # macOS). This poll is the ONE status read that consumes the queue —
                # every other reader in `src/` passes `consume_notifications=False`,
                # because it cannot show what it takes. `status` has fourteen callers,
                # and the overlay polls it continuously right beside this loop.
                # A failure to display one still loses it; that is the right trade for
                # a transient status message, and far better than the log-only silence
                # it replaces.
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
                    stop_requested=stop_requested_since(
                        platform.paths.data_dir, tray_started_wall
                    ),
                )
                if decision.close_tray:
                    log.info("`yazses stop` stopped the daemon; closing the tray too.")
                    tray.stop()
                    return
                if decision.give_up:
                    log.warning("Daemon never became reachable; stopping poll.")
                    return
                tray.set_state(
                    # `model=""`: no daemon answered, so no model is known. The
                    # dataclass default ("tiny.en") would otherwise be shown as the
                    # model on the macOS menu's status line.
                    TrayModel(state=decision.state, last_error=decision.last_error, model="")
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
                tray.set_state(
                    TrayModel(state=TrayState.ERROR, last_error=str(exc), model="")
                )
            except Exception:
                log.exception("Tray poller crashed")
                return
            stop_event.wait(interval)

    poll_thread = threading.Thread(target=_poller, name="tray-poller", daemon=True)
    poll_thread.start()
    start_addon_refetch(tray, stop_event)

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


#: Seconds the add-on re-download waits after the tray starts, so the daemon and the icon
#: come up first (and a balloon has an icon to hang from).
_ADDON_REFETCH_DELAY_S = 5.0


def _pack_install(ctx, entry):  # noqa: ANN001
    from yazses.packs.manage import install

    return install(ctx, entry)


def _pack_verify(ctx, name):  # noqa: ANN001
    from yazses.packs.manage import verify

    return verify(ctx, name, set_aside=True)


def start_addon_refetch(tray: object, stop_event: threading.Event, *,
                        delay_s: float = _ADDON_REFETCH_DELAY_S, refetch=None) -> threading.Thread:
    """After an update the user agreed to, download this version's copies of the add-ons
    they had (ADR-028 Q3), on a worker thread, and say how it went once.

    The downloader is bound here, in the tray's entry point, and nowhere the daemon can
    import: ``tray.updates`` and ``packs.refetch`` only receive it. Never blocks start-up
    (it waits ``delay_s`` first, and returns at once without a consent) and never raises.
    """
    def _job() -> None:
        if stop_event.wait(delay_s):
            return
        try:
            if refetch is None:
                from yazses.tray.updates import refetch_after_update as run_job
            else:
                run_job = refetch
            message = run_job(install=_pack_install, verify=_pack_verify)
        except Exception:
            log.warning("add-on re-download after the update failed", exc_info=True)
            return
        if message is None or stop_event.is_set():
            return
        show = getattr(tray, "notify", None)
        if callable(show):
            try:
                show(*message)
            except Exception:
                log.debug("add-on re-download notice failed", exc_info=True)

    thread = threading.Thread(target=_job, name="tray-addon-refetch", daemon=True)
    thread.start()
    return thread


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
