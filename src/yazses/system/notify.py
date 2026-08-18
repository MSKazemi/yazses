"""Best-effort desktop notifications with optional action buttons (Linux).

Used to make audio-input problems *visible* instead of silently dropping speech: when
the mic changes or dictation goes quiet, the daemon pops a toast — ideally with clickable
buttons ([Re-calibrate] / [Pin this mic] / [Ignore]) — telling the user what happened and
offering a one-click fix.

Implementation is ``notify-send`` (libnotify). Action buttons need ``--wait`` +
``--action`` (libnotify >= 0.8, present on current Ubuntu/GNOME/KDE); where unavailable
we degrade to a plain informational toast whose body already contains the fix commands,
and where ``notify-send`` is absent entirely we log only. Nothing here ever raises into
the daemon. macOS/Windows backends are a future extension; this is the Linux path.
"""
from __future__ import annotations

import atexit
import logging
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

_DEFAULT_ICON = "audio-input-microphone"
_APP_NAME = "YazSes"
# Actionable notifications block on --wait until clicked or dismissed. Cap it so a
# forgotten toast can't pin a daemon thread forever.
_ACTION_TIMEOUT_S = 120.0

# Every actionable toast currently blocked on --wait. Tracked because the cap above
# is enforced *inside* the worker thread, and a thread is not where a process's last
# word is spoken: the thread is a daemon thread, so when the interpreter exits it is
# abandoned without unwinding, its `except TimeoutExpired` never runs, and nothing
# ever kills `notify-send`. In the long-lived daemon the cap fires and that is
# invisible; in every short-lived process -- a CLI command, `yazses verify`, a test
# run -- the process is gone in seconds and the toast is orphaned onto the user's
# desktop for good. One test suite leaked four per run, forever.
#
# `--urgency critical` is what makes it permanent rather than merely untidy: a
# critical notification never expires on its own (freedesktop spec), so `--wait`
# has nothing to wait for once no one is left to click it.
_inflight: set[subprocess.Popen] = set()
_inflight_lock = threading.Lock()
_shutting_down = False


def _kill_inflight() -> None:
    """Kill every toast still waiting for a click. Runs at interpreter exit.

    Registered with `atexit`, which runs on the main thread *before* daemon threads
    are torn down -- so this is the one place that still gets to speak for them.
    Never raises: it runs during shutdown, where an exception is both useless and
    ugly, and a toast we failed to kill is not worth a traceback on the way out.
    """
    global _shutting_down
    with _inflight_lock:
        _shutting_down = True
        procs = list(_inflight)
        _inflight.clear()
    for proc in procs:
        try:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=1.0)
        except Exception:  # pragma: no cover - shutdown is not a place to fail
            pass


atexit.register(_kill_inflight)


@dataclass(frozen=True)
class NotifyAction:
    """A clickable button on a notification. ``key`` is echoed back on click."""

    key: str
    label: str


def build_notify_argv(
    title: str,
    body: str,
    *,
    urgency: str = "normal",
    app_name: str = _APP_NAME,
    icon: str | None = _DEFAULT_ICON,
    actions: list[NotifyAction] | None = None,
    wait: bool = False,
) -> list[str]:
    """Assemble the ``notify-send`` argv. Pure — no process is spawned."""
    argv = ["notify-send", "--app-name", app_name, "--urgency", urgency]
    if icon:
        argv += ["--icon", icon]
    if wait:
        argv.append("--wait")
    for action in actions or []:
        argv.append(f"--action={action.key}={action.label}")
    argv += [title, body]
    return argv


def parse_action_result(stdout: str | None, actions: list[NotifyAction] | None) -> str | None:
    """Return the clicked action key from ``notify-send --wait`` stdout, or None.

    ``notify-send`` prints the invoked action's key (the part before ``=``) and nothing
    when the toast expires or is dismissed without a choice.
    """
    key = (stdout or "").strip()
    valid = {a.key for a in (actions or [])}
    return key if key in valid else None


# Where a notification goes when libnotify is absent. The daemon registers a sink
# that queues the message onto its `status` reply, which the tray is already
# polling; the tray then shows it with the OS's own toast (pystray on Windows,
# rumps on macOS). Module-level because `notify()` is called from eight places in
# the daemon that have no business knowing how a toast is delivered.
_fallback_sink: Callable[[str, str], None] | None = None


