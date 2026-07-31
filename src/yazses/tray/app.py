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

from yazses.ipc.client import IpcCallError, IpcUnreachableError
from yazses.platform import TrayModel, TrayState, get_platform

log = logging.getLogger(__name__)


_POLL_INTERVAL_S = 1.0
# Poll faster while recording so the icon reflects the burst (green ↔ yellow when there's
# no text target) during a short hold, instead of lagging a full second behind.
_FAST_POLL_INTERVAL_S = 0.15
_RECORDING_STATES = frozenset({"recording", "transcribing", "injecting", "meeting"})
_DAEMON_BOOT_TIMEOUT_S = 30.0


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
        boot_deadline = time.monotonic() + _DAEMON_BOOT_TIMEOUT_S
        while not stop_event.is_set():
            interval = _POLL_INTERVAL_S
            try:
                info = client.call("status")
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
                if time.monotonic() > boot_deadline:
                    log.warning("Daemon never became reachable; stopping poll.")
                    return
                tray.set_state(TrayModel(state=TrayState.IDLE, last_error="daemon starting"))
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