def set_fallback_sink(sink: Callable[[str, str], None] | None) -> None:
    """Register (or clear with ``None``) the no-libnotify delivery sink."""
    global _fallback_sink
    _fallback_sink = sink


def _deliver_to_fallback(title: str, body: str) -> bool:
    """Hand the message to the sink. True if it took it. Never raises."""
    sink = _fallback_sink
    if sink is None:
        return False
    try:
        sink(title, body)
        return True
    except Exception:
        log.debug("fallback notification sink raised", exc_info=True)
        return False


def notifier_available(which: Callable[[str], str | None] = shutil.which) -> bool:
    """True when ``notify-send`` is on PATH."""
    return which("notify-send") is not None


def supports_actions(runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bool:
    """True when the installed ``notify-send`` understands ``--action`` and ``--wait``.

    Probed from ``notify-send --help`` (cheap, no toast). Failures degrade to False so
    we fall back to a plain informational toast rather than erroring.
    """
    try:
        proc = runner(
            ["notify-send", "--help"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except Exception:  # pragma: no cover - hardware/backend dependent
        return False
    help_text = f"{proc.stdout or ''}{proc.stderr or ''}"
    return "--action" in help_text and "--wait" in help_text


def notify(
    title: str,
    body: str,
    *,
    urgency: str = "normal",
    icon: str | None = _DEFAULT_ICON,
    actions: list[NotifyAction] | None = None,
    on_action: Callable[[str], None] | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    spawner: Callable[..., subprocess.Popen] = subprocess.Popen,
    available: bool | None = None,
    actions_supported: bool | None = None,
    spawn: bool = True,
) -> None:
    """Show a desktop notification; never raises.

    With ``actions`` and a notifier that supports them, an actionable toast is shown
    and — because ``--wait`` blocks until the user chooses — it runs on a background
    thread that invokes ``on_action(key)`` with the clicked key. Otherwise a plain
    informational toast is shown (its ``body`` should already spell out the fix). When
    ``notify-send`` is missing, the message is logged only.

    ``runner`` spawns the plain toast and the capability probe (both return promptly);
    ``spawner`` starts the actionable one, whose lifetime we must own -- see
    ``_kill_inflight``. ``available``/``actions_supported`` override the capability
    probes (for tests); ``spawn=False`` runs the actionable path inline instead of on
    a thread (for tests).
    """
    avail = notifier_available() if available is None else available
    if not avail:
        # No libnotify — i.e. Windows and macOS, where every self-healing event
        # (the mic auto-heal, a VAD retune, a silent streak) used to be written to
        # a log file the user never opens. Hand it to whatever sink is registered
        # so the tray can surface it natively; the log line stays either way.
        if _deliver_to_fallback(title, body):
            log.info("Desktop notification (via fallback sink): %s — %s", title, body)
        else:
            log.info("Desktop notification (notify-send unavailable): %s — %s", title, body)
        return

    use_actions = bool(actions) and (
        supports_actions(runner) if actions_supported is None else actions_supported
    )

    if not use_actions:
        argv = build_notify_argv(title, body, urgency=urgency, icon=icon)
        try:
            runner(argv, timeout=10.0)
        except Exception as exc:  # never let a toast break the caller
            log.debug("notify-send failed: %s", exc)
        return

    def _run() -> None:
        argv = build_notify_argv(
            title, body, urgency=urgency, icon=icon, actions=actions, wait=True
        )
        # Spawn and register under one lock, so a toast started as the interpreter is
        # going down is either killed by `_kill_inflight` or never started at all --
        # never spawned into the gap just after it stopped looking.
        try:
            with _inflight_lock:
                if _shutting_down:
                    return
                proc = spawner(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                _inflight.add(proc)
        except Exception as exc:
            log.debug("actionable notify-send failed to start: %s", exc)
            return

        try:
            stdout, _ = proc.communicate(timeout=_ACTION_TIMEOUT_S)
        except Exception as exc:
            log.debug("actionable notify-send failed: %s", exc)
            try:
                proc.kill()
                proc.communicate(timeout=1.0)
            except Exception:
                log.debug("could not kill a timed-out notify-send", exc_info=True)
            return
        finally:
            with _inflight_lock:
                _inflight.discard(proc)

        key = parse_action_result(stdout, actions)
        if key and on_action is not None:
            try:
                on_action(key)
            except Exception:
                log.exception("Notification action handler raised")

    if spawn:
        threading.Thread(target=_run, daemon=True, name="yazses-notify").start()
    else:
        _run()
