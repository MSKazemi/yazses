"""Cross-platform daemon orchestrator.

Wires the hotkey backend → audio recorder → STT engine → injector pipeline,
exposes a JSON-RPC IPC server for the CLI and tray, and manages PID/signal
lifecycle. All platform-specific concerns are reached through
:mod:`yazses.platform`.
"""

from __future__ import annotations

import functools
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from types import FrameType
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    # All imported lazily at runtime (in _build_gaze_targeter and the other builders
    # below) so the optional/heavy dependencies stay dormant; the names exist here only
    # so the `X | None` attribute annotations resolve for the type checker.
    from yazses.gaze.targeter import GazeTargeter
    from yazses.inject.target import TargetDetector
    from yazses.learning.edit_watch import EditWatcher
    from yazses.meeting.controller import MeetingController
    from yazses.polyglot.router import PolyglotRouter
    from yazses.system.single_instance import SingleInstanceLock
    from yazses.timeline.history import InjectionTimeline
    from yazses.tts.base import TtsBackend
    from yazses.verbatim.gate import VerbatimGate
    from yazses.voiceprint.base import SpeakerEmbedder

from yazses.audio.adaptive_vad import AdaptiveThreshold
from yazses.audio.device_monitor import DeviceMonitor, SilentStreakTracker, capture_proved
from yazses.audio.mic_prompt import MicPrompt
from yazses.audio.padding import PreSpeechRingBuffer
from yazses.audio.recorder import AudioRecorder
from yazses.audio.vad_calibrated import is_silent_calibrated
from yazses.cmdsafety.classify import ConfirmGate
from yazses.commands.dispatch import dispatch as cmd_dispatch
from yazses.commands.grammar import IntentType, classify
from yazses.commands.macros import MacroContext, build_macro_table
from yazses.commands.revise import DictationLedger, parse_revise
from yazses.config import Config, load_config
from yazses.earcon.play import EarconPlayer
from yazses.inject.streaming import StreamingInjector
from yazses.ipc.protocol import Request
from yazses.learning.capture import CorpusWriter, build_writer
from yazses.platform import Platform, get_platform
from yazses.platform.base import HotkeyBackend, InjectorBackend, IpcServer, TrayState
from yazses.postprocess.cleaner import clean_text
from yazses.postprocess.llm_cleanup import LlmCleaner, build_cleaner
from yazses.postprocess.prosody import Word, annotate
from yazses.postprocess.punch_in import apply_top_candidate
from yazses.postprocess.spacing import continuation_prefix
from yazses.postprocess.voice_punctuation import apply_voice_punctuation
from yazses.remote.forwarder import RemoteForwarder
from yazses.remote.local_proxy import RemoteInjectorProxy
from yazses.staged.buffer import StagedAction, StagedBuffer
from yazses.staged.buffer import classify as staged_classify
from yazses.staged.buffer import describe as staged_describe
from yazses.stt.base import SttEngine
from yazses.stt.endpoint import EndpointAnticipator
from yazses.stt.errors import ModelUnavailableError
from yazses.stt.factory import build_engine
from yazses.stt.filters.disfluency import filter_transcript
from yazses.stt.latency import LatencyWindow
from yazses.stt.streaming import StreamingEngine
from yazses.styleguard.loader import build_style_rules
from yazses.styleguard.rules import apply_style
from yazses.system.outcomes import OutcomeWindow, classify_outcome
from yazses.system.relaunch import Mode, command_for
from yazses.system.uptime import monotonic_including_suspend
from yazses.tts.factory import build_tts

log = logging.getLogger(__name__)


@functools.cache
def _running_version() -> str:
    """The version of the yazses package this daemon imported. Never raises.

    Deferred rather than module-level: `importlib.metadata` is the single most
    expensive import in the tree (52 ms, measured), and CLI start-up cost is
    guarded by `tests/test_cli_startup_cost.py`.

    Cached because this is not a one-shot: `_handle_status` reads it on **every**
    IPC status call, and the pollers are relentless -- the overlay asks 4x a second
    while idle and 20x while recording, the tray 1x and 6.7x. The lookup is not
    free: `importlib.metadata.version` walks `sys.path` for a `.dist-info` on each
    call and cost **2.1 ms** measured here, so an idle daemon with the overlay on
    spent ~30 s of CPU an hour re-reading a string that cannot change -- inside
    `self._lock`, the same mutex `_on_hold_start` takes when the key goes down.
    A process runs the build it imported; that is the very fact this field exists
    to report, so one lookup is all there can be to do.
    """
    try:
        from importlib.metadata import version

        return version("yazses")
    except Exception:
        return ""



def should_launch_overlay(config: Config, env: Mapping[str, str]) -> bool:
    """Whether the daemon should auto-spawn the voice-activity overlay.

    Only when explicitly enabled in config AND a graphical session is present
    (``DISPLAY`` for X11 or ``WAYLAND_DISPLAY``). Headless servers and the test
    suite therefore never spawn it.
    """
    if not config.overlay.enabled:
        return False
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def overlay_dependency_available() -> bool:
    """Whether PySide6 (the optional ``overlay`` extra) is importable.

    The overlay is on by default, but PySide6 stays an optional dependency so the
    base install never fails on older distros without a compatible Qt6 wheel. When
    it's missing we skip the launch quietly rather than spawn a process that dies
    on the import — see :meth:`Daemon._maybe_launch_overlay`.
    """
    import importlib.util

    return importlib.util.find_spec("PySide6") is not None


@dataclass
class _DaemonState:
    state: TrayState = TrayState.LOADING
    last_error: str | None = None
    started_at: float = 0.0
    ready: bool = False
    # Live mic level (mean(|samples|)) of the most recent audio chunk while
    # recording; 0.0 otherwise. Surfaced over `status` to drive the overlay.
    audio_level: float = 0.0
    # Audio-input health (surfaced over `status`, driven by the device monitor +
    # silent-streak detector): the device capture last opened, the last device that
    # produced usable audio ("last-good", the auto-heal target), the current run of
    # consecutive silent-discards, and when the default input last changed.
    input_device: str | None = None
    last_good_device: str | None = None
    silent_streak: int = 0
    device_changed_at: float | None = None
    # "No text target" guard: whether the focused element accepts text for the current
    # burst — True (editable field), False (no target → warn/clipboard), None (unknown).
    target_ok: bool | None = None
    # Per-app profiles (ADR-v2-100): the focused application, resolved alongside
    # `target_ok` by the same detector, so a profile can key off it. "" when unknown.
    app_class: str = ""


# Tone names with house phrasing. Anything else in `[profiles.app]` is appended
# verbatim as "Use a <tone> tone." — see `Daemon._clean_dictation`.
# How many undelivered toasts to hold for the tray. Small on purpose: these are
# transient status messages, and a tray that has been quit must not make the
# daemon accumulate them for the rest of the session.
_MAX_PENDING_NOTIFICATIONS = 10

_TONE_INSTRUCTIONS: dict[str, str] = {
    "casual": "Use a casual, conversational tone.",
    "formal": "Use a formal, professional tone.",
}


class Daemon:
    """The dictation daemon. Holds a hotkey listener and an IPC server."""

    def __init__(
        self,
        config: Config | None = None,
        platform: Platform | None = None,
    ) -> None:
        self._config = config or load_config()
        self._platform = platform or get_platform()
        self._state = _DaemonState()
        self._lock = threading.RLock()
        self._hotkey: HotkeyBackend | None = None
        # Optional dedicated command key (force-command mode). Runs its own
        # listener in a background thread; _command_mode is set while held.
        self._command_hotkey: HotkeyBackend | None = None
        self._command_thread: threading.Thread | None = None
        self._command_mode: bool = False
        # Toasts awaiting collection by the tray, where the OS has no libnotify.
        self._pending_notifications: list[dict[str, str]] = []
        # Non-keyboard activation sources (EMG squeeze — [emg] device_port).
        # Each is a HotkeyBackend duck-type driving the same hold callbacks.
        self._extra_activations: list[HotkeyBackend] = []
        # Verbatim/autoformat mode (ADR-v2-078): a persistent gate toggled by the
        # spoken commands "dictate verbatim" / "resume formatting". Lazily created on
        # first use when [verbatim] enabled; holds mode across bursts. None = feature off.
        self._verbatim_gate: VerbatimGate | None = None
        # Features that are switched on but cannot actually run: warned once each, so a
        # user never sits through a whole session wondering why nothing changed.
        self._warned_inert: set[str] = set()
        self._injector: InjectorBackend | None = None
        self._engine: SttEngine | None = None
        self._recorder: AudioRecorder | None = None
        self._ipc_server: IpcServer | None = None
        self._padding_buffer: PreSpeechRingBuffer | None = None
        self._remote_forwarder: RemoteForwarder | None = None
        self._remote_injector: RemoteInjectorProxy | None = None
        self._stream_engine: StreamingEngine | None = None
        self._stream_injector: StreamingInjector | None = None
        # Glance-Type look-to-pane targeter (None unless [gaze] enabled + routing
        # + calibration + an X11 desktop backend all present — otherwise dormant).
        self._gaze_targeter: GazeTargeter | None = None
        # Ghost Ahead endpoint anticipator (None when [endpoint] disabled — dormant).
        self._endpoint: EndpointAnticipator | None = (
            EndpointAnticipator(
                min_silence_s=self._config.endpoint.min_silence_s,
                stable_updates=self._config.endpoint.stable_updates,
                debounce_s=self._config.endpoint.debounce_ms / 1000.0,
            )
            if self._config.endpoint.enabled
            else None
        )
        self._poll_stop: threading.Event | None = None
        self._poll_thread: threading.Thread | None = None
        # monotonic timestamp of the last dictation injection; drives
        # continuation spacing between successive hold-to-talk bursts.
        self._last_dictation_monotonic: float | None = None
        self._streaming_active: bool = False
        self._corpus: CorpusWriter | None = None
        # Personal Adapter P1 (ADR-v2-009): corpus-mined biasing terms, computed
        # once and cached (None = not yet computed). Off unless [personalize].
        self._personal_bias: list[str] | None = None
        # Confidence Ink (ADR-v2-001): low-confidence word count from the last
        # burst, surfaced in `yazses status` (metadata only, never the words).
        self._last_low_confidence_words: int = 0
        # Recent decode times per model, for the p50/p95 in `yazses status`
        # (#296). Bounded and in-memory: a diagnostic must not depend on the
        # opt-in learning corpus, and it must not write anything to disk.
        self._latency = LatencyWindow()
        self._outcomes = OutcomeWindow()
        # Staged dictation (#294): when on, a burst lands here for review instead
        # of typing straight into the focused app. Off by default.
        self._staged = StagedBuffer()
        # Command Safety Gate (ADR-v2-065): holds one dangerous dictated command
        # pending a spoken confirm. Always constructed — it is a couple of fields and
        # stays inert unless [cmdsafety] enabled, which keeps `_on_hold_end` free of
        # a None check on the hot path.
        self._cmdsafety = ConfirmGate()
        # When the mic guard last asked something, so a spoken answer can be
        # scoped to an open question rather than to the whole session.
        self._mic_prompt = MicPrompt()
        # Earcon feedback (ADR-v2-096): non-speech tones for state changes, so the
        # daemon is usable without seeing the tray. Always constructed and inert
        # unless [earcon] enabled, keeping the hot path free of a None check.
        self._earcon = EarconPlayer(self._config.earcon.enabled)
        self._edit_watcher: EditWatcher | None = None
        self._cleaner: LlmCleaner | None = None
        # Read-Back Loop TTS backend (None when [tts] disabled — dormant).
        self._tts: TtsBackend | None = None
        # v2 cognitive layer: speaker embedder + enrolled voiceprint (Cocktail Filter).
        # None when [voiceprint]/[cocktail] dormant or unavailable.
        self._embedder: SpeakerEmbedder | None = None
        # The enrolled speaker's d-vector itself, not the Embedding wrapper —
        # `_load_voiceprint_vector` unwraps it (`emb.vector`).
        self._voiceprint: np.ndarray | None = None
        # Single-instance lock; prevents a second daemon (detached `yazses start`
        # vs the systemd unit) from grabbing the hotkey and double-injecting.
        self._instance_lock: SingleInstanceLock | None = None
        self._overlay_proc: subprocess.Popen | None = None
        self._tray_proc: subprocess.Popen | None = None
        self._tray_supervisor: threading.Thread | None = None
        # Set on shutdown so background supervisors stop waiting and exit promptly.
        self._stop_event = threading.Event()
        # Say-Macro table (None when [macros] disabled — feature dormant).
        self._macro_table = build_macro_table(
            self._config, self._platform.paths.config_file.parent
        )
        # Style-Consistency Enforcer rules (None when [styleguard] disabled).
        self._style_rules = build_style_rules(
            self._config, self._platform.paths.config_file.parent
        )
        # Mid-Thought Undo: ledger of injected dictation bursts for "scratch that".
        self._ledger = DictationLedger()
        # Voice Undo/Redo Timeline (ADR-v2-089) — None when [timeline] is off.
        self._timeline: InjectionTimeline | None = None
        if self._config.timeline.enabled:
            from yazses.timeline.history import InjectionTimeline as _InjectionTimeline

            self._timeline = _InjectionTimeline()
        # Meeting Mode (ADR-v2-127): active controller + its dedicated mic recorder,
        # None when no meeting is running. `_meeting_finalizing` guards the post-pass.
        self._meeting_controller: MeetingController | None = None
        self._meeting_recorder: AudioRecorder | None = None
        self._meeting_finalizing = False
        # slug -> monotonic time it was last reported to the user, so a fault that
        # recurs on every burst is explained once rather than every time. See
        # `system/diagnosis.py::should_notify` for why the ceiling matters more than
        # the repeats do.
        self._diagnosed_at: dict[str, float] = {}
        # Audio-input resilience: count consecutive silent-discards and watch the OS
        # default input device so a mic that silently switches (e.g. a USB-C monitor
        # stealing capture) is auto-healed to the last-good device + notified, instead
        # of dropping speech in silence. Built in _build_pipeline; monitor may be None.
        self._silent_streak = SilentStreakTracker()
        # Learns the silence gate from outcomes, so a threshold that no longer fits this
        # mic stops being a silent "I speak and nothing happens".
        self._adaptive_vad = AdaptiveThreshold()
        self._device_monitor: DeviceMonitor | None = None
        # "No text target" guard: detects whether the focused element accepts text so a
        # burst with no field focused is warned (yellow tray) + saved to the clipboard
        # instead of typed into the wrong place. None until built ([injection] target_guard).
        self._target_detector: TargetDetector | None = None
        # True once we've auto-healed for the current silent streak, so a device that
        # is genuinely gone doesn't re-trigger the switch on every subsequent clip.
        self._healed_this_streak = False

    # ---- Public entrypoints -----------------------------------------------

    def _acquire_instance_lock(self) -> bool:
        """Take the single-instance lock; False (and log) if a daemon already runs."""
        from yazses.system.single_instance import SingleInstanceLock

        self._instance_lock = SingleInstanceLock(
            self._platform.paths.data_dir / "daemon.lock"
        )
        if not self._instance_lock.acquire():
            log.error(
                "Another YazSes daemon is already running — exiting. "
                "Manage the daemon with: systemctl --user restart yazses "
                "(avoid `yazses start`, which detaches a second one)."
            )
            return False
        return True

    def run(self) -> None:
        self._configure_logging()
        # Refuse to start a duplicate daemon (prevents double-typing).
        if not self._acquire_instance_lock():
            return
        self._install_signal_handlers()
        # Where a toast goes when this OS has no libnotify: onto the status reply
        # for the tray to show. No-op on Linux, which uses notify-send directly.
        from yazses.system.notify import set_fallback_sink

        set_fallback_sink(self._queue_notification)

        lifecycle = self._platform.lifecycle
        lifecycle.write_pid()
        with self._lock:
            # Not `time.monotonic()`: that clock stops while the machine is suspended,
            # so a laptop daemon reported an uptime short by however long the lid was
            # shut -- measured here at 5 h 29 m against a real 9 h 25 m. Uptime's job is
            # to reveal a daemon that predates an upgrade, which is exactly what that
            # under-report hides. `_handle_status` must read the same clock.
            self._state.started_at = monotonic_including_suspend()
            self._state.state = TrayState.LOADING
        try:
            # Start IPC FIRST so the tray and CLI see honest state immediately,
            # rather than getting "daemon not reachable" for the 5–10 seconds
            # the model takes to load on first run.
            self._start_ipc_server()
            try:
                self._build_pipeline()
            except ModelUnavailableError as exc:
                # The one startup failure the user can fix themselves, and the one
                # that used to kill the daemon with a raw traceback (#310). Hold the
                # process in ERROR state instead: IPC is already up, so the tray goes
                # red with the reason and `yazses status` can answer, rather than the
                # daemon vanishing and leaving "not running" as the only clue.
                self._await_shutdown_in_error(exc)
                return
            with self._lock:
                self._state.ready = True
                self._state.state = TrayState.IDLE
            assert self._hotkey is not None
            log.info("YazSes ready. Hold %s to dictate.", self._resolved_hotkey())
            self._maybe_launch_overlay()
            self._maybe_launch_tray()
            # Run the optional command-key listener in the background; the
            # dictation listener owns the main thread (blocking) as before.
            if self._command_hotkey is not None:
                self._command_thread = threading.Thread(
                    target=self._command_hotkey.run,
                    daemon=True,
                    name="command-hotkey",
                )
                self._command_thread.start()
            # Non-keyboard activation sources (EMG squeeze, …): each runs its
            # own blocking loop like the command key does.
            for i, source in enumerate(self._extra_activations):
                threading.Thread(
                    target=source.run,
                    daemon=True,
                    name=f"activation-{i}",
                ).start()
            # Watch for the OS default input device changing under us.
            if self._device_monitor is not None:
                self._device_monitor.start()
                log.info("Watching for audio-input device changes.")
            self._start_update_watcher()
            self._hotkey.run()
        finally:
            self._shutdown()

    def _await_shutdown_in_error(self, exc: ModelUnavailableError) -> None:
        """Report a fixable startup failure and stay up until asked to stop.

        Exiting here would be worse than it looks: the tray dies with the daemon,
        so the user is left with a window that closed and no statement of why.
        Staying resident costs nothing (no model is loaded, no hotkey is hooked)
        and keeps every channel that can explain the problem alive — the tray
        icon, `yazses status`, and the log.
        """
        message = str(exc)
        log.error("%s", message)
        with self._lock:
            self._state.state = TrayState.ERROR
            self._state.last_error = message
            self._state.ready = False
        try:
            from yazses.system import notify as notify_mod

            # Asked of the exception rather than composed here: this text used to
            # say "missing and could not be downloaded" unconditionally, so the
            # toast contradicted the log line above it for any cause that was not
            # a missing model.
            title, body = exc.notification()
            notify_mod.notify(title, body)
        except Exception:  # noqa: BLE001 — a toast must not mask the real error
            log.debug("Could not send the model-unavailable notification", exc_info=True)
        self._stop_event.wait()

    def _maybe_launch_overlay(self) -> None:
        """Spawn the sonar overlay as a detached process when configured."""
        if not should_launch_overlay(self._config, os.environ):
            return
        if not overlay_dependency_available():
            log.info(
                "Overlay is enabled but PySide6 is not installed; skipping. "
                "Install it with: uv sync --extra overlay  (or pip install 'yazses[overlay]')"
            )
            return
        try:
            self._overlay_proc = subprocess.Popen(
                command_for(Mode.OVERLAY),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("Launched voice-activity overlay (pid %d).", self._overlay_proc.pid)
        except Exception:
            log.exception("Failed to launch overlay; continuing without it")

    def _maybe_launch_tray(self) -> None:
        """Spawn the system-tray indicator as a detached process when configured."""
        from yazses.tray.launch import should_launch_tray, tray_dependency_available

        if not should_launch_tray(self._config, os.environ):
            return
        if not tray_dependency_available():
            log.info(
                "Tray is enabled but PySide6 is not installed; skipping. "
                "Install it with: uv sync --extra overlay  (or pip install 'yazses[overlay]')"
            )
            return
        try:
            self._tray_proc = subprocess.Popen(
                command_for(Mode.TRAY),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=self._open_tray_stderr(),
            )
            log.info("Launched system-tray indicator (pid %d).", self._tray_proc.pid)
        except Exception:
            log.exception("Failed to launch tray; continuing without it")
            return
        self._start_tray_supervisor()

    def _start_tray_supervisor(self) -> None:
        """Watch the tray for the rest of the session and bring it back if it dies.

        Without this the icon is launched once and never checked again, so a tray that
        crashes leaves dictation working with no indicator at all — and the indicator is
        the only thing that says whether YazSes is listening, in command mode, or has
        nowhere to type.
        """
        if self._tray_supervisor is not None:
            return
        self._tray_supervisor = threading.Thread(
            target=self._supervise_tray, name="tray-supervisor", daemon=True
        )
        self._tray_supervisor.start()

    def _tray_stderr_path(self):
        """Where a tray process's stderr is parked until someone asks why it died."""
        return self._platform.paths.data_dir / "tray-stderr.log"

    def _open_tray_stderr(self):
        """A write handle for the next tray's stderr, or DEVNULL if that is impossible.

        Truncated per launch: this answers "why did the tray that just died die?", and a
        growing file would answer it with the previous six failures as well. Falls back
        to DEVNULL rather than raising -- a tray that cannot be launched at all is a
        worse outcome than a tray whose error is unreadable, which is the status quo.
        """
        try:
            path = self._tray_stderr_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            return path.open("w", encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - diagnostics must never block the tray
            return subprocess.DEVNULL

    def _last_tray_error(self) -> str:
        """What the tray printed before it died, formatted for one log call."""
        from yazses.tray.supervisor import describe_exit

        try:
            text = self._tray_stderr_path().read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - no file is the normal case
            return ""
        summary = describe_exit(text)
        if not summary:
            return ""
        indented = summary.replace("\n", "\n    ")
        return f"\n  it said:\n    {indented}"

    def _supervise_tray(self) -> None:
        from yazses.system.single_instance import holder_pid
        from yazses.tray.supervisor import DEFAULT_INTERVAL_S, decide

        lock = self._platform.paths.data_dir / "tray.lock"
        relaunches = 0
        while not self._stop_event.wait(DEFAULT_INTERVAL_S):
            try:
                decision = decide(
                    alive=holder_pid(lock) is not None, relaunches_so_far=relaunches
                )
                if decision.give_up:
                    # Say why, not just that. The reason text tells the user to run
                    # `yazses tray` to see the error -- advice that only ever existed
                    # because the error was being discarded.
                    log.warning(
                        "Tray supervisor: %s%s", decision.reason, self._last_tray_error()
                    )
                    return
                if not decision.relaunch:
                    continue
                log.info(
                    "Tray supervisor: %s%s", decision.reason, self._last_tray_error()
                )
                proc = subprocess.Popen(
                    command_for(Mode.TRAY),
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=self._open_tray_stderr(),
                )
                self._tray_proc = proc
                relaunches += 1
                log.info("Relaunched system-tray indicator (pid %d).", proc.pid)
            except Exception:  # noqa: BLE001 — supervision must outlive its own errors
                log.exception("Tray supervisor iteration failed")

    # ---- update watcher ---------------------------------------------------

    def _start_update_watcher(self) -> None:
        """Start the opt-in "a newer YazSes is out" watcher.

        Dormant unless ``[general] update_check`` is on — it is the only outbound
        connection YazSes ever makes, so it is a choice, not a default.
        """
        if not getattr(self._config.general, "update_check", False):
            return
        threading.Thread(
            target=self._watch_for_updates, name="update-check", daemon=True
        ).start()
        log.info("Update check enabled; will look for a newer release periodically.")

    def _watch_for_updates(self) -> None:
        """Ask periodically whether a newer release exists; announce it once.

        Every failure is swallowed on purpose. A machine behind a firewall must
        keep dictating exactly as before — a blocked check is a no-op that retries
        at the next tick, never an error the user has to clear.
        """
        import time

        from yazses.system import update_notify
        from yazses.system.notify import notify
        from yazses.system.updater import check_update

        state_path = self._platform.paths.data_dir / update_notify.STATE_NAME
        interval_h = getattr(self._config.general, "update_check_interval_hours", 24)
        # Tick often enough to react to a laptop waking up mid-interval, but let
        # `should_check` decide what is actually due.
        tick_s = 900.0
        # A first check right at startup would race the model load and compete
        # with the user's first dictation, so the loop waits one tick first.
        while not self._stop_event.wait(tick_s):
            try:
                state = update_notify.read_state(state_path)
                now = time.time()
                if not update_notify.should_check(now, state.last_check, interval_h):
                    continue
                status = check_update(self._version())
                state.last_check = now
                if update_notify.should_notify(status, state.notified_version):
                    summary, body = update_notify.notification(status)
                    notify(summary, body)
                    state.notified_version = status.latest or ""
                    log.info("A newer YazSes is available: %s", status.latest)
                elif status.latest is None:
                    log.debug("Update check could not reach the source: %s", status.note)
                update_notify.write_state(state_path, state)
            except Exception:  # noqa: BLE001 — a background check must never escalate
                log.debug("Update check iteration failed", exc_info=True)

    def _version(self) -> str:
        """The running version, for the update check ("dev" in a source tree)."""
        from yazses import branding

        return branding.version()

    def shutdown(self) -> None:
        log.info("Shutting down.")
        # Stop the tray supervisor first, so it can't relaunch a tray on the way out.
        self._stop_event.set()
        if self._command_hotkey is not None:
            try:
                self._command_hotkey.stop()
            except Exception:
                log.exception("Command-hotkey stop raised")
        for source in self._extra_activations:
            try:
                source.stop()
            except Exception:
                log.exception("Activation-source stop raised")
        if self._hotkey is not None:
            try:
                self._hotkey.stop()
            except Exception:
                log.exception("Hotkey stop raised")
        # The rest happens in the finally block of run().

    # ---- Build phase -------------------------------------------------------

    def _build_pipeline(self) -> None:
        cfg = self._config
        log.info("Loading STT engine %r (model %r)...", cfg.stt.engine, cfg.stt.model)
        self._engine = build_engine(cfg.stt)

        # [injection] backend selects the Linux injector (type | ydotool |
        # clipboard | wtype | auto), and fallback_to_clipboard the runtime fallback.
        # Both are bridged through the env vars inject.auto.get_injector honours, so
        # no platform factory signature changes; non-Linux platforms ignore them.
        # The bridge lives in inject/auto.py because the three CLI commands whose job
        # is to *test the injector* have to apply the same one -- they did not, and
        # tested `auto` while the daemon used what the user configured.
        from yazses.inject.auto import apply_injection_config

        apply_injection_config(self._config.injection)
        self._injector = self._platform.injector_factory()
        log.info("Injection backend: %s", self._injection_backend_name())

        if cfg.streaming.enabled:
            self._stream_engine = StreamingEngine(
                self._engine,
                cfg.streaming.partial_interval_ms,
            )
            log.info("Streaming STT enabled (partial every %d ms)", cfg.streaming.partial_interval_ms)

        if self._endpoint is not None:
            log.info("Endpoint anticipation enabled (pre-warm=%s)", cfg.endpoint.prewarm)

        self._recorder = AudioRecorder(
            cfg.audio.sample_rate,
            cfg.audio.max_record_seconds,
            on_chunk=self._on_audio_chunk,
            device=cfg.audio.device or None,
        )

        self._padding_buffer = PreSpeechRingBuffer(
            padding_ms=cfg.accessibility.pre_speech_padding_ms,
            sample_rate=cfg.audio.sample_rate,
        )

        # Watch the OS default input device so a silent switch (a plugged-in monitor /
        # headset stealing capture) is surfaced + auto-healed. Polls only while idle,
        # so PortAudio is never re-initialised mid-recording. Dormant when disabled.
        if cfg.audio.device_change_notify and cfg.audio.device_poll_interval_s > 0:
            from yazses.audio.devices import current_default_input_name, reinit_portaudio

            def _poll_default() -> str | None:
                reinit_portaudio()  # refresh so hotplugged devices are visible
                return current_default_input_name()

            self._device_monitor = DeviceMonitor(
                poll_fn=_poll_default,
                is_idle=self._audio_idle,
                on_change=self._on_default_device_changed,
                interval_s=cfg.audio.device_poll_interval_s,
            )

        # "No text target" guard: build the detector (AT-SPI focus tracker when available,
        # else best-effort xdotool). Dormant when [injection] target_guard == "off".
        if cfg.injection.target_guard != "off":
            from yazses.inject.target import AtspiFocusTracker, TargetDetector

            tracker = AtspiFocusTracker()
            if tracker.available() and tracker.start():
                self._target_detector = TargetDetector(atspi=tracker)
            else:
                self._target_detector = TargetDetector()  # best-effort xdotool only
            log.info(
                "Text-target guard enabled (%s; action=%s).",
                "AT-SPI" if tracker.available() else "best-effort X11",
                cfg.injection.target_guard,
            )

        key_id = cfg.hotkey.key
        if key_id == "auto":
            key_id = self._platform.default_hotkey
        self._hotkey = self._platform.hotkey_factory(
            key_id,
            cfg.hotkey.hold_threshold_ms,
            self._on_hold_start,
            self._on_hold_end,
        )

        # Optional dedicated command key: a second listener that forces command
        # mode while held. Ignored if unset or the same as the dictation key.
        self._command_hotkey = self._make_command_hotkey(cfg, key_id)

        # Glance-Type look-to-pane (design/v2-cognitive-layer §3.3). Dormant unless
        # [gaze] enabled + route_dictation, with a calibration + X11 desktop + deps.
        #
        # Built before the activation sources so the modality router below can ask
        # whether gaze *actually* came up, rather than whether it was requested.
        self._gaze_targeter = self._build_gaze_targeter(cfg)

        # ADR-v2-011 role arbitration. Must precede the activation sources, because
        # it decides what role EMG plays among them.
        self._modality_roles = self._resolve_modality_roles(cfg)

        # Voice window focus (#39). None on Wayland (which forbids cross-client
        # focus) and without xdotool; the spoken command then stays dictation.
        self._window_backend = self._build_window_backend(cfg)

        # Optional non-keyboard activation sources (EMG squeeze via [emg]).
        self._extra_activations = self._build_activation_sources(cfg)

        # Opt-in self-improvement corpus (ADR-012). Dormant unless enabled.
        self._corpus = build_writer(self._platform.paths.data_dir, cfg.learning)

        # True Code-Switch routing (ADR-v2-008). Dormant unless [polyglot] is
        # fully configured with an out-of-band adapter; surface a hint otherwise.
        self._polyglot: PolyglotRouter | None = None
        try:
            from yazses.polyglot.router import PolyglotRouter
            self._polyglot = PolyglotRouter.from_config(cfg.polyglot)
            # `active` already implies a parsed pair, but bind it locally so the
            # unpacking below is provably safe rather than relying on that.
            pair = self._polyglot.pair
            if self._polyglot.active and pair is not None:
                log.info("Polyglot code-switch routing active (pair %s-%s).", *pair)
            else:
                reason = self._polyglot.status_reason()
                if reason:
                    log.warning("Polyglot enabled but dormant: %s.", reason)
        except Exception:
            self._polyglot = None
            log.debug("Polyglot router init failed; skipping", exc_info=True)

        # Opt-in post-dictation edit capture (signal b). Reads the editor line
        # back after a dictation; never logs keystrokes. Disabled unless a
        # reachable editor socket is configured.
        self._edit_watcher = None
        if self._corpus is not None and cfg.learning.capture_edits:
            from yazses.learning.edit_watch import EditWatcher, build_neovim_reader

            reader = build_neovim_reader(cfg.learning.editor_socket)
            if reader is not None:
                self._edit_watcher = EditWatcher(
                    reader,
                    self._corpus.update_correction_for,
                    delay_s=cfg.learning.edit_capture_delay_s,
                )
                log.info("Edit capture enabled (editor read-back).")

        # Opt-in offline LLM dictation cleanup (parity with Rust [cleanup]).
        # None unless [filters.disfluency] llm_enabled is set.
        self._cleaner = build_cleaner(cfg.filters.disfluency)

        # Read-Back Loop: offline TTS that speaks the transcript back (ADR-011).
        # None when [tts] disabled; NullTtsBackend when enabled-but-unavailable.
        self._tts = build_tts(cfg.tts)
        if self._tts is not None:
            log.info(
                "Read-back TTS enabled (backend=%s, mode=%s)",
                self._tts.name, cfg.accessibility.read_back,
            )

        # Cocktail Filter / Voiceprint Mind: build the speaker embedder and load the
        # enrolled voiceprint when either feature is on (dormant/None otherwise).
        if cfg.cocktail.enabled or cfg.voiceprint.enabled:
            from yazses.voiceprint.factory import build_embedder
            from yazses.voiceprint.store import load_voiceprint

            self._embedder = build_embedder(cfg.voiceprint)
            self._voiceprint = self._load_voiceprint_vector()
            if self._embedder is None:
                log.warning(
                    "Voiceprint enabled but the `voiceprint` extra is missing; "
                    "Cocktail Filter stays dormant (uv sync --extra voiceprint)."
                )
            elif self._voiceprint is None:
                log.warning("No enrolled voiceprint yet; run `yazses enroll-voice`.")
            _ = load_voiceprint  # referenced via the helper below

    def _voiceprint_path(self):
        return self._platform.paths.data_dir / "voiceprint.enc"

    def _load_voiceprint_vector(self):
        """Load the enrolled speaker embedding vector, or None if not enrolled."""
        try:
            from yazses.learning.crypto import Cipher, load_or_create_key
            from yazses.voiceprint.store import load_voiceprint

            cipher = Cipher(load_or_create_key(self._platform.paths.data_dir))
            emb = load_voiceprint(self._voiceprint_path(), cipher)
            return emb.vector if emb is not None else None
        except Exception as exc:
            log.debug("Voiceprint load failed: %s", exc)
            return None

    def _load_meeting_participants(self):
        """Load enrolled meeting participants ({name: vector}); empty if none/no embedder."""
        if self._embedder is None:
            return {}
        try:
            from yazses.learning.crypto import Cipher, load_or_create_key
            from yazses.meeting.participants import load_participants

            cipher = Cipher(load_or_create_key(self._platform.paths.data_dir))
            return load_participants(self._config.meeting, cipher)
        except Exception as exc:
            log.debug("Participant load failed: %s", exc)
            return {}

    def _start_ipc_server(self) -> None:
        socket_path = self._platform.paths.ipc_socket
        server = self._platform.ipc_server_factory(socket_path)
        server.register("status", self._handle_status)
        # Staged dictation (#294): the deterministic commit path. Deliberately the
        # default one — a spoken commit can be produced by the mis-transcription
        # the buffer exists to catch.
        server.register("staged", self._handle_staged)
        server.register("shutdown", self._handle_shutdown)
        server.register("inject", self._handle_inject)
        server.register("remote_start", self._handle_remote_start)
        server.register("remote_stop", self._handle_remote_stop)
        server.register("remote_status", self._handle_remote_status)
        server.register("enroll_start", self._handle_enroll_start)
        server.register("streaming_enable", self._handle_streaming_enable)
        server.register("streaming_disable", self._handle_streaming_disable)
        server.register("mark_last_wrong", self._handle_mark_last_wrong)
        server.register("punch_in", self._handle_punch_in)
        server.register("readback_speak", self._handle_readback_speak)
        server.register("recall", self._handle_recall)
        server.register("scratch", self._handle_scratch)
        server.register("meeting_start", self._handle_meeting_start)
        server.register("meeting_stop", self._handle_meeting_stop)
        server.register("meeting_status", self._handle_meeting_status)
        server.register("pin_mic", self._handle_pin_mic)
        server.register("recalibrate_mic", self._handle_recalibrate_mic)
        server.register("ask_human", self._handle_ask_human)
        server.serve_in_thread()
        self._ipc_server = server

    # ---- Pipeline callbacks -----------------------------------------------

    def _make_command_hotkey(self, cfg, dictation_key_id: str):
        """Build the dedicated command-key backend, or None when not configured.

        Returns None when ``[hotkey] command_key`` is empty or equal to the
        dictation key (a second listener on the same key would be redundant).
        """
        command_key = (cfg.hotkey.command_key or "").strip()
        if not command_key or command_key.lower() == dictation_key_id.lower():
            return None
        log.info("Command key enabled: hold %s for command mode.", command_key)
        return self._platform.hotkey_factory(
            command_key,
            cfg.hotkey.hold_threshold_ms,
            self._on_command_hold_start,
            self._on_command_hold_end,
        )

    def _resolve_modality_roles(self, cfg) -> dict[str, str]:
        """Resolve ``role -> modality`` from what is actually available (#136).

        ADR-v2-011's router has been pure policy with no caller since July: the
        `modality` slug sat in `_UNWIRED` because enabling it wrote a config key
        nothing read. This is the read.

        "Available" means configured-and-constructible, not merely enabled, so
        the map describes the machine in front of the user: `voice` and
        `keyboard` are always present, `emg` only with a device port, `gaze`
        only when the targeter actually built (calibration + X11 + deps). An
        empty map means the feature is off, and every caller treats that as
        "behave exactly as before".
        """
        if not cfg.modality.enabled:
            return {}
        from yazses.modality.router import ModalityPolicy, resolve_roles

        available = ["voice", "keyboard"]
        if (cfg.emg.device_port or "").strip():
            available.append("emg")
        if getattr(self, "_gaze_targeter", None) is not None:
            available.append("gaze")
        policy = ModalityPolicy.from_preset(cfg.modality.preset, cfg.modality.priority)
        roles = resolve_roles(available, policy)
        log.info("Modality roles (%s): %s", cfg.modality.preset,
                 ", ".join(f"{r}->{m}" for r, m in sorted(roles.items())) or "none")
        return roles

    def _build_activation_sources(self, cfg) -> list:
        """Build the non-keyboard activation sources ([emg] squeeze-to-talk).

        Constructed only when ``[emg] device_port`` is set. ``mode = "command"``
        (the default) drives the command-key callbacks — a squeeze speaks a
        command; ``full_text`` drives plain hold-to-talk dictation. A missing
        pyserial makes the backend's run() a logged no-op, and any init failure
        is caught, so this can never break startup.
        """
        sources: list = []
        port = (cfg.emg.device_port or "").strip()
        if not port:
            return sources
        try:
            from yazses.platform.emg.backend import EMGBackend

            # The modality router, when enabled, is what decides whether EMG owns
            # commands — that is the arbitration ADR-v2-011 describes, and the
            # runtime read that takes `modality` out of _UNWIRED. With it off,
            # `[emg] mode` alone decides, exactly as before.
            mode = cfg.emg.mode
            roles = getattr(self, "_modality_roles", {})
            if roles:
                mode = "command" if roles.get("command") == "emg" else "full_text"
                if mode != cfg.emg.mode:
                    log.info("Modality router set EMG to %s mode (config said %s).",
                             mode, cfg.emg.mode)
            if mode == "command":
                start, end = self._on_command_hold_start, self._on_command_hold_end
            else:
                start, end = self._on_hold_start, self._on_hold_end
            sources.append(EMGBackend(port, cfg.emg.baud_rate, start, end))
            log.info("EMG activation source enabled on %s (%s mode).", port, mode)
        except Exception:
            log.warning("EMG activation source init failed; continuing without.",
                        exc_info=True)
        return sources

    def _build_gaze_targeter(self, cfg):
        """Build the look-to-pane targeter, or None when any piece is missing.

        Requires ``[gaze] enabled`` + (``route_dictation`` or ``deixis``), a
        saved calibration, an X11 desktop backend (xdotool), and the gaze deps.
        Any absent → None, so dictation simply stays on the focused window.
        """
        if not (cfg.gaze.enabled and (cfg.gaze.route_dictation or cfg.gaze.deixis)):
            return None
        try:
            from yazses.gaze.desktop import build_desktop
            from yazses.gaze.factory import build_gaze
            from yazses.gaze.store import load_calibration
            from yazses.gaze.targeter import GazeTargeter

            desktop = build_desktop()
            if desktop is None:
                log.warning("Gaze routing enabled but no X11 desktop backend; dormant.")
                return None
            calibration = load_calibration(self._platform.paths.data_dir)
            if calibration is None:
                log.warning("Gaze routing enabled but not calibrated; run `yazses gaze calibrate`.")
                return None
            backend = build_gaze(cfg.gaze)
            if backend is None:
                log.warning("Gaze routing enabled but gaze deps unavailable; dormant.")
                return None
            log.info("Glance-Type look-to-pane routing active.")
            return GazeTargeter(backend, calibration, desktop, cfg.gaze.confidence_min)
        except Exception:
            log.debug("Gaze targeter init failed; skipping", exc_info=True)
            return None

    def _on_command_hold_start(self, leaked: int) -> None:
        """Hold-start for the dedicated command key — arm force-command mode."""
        self._command_mode = True
        self._on_hold_start(leaked)

    def _on_command_hold_end(self) -> None:
        """Hold-end for the command key. `_on_hold_end` consumes _command_mode."""
        self._on_hold_end()

    def _on_hold_start(self, leaked: int) -> None:
        # Barge-in: a new hold during read-back cancels TTS playback immediately
        # so the user's speech is never recorded over the spoken transcript.
        if self._tts is not None:
            try:
                self._tts.cancel()
            except Exception:
                pass
        with self._lock:
            self._state.state = TrayState.RECORDING
        log.info("Recording started (cleaning up %d leaked char(s))", leaked)
        # The eyes-free counterpart of the tray turning green. Non-blocking.
        self._earcon.play("recording_start")

        # "No text target" guard: detect (off the hot path, so recording onset isn't
        # delayed) whether the focused element accepts text. Drives the yellow tray state
        # and lets _on_hold_end save to the clipboard instead of typing into the wrong place.
        self._detect_target_async()

        # Glance-Type: focus the looked-at window now (while the user is looking
        # at their target) so this burst's injection lands there. Best-effort.
        # With only deixis on (route_dictation off), snapshot the decision
        # without focusing so "close this" still knows the looked-at window.
        if self._gaze_targeter is not None:
            try:
                self._gaze_targeter.retarget(
                    activate=self._config.gaze.route_dictation
                )
            except Exception as exc:
                log.warning("Gaze retarget failed: %s", exc)
        if leaked > 0 and self._injector is not None:
            try:
                self._injector.inject_backspaces(leaked)
            except Exception as exc:
                log.warning("Failed to clean %d leaked char(s): %s", leaked, exc)

        if (
            self._stream_engine is not None
            and self._config.streaming.enabled
            and not self._command_mode  # commands never stream-type live
        ):
            self._stream_engine.start()
            # Seed with pre-speech padding so voice onset isn't lost
            if self._padding_buffer is not None:
                padding = self._padding_buffer.get()
                if padding.size > 0:
                    self._stream_engine.push(padding)
            self._stream_injector = StreamingInjector(self._active_injector())
            self._poll_stop = threading.Event()
            stop = self._poll_stop
            self._poll_thread = threading.Thread(
                target=self._partial_poll_loop,
                args=(stop,),
                daemon=True,
                name="partial-poll",
            )
            self._streaming_active = True
            self._poll_thread.start()

        if self._recorder is not None:
            try:
                self._recorder.start()
            except Exception as exc:
                log.error("Microphone unavailable: %s", exc)
                self._streaming_active = False
                if self._poll_stop is not None:
                    self._poll_stop.set()
                with self._lock:
                    self._state.last_error = f"Microphone unavailable: {exc}"
                    self._state.state = TrayState.IDLE
                # The user is holding the key right now and nothing is happening.
                # Before this, that produced a log line and a blue idle badge.
                from yazses.system.diagnosis import CAPTURE

                self._report_failure(exc, CAPTURE)

    # Evdev/ydotool keycodes for the hold-to-talk hotkeys (Linux input-event-codes;
    # ydotool uses the same numbers). Mirrors platform/linux/hotkey.py's keymap.
    _HOTKEY_KEYCODES = {
        "space": 57, "right_ctrl": 97, "left_ctrl": 29, "right_alt": 100,
        "left_alt": 56, "right_meta": 126, "left_meta": 125,
        "right_shift": 54, "left_shift": 42,
    }

    def _hotkey_release_codes(self) -> set:
        """The evdev keycodes to synth-release on hold-end: the dictation hotkey
        plus the command key (if configured), resolved from names. Pure."""
        names = {
            (self._config.hotkey.key or "").strip(),
            (self._config.hotkey.command_key or "").strip(),
        }
        default = getattr(self._platform, "default_hotkey", "right_alt")
        codes = set()
        for name in names:
            if name in ("", "auto"):
                name = default
            code = self._HOTKEY_KEYCODES.get(name)
            if code is not None:
                codes.add(code)
        return codes

    def _release_hotkey_modifier(self) -> None:
        """Synthesise a key-up for the hold-to-talk key(s) so the compositor's
        view matches reality.

        yazses reads the physical input device, so it reliably knows the hold
        ended — but GNOME Wayland's mutter intermittently drops the *same* key-up
        for modifier events, leaving right_alt logically held: the next Space
        becomes Alt+Space (the window menu whose first item is 'Take Screenshot')
        and typed letters mangle through the AltGr layer. Sending a synthetic
        key-up via ydotool forces mutter to release it. Runs on every hold-end
        (dictation OR silent discard). Best-effort: Linux-only, never raises.

        Only spawns ydotool when ydotoold's socket is actually present. Without a
        running ydotoold the ``ydotool`` client ``abort()``s (SIGABRT), which the
        desktop's crash reporter (Apport) surfaces as a "ydotool has stopped
        unexpectedly" dialog on every hold-end. This synthetic key-up is a GNOME
        Wayland/mutter workaround anyway — X11 delivers the real key-up itself, so
        skipping it there (where there is no ydotoold) is both safe and correct.
        """
        import os as _os
        import sys as _sys

        if _sys.platform != "linux":
            return
        # Don't fire real key events (or spawn ydotool) inside the test suite.
        if _os.environ.get("PYTEST_CURRENT_TEST"):
            return
        try:
            codes = self._hotkey_release_codes()
            if not codes:
                return
            # ydotool aborts (→ Apport crash dialog) when ydotoold isn't running;
            # only invoke it when its socket exists (i.e. it will actually work).
            from yazses.inject.auto import ydotool_ready

            if not ydotool_ready():
                return
            import subprocess
            args = ["ydotool", "key"] + [f"{c}:0" for c in sorted(codes)]
            subprocess.run(args, check=False, timeout=3)
        except Exception:  # pragma: no cover - best-effort, environment dependent
            log.debug("hotkey-modifier release (best-effort) failed", exc_info=True)

    def _on_hold_end(self) -> None:
        self._earcon.play("recording_stop")
        log.info("Recording stopped, transcribing...")

        # Force the compositor to release the hold-to-talk key NOW, before the
        # (slow) transcription, and regardless of whether this burst ends in an
        # injection or a silent discard. Fixes stuck right_alt → Alt+Space window
        # menu / screenshots on GNOME Wayland. Best-effort; never breaks dictation.
        self._release_hotkey_modifier()

        # Consume the dedicated-command-key flag for this burst (reset for next).
        command_mode = self._command_mode
        self._command_mode = False

        # Stop streaming poll before touching the injector state
        self._streaming_active = False
        if self._poll_stop is not None:
            self._poll_stop.set()
        if self._poll_thread is not None:
            # Deliberately short, and deliberately not relied upon. The thread can
            # be inside an injection subprocess whose own timeout is far longer
            # than any join we would want on the hold-release hot path, so this
            # join *will* sometimes return with the thread still alive. Ordering
            # is guaranteed by StreamingInjector's lock and seal instead: a late
            # partial is dropped rather than typed after the final text.
            self._poll_thread.join(timeout=1.0)
            self._poll_thread = None
        # Stop the engine's decode loop too. Only commit() used to end it, so any
        # burst that returned early below (silent discard, cocktail gate, no
        # recorder) left the loop re-decoding its frozen buffer once per interval
        # forever — one leaked Whisper decode per second, per discarded burst,
        # surviving until the process exited. Non-blocking so hold-release stays
        # on the hot path; commit() still joins before the final decode.
        if self._stream_engine is not None:
            self._stream_engine.request_stop()

        if self._recorder is None or self._engine is None or self._injector is None:
            return
        with self._lock:
            self._state.state = TrayState.TRANSCRIBING

        stream_injector = self._stream_injector
        self._stream_injector = None

        # Learning corpus event accumulated across the pipeline; written once in
        # the finally block when capture is enabled. None-safe and never blocking.
        event: dict = {"ts": time.time(), "model": self._config.stt.model}
        clip: np.ndarray | None = None
        sample_rate = self._config.audio.sample_rate
        # Set by the pipeline's `except` handler. Declared here because the `finally`
        # reads it on every burst, including the ones that never raise.
        pipeline_failed = False

        try:
            audio = self._recorder.stop()

            # Modifier hotkeys start recording on key-down, so voice onset is
            # already in `audio`. (The old code pushed this recording into the
            # ring buffer and then prepended that same tail to its own front,
            # which corrupted the start rather than recovering onset.)
            padded = audio

            clip = padded
            event["audio_secs"] = padded.size / sample_rate
            event["level"] = float(np.abs(padded).mean()) if padded.size else 0.0

            # VAD. Accessibility Continuum — Whisper/Low-Effort Mode lowers the VAD
            # threshold so quiet speech isn't gated as silence (ADR-v2-012). Guarded
            # so it can never break the gate; off by default → base threshold.
            acc = self._config.accessibility
            try:
                from dataclasses import replace

                from yazses.continuum.whisper_mode import effective_vad_threshold
                eff = effective_vad_threshold(acc.vad_threshold, self._config.continuum)
                if eff != acc.vad_threshold:
                    acc = replace(acc, vad_threshold=eff)
            except Exception:
                acc = self._config.accessibility
            if is_silent_calibrated(padded, acc):
                event["discard_reason"] = "silent"
                level = float(np.abs(padded).mean()) if padded.size else 0.0
                log.info(
                    "Silent audio -- discarding (level %.4f < vad_threshold %.4f; "
                    "run 'yazses mic-level --set' to retune).",
                    level,
                    acc.vad_threshold,
                )
                # A run of these is the "dictation silently stopped writing" symptom
                # (mic switched to a dead/quiet source): auto-heal + notify the user.
                self._adaptive_vad.observe_discard(level)
                self._maybe_retune_threshold(acc.vad_threshold)
                self._note_silent_discard()
                # Nothing was heard, so nothing will be typed. Without a screen this is
                # indistinguishable from a slow transcription, and the user waits for
                # text that is never coming.
                self._earcon.play("error")
                if stream_injector is not None:
                    stream_injector.cancel()
                return

            # Cocktail Filter: drop frames that aren't the enrolled target speaker
            # before STT, so an interfering voice never enters the transcript.
            padded = self._maybe_cocktail_gate(padded)
            if padded.size == 0:
                event["discard_reason"] = "cocktail_gated"
                log.info("Cocktail Filter gated out all audio (no target speaker).")
                if stream_injector is not None:
                    stream_injector.cancel()
                return

            # Sotto-voce command channel (ADR-v2-100, DualVoice pattern): a
            # *whispered* burst is a command, voiced speech dictates. Purely
            # acoustic (no F0 in whisper), so it can never fire on normal
            # speech louder than the VAD gate. Guarded: detection failure
            # means dictation, never a crash.
            wm = self._config.whispermode
            if not command_mode and wm.enabled and wm.command_channel:
                try:
                    from yazses.whispermode.detect import burst_is_whispered

                    if burst_is_whispered(
                        padded, sample_rate,
                        voicing_max=wm.voicing_max, tilt_min=wm.tilt_min,
                    ):
                        command_mode = True
                        event["whispered"] = True
                        log.info("Sotto-voce: whispered burst → command mode.")
                except Exception:
                    log.debug("Whisper detection failed; treating as voiced.",
                              exc_info=True)

            use_streaming = (
                self._config.streaming.enabled
                and self._stream_engine is not None
                and stream_injector is not None
            )

            bias_prompt = self._effective_initial_prompt()

            # Prepend a short silence lead-in so faster-whisper doesn't drop the
            # opening word on an abrupt onset. Done here (after the VAD gate) so
            # the added zeros never lower the measured level and cause a false
            # "silent" discard. Streaming commits its own buffer, so skip there.
            decode_audio = padded
            lead_ms = self._config.accessibility.pre_speech_padding_ms
            if lead_ms > 0:
                lead = np.zeros(
                    int(lead_ms * self._config.audio.sample_rate / 1000),
                    dtype=padded.dtype,
                )
                decode_audio = np.concatenate([lead, padded])

            # Noise-suppression front-end (ADR-v2-015): identity passthrough when
            # off/unavailable; never raises. Improves STT input in noisy rooms.
            try:
                from yazses.denoise.frontend import apply_denoise
                decode_audio = apply_denoise(
                    decode_audio, self._config.denoise, self._config.audio.sample_rate
                )
            except Exception:
                pass

            audio_secs = padded.size / self._config.audio.sample_rate
            # Prosody Ink (batch only) needs per-word timestamps; capture them on
            # the non-streaming path when [prosody] enabled, else use the fast
            # path so non-prosody users never pay the word_timestamps cost.
            prosody_words: list[Word] = []
            want_prosody = self._config.prosody.enabled and not use_streaming
            # Confidence Ink (ADR-v2-001) also needs the word-timestamps path for
            # per-word probabilities; share the same decode as prosody.
            want_confidence = self._config.confidence.enabled and not use_streaming
            want_words = want_prosody or want_confidence
            # Speech translation (ADR-v2-014): X→English via Whisper's translate task
            # when [translate] is enabled (whisper backend, target en). None → normal.
            try:
                from yazses.translate.mode import inactive_reason, translation_task
                stt_task = translation_task(self._config.translate)
                # Enabled-but-inert is indistinguishable from "translation isn't
                # working" unless we say so. Once per process, not per burst.
                if stt_task is None:
                    self._warn_feature_inert(
                        "translate", inactive_reason(self._config.translate)
                    )
            except Exception:
                stt_task = None
            t_decode = time.monotonic()
            if use_streaming:
                assert self._stream_engine is not None
                text = self._stream_engine.commit()
            elif want_words:
                text, prosody_words = self._engine.transcribe_words(
                    decode_audio,
                    self._config.audio.sample_rate,
                    initial_prompt=bias_prompt,
                    task=stt_task,
                )
            else:
                text = self._engine.transcribe(
                    decode_audio,
                    self._config.audio.sample_rate,
                    initial_prompt=bias_prompt,
                    task=stt_task,
                )
            decode_ms = (time.monotonic() - t_decode) * 1000.0
            event["raw_text"] = text
            event["decode_ms"] = decode_ms
            # Aggregated into p50/p95 for `yazses status` (#296). In-memory and
            # bounded, so this works whether or not the learning corpus is on.
            self._latency.record(self._config.stt.model, decode_ms)
            # Metadata only (no transcript text) so the file log is safe to share.
            log.info(
                "Transcribed %.1fs audio in %.0f ms (model %s, level %.4f)",
                audio_secs, decode_ms, self._config.stt.model,
                float(np.abs(padded).mean()) if padded.size else 0.0,
            )

            # Confidence Ink (ADR-v2-001): flag words the recognizer was unsure
            # about, using its own token probabilities. Metadata only here (a COUNT,
            # never the words) to honor ADR-011; the overlay marker + voice re-pick
            # UX consume `low_confidence_spans` from `event` downstream. Guarded so
            # it can never break dictation.
            if want_confidence and prosody_words:
                try:
                    from yazses.postprocess.confidence import low_confidence_spans
                    pairs = [(w.text, w.probability) for w in prosody_words]
                    spans = low_confidence_spans(pairs, self._config.confidence.threshold)
                    n_low = sum(e - s for s, e in spans)
                    event["low_confidence_words"] = n_low
                    self._last_low_confidence_words = n_low
                    if n_low:
                        log.info(
                            "Confidence Ink: %d low-confidence word(s) (threshold %.2f).",
                            n_low, self._config.confidence.threshold,
                        )
                except Exception:
                    pass  # confidence annotation is best-effort; never break dictation

            text = clean_text(text)
            text = self._correct_vocabulary(text, event)
            event["cleaned_text"] = text
            if not text:
                event["discard_reason"] = "empty"
                log.info("Empty transcription -- discarding.")
                # Decoding to nothing is the same failure as hearing nothing: the key
                # was held, speech happened, no text appears. It used to differ only
                # in that this path said nothing at all -- so a microphone capturing
                # audible but unintelligible audio (too quiet, wrong device, badly
                # attenuated) discarded for ever with `silent_streak` stuck at 0,
                # while the guard built for exactly that symptom saw a healthy mic.
                # Measured on a real machine: four consecutive empty transcriptions
                # at levels 0.0022-0.0069, against 0.0199 for that machine's last
                # successful capture, and not one word said about it.
                self._note_silent_discard()
                # Same reasoning as the silent branch: nothing will be typed, and
                # without a screen that is indistinguishable from a slow decode.
                self._earcon.play("error")
                if stream_injector is not None:
                    stream_injector.cancel()
                return

            # Hallucination Guard (ADR-v2-025): drop Whisper's fabricated ghost text
            # (silence outros, repetition loops) before injection. Off by default.
            if self._config.hallucination.enabled:
                from yazses.postprocess.hallucination import should_drop
                if should_drop(text, self._config.hallucination):
                    event["discard_reason"] = "hallucination"
                    log.info("Hallucination guard -- discarding fabricated transcript.")
                    if stream_injector is not None:
                        stream_injector.cancel()
                    return

            if self._config.filters.disfluency.enabled:
                result = filter_transcript(text, self._config.filters.disfluency)
                text = result.text
                event["filtered_text"] = text
                if not text:
                    event["discard_reason"] = "post_filter"
                    log.info("Post-filter empty -- discarding.")
                    if stream_injector is not None:
                        stream_injector.cancel()
                    return

            # INFO: metadata only (length); DEBUG: the actual text.
            log.info("Injecting %d chars, %d words.", len(text), len(text.split()))
            log.debug("Injecting text: %r", text)
            with self._lock:
                self._state.state = TrayState.INJECTING

            injector = self._active_injector()
            event["final_text"] = text
            event["injected"] = True

            # Classify first so we know whether this burst is dictation (which
            # gets cleanup + continuation spacing) or a command (key sequence —
            # no spacing, no dictation-timestamp update).
            #
            # Command mode (dedicated command key held): always parse as a
            # command and NEVER type literal text — an unrecognised phrase is
            # ignored. Otherwise: auto-detect on the shared dictation key.
            intent = None
            if command_mode:
                intent = classify(text, self._config.commands.profile,
                                  macro_table=self._macro_table)
                event["command_mode"] = True
                event["intent_type"] = intent.intent.value
                event["intent_action"] = intent.action
                if intent.intent == IntentType.DICTATE:
                    # Gaze deixis: "close this" / "focus that" acts on the window
                    # the gaze snapshot says you are looking at. Tried first —
                    # its grammar is strict whole-utterance, so it can't shadow
                    # the scratch/spoken-edit parsers below.
                    if self._config.gaze.deixis:
                        if self._try_deixis(text, event):
                            if stream_injector is not None:
                                stream_injector.cancel()
                            return
                    # "focus the browser" (#39). Whole-utterance grammar, so it
                    # cannot shadow dictation containing the word "focus".
                    if self._try_window_focus(text, event):
                        if stream_injector is not None:
                            stream_injector.cancel()
                        return
                    # From here down, handlers put text on screen. The no-text-target
                    # guard lives ~300 lines away on the dictation path, so in command
                    # mode these ran unguarded: with nothing editable focused,
                    # `_try_spoken_edit` would backspace into whatever window *did*
                    # have focus, and `_try_rewrite` would type a rewritten selection
                    # there.
                    #
                    # Gated individually rather than hoisting one check to the top of
                    # this branch, because the handlers above and between are the ones
                    # that SHOULD still work with no text target: deixis and window
                    # focus act on a window, and Ambient Scratch captures a note to a
                    # pad — that is most useful precisely when nothing is focused.
                    #
                    # `_handle_no_target` is deliberately not reused: it copies the
                    # transcript to the clipboard, which is right for dictation and
                    # wrong for a command. "change hello to goodbye" on the clipboard
                    # helps nobody.
                    can_type = self._state.target_ok is not False

                    # Offline Command Mode (#99): rewrite the selection locally.
                    # Whole-utterance grammar, so dictation containing "make this
                    # shorter" as prose is unaffected.
                    if can_type and self._try_rewrite(text, event):
                        if stream_injector is not None:
                            stream_injector.cancel()
                        return
                    # Ambient Scratch (ADR-v2-005): capture a note-to-self ("note to
                    # self ...") to the scratch pad instead of typing it. Command-key
                    # gated + off by default.
                    if self._config.recall.scratch:
                        if stream_injector is not None:
                            stream_injector.cancel()
                        if self._try_scratch(text, event):
                            return
                    # Spoken Edit Mode (ADR-v2-003): before discarding an unmatched
                    # command, try to read it as an open-ended edit of the last
                    # dictation ("change X to Y"). Command-key gated + off by default.
                    if can_type and self._config.commands.spoken_edit:
                        if stream_injector is not None:
                            stream_injector.cancel()
                        if self._try_spoken_edit(text, event):
                            return
                    if not can_type:
                        # Say which of the two it was. "no command matched" would be
                        # a lie here: the phrase may well have matched, and was
                        # refused because applying it would have typed elsewhere.
                        event["discard_reason"] = "command_no_text_target"
                        log.info("Command mode: no editable target, so the %d-char "
                                 "phrase was not applied — an edit would have typed "
                                 "into another window.", len(text))
                    else:
                        event["discard_reason"] = "command_unmatched"
                        log.info("Command mode: no command matched %d-char phrase; "
                                 "ignoring (not typed).", len(text))
                    if stream_injector is not None:
                        stream_injector.cancel()
                    return
                is_dictation = False
            else:
                if self._config.commands.enabled:
                    intent = classify(text, self._config.commands.profile,
                                       macro_table=self._macro_table)
                    event["intent_type"] = intent.intent.value
                    event["intent_action"] = intent.action
                    # `run <anything>` types the words AND presses Return, so it
                    # EXECUTES. Its grammar is `^run (.+)$`, which any ordinary
                    # sentence beginning with "run" satisfies — "run the numbers
                    # again before Friday" would be executed in whatever window
                    # has focus. Every other command is recoverable by retyping;
                    # this one is not, so the open-ended form requires the
                    # command key, where the user has said they mean a command.
                    # The closed-vocabulary rules (`run the tests`, `run the
                    # build`, `run that`) are unambiguous whole utterances and
                    # stay available without it.
                    if intent.action == "run_command":
                        log.info("Ignoring open-ended `run …` outside command mode; "
                                 "typing it instead. Bind [hotkey] command_key to use it.")
                        event["intent_type"] = IntentType.DICTATE.value
                        event["intent_action"] = "dictate"
                        event["refused_open_run"] = True
                        intent = None
                is_dictation = intent is None or intent.intent == IntentType.DICTATE

            # Voice Undo/Redo Timeline (ADR-v2-089): a whole-utterance "undo the last
            # word" / "redo" replays YazSes's own injection history, in the same shape
            # as "scratch that" above — backspaces and retypes only what this daemon
            # put on screen, so it can never eat the user's own typing.
            if is_dictation and self._config.timeline.enabled and self._timeline is not None:
                from yazses.timeline.history import parse_timeline_command
                t_cmd = parse_timeline_command(text)
                if t_cmd:
                    action, count, scope = t_cmd
                    if use_streaming and stream_injector is not None:
                        stream_injector.cancel()
                    # Both branches below return before ever reaching the
                    # no-text-target guard on the dictation path ~250 lines down,
                    # so they replayed history into whatever window had focus.
                    # "it can never eat the user's own typing" above is true of
                    # *what* it replays and says nothing about *where* — if focus
                    # moved since the text was injected, these backspaces land on
                    # someone else's document.
                    if self._state.target_ok is False:
                        event["discard_reason"] = "timeline_no_text_target"
                        log.info("Timeline: no editable target, so '%s' was not "
                                 "replayed — the keystrokes would have gone to "
                                 "another window.", action)
                        return
                    applied = 0
                    for _ in range(count):
                        # Peek, inject, then commit — same ordering as "scratch
                        # that" below. `undo()`/`redo()` mutate as they report, so
                        # asking what to do *is* doing it: if the injection then
                        # failed, the history had already moved on and the next
                        # undo would target text that is still on screen.
                        op = (
                            self._timeline.peek_undo(scope) if action == "undo"
                            else self._timeline.peek_redo()
                        )
                        if op is None:
                            break  # history exhausted — stop, don't keep pressing keys
                        if op.backspaces:
                            injector.inject_key_sequence(["BackSpace"] * op.backspaces)
                        if op.insert:
                            injector.inject(op.insert)
                        if action == "undo":
                            self._timeline.undo(scope)
                        else:
                            self._timeline.redo()
                        applied += 1
                    event["intent_type"] = action
                    event["timeline_scope"] = scope
                    event["timeline_applied"] = applied
                    log.info("Timeline: %s %d/%d (scope=%s).", action, applied, count, scope)
                    return

            # Mid-Thought Undo: a whole-utterance "scratch that" deletes the last
            # burst YazSes injected (backspaces), instead of typing it literally.
            if is_dictation and self._config.revise.enabled and parse_revise(text):
                if use_streaming and stream_injector is not None:
                    stream_injector.cancel()
                # Same gap as the timeline branch above: this returns before the
                # no-text-target guard, so with focus moved away the backspaces
                # would delete someone else's text rather than YazSes's own.
                if self._state.target_ok is False:
                    event["discard_reason"] = "revise_no_text_target"
                    log.info("Mid-thought undo: no editable target, so 'scratch "
                             "that' was not applied — the backspaces would have "
                             "gone to another window.")
                    return
                # Peek, inject, and only THEN commit. `scratch_last()` pops as it
                # reports, so asking the ledger for the count *is* the undo: if the
                # injection below then failed, the burst had already been dropped
                # while its text was still on screen, and the next "scratch that"
                # would delete the burst *before* it — text the user never asked to
                # remove. Compounding, and silent, because the surrounding pipeline
                # swallows the exception. `last_text()` is a sound non-mutating peek:
                # `record()` and `replace_last()` are the only writers and both keep
                # `_counts[-1] == len(_texts[-1])`.
                n = len(self._ledger.last_text())
                if n > 0:
                    injector.inject_key_sequence(["BackSpace"] * n)
                    self._ledger.scratch_last()
                event["intent_type"] = "revise"
                event["revise_chars"] = n
                log.info("Mid-thought undo: scratched %d chars.", n)
                return

            with self._lock:
                app_class = self._state.app_class

            from yazses.postprocess.profiles import resolve_profile
            profile = resolve_profile(app_class, self._config.profiles)

            # Verbatim/Autoformat mode (ADR-v2-078): the spoken commands "dictate
            # verbatim" / "resume formatting" toggle a persistent gate and type nothing;
            # while verbatim, all formatting transforms are bypassed (literal capture).
            verbatim_active = profile.tone == "verbatim"
            if is_dictation and self._config.verbatim.enabled:
                if self._verbatim_gate is None:
                    from yazses.verbatim.gate import VerbatimGate

                    self._verbatim_gate = VerbatimGate()
                if self._verbatim_gate.handle_command(text):
                    event["intent_type"] = "verbatim_mode"
                    event["verbatim_mode"] = self._verbatim_gate.mode
                    if stream_injector is not None:
                        stream_injector.cancel()
                    log.info("Formatting mode set to %s.", self._verbatim_gate.mode)
                    return
                if self._verbatim_gate.is_verbatim():
                    verbatim_active = True

            if is_dictation:
                text = self._clean_dictation(text, event, profile.tone)
                verbatim_literal = text  # cleaned literal, before any formatting transform
                # Mid-Utterance Self-Repair: apply "no I mean X" corrections before anything
                # else consumes the text. Opt-in (ADR-v2-058).
                if self._config.commands.self_repair:
                    from yazses.selfrepair.repair import apply_self_repair

                    text = apply_self_repair(text)
                    event["final_text"] = text
                # Inline Compute: a whole-utterance arithmetic expression -> its answer
                # ("what's 15% of 240" -> "36"). Self-gating: evaluate() returns None
                # (no-op) unless the utterance is arithmetic. Opt-in (ADR-v2-086).
                if self._config.compute.enabled:
                    from yazses.compute.evaluate import evaluate

                    _ans = evaluate(text)
                    if _ans is not None:
                        text = _ans
                        event["final_text"] = text
                # Phonetic Corrector: fix mis-heard names/jargon against your personal
                # dictionary by sound ("kubernetis" -> "Kubernetes"). Opt-in (ADR-v2-027).
                if self._config.phonetic.enabled:
                    from yazses.postprocess.phonetic import correct_text
                    from yazses.system.vocabulary import load_vocab, vocab_path

                    _vocab = load_vocab(vocab_path(self._platform.paths.config_file.parent))
                    _raw = os.environ.get("YAZSES_VOCABULARY", "")
                    _vocab += [t.strip() for t in _raw.split(",") if t.strip()]
                    if _vocab:
                        text = correct_text(text, _vocab)
                        event["final_text"] = text
                # Spoken punctuation/formatting ("comma" -> ","). Opt-in.
                if self._config.commands.voice_punctuation:
                    text = apply_voice_punctuation(text)
                    event["final_text"] = text
                # Entity ITN: "john dot doe at gmail dot com" -> john.doe@gmail.com,
                # "version two point one" -> v2.1. No command words. Opt-in (ADR-v2-045).
                if self._config.itn.enabled:
                    from yazses.itn.normalize import normalize_entities

                    text = normalize_entities(text)
                    event["final_text"] = text
                # Redaction Ink: mask spoken secrets (card/SSN/key/email/...) before they
                # are typed into another window. Opt-in (ADR-v2-046).
                if self._config.redaction.enabled:
                    from yazses.redaction.scrub import redact

                    text = redact(text, mode=self._config.redaction.mode).text
                    event["final_text"] = text
                # Emoji & Symbol by Voice: "right arrow" -> "→". Opt-in (ADR-v2-055).
                if self._config.commands.symbols:
                    from yazses.symbols.lookup import apply_symbols

                    text = apply_symbols(text)
                    event["final_text"] = text
                # Voice Unit Conversion: "20 miles in km" -> "32.19 km". Opt-in (ADR-v2-056).
                if self._config.convert.enabled:
                    from yazses.convert.units import apply_conversions

                    text = apply_conversions(text)
                    event["final_text"] = text
                # Spoken Temporal Normalizer: "next Friday" -> a concrete date. Opt-in (ADR-v2-057).
                if self._config.temporal.enabled:
                    from datetime import datetime as _dt

                    from yazses.temporal.resolve import resolve_temporal

                    text = resolve_temporal(text, _dt.now())
                    event["final_text"] = text
                # Grammar Repair (GEC): minimal-edit fixes like "a apple" -> "an apple".
                # Rule tier only. Opt-in (ADR-v2-050).
                if self._config.gec.enabled:
                    from yazses.gec.guard import fix_articles

                    text = fix_articles(text)
                    event["final_text"] = text
                # Diacritize: restore dropped diacritics ("cafe cliche" -> "café cliché")
                # from a dictionary of known words. Opt-in (ADR-v2-122).
                if self._config.diacritize.enabled:
                    from yazses.diacritize.restore import restore_diacritics

                    text = restore_diacritics(text)
                    event["final_text"] = text
                # Transliteration: romanized input in the configured scheme -> native
                # script ("finglish" Persian, etc.). Opt-in mode (ADR-v2-116).
                if self._config.translit.enabled:
                    from yazses.translit.scheme import detect_scheme, transliterate

                    _scheme = detect_scheme(text, self._config.translit.scheme)
                    if _scheme:
                        text = transliterate(text, _scheme)
                        event["final_text"] = text
                # Semantic Line Breaks: put one clause per source line for diff-friendly
                # prose. Opt-in (ADR-v2-111).
                if self._config.sembr.enabled:
                    from yazses.sembr.breaks import semantic_breaks

                    text = semantic_breaks(text)
                    event["final_text"] = text
                # Structured-Markup Dictation: spoken lists/tables -> Markdown/org.
                # Self-gating: parse_structure() returns None for ordinary prose.
                # Opt-in (ADR-v2-067).
                if self._config.markup.enabled:
                    from yazses.markup.render import parse_structure, render_markup

                    _struct = parse_structure(text)
                    if _struct is not None:
                        text = render_markup(_struct, self._config.markup.flavor)
                        event["final_text"] = text
                # Style-Consistency Enforcer: rewrite terms/spellings to your house
                # style ('email' -> 'e-mail'), a local Vale-lite pass driven by
                # ~/.config/yazses/style-rules.toml. Opt-in (ADR-v2-109).
                if self._config.styleguard.enabled and self._style_rules:
                    text, _ = apply_style(text, self._style_rules)
                    event["final_text"] = text
                # SafeGlyph: flag confusable homoglyphs (e.g. Cyrillic look-alikes) in the
                # outgoing text before injection. Non-destructive — logs a warning only.
                # Opt-in (ADR-v2-123).
                if self._config.safeglyph.enabled:
                    from yazses.safeglyph.confusables import scan_confusables

                    _sg = scan_confusables(text)
                    if _sg:
                        log.warning(
                            "SafeGlyph: %d confusable glyph(s) in dictated text: %s",
                            len(_sg), _sg,
                        )
                # Auto-Pairing: append the closers needed to balance brackets/quotes
                # ("(a plus b" -> "(a plus b)"). Opt-in (ADR-v2-088).
                if self._config.autopair.enabled:
                    from yazses.autopair.balance import balance_delimiters

                    text = balance_delimiters(text)
                    event["final_text"] = text
                # Prosody Ink: map vocal prosody (inter-word pause, emphasis) onto
                # text formatting. Batch + dictation only; word timings drive the
                # spacing/emphasis, content stays the cleaned text. Off by default.
                if want_prosody and prosody_words:
                    presult = annotate(
                        text, padded, sample_rate, prosody_words, self._config.prosody
                    )
                    if presult.latency_ms > self._config.prosody.max_latency_ms:
                        log.warning(
                            "Prosody pass took %.0f ms (> max_latency_ms %d); "
                            "consider format=none (pause-only).",
                            presult.latency_ms, self._config.prosody.max_latency_ms,
                        )
                    text = presult.text
                    event["prosody_breaks"] = presult.paragraph_breaks
                    event["prosody_emphasized"] = presult.emphasized
                    event["final_text"] = text
                # Verbatim mode: discard every formatting transform above and inject the
                # cleaned literal text (ITN/punctuation/reflow/etc. all bypassed).
                if verbatim_active:
                    text = verbatim_literal
                    event["final_text"] = text
                    event["verbatim"] = True
                # Prepend a separating space when this dictation continues a
                # recent burst, so consecutive hold-to-talk utterances don't
                # glue together at the boundary ("words together" + "I mean"
                # -> "... togetherI mean"). Suppressed before closing punctuation.
                if self._config.injection.continuation_window_ms > 0:
                    window_s = self._config.injection.continuation_window_ms / 1000.0
                    had_recent = (
                        self._last_dictation_monotonic is not None
                        and (time.monotonic() - self._last_dictation_monotonic) <= window_s
                    )
                    text = continuation_prefix(text, had_recent_injection=had_recent) + text
                event["final_text"] = text

            if not is_dictation:
                assert intent is not None
                if use_streaming and stream_injector is not None:
                    stream_injector.cancel()
                cmd_dispatch(intent, injector,
                             macro_table=self._macro_table,
                             macro_context=self._build_macro_context())
            else:
                # Command Safety Gate (ADR-v2-065): a dictated `rm -rf` waits for a
                # spoken "confirm" instead of typing straight into a shell. Runs
                # BEFORE staged dictation on purpose — the confirm word has to be
                # consumed as a control utterance, and the staged buffer would
                # otherwise swallow it as ordinary text.
                if self._config.cmdsafety.enabled:
                    gated = self._cmdsafety_gate(text, event)
                    if gated is None:
                        return
                    text = gated
                    event["final_text"] = text

                # Checksum-Validated Entry (ADR-v2-106, wired by ADR-021): a dictated
                # card number, IBAN or ISBN whose check digit fails waits rather than
                # typing a number nothing downstream will notice is wrong. Shares the
                # command gate's confirm word, so the user learns one release phrase
                # rather than one per guard.
                if self._config.checkdigit.enabled:
                    checked = self._checkdigit_gate(text, event)
                    if checked is None:
                        return
                    text = checked
                    event["final_text"] = text

                # Spoken answer to the mic guard's toast (ADR-022): the daemon may
                # not ask a question about your microphone that only a pointer can
                # answer. After the two safety gates so a held command keeps first
                # claim on the utterance; before staged, which would swallow it.
                if self._config.audio.voice_answer:
                    answered = self._mic_answer_gate(text, event)
                    if answered is None:
                        return
                    text = answered
                    event["final_text"] = text

                # Staged dictation (#294): bursts land in a review buffer instead of
                # typing, and only a commit types — `scratch that` is already too
                # late once the wrong token is in a terminal. A commit hands back the
                # buffer contents and falls through to the ordinary injection path
                # below, so the no-text-target guard still applies to it.
                if self._config.staged.enabled:
                    staged_text = self._stage_or_commit(text, event)
                    if staged_text is None:
                        return
                    text = staged_text
                    event["final_text"] = text

                # "No text target" guard: if there was no editable field focused, don't
                # type into the wrong place — copy to the clipboard + notify (or warn only).
                with self._lock:
                    target_ok = self._state.target_ok
                if (
                    self._config.injection.target_guard != "off"
                    and target_ok is False
                    and self._handle_no_target(text)
                ):
                    event["discard_reason"] = "no_target"
                    if use_streaming and stream_injector is not None:
                        stream_injector.cancel()
                    return
                if use_streaming:
                    assert stream_injector is not None
                    stream_injector.commit(text)
                else:
                    injector.inject(text)
                self._last_dictation_monotonic = time.monotonic()
                if self._config.revise.enabled:
                    self._ledger.record(text)
                if self._timeline is not None:
                    self._timeline.record(text)
                # Read-Back Loop: speak the final transcript back (dictation only).
                self._maybe_read_back(text)

        except Exception as exc:
            # Recorded for the outcome gauge: nothing reached the window, and
            # `discard_reason` is not set on this path.
            pipeline_failed = True
            log.warning("Pipeline error: %s", exc)
            with self._lock:
                self._state.last_error = str(exc)
            # `INJECT` rather than `TRANSCRIBE` for the fallback wording: this block
            # wraps decode *and* delivery, and of the two, "it heard you and the text
            # went nowhere" is the one the user is looking at. A failure that is
            # recognisable at all is recognised by its own markers regardless.
            from yazses.system.diagnosis import INJECT

            self._report_failure(exc, INJECT)
            if stream_injector is not None:
                try:
                    stream_injector.cancel()
                except Exception:
                    pass
        finally:
            # Every burst passes through here exactly once, whatever became of it, so
            # this is the one place the outcome can be counted without threading a
            # return value through each early return. The per-burst result was always
            # in the log and never summarised -- the same gap #296 closed for decode
            # latency, and the more basic number of the two.
            self._outcomes.record(
                classify_outcome(
                    event.get("discard_reason"), pipeline_failed=pipeline_failed
                )
            )
            # Non-silent capture that produced a transcript means the mic is working:
            # reset the silent streak and remember this device as the auto-heal target.
            #
            # The test is `capture_proved`, not "was it typed". Most discard reasons are
            # set *after* a transcript exists and decide only where the text goes -- an
            # unmatched command, no editable target -- and those prove the microphone
            # works just as well as typing does. Requiring no discard reason at all meant
            # a command-key burst was neither a success nor a discard, so it left the
            # streak standing: measured here, "2 silent clips in a row" spanning an hour
            # that contained three good captures.
            if event.get("raw_text") and capture_proved(event.get("discard_reason")):
                self._note_good_capture()
            if self._corpus is not None and (
                event.get("raw_text") or event.get("discard_reason")
            ):
                cap_audio = clip if self._config.learning.capture_audio else None
                self._corpus.write(event, cap_audio, sample_rate)
            # Edit capture (signal b): for plain dictation, read the editor back
            # shortly and record any in-place correction.
            if (
                self._edit_watcher is not None
                and event.get("injected")
                and event.get("final_text")
                and event.get("intent_type", "dictate") == "dictate"
            ):
                self._edit_watcher.watch(event["final_text"])
            with self._lock:
                self._state.audio_level = 0.0  # recording done — overlay calms down
                if self._state.state in (TrayState.TRANSCRIBING, TrayState.INJECTING):
                    self._state.state = TrayState.IDLE

    def _on_audio_chunk(self, chunk: np.ndarray) -> None:
        """Called from the sounddevice audio thread for each recorded chunk."""
        # Publish the live mic level for the overlay. Same metric as the VAD
        # gate (mean(|samples|), cf. _on_hold_end / system.miclevel), kept cheap
        # because this runs on the audio callback thread.
        if chunk.size:
            with self._lock:
                self._state.audio_level = float(np.abs(chunk).mean())
        if self._streaming_active and self._stream_engine is not None:
            self._stream_engine.push(chunk)

    # ---- Audio-input resilience (device change + silent-streak) -------------

    def _audio_idle(self) -> bool:
        """True when no recording is in flight — safe to poll/reinit the mic."""
        with self._lock:
            return self._state.state == TrayState.IDLE

    def _active_device_name(self) -> str | None:
        """The mic capture would currently use: the pin, else the OS default."""
        pinned = self._config.audio.device
        if pinned:
            return pinned
        try:
            from yazses.audio.devices import current_default_input_name

            return current_default_input_name()
        except Exception:
            return None

    def _mic_actions(self):
        """The [Re-calibrate] [Pin this mic] [Ignore] buttons for a mic toast."""
        from yazses.system.notify import NotifyAction

        return [
            NotifyAction("recalibrate", "Re-calibrate"),
            NotifyAction("pin", "Pin this mic"),
            NotifyAction("ignore", "Ignore"),
        ]

    def _on_mic_action(self, key: str) -> None:
        """Dispatch a clicked notification button (runs on the notifier thread)."""
        if key == "recalibrate":
            self._recalibrate_mic()
        elif key == "pin":
            self._pin_current_mic()
        # "ignore" (and anything else) — no-op.

    def _notify_mic(self, title: str, body: str, *, actions: bool = True) -> None:
        """Fire a desktop notification about the mic; never raises."""
        if actions:
            # Open the spoken-answer window (ADR-022). Only for toasts that actually
            # ask something -- the nine informational ones pass actions=False, and
            # arming "ignore" after a toast with no buttons would be a control word
            # with nothing to control.
            self._mic_prompt.ask(time.time())
        try:
            from yazses.system import notify as notify_mod

            urgency, expire_ms = notify_mod.toast_policy(bool(actions))
            notify_mod.notify(
                title,
                body,
                urgency=urgency,
                expire_ms=expire_ms,
                actions=self._mic_actions() if actions else None,
                on_action=self._on_mic_action if actions else None,
            )
        except Exception:
            log.exception("Mic notification failed")

    def _on_default_device_changed(self, prev: str | None, cur: str | None) -> None:
        """Callback from the DeviceMonitor when the OS default input flips."""
        log.info("Default input device changed: %r -> %r", prev, cur)
        with self._lock:
            self._state.device_changed_at = time.time()
            self._state.input_device = cur
        body = (
            f"Input switched to '{cur}' (was '{prev}').\n"
            "If dictation stops working, re-calibrate or pin your mic:\n"
            "  yazses mic-level --set   ·   yazses audio use <name>"
        )
        self._notify_mic("🎤 Microphone changed", body)

    def _note_silent_discard(self) -> None:
        """Register a silent-discard; auto-heal + notify once a streak forms."""
        streak = self._silent_streak.record_silent()
        with self._lock:
            self._state.silent_streak = streak
        threshold = self._config.audio.silent_streak_threshold
        if not self._silent_streak.should_notify(threshold):
            return
        if self._healed_this_streak:
            return  # already acted for this streak; don't re-fire every clip
        self._healed_this_streak = True

        active = self._active_device_name()
        last_good = self._state.last_good_device
        healed = False
        if (
            self._config.audio.auto_heal_device
            and last_good
            and last_good != active
            and self._recorder is not None
        ):
            # Switch the live recorder back to the last device that produced usable
            # audio. Resolved by name at the next start(), so it survives index shifts.
            self._recorder.device = last_good
            with self._lock:
                self._state.input_device = last_good
            healed = True

        # The guard's only other output is a desktop toast, and a delivered toast
        # leaves nothing behind: `notify.py` logs at INFO *only* when notify-send is
        # unavailable, so on a working desktop this fired silently unless it also had
        # somewhere to heal to -- and it has somewhere only if the microphone has
        # actually changed, which is the rarer half of what the guard catches.
        # `yazses logs` is where the product sends someone whose dictation stopped,
        # and `yazses report` bundles that tail into a bug report; both showed the run
        # of discards with no sign the daemon had noticed. Logged before the notify
        # opt-out below, because `silent_streak_notify = false` is exactly the case
        # where a log line is the only record that can exist.
        log.info(
            "No text from %d burst(s) in a row (device %r, threshold %d) -- %s.",
            streak,
            active,
            threshold,
            f"auto-healed capture to '{last_good}' (last-good)"
            if healed
            else "no different last-good device to switch to",
        )

        if not self._config.audio.silent_streak_notify:
            return
        # One implementation for every surface. `yazses audio status` used to phrase
        # this fault differently and name no command at all, so the advice `yazses
        # status` sends you to was a dead end.
        from yazses.audio.device_monitor import silent_streak_advice

        headline, remedies = silent_streak_advice(
            streak, active=active, last_good=last_good, healed=healed
        )
        body = "\n".join([headline, *remedies])
        title = "🔇 Mic recovered" if healed else "🔇 Dictation isn't hearing you"
        self._notify_mic(title, body)

    def _note_good_capture(self) -> None:
        """A clip produced usable audio — reset the streak, remember the device."""
        self._silent_streak.record_success()
        # Working dictation is proof the gate is fine; don't retune off stale evidence.
        self._adaptive_vad.observe_speech(0.0)
        self._healed_this_streak = False
        name = getattr(self._recorder, "current_device_name", None)
        with self._lock:
            self._state.silent_streak = 0
            if name:
                self._state.last_good_device = name
                self._state.input_device = name

    def _maybe_retune_threshold(self, current: float) -> None:
        """Lower the silence gate when it is demonstrably swallowing this user's voice.

        The threshold is machine-, room- and voice-dependent, so the shipped default fits
        nobody in particular and a value calibrated once stops fitting as soon as anything
        changes. When it drifts too high the failure is invisible — you speak and nothing
        appears — so it is the one worth healing without being asked. Raising the gate
        stays manual: leaked room noise shows up in the transcript, where the user can see
        it and act.

        Persisted to config.toml so the fix survives a restart, and announced, because a
        setting that changes itself silently is its own kind of unreliability.
        """
        proposed = self._adaptive_vad.suggest(current)
        if proposed is None:
            return
        self._adaptive_vad.reset()
        try:
            from dataclasses import replace

            from yazses.system import miclevel

            miclevel.update_threshold_in_config(
                self._platform.paths.config_file, round(proposed, 5)
            )
            with self._lock:
                self._config = replace(
                    self._config,
                    accessibility=replace(
                        self._config.accessibility, vad_threshold=proposed
                    ),
                )
            log.info(
                "Speech kept falling below the silence gate — lowered vad_threshold "
                "%.4f -> %.4f and saved it. Say something to check.",
                current, proposed,
            )
            self._notify_mic(
                "🎤 Microphone sensitivity adjusted",
                f"Your voice was being treated as silence. The threshold is now "
                f"{proposed:.4f} (was {current:.4f}). Try dictating again.",
                actions=False,
            )
        except Exception:
            log.exception("Adaptive threshold retune failed")

    def _recalibrate_mic(self) -> None:
        """[Re-calibrate] action: measure the active mic and write vad_threshold."""
        try:
            from yazses.system import miclevel

            sr = self._config.audio.sample_rate
            audio = miclevel.record(3.0, sr, device=self._config.audio.device or None)
            stats = miclevel.analyze(audio, sr)
            path = self._platform.paths.config_file
            miclevel.update_threshold_in_config(path, stats.recommended_threshold)
            with self._lock:
                from dataclasses import replace

                self._config = replace(
                    self._config,
                    accessibility=replace(
                        self._config.accessibility,
                        vad_threshold=stats.recommended_threshold,
                    ),
                )
            log.info("Re-calibrated vad_threshold -> %.4f", stats.recommended_threshold)
            self._notify_mic(
                "✅ Mic re-calibrated",
                f"vad_threshold set to {stats.recommended_threshold:.4f}. "
                "Try dictating again.",
                actions=False,
            )
        except Exception:
            log.exception("Re-calibrate action failed")

    def _pin_current_mic(self) -> None:
        """[Pin this mic] action: write [audio] device to the current default."""
        try:
            from yazses.audio.devices import current_default_input_name

            name = current_default_input_name()
            if not name:
                return
            self._apply_pin(name)
        except Exception:
            log.exception("Pin-mic action failed")

    def _apply_pin(self, name: str) -> None:
        """Pin capture to ``name`` (a device-name substring); ``""`` = follow OS default.

        Writes ``[audio] device``, retargets the live recorder, updates config + state,
        and notifies. Shared by the notification [Pin] action and the tray/IPC path so
        pinning takes effect immediately without a restart.
        """
        from dataclasses import replace

        from yazses.system.configedit import set_config_key

        name = (name or "").strip()
        set_config_key(self._platform.paths.config_file, "audio", "device", name)
        if self._recorder is not None:
            self._recorder.device = name or None
        with self._lock:
            self._config = replace(
                self._config, audio=replace(self._config.audio, device=name)
            )
            self._state.input_device = name or None
        if name:
            log.info("Pinned input device: %r", name)
            self._notify_mic(
                "📌 Microphone pinned",
                f"Capture pinned to '{name}'. It won't be stolen by a device change.",
                actions=False,
            )
        else:
            log.info("Unpinned input device — following OS default.")

    def _detect_target_async(self) -> None:
        """Resolve whether there's a text target for this burst, off the hot path."""
        with self._lock:
            self._state.target_ok = None
        detector = self._target_detector
        if detector is None or self._command_mode:
            return  # guard off, or command mode types no text

        def _run() -> None:
            try:
                ok = detector.resolve()
                app_class = detector.get_app_class()
            except Exception:
                ok = None
                app_class = ""
            with self._lock:
                self._state.target_ok = ok
                self._state.app_class = app_class

        threading.Thread(target=_run, name="target-detect", daemon=True).start()

    def _handle_staged(self, request: Request) -> dict[str, object]:
        """`yazses staged status|commit|discard|undo` over IPC.

        Available whether or not staged mode is enabled, so `status` can answer
        honestly instead of erroring, and so text already staged can still be
        committed after the feature is turned off.
        """
        action = str((request.params or {}).get("action") or "status").lower()

        if action == "commit":
            result = self._staged.commit()
            if not result.committed:
                return {"ok": False, "committed": False, "detail": "nothing staged",
                        "pending": self.staged_state()}
            # Same injector the dictation path uses, so the backend, the target
            # guard's absence here, and the failure mode are all the familiar ones.
            injector = self._injector
            if injector is None:
                # Put it back rather than losing what the user dictated.
                self._staged.chunks.append(result.text)
                return {"ok": False, "committed": False, "detail": "no injector available",
                        "pending": self.staged_state()}
            try:
                injector.inject(result.text)
            except Exception as exc:
                self._staged.chunks.append(result.text)
                return {"ok": False, "committed": False, "detail": str(exc),
                        "pending": self.staged_state()}
            self._last_dictation_monotonic = time.monotonic()
            return {"ok": True, "committed": True, "text": result.text,
                    "pending": self.staged_state()}

        if action == "discard":
            dropped = self._staged.discard()
            return {"ok": True, "discarded_words": len(dropped.split()),
                    "pending": self.staged_state()}

        if action == "undo":
            removed = self._staged.undo()
            return {"ok": removed, "pending": self.staged_state()}

        return {"ok": True, "pending": self.staged_state()}

    def staged_state(self) -> dict[str, object]:
        """The buffer as the CLI, the tray and the overlay see it."""
        return {
            "enabled": self._config.staged.enabled,
            "spoken_commit": self._config.staged.spoken_commit,
            "bursts": len([c for c in self._staged.chunks if c.strip()]),
            "words": len(self._staged.text.split()),
            "preview": self._staged.preview(),
            "summary": staged_describe(self._staged),
        }

    def _mic_answer_gate(self, text: str, event: dict) -> str | None:
        """Spoken answer to the mic guard's toast. The text to type, or None.

        Runs **after** the command-safety and check-digit gates and **before**
        staged dictation, and both halves of that are deliberate.

        After the safety gates, because a held `rm -rf` must keep first claim on the
        utterance: putting this first would let "ignore" answer a mic toast while a
        dangerous command sat waiting. It cannot steal their release words either --
        the vocabularies do not overlap -- and if a command *is* held, saying a mic
        answer discards it as an implicit cancel, which is the safe direction.

        Before staged dictation, for the reason ADR-021 gives for the others: the
        staged buffer would swallow the answer as ordinary text.
        """
        from yazses.audio.mic_prompt import match_mic_answer

        now = time.time()
        if not self._mic_prompt.is_open(now, self._config.audio.voice_answer_window_s):
            return text
        answer = match_mic_answer(text)
        if answer is None:
            return text

        self._mic_prompt.close()
        event["mic_answer"] = answer
        log.info("Mic guard: answered %r by voice.", answer)
        try:
            self._on_mic_action(answer)
        except Exception:
            # The answer was still consumed -- typing "re-calibrate" into the user's
            # document because re-calibration failed would be the worse outcome.
            log.exception("Mic guard: spoken action %r failed", answer)
        return None

    def _cmdsafety_gate(self, text: str, event: dict) -> str | None:
        """Command Safety Gate (ADR-v2-065). The text to type, or None when nothing types.

        Three outcomes, in the order they are checked:

        1. **A control word while something is held.** "confirm" releases the held
           command and returns *it* — not the word "confirm", which would type the
           word into the shell instead of running the command. An explicit cancel
           discards it and types nothing.
        2. **Anything else while something is held.** The held command is discarded
           and the new utterance is typed normally. This is deliberate: the
           alternative is a modal state where the daemon ignores everything until the
           magic word is said, and a user who has forgotten the word — or whose
           "confirm" was mis-heard — is stuck with dictation apparently broken. The
           safe direction is losing the dangerous command, never running it by
           accident, so an implicit cancel costs one re-dictation and nothing else.
        3. **Nothing held.** A dangerous command is held and announced; everything
           else passes through untouched.

        The gate never raises into the dictation path — notification is best-effort
        and the text either types or does not.
        """
        from yazses.cmdsafety.classify import assess_command
        from yazses.cmdsafety.spoken import match_control

        control = match_control(
            text,
            self._config.cmdsafety.confirm_words,
            self._config.cmdsafety.cancel_words,
        )

        if self._cmdsafety.pending is not None:
            held = self._cmdsafety.pending
            if control == "confirm":
                released = self._cmdsafety.confirm()
                event["cmdsafety_action"] = "confirm"
                log.info("Command safety: confirmed, running the held command.")
                self._notify_cmdsafety("Confirmed — running the held command.")
                return released
            self._cmdsafety.cancel()
            if control == "cancel":
                event["cmdsafety_action"] = "cancel"
                log.info("Command safety: cancelled the held command.")
                self._notify_cmdsafety("Cancelled — the command was not run.")
                return None
            # Neither word: drop the held command and treat this as ordinary dictation.
            event["cmdsafety_action"] = "implicit_cancel"
            log.info("Command safety: discarded the held command (not confirmed).")
            self._notify_cmdsafety(
                "Discarded the held command — it was not confirmed."
            )
            _ = held  # kept for the log line above; deliberately never injected

        risk = assess_command(text)
        if self._cmdsafety.submit(text) is None:
            event["cmdsafety_action"] = "held"
            event["cmdsafety_reason"] = risk.reason
            log.warning("Command safety: holding a dangerous command (%s).", risk.reason)
            self._notify_cmdsafety(
                f"Held: {risk.reason}. Say “confirm” to run it."
            )
            return None
        return text

    def _checkdigit_gate(self, text: str, event: dict) -> str | None:
        """Checksum-Validated Entry (ADR-021). The text to type, or None when it waits.

        Deliberately narrow, per ADR-021's rule that a confirmation is judged on how
        *rarely* it fires: this only holds an utterance that is a bare number, long
        enough for a checksum to mean anything, and failing every scheme whose length it
        fits. Prose containing a number, a short number, and any number that satisfies an
        applicable checksum all pass through with no comment.

        Reuses the command gate's held-command slot and its confirm word. A second guard
        with a second release phrase would be a second thing to remember at exactly the
        moment the user is already surprised.
        """
        from yazses.checkdigit.guard import check, describe

        # A pending hold is the command gate's to resolve — it owns the confirm word,
        # and re-checking the confirmation utterance here would hold "confirm" itself
        # for failing a checksum it was never a candidate for.
        if self._cmdsafety.pending is not None:
            return text

        result = check(
            text,
            self._config.checkdigit.schemes,
            min_digits=self._config.checkdigit.min_digits,
            want_suggestion=self._config.checkdigit.suggest_fix,
        )
        if not result.failed:
            return text

        self._cmdsafety.hold(text)
        event["checkdigit_action"] = "held"
        event["checkdigit_scheme"] = result.scheme
        if result.suggestion:
            event["checkdigit_suggestion"] = result.suggestion
        log.warning("Check digit: holding a number that fails %s.", result.scheme)
        self._notify_cmdsafety(describe(result))
        return None

    def _notify_cmdsafety(self, message: str) -> None:
        """Say what the gate did. Best-effort; never raises into dictation."""
        log.info("Command safety: %s", message)
        try:
            from yazses.system.notify import notify

            notify("YazSes — command safety", message)
        except Exception:  # pragma: no cover - notification is never load-bearing
            log.debug("Command-safety notification failed", exc_info=True)

    def _stage_or_commit(self, text: str, event: dict) -> str | None:
        """Staged dictation (#294). The text to type, or None when nothing types.

        A spoken commit returns the **buffer contents**, not the utterance that
        triggered it — typing "commit that" into the editor would be an absurd but
        very easy bug. It is returned rather than injected here so the ordinary
        path still applies, including the no-text-target guard, which staged mode
        has no business bypassing. Everything else (staging, undo, discard, an
        empty commit) is terminal and returns None.
        """
        action = staged_classify(text, spoken_commands=self._config.staged.spoken_commit)

        if action is StagedAction.UNDO:
            removed = self._staged.undo()
            event["staged_action"] = "undo"
            self._notify_staged("Removed the last staged burst." if removed
                                else "Nothing staged to remove.")
            return None

        if action is StagedAction.DISCARD:
            self._staged.discard()
            event["staged_action"] = "discard"
            self._notify_staged("Discarded everything pending.")
            return None

        if action is StagedAction.COMMIT:
            result = self._staged.commit()
            event["staged_action"] = "commit"
            if not result.committed:
                # Nothing pending is not the same as typing nothing: say so rather
                # than letting a commit look like it silently failed.
                self._notify_staged("Nothing staged to commit.")
                return None
            return result.text

        # Ordinary dictation: stage it. A runaway buffer is a bug, not a workflow.
        if len(self._staged.chunks) >= max(1, self._config.staged.max_chunks):
            self._notify_staged(
                f"Staged buffer is full ({self._config.staged.max_chunks} bursts) — "
                "commit or discard it."
            )
            event["staged_action"] = "full"
            return None
        self._staged.stage(text)
        event["staged_action"] = "stage"
        event["staged_pending_words"] = len(self._staged.text.split())
        log.info("Staged %d word(s); %d burst(s) pending.",
                 len(text.split()), len(self._staged.chunks))
        return None

    def _notify_staged(self, message: str) -> None:
        """Say what happened to the buffer. Best-effort; never raises into dictation."""
        log.info("Staged: %s", message)
        try:
            from yazses.system.notify import notify

            notify("YazSes", f"{message} {staged_describe(self._staged)}")
        except Exception:
            log.debug("Staged notification failed", exc_info=True)

    def _handle_no_target(self, text: str) -> bool:
        """Handle a dictation with no text target. Returns True if injection was suppressed.

        ``clipboard`` → copy the transcript so it isn't lost, notify, and skip typing.
        ``warn`` → notify but let the caller type as usual. ``off`` never reaches here.
        """
        action = self._config.injection.target_guard
        if action == "clipboard":
            from yazses.system.clipboard import set_clipboard

            copied = set_clipboard(text)
            log.info("No text target -- transcript %s the clipboard.",
                     "copied to" if copied else "could NOT be copied to")
            body = (
                "No text field was focused, so your dictation was copied to the clipboard "
                "— click where you want it and paste (Ctrl+V)."
                if copied
                else "No text field was focused and the clipboard copy failed; "
                "click into a text field and dictate again."
            )
            self._notify_mic("⌨ No place to type", body, actions=False)
            return True
        # "warn" — tell the user but still type (below).
        self._notify_mic(
            "⌨ No text field focused",
            "You may be dictating into the wrong place — click a text field first.",
            actions=False,
        )
        return False

    def _partial_poll_loop(self, stop: threading.Event) -> None:
        """Background thread: drain partial hypotheses and inject them.

        Re-reads ``stop`` immediately before injecting. Hold-release sets it, so
        without this check a partial that arrived while the previous injection
        was still running would be typed *after* the burst had ended. The
        injector's own seal is the real guarantee (this thread cannot win a race
        against ``commit``); this just avoids starting work already known to be
        pointless.
        """
        while not stop.is_set():
            partial = self._stream_engine.get_partial() if self._stream_engine else None
            if partial and partial.text and self._stream_injector is not None and not stop.is_set():
                log.debug("Streaming partial: %r", partial.text)
                try:
                    self._stream_injector.inject_partial(partial.text)
                except Exception as exc:
                    log.warning("Partial inject error: %s", exc)
            # Ghost Ahead: feed the confirmed-prefix stability to the anticipator so
            # a likely endpoint pre-warms the decode path. Harmless; the real commit
            # still happens on hold-release.
            if self._endpoint is not None and self._stream_engine is not None:
                silence_s = self._stream_engine.prefix_stable_for_ms() / 1000.0
                self._endpoint_prewarm_tick(self._stream_engine._last_emitted, silence_s)
            stop.wait(timeout=0.05)

    def _endpoint_prewarm_tick(
        self, partial_text: str, silence_s: float, now: float | None = None
    ) -> bool:
        """Observe the endpoint signal; pre-warm the decode path on a likely stop.

        Returns whether an endpoint fired. No-op (returns False) when [endpoint] is
        disabled. Pre-warm is harmless — it eagerly decodes the streaming buffer and
        discards the result; the authoritative transcript is unchanged.
        """
        if self._endpoint is None:
            return False
        if now is None:
            now = time.monotonic()
        fired = self._endpoint.observe(partial_text, silence_s, now=now)
        if (
            fired
            and self._config.endpoint.prewarm
            and self._stream_engine is not None
        ):
            try:
                self._stream_engine.prewarm()
            except Exception as exc:
                log.debug("Endpoint pre-warm failed: %s", exc)
        return fired

    def _personal_bias_terms(self) -> list[str]:
        """Corpus-mined biasing terms (Personal Adapter P1, ADR-v2-009).

        Computed once and cached: reads recent corpus transcripts and mines
        frequent personal phrases/words into Whisper biasing terms. Empty unless
        ``[personalize] enabled`` + ``bias_from_corpus`` AND the encrypted learning
        corpus (ADR-012) exists with content. Fully guarded and bounded (last 500
        events) — never breaks or slows dictation beyond the one-time mine.
        """
        if self._personal_bias is not None:
            return self._personal_bias
        self._personal_bias = []  # cache "computed" even if we bail/error
        pc = self._config.personalize
        if not (pc.enabled and pc.bias_from_corpus and self._config.learning.enabled):
            return self._personal_bias
        try:
            from yazses.learning.capture import open_store
            from yazses.personalize.prompt_builder import mine_personal
            store = open_store(self._platform.paths.data_dir)
            try:
                texts = [e.final_text for e in store.events() if e.final_text]
            finally:
                store.close()
            self._personal_bias = mine_personal(
                texts[-500:], max_terms=pc.max_prompt_terms
            )
            if self._personal_bias:
                log.info("Personal Adapter: mined %d biasing term(s) from corpus.",
                         len(self._personal_bias))
        except Exception:
            log.debug("Personal Adapter corpus mining failed; skipping", exc_info=True)
            self._personal_bias = []
        return self._personal_bias

    def _correct_vocabulary(self, text: str, event: dict) -> str:
        """Restore personal-vocabulary words the recogniser mangled (#73).

        Runs after `clean_text` and before command classification, so a mis-heard
        command word ("cubernetties") gets a chance to become the real one before
        the grammar sees it.

        Off unless `[stt] vocab_correction`. Every substitution is logged and
        recorded on the learning event — silently rewriting what someone said is
        the thing this must never do.
        """
        if not text or not getattr(self._config.stt, "vocab_correction", False):
            return text
        try:
            from yazses.postprocess.vocab_correct import correct

            fixed, changes = correct(text, self._vocabulary_terms())
        except Exception:
            log.debug("vocabulary correction failed; leaving text alone", exc_info=True)
            return text
        if changes:
            event["vocab_corrections"] = [(c.heard, c.corrected) for c in changes]
            log.info("Vocabulary correction: %s",
                     ", ".join(f"{c.heard!r}->{c.corrected!r}" for c in changes))
        return fixed

    def _vocabulary_terms(self) -> list:
        """The user's dictionary terms, as a list rather than a prompt string.

        Same sources `_effective_initial_prompt` primes Whisper with, so the two
        paths cannot disagree about what the user's vocabulary is.
        """
        from yazses.stt.vocabulary import APP_NAME
        from yazses.system.vocabulary import load_vocab, vocab_path

        # The coined product name is the one term every install shares, and
        # the one `merge_initial_prompt` always primes — so it belongs here too.
        words = [APP_NAME]
        words += load_vocab(vocab_path(self._platform.paths.config_file.parent))
        raw = os.environ.get("YAZSES_VOCABULARY", "")
        words += [w.strip() for w in raw.split(",") if w.strip()]
        return words

    def _effective_initial_prompt(self) -> str | None:
        """The STT ``initial_prompt``, biased toward the user (Voiceprint Mind P1).

        When ``[personalize] enabled``, the configured ``[stt] initial_prompt`` is
        extended with the user's vocabulary (``YAZSES_VOCABULARY``), so the
        recognizer favours their jargon/proper nouns. Off → the configured prompt.
        """
        from yazses.personalize.prompt_builder import build_prompt
        from yazses.stt.vocabulary import merge_initial_prompt
        from yazses.system.vocabulary import load_vocab, vocab_path

        base = self._config.stt.initial_prompt or ""
        # The user's explicit dictionary (`yazses vocab add`) + YAZSES_VOCABULARY —
        # always applied so hard-to-recognise names are spelled right (independent
        # of [personalize], which gates only the future corpus-mining bias).
        words = load_vocab(vocab_path(self._platform.paths.config_file.parent))
        raw = os.environ.get("YAZSES_VOCABULARY", "")
        words += [t.strip() for t in raw.split(",") if t.strip()]
        mined = self._personal_bias_terms()
        if words or mined:
            base = build_prompt(
                words, mined, existing_prompt=base,
                max_terms=self._config.personalize.max_prompt_terms,
            ) or base
        # v2.0.0 Context-Primed Dictation (ADR-v2-004): transiently fold salient
        # terms from the active window/selection/clipboard into the prompt so
        # domain words are transcribed right. OFF by default; readers are
        # best-effort (bounded timeout, never raise) and nothing is stored. The
        # whole block is guarded so context priming can never break dictation.
        ctx = self._config.context
        if ctx.enabled:
            try:
                from yazses.commands.context import compose_context_prompt
                from yazses.system.context_read import read_sources
                sources = read_sources(
                    ctx.use_window_title, ctx.use_selection, ctx.use_clipboard
                )
                extra = compose_context_prompt(
                    sources,
                    max_terms=ctx.max_terms,
                    use_window_title=ctx.use_window_title,
                    use_selection=ctx.use_selection,
                    use_clipboard=ctx.use_clipboard,
                    use_lsp=False,
                )
                if extra:
                    base = f"{base}. {extra}" if base else extra
            except Exception:
                pass  # context priming is best-effort; never break dictation
        # Always prime the coined app name so Whisper spells "YazSes".
        return merge_initial_prompt(base)

    def _warn_feature_inert(self, feature: str, reason: str | None) -> None:
        """Log once that *feature* is enabled but cannot do anything, and why.

        A no-op when *reason* is None (the feature is working). Best-effort: a
        diagnostic must never interrupt dictation.
        """
        if not reason or feature in self._warned_inert:
            return
        self._warned_inert.add(feature)
        log.warning("[%s] is enabled but inactive: %s.", feature, reason)

    def _maybe_cocktail_gate(self, audio: np.ndarray) -> np.ndarray:
        """Drop non-target-speaker frames before STT (Cocktail Filter P1).

        No-op unless ``[cocktail] enabled`` in ``gate`` mode AND an enrolled
        voiceprint + a speaker embedder are available (else returns *audio*
        unchanged). Never raises — a gate error degrades to passing the audio through.
        """
        cfg = self._config.cocktail
        if (
            not cfg.enabled
            or cfg.mode != "gate"
            or self._embedder is None
            or self._voiceprint is None
        ):
            return audio
        from yazses.audio.personal_vad import gate

        sr = self._config.audio.sample_rate
        target = self._voiceprint
        # Bind the embedder locally: the closure runs per frame, and reading the
        # attribute again would race a concurrent shutdown that clears it.
        embedder = self._embedder

        def embed_frame(frame: np.ndarray) -> np.ndarray:
            return embedder.embed(frame, sr).vector

        try:
            return gate(
                audio, target, embed_frame,
                sample_rate=sr, window_ms=cfg.window_ms, threshold=cfg.target_threshold,
            )
        except Exception as exc:
            log.debug("Cocktail gate error: %s", exc)
            return audio

    def _clean_dictation(self, text: str, event: dict, tone: str = "") -> str:
        """Apply optional LLM cleanup to dictation text; record it in *event*.

        Returns *text* unchanged when cleanup is dormant or its guards reject the
        reformatted output. Never raises — :meth:`LlmCleaner.cleanup` swallows
        backend errors internally.
        """
        if self._cleaner is None:
            return text

        custom_prompt = None
        if tone and tone not in ("verbatim", "default"):
            base_prompt = self._config.filters.disfluency.llm_system_prompt
            # Three documented shapes (docs/how-to/app-profiles.md): a house tone name
            # extends the base prompt, and anything else is taken as a complete custom
            # prompt and replaces it. Replacing is safe because `LlmCleaner`'s guards
            # are output-side — `_length_ratio_ok` and `_tokens_preserved` compare input
            # to output and never read the prompt — so a custom prompt cannot widen what
            # the cleanup pass is allowed to do to the user's words.
            instruction = _TONE_INSTRUCTIONS.get(tone)
            custom_prompt = f"{base_prompt} {instruction}" if instruction else tone

        cleaned = self._cleaner.cleanup(text, custom_prompt)
        if cleaned != text:
            event["llm_cleaned_text"] = cleaned
            event["final_text"] = cleaned
        return cleaned

    def _record_respeak(self) -> str:
        """Record a short window and transcribe it — the respoken Punch-In phrase.

        Bounded by ``[punch_in] record_seconds``. Reuses the daemon's own recorder
        and STT engine; returns the cleaned transcript ("" if nothing usable).
        """
        if self._recorder is None or self._engine is None:
            return ""
        self._recorder.start()
        window = max(0.0, self._config.punch_in.record_seconds)
        if window:
            time.sleep(window)
        audio = self._recorder.stop()
        if audio.size == 0:
            return ""
        text = self._engine.transcribe(audio, self._config.audio.sample_rate)
        return clean_text(text)

    def _handle_punch_in(self, request: Request) -> dict[str, object]:
        """IPC: re-record a phrase and correct the last dictation burst (spec-punch-in)."""
        if not self._config.punch_in.enabled:
            return {"ok": False, "reason": "punch_in disabled in config"}
        with self._lock:
            ready = self._state.ready
        if not ready:
            return {"ok": False, "reason": "daemon still loading; try again in a moment"}
        if not self._ledger.last_text():
            return {"ok": False, "reason": "nothing to correct"}
        respoken = str(request.params.get("respoken", "")) or self._record_respeak()
        if not respoken:
            return {"ok": False, "reason": "no respoken phrase captured"}
        choose = int(request.params.get("choose", 0))
        apply = bool(request.params.get("apply", True))
        return self._apply_punch_in(respoken, choose=choose, apply=apply)

    def _apply_punch_in(
        self, respoken: str, choose: int = 0, apply: bool = True
    ) -> dict[str, object]:
        """Correct the last dictation burst by re-speaking part of it (spec-punch-in).

        Aligns ``respoken`` against the last YazSes-injected burst, deletes that
        burst (backspaces — works in any text field), retypes the corrected text,
        and updates the ledger so a later "scratch that" still works. Returns a
        result dict with ``ok``, ``old``/``new`` text, and the ranked ``candidates``
        so the caller (CLI) can let the user confirm or pick a different span. With
        ``apply=False`` it is a dry run: candidates and the proposed ``new`` text are
        returned but nothing is injected. Never edits when there is no history or
        nothing clears the similarity threshold.
        """
        last = self._ledger.last_text()
        if not last:
            return {"ok": False, "reason": "nothing to correct", "candidates": []}
        corrected, cands = apply_top_candidate(
            last,
            respoken,
            max_candidates=self._config.punch_in.max_candidates,
            min_score=self._config.punch_in.min_score,
            choose=choose,
        )
        cand_view = [
            {"old": c.old_text, "new": c.new_text, "score": round(c.score, 3)}
            for c in cands
        ]
        if corrected is None:
            return {"ok": False, "reason": "no confident match", "candidates": cand_view}
        if not apply:
            return {
                "ok": False, "applied": False, "old": last, "new": corrected,
                "candidates": cand_view,
            }
        injector = self._active_injector()
        injector.inject_backspaces(len(last))
        injector.inject(corrected)
        self._ledger.replace_last(corrected)
        self._last_dictation_monotonic = time.monotonic()
        log.info("Punch-In: corrected %d chars.", len(last))
        return {"ok": True, "applied": True, "old": last, "new": corrected, "candidates": cand_view}

    def _build_window_backend(self, cfg):
        """X11 window backend for voice focus, or None (logged) when impossible.

        `[windowctl] enabled` is checked HERE rather than at the call site, and that
        is the whole gate: `_try_window_focus` already returns False on a None
        backend, so a disabled feature leaves "focus the browser" to be dictated as
        text -- the same path Wayland takes, which is already the tested one.

        It had no gate at all. The daemon called `_try_window_focus` unconditionally
        in command mode, so voice focus ran whether or not the feature was enabled:
        `yazses features disable windowctl` was a no-op, and the catalogue's "Off by
        default" was false. It also cost every user an xdotool probe at startup for a
        feature they had not asked for.
        """
        if not getattr(cfg.windowctl, "enabled", False):
            return None
        try:
            import os

            from yazses.windowctl.focus import build_window_backend

            return build_window_backend(os.environ.get("XDG_SESSION_TYPE", ""))
        except Exception:
            log.debug("window focus backend init failed", exc_info=True)
            return None

    def _try_rewrite(self, phrase: str, event: dict) -> bool:
        """Rewrite the current selection with the local model (#99).

        Returns True when the phrase was a rewrite command, so it is consumed
        rather than typed — including when the rewrite is refused. Typing "make
        this shorter" into the document because the model misbehaved would be the
        worst of both outcomes.

        Dormant unless `[commands] rewrite` and a local model are configured. The
        selection is never destroyed: every failure path leaves it untouched and
        the original is on the clipboard before the model is called.
        """
        if not getattr(self._config.commands, "rewrite", False):
            return False
        try:
            from yazses.commands.rewrite import parse_rewrite
        except Exception:
            return False
        intent = parse_rewrite(phrase)
        if intent is None:
            return False

        event["intent_type"] = "rewrite"
        event["intent_action"] = intent.action
        cleaner = self._cleaner
        if cleaner is None:
            log.warning("Rewrite needs a local model — set [filters.disfluency] "
                        "llm_model and enable llm-cleanup.")
            self._notify_rewrite("Rewrite unavailable",
                                 "No local model is configured, so the selection was left alone.")
            return True

        injector = self._injector
        if injector is None:
            # Same shape as the cleaner guard above: the injector is built during
            # startup, so None here means a rewrite arrived before the daemon was
            # ready. Saying so beats an AttributeError from inside the rewrite.
            log.warning("Rewrite needs the injector, which is not ready yet.")
            self._notify_rewrite("Rewrite unavailable",
                                 "Text injection is not ready yet, so the selection was left alone.")
            return True

        from yazses.rewrite.engine import rewrite_selection
        from yazses.system.clipboard import read_selection, set_clipboard

        outcome = rewrite_selection(
            intent,
            read_selection=read_selection,
            rewrite=lambda instruction, text: cleaner.cleanup(text, custom_prompt=instruction),
            inject=injector.inject,
            save_original=set_clipboard,
            fallback_text=self._ledger.last_text() or "",
        )
        event["rewrite_ok"] = outcome.ok
        event["rewrite_ms"] = round(outcome.elapsed_ms, 1)
        if not outcome.ok:
            self._notify_rewrite("Selection left unchanged", outcome.message)
        return True

    def _notify_rewrite(self, title: str, body: str) -> None:
        try:
            from yazses.system.notify import notify

            notify(title, body)
        except Exception:
            log.debug("rewrite notification failed", exc_info=True)

    def _try_window_focus(self, phrase: str, event: dict) -> bool:
        """Focus a window the user named out loud ("focus the browser", #39).

        Returns True when the phrase was a focus command, so it is consumed
        rather than typed. A command that matched nothing is still consumed —
        typing "focus the browser" into the document because no window matched
        would be a worse outcome than doing nothing.

        X11 only: Wayland forbids one client focusing another's window, so the
        backend is None there and this returns False, leaving the words to be
        dictated normally. `yazses doctor` explains why.
        """
        try:
            from yazses.windowctl.focus import focus_by_name, parse_focus_command
        except Exception:
            return False
        target = parse_focus_command(phrase)
        if target is None:
            return False
        backend = self._window_backend
        if backend is None:
            return False
        event["intent_type"] = "window_focus"
        event["intent_action"] = target
        window = focus_by_name(target, backend)
        if window is None:
            event["discard_reason"] = "window_focus_no_match"
            log.info("Voice focus: no unambiguous window matches %r.", target)
            try:
                from yazses.system.notify import notify

                notify("No window matched",
                       f"Nothing was focused for {target!r}. Say part of the "
                       "window title, or check `yazses doctor`.")
            except Exception:
                log.debug("focus notification failed", exc_info=True)
            return True
        log.info("Voice focus: activated %r (%s).", window.title, window.id)
        return True

    def _try_deixis(self, phrase: str, event: dict) -> bool:
        """Act on a gaze-deixis command ("close this", "focus that").

        Returns True when the phrase was a deixis command (consumed either way,
        so it is never typed literally). Destructive actions on a gaze-routed
        target are confirm-gated via an actionable toast per
        ``[gaze] confirm_destructive`` (ADR-v2-010 ``needs_confirm``).
        """
        targeter = self._gaze_targeter
        if targeter is None:
            return False
        try:
            from yazses.gaze.deixis import parse_deixis, requires_confirm
        except Exception:
            return False
        intent = parse_deixis(phrase)
        if intent is None:
            return False
        event["intent_type"] = "deixis"
        event["intent_action"] = intent.action
        decision = getattr(targeter, "last_decision", None)
        if decision is None or decision.target is None:
            event["discard_reason"] = "deixis_no_target"
            log.info("Deixis %r: no window target from gaze; ignoring.", intent.action)
            return True
        if requires_confirm(intent, decision, self._config.gaze.confirm_destructive):
            self._confirm_deixis(intent, decision)
            return True
        try:
            done = targeter.window_action(intent.action, decision.target)
        except Exception as exc:
            log.warning("Deixis %r on window %s failed: %s",
                        intent.action, decision.target, exc)
            return True
        if done:
            log.info("Deixis: %s window %s (%s).", intent.action, decision.target,
                     "gaze-routed" if decision.used_gaze else "focused fallback")
        else:
            log.info("Deixis %r unsupported by the desktop backend; ignored.",
                     intent.action)
        return True

    def _confirm_deixis(self, intent, decision) -> None:
        """Confirm a destructive gaze-routed action via an actionable toast.

        Coarse webcam gaze can pick the wrong window, so "close this" on a
        gaze-routed target asks first. Without actionable-notification support
        the window is left untouched (the honest degradation), and the plain
        toast says so.
        """
        from yazses.system.notify import NotifyAction, notify

        targeter = self._gaze_targeter
        target = decision.target
        actions = [
            NotifyAction("do", f"{intent.action.capitalize()} it"),
            NotifyAction("cancel", "Keep it"),
        ]

        def on_action(key: str) -> None:
            if key != "do" or targeter is None:
                return
            try:
                targeter.window_action(intent.action, target)
                log.info("Deixis confirmed: %s window %s.", intent.action, target)
            except Exception as exc:
                log.warning("Confirmed deixis %r failed: %s", intent.action, exc)

        notify(
            f"{intent.action.capitalize()} the window you looked at?",
            "Gaze picked the target — confirm with the button. Without buttons "
            "the window stays untouched (set [gaze] confirm_destructive=false "
            "to skip confirmation).",
            actions=actions,
            on_action=on_action,
        )

    def _try_spoken_edit(self, phrase: str, event: dict) -> bool:
        """Apply an open-ended voice edit to the last dictation (ADR-v2-003).

        Returns True if the phrase was an edit command (so the caller returns
        without typing it literally). Reuses the Punch-In delete-and-retype
        mechanism + ledger. Non-destructive ops (replace, recase) apply
        immediately; destructive ops (delete) apply only when
        ``[commands] spoken_edit_destructive`` is on (and then remain undoable via
        "scratch that", since the ledger is updated) — otherwise they are
        recognised but skipped, never typed literally. Guarded so it can never
        break dictation.
        """
        try:
            from yazses.commands.edit_ops import DESTRUCTIVE, apply_edit, parse_edit
            parsed = parse_edit(phrase)
            if parsed is None:
                return False
            op = parsed[0]
            if op in DESTRUCTIVE and not self._config.commands.spoken_edit_destructive:
                event["intent_type"] = "spoken_edit_skipped"
                log.info("Spoken Edit: destructive op '%s' skipped; enable "
                         "[commands] spoken_edit_destructive to allow it "
                         "(undo with 'scratch that').", op)
                return True
            last = self._ledger.last_text()
            if not last:
                return False
            result = apply_edit(last, phrase)
            if not result.changed:
                return False
            injector = self._active_injector()
            injector.inject_backspaces(len(last))
            injector.inject(result.text)
            self._ledger.replace_last(result.text)
            self._last_dictation_monotonic = time.monotonic()
            event["intent_type"] = "spoken_edit"
            event["spoken_edit_op"] = op
            log.info("Spoken Edit: %s applied (%d -> %d chars).",
                     op, len(last), len(result.text))
            return True
        except Exception:
            log.debug("Spoken Edit failed; ignoring", exc_info=True)
            return False

    def _scratch_pad(self):
        """The ambient-scratch note store (ADR-v2-005), rooted in the data dir."""
        from yazses.recall.scratch import ScratchPad
        return ScratchPad(self._platform.paths.data_dir / "scratch.jsonl")

    def _try_scratch(self, phrase: str, event: dict) -> bool:
        """Capture a spoken note-to-self to the scratch pad (ADR-v2-005).

        Returns True if the phrase was a note-to-self (so it is not typed). An empty
        note (bare trigger) is recognised but not stored. Guarded — never breaks.
        """
        try:
            from yazses.recall.scratch import parse_scratch
            note = parse_scratch(phrase)
            if note is None:
                return False
            if note:
                self._scratch_pad().add(note, time.time())
                event["intent_type"] = "scratch_note"
                log.info("Ambient Scratch: captured a %d-char note.", len(note))
            return True
        except Exception:
            log.debug("Ambient Scratch failed; ignoring", exc_info=True)
            return False

    def _handle_recall(self, request: Request) -> dict[str, object]:
        """IPC: query past dictations from the corpus (Spoken Recall, ADR-v2-005)."""
        if not self._config.recall.enabled:
            return {"ok": False, "reason": "recall disabled — set [recall] enabled = true"}
        if not self._config.learning.enabled:
            return {"ok": False, "reason": "learning corpus disabled — set [learning] enabled = true"}
        query = str(request.params.get("query", "")).strip()
        try:
            from yazses.learning.capture import open_store
            from yazses.recall.query import rank_events
            store = open_store(self._platform.paths.data_dir)
            try:
                records = [(e.final_text, e.ts) for e in store.events() if e.final_text]
            finally:
                store.close()
            hits = rank_events(records, query, limit=self._config.recall.max_hits)
            return {
                "ok": True, "query": query,
                "hits": [{"text": h.text, "ts": h.ts, "score": h.score} for h in hits],
            }
        except Exception as exc:
            return {"ok": False, "reason": f"recall failed: {exc}"}

    def _handle_scratch(self, request: Request) -> dict[str, object]:
        """IPC: list or clear ambient-scratch notes (ADR-v2-005)."""
        action = str(request.params.get("action", "list"))
        try:
            pad = self._scratch_pad()
            if action == "clear":
                return {"ok": True, "cleared": pad.clear()}
            notes = pad.list()
            return {"ok": True, "notes": [{"text": n.text, "ts": n.ts} for n in notes]}
        except Exception as exc:
            return {"ok": False, "reason": f"scratch failed: {exc}"}

    # ---- Meeting Mode (ADR-v2-127) ----------------------------------------

    def _handle_meeting_start(self, _request: Request) -> dict[str, object]:
        """IPC: begin a hands-free meeting recording. Streams a live transcript."""
        cfg = self._config.meeting
        if not cfg.enabled:
            return {"ok": False, "reason": "meeting mode is off; run `yazses features enable meeting`"}
        with self._lock:
            if not self._state.ready or self._engine is None:
                return {"ok": False, "reason": "daemon still loading; try again in a moment"}
            if self._meeting_controller is not None:
                return {"ok": False, "reason": "a meeting is already running; `yazses meeting stop` first"}
            if self._state.state not in (TrayState.IDLE, TrayState.PAUSED):
                return {"ok": False, "reason": f"busy ({self._state.state.value})"}
            try:
                from yazses.meeting import store
                from yazses.meeting.controller import MeetingController
                from yazses.meeting.vad import build_is_silent
                from yazses.recimport.factory import build_diarizer

                meeting_id = time.strftime("%Y%m%d-%H%M%S")
                meeting_dir = store.new_meeting(cfg, meeting_id)
                sr = self._config.audio.sample_rate
                acc = self._config.accessibility
                controller = MeetingController(
                    cfg, meeting_dir, meeting_id,
                    engine=self._engine,
                    is_silent=build_is_silent(cfg, acc),
                    embedder=self._embedder,
                    voiceprint=self._voiceprint,
                    participants=self._load_meeting_participants(),
                    diarizer=build_diarizer(cfg),
                    sample_rate=sr,
                    started_at=time.monotonic(),
                    clock=time.monotonic,
                    max_seconds=cfg.max_minutes * 60,
                    on_auto_stop=self._auto_stop_meeting,
                )
                recorder = AudioRecorder(
                    sample_rate=sr,
                    max_seconds=0,  # controller owns the cap (finalizes, no silent drop)
                    on_chunk=controller.feed,
                    accumulate=False,
                    device=self._config.audio.device or None,
                )
                controller.start()
                recorder.start()
            except Exception as exc:
                log.exception("Meeting start failed")
                # The tray's Start meeting entry shows this reason itself, but the
                # CLI caller and an auto-stop have no such surface — and a meeting
                # that failed to start is exactly the failure someone walks away from.
                from yazses.system.diagnosis import MEETING

                self._report_failure(exc, MEETING)
                return {"ok": False, "reason": f"could not start meeting: {exc}"}
            self._meeting_controller = controller
            self._meeting_recorder = recorder
            self._state.state = TrayState.MEETING
        log.info("Meeting started: %s", meeting_id)
        resp: dict[str, object] = {
            "ok": True, "meeting_id": meeting_id, "dir": str(meeting_dir),
            "live_transcript": cfg.live_transcript,
        }
        if cfg.diarize:
            from yazses.recimport.factory import diarization_status

            diar = diarization_status(cfg)
            # Same advice `yazses meeting status` prints, from one implementation.
            # This used to name both remedies unconditionally, which asks the user to
            # do a step they cannot act on yet — and the CLI's copy named only the
            # wrong one. Two surfaces phrasing one fault differently is the shape.
            from yazses.recimport.factory import diarization_advice

            if advice := diarization_advice(diar):
                resp["warning"] = advice
        return resp

    def _handle_meeting_status(self, _request: Request) -> dict[str, object]:
        """IPC: report the running meeting, or list recent stored meetings."""
        with self._lock:
            controller = self._meeting_controller
            finalizing = self._meeting_finalizing
        # `enabled` is the fact that decides what every other key in this payload
        # means. It is already published on the general `status` payload, because the
        # tray needed it for exactly this reason -- the feature is off by default and
        # no state value can express that -- and it was missing here, on the handler
        # whose whole job is to report Meeting Mode.
        enabled = self._config.meeting.enabled
        if controller is not None:
            return {"ok": True, "enabled": enabled, "active": True,
                    "finalizing": finalizing, **controller.status()}
        try:
            from yazses.meeting import store

            recent = store.list_meetings(self._config.meeting)[:10]
        except Exception:
            recent = []
        from yazses.recimport.factory import diarization_status

        diar = diarization_status(self._config.meeting)
        return {"ok": True, "enabled": enabled, "active": False, "finalizing": finalizing,
                "recent": recent, "diarization": diar}

    def _handle_meeting_stop(self, _request: Request | None) -> dict[str, object]:
        """IPC: stop capture and kick off the batch diarization post-pass.

        The request is unused, so ``_auto_stop_meeting`` reuses this path with None
        when ``max_minutes`` fires — the stop is identical, it just has no caller.
        """
        with self._lock:
            controller = self._meeting_controller
            recorder = self._meeting_recorder
            if controller is None:
                return {"ok": False, "reason": "no meeting is running"}
            self._meeting_controller = None
            self._meeting_recorder = None
            self._meeting_finalizing = True
            self._state.state = TrayState.TRANSCRIBING

        cfg = self._config.meeting
        try:
            if recorder is not None:
                recorder.stop()
            wav_path = controller.stop_capture()
            from yazses.meeting.session import read_wav_mono_f32

            audio = read_wav_mono_f32(wav_path)
        except Exception as exc:
            log.exception("Meeting stop/capture failed")
            with self._lock:
                self._meeting_finalizing = False
                self._state.state = TrayState.IDLE
            return {"ok": False, "reason": f"could not stop meeting: {exc}"}

        def _finalize() -> None:
            # The recording is deleted only *after* the post-pass that consumes it
            # has succeeded. It used to be unlinked immediately after being read
            # into `audio`, which made every failure below unrecoverable: the file
            # was gone, and the only remaining copy was in a `daemon=True` thread
            # that a daemon stop or a shutdown kills without running `finally`.
            # A whole meeting could be lost on the default path, since
            # `retain_audio` is False by default — and `stop` had already told the
            # user `ok: True`. Deleting last turns that into a retry.
            try:
                info = controller.finalize(audio)
                log.info("Meeting finalized: %s (%d speakers)",
                         info["id"], info["num_speakers"])
                if not cfg.retain_audio:
                    try:
                        wav_path.unlink()
                    except OSError:
                        pass
            except Exception:
                log.exception(
                    "Meeting finalize failed — the recording has been KEPT at %s "
                    "so it can be retried; it is not deleted until finalize succeeds",
                    wav_path,
                )
            finally:
                with self._lock:
                    self._meeting_finalizing = False
                    if self._state.state == TrayState.TRANSCRIBING:
                        self._state.state = TrayState.IDLE

        threading.Thread(target=_finalize, name="meeting-finalize", daemon=True).start()
        return {"ok": True, "meeting_id": controller.meeting_id,
                "dir": str(controller.dir), "finalizing": True}

    def _auto_stop_meeting(self) -> None:
        """Auto-stop hook fired from the controller when ``max_minutes`` is reached.

        Runs the normal stop path on a worker thread — the controller invokes this
        from the mic-callback thread, and stopping the mic stream from inside its own
        callback would deadlock PortAudio, so the actual stop is deferred here.
        """
        threading.Thread(
            target=lambda: self._handle_meeting_stop(None),
            name="meeting-autostop", daemon=True,
        ).start()

    def _handle_readback_speak(self, request: Request) -> dict[str, object]:
        """IPC: speak arbitrary text via the TTS backend (`yazses say "..."`)."""
        text = str(request.params.get("text", "")).strip()
        if not text:
            return {"ok": False, "reason": "empty text"}
        if self._tts is None:
            return {"ok": False, "reason": "TTS disabled — set [tts] enabled = true"}
        self._speak_readback(text)
        return {"ok": True, "backend": self._tts.name}

    def _maybe_read_back(self, text: str) -> None:
        """Speak the final dictation transcript back when read-back is enabled.

        Gated by ``[tts] enabled`` (``self._tts`` is None when dormant) and
        ``[accessibility] read_back != "off"``. Very long bursts are truncated to
        ``[tts] max_readback_chars`` (with an ellipsis). Commands are never read
        back — only this dictation path calls it.
        """
        if self._tts is None or self._config.accessibility.read_back == "off":
            return
        rb = text
        cap = self._config.tts.max_readback_chars
        if cap and len(rb) > cap:
            rb = rb[:cap].rstrip() + "…"
        if rb:
            self._speak_readback(rb)

    def _speak_readback(self, text: str) -> None:
        """Enter READBACK and speak *text* on a background thread.

        Runs off the hotkey loop so playback never blocks recording. The recorder
        is push-to-talk, so TTS audio is never auto-captured (echo-loop interlock);
        a hold during playback is treated as barge-in in ``_on_hold_start``.
        """
        if self._tts is None:
            return
        with self._lock:
            self._state.state = TrayState.READBACK
        tts = self._tts

        def _run() -> None:
            try:
                tts.speak(text)
            except Exception as exc:
                log.debug("Read-back error: %s", exc)
            finally:
                with self._lock:
                    if self._state.state == TrayState.READBACK:
                        self._state.state = TrayState.IDLE

        threading.Thread(target=_run, daemon=True, name="readback").start()

    def _active_injector(self) -> InjectorBackend:
        """Return remote injector when remote session is active, else local."""
        with self._lock:
            remote_active = self._state.state == TrayState.REMOTE_ACTIVE
        if remote_active and self._remote_injector is not None:
            return self._remote_injector
        assert self._injector is not None
        return self._injector

    # ---- IPC handlers ------------------------------------------------------

    def _injection_backend_name(self) -> str | None:
        """The concrete injector in use. Wrappers (e.g. LinuxInjector) expose the
        selected primary via ``backend_name`` — prefer it so status/doctor report
        the real backend (ClipboardInjector, YdotoolInjector, …) rather than the
        opaque wrapper class."""
        from yazses.inject.auto import describe_injector

        if self._injector is None:
            return None
        return describe_injector(self._injector)

    def _report_failure(self, error: BaseException | str, where: str) -> object | None:
        """Tell the user what broke and what to do about it. Never raises.

        Every caller of this already logged the failure and set ``last_error``. Both
        are invisible: the log needs `yazses logs`, and ``last_error`` reaches only
        `yazses status` — the tray does not colour on it, so a microphone that will
        not open leaves the badge **idle blue** while nothing is typed. This is the
        only path on which the person holding the key finds out.

        Rate-limited by diagnosis slug: a broken microphone fails on every burst, and
        five identical toasts teach the user to dismiss YazSes notifications, which
        costs more than the suppressed repeats. Returns the ``Diagnosis`` when one was
        shown and None when it was suppressed, so callers (and tests) can tell the two
        apart.

        Wrapped whole, because it runs from the audio and hotkey threads on paths that
        are *already* handling a failure — an exception here would replace a fixable
        problem with an unfixable one.
        """
        try:
            from yazses.system import notify as notify_mod
            from yazses.system.diagnosis import diagnose, should_notify

            found = diagnose(error, where=where)
            with self._lock:
                fresh = should_notify(found.slug, time.monotonic(), self._diagnosed_at)
            if not fresh:
                return None

            # ADR-v2-132 asks whether the report offer should wait for a *repeated*
            # fault. The better rule falls out of the diagnosis itself: offer it only
            # when YazSes could not identify the failure. A recognised one already
            # carries the command that fixes it, and an issue about a missing ydotool
            # helps nobody -- least of all the person who now has two things to do.
            actions = None
            if found.slug.startswith("unknown-"):
                actions = [notify_mod.NotifyAction("report", "Prepare a bug report")]

            # A named function, not a lambda with a default argument: `notify` declares
            # `on_action: Callable[[str], None] | None`, and the two-parameter lambda
            # neither matched that signature nor gave mypy a type to infer. `found` is
            # closed over rather than bound as a default -- there is exactly one call
            # here and it happens before the loop variable can change.
            diagnosis = found

            def _on_action(key: str) -> None:
                if key == "report":
                    self._prepare_bug_report(diagnosis)

            # A recognised fault carries no button, so there is nothing to answer and no
            # reason for it to outlive its own relevance -- it clears itself. Only the
            # unrecognised one, which offers to prepare a report, stays until you decide.
            urgency, expire_ms = notify_mod.toast_policy(bool(actions))
            notify_mod.notify(
                found.title,
                found.body,
                urgency=urgency,
                expire_ms=expire_ms,
                actions=actions,
                on_action=_on_action,
            )
            return found
        except Exception:  # noqa: BLE001 - never mask the failure being reported
            log.debug("Could not report a failure to the user", exc_info=True)
            return None

    def _prepare_bug_report(self, diagnosis) -> bool:
        """Open GitHub's issue form, pre-filled. Sends nothing. Never raises.

        ADR-v2-132 option (b). **YazSes makes no request** — the browser does, to a page
        the user then reads and submits from their own account. So this adds no entry to
        ADR-019's egress inventory, and `tests/test_egress_inventory.py` should keep
        passing untouched; if it ever needed editing for this, the implementation went
        wrong.

        The body is assembled by the same `report.collect` the `yazses report` command
        uses, so redaction has one implementation rather than two. Returns whether a
        browser was reached, so a silent failure is distinguishable from a silent
        success — this runs from a toast, where there is nothing else to see.
        """
        try:
            from yazses.system import report as report_mod
            from yazses.system.browser import open_url

            paths = self._platform.paths
            gathered = report_mod.collect(
                config_file=paths.config_file,
                # `daemon.log`, the same name `yazses report` passes. Getting this
                # wrong costs nothing visible: `_log_tail` answers "<no log file>"
                # and the report is filed without the section that explains the bug.
                log_file=paths.log_dir / "daemon.log",
                data_dir=paths.data_dir,
                status=self._handle_status(None),  # type: ignore[arg-type]
            )
            body = report_mod.summarise_for_issue(gathered, diagnosis=diagnosis)
            title = getattr(diagnosis, "title", "YazSes problem report")
            return bool(open_url(report_mod.issue_url(title, body)))
        except Exception:  # noqa: BLE001 - a toast button must never take the daemon down
            log.exception("Could not prepare a bug report")
            return False

    def _queue_notification(self, title: str, body: str) -> None:
        """Hold a toast the daemon cannot show, for the tray to collect.

        Registered with ``system.notify.set_fallback_sink`` at startup, so it only
        ever runs where ``notify-send`` is absent — Windows and macOS. Called from
        the audio and hotkey threads, hence the lock.

        The queue is bounded and drops the OLDEST on overflow: these are status
        messages, so a recent one ("switched back to your USB mic") is worth more
        than the tenth copy of an older one, and an unbounded queue behind a tray
        that has quit would grow for the life of the daemon.
        """
        with self._lock:
            self._pending_notifications.append({"title": title, "body": body})
            if len(self._pending_notifications) > _MAX_PENDING_NOTIFICATIONS:
                del self._pending_notifications[:-_MAX_PENDING_NOTIFICATIONS]

    def _drain_notifications(self) -> list[dict[str, str]]:
        """Take the queued toasts. Caller must hold ``self._lock``."""
        if not self._pending_notifications:
            return []
        pending = self._pending_notifications
        self._pending_notifications = []
        return pending

    def _handle_status(self, _request: Request) -> dict[str, object]:
        with self._lock:
            # Same clock as the stamp in `run()` -- mixing the two yields a
            # difference that is neither.
            uptime = (
                (monotonic_including_suspend() - self._state.started_at)
                if self._state.started_at
                else 0.0
            )
            return {
                "state": self._state.state.value,
                "ready": self._state.ready,
                # The version of the code THIS PROCESS is running, which is not the
                # version of the CLI asking. A daemon keeps running the build it
                # started with until it is restarted, so an upgrade leaves the two
                # disagreeing until `yazses restart` -- and nothing could see that
                # before this field existed.
                "version": _running_version(),
                "model": self._config.stt.model,
                "hotkey": self._resolved_hotkey(),
                "injection_backend": self._injection_backend_name(),
                "last_error": self._state.last_error,
                "uptime_s": round(uptime, 2),
                "platform": self._platform.name,
                "streaming_enabled": self._config.streaming.enabled,
                "commands_enabled": self._config.commands.enabled,
                # Resolved ADR-v2-011 role map; {} when [modality] is off.
                "modality_roles": dict(getattr(self, "_modality_roles", {})),
                "read_back": self._config.accessibility.read_back,
                "tts_backend": self._tts.name if self._tts is not None else None,
                "remote_connected": self._remote_forwarder is not None and self._remote_forwarder.is_connected(),
                # For the voice-activity overlay (yazses-overlay).
                "audio_level": round(self._state.audio_level, 6),
                "vad_threshold": self._config.accessibility.vad_threshold,
                # Audio-input health (device change + silent-streak resilience).
                "input_device": self._state.input_device or self._config.audio.device or None,
                "last_good_device": self._state.last_good_device,
                "silent_streak": self._state.silent_streak,
                # How many consecutive silent clips count as trouble. The tray needs this
                # to colour the icon on the same rule the daemon notifies on, instead of
                # calling a single discarded clip a fault.
                "silent_streak_threshold": self._config.audio.silent_streak_threshold,
                # "No text target" guard: True/False/None for the current burst (drives yellow).
                "target_ok": self._state.target_ok,
                # Command mode: True while the dedicated command key is held (drives purple).
                "command_mode": self._command_mode,
                # Confidence Ink (ADR-v2-001): feature state + last-burst count.
                "confidence_enabled": self._config.confidence.enabled,
                "low_confidence_last": self._last_low_confidence_words,
                # Meeting Mode (ADR-v2-127), for the tray's Start/Stop entries. `state`
                # already says "meeting" while capturing, but two things it cannot say
                # are whether the feature is even on and whether the post-pass is still
                # running -- and both are states in which a click must be refused with a
                # reason rather than silently doing nothing. Finalizing is invisible
                # otherwise: capture has ended, the state is back to IDLE, and the
                # transcript is still being written.
                "meeting_enabled": self._config.meeting.enabled,
                "meeting_active": self._meeting_controller is not None,
                "meeting_finalizing": self._meeting_finalizing,
                # Decode latency over a bounded recent window, per model (#296).
                # Percentiles, not a mean: decode time is right-skewed and it is
                # the slow tail you wait through. The count travels with it so a
                # p95 over six utterances cannot be read as a p95.
                "decode_latency": self._latency.as_dict(),
                "outcomes": self._outcomes.as_dict(),
                # Staged dictation (#294): what is pending review, if anything.
                "staged": self.staged_state(),
                # Toasts the daemon could not show itself (no libnotify — Windows and
                # macOS), handed to the tray to display natively. DRAINED by this
                # read, so each one is delivered once; see _queue_notification.
                "notifications": self._drain_notifications(),
            }

    def _handle_shutdown(self, _request: Request) -> dict[str, bool]:
        threading.Thread(target=self.shutdown, name="ipc-shutdown", daemon=True).start()
        return {"ok": True}

    def _handle_pin_mic(self, request: Request) -> dict[str, object]:
        """Pin capture to a mic by name (empty = follow OS default). Applies live."""
        device = str(request.params.get("device", "")).strip()
        try:
            self._apply_pin(device)
        except Exception as exc:
            log.exception("pin_mic failed")
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "device": device}

    def _handle_recalibrate_mic(self, _request: Request) -> dict[str, object]:
        """Re-measure the active mic and write vad_threshold. Async (records ~3s)."""
        with self._lock:
            busy = self._state.state != TrayState.IDLE
        if busy:
            return {"ok": False, "reason": "busy — try again when idle"}
        threading.Thread(
            target=self._recalibrate_mic, name="tray-recalibrate", daemon=True
        ).start()
        return {"ok": True, "started": True}

    def _handle_inject(self, request: Request) -> dict[str, object]:
        text = str(request.params.get("text", ""))
        if not text:
            return {"ok": False, "reason": "empty text"}
        with self._lock:
            ready = self._state.ready
        if not ready or self._injector is None:
            return {"ok": False, "reason": "daemon still loading; try again in a moment"}
        self._injector.inject(text)
        return {"ok": True, "backend": type(self._injector).__name__}

    def _handle_remote_start(self, request: Request) -> dict[str, object]:
        host = str(request.params.get("host", ""))
        if not host:
            return {"ok": False, "reason": "host is required"}
        port = int(request.params.get("port", self._config.remote.ssh_port))
        key_file = str(request.params.get("key_file", self._config.remote.key_file))

        with self._lock:
            self._state.state = TrayState.REMOTE_SETUP

        def _connect() -> None:
            try:
                fwd = RemoteForwarder(
                    agent_port=self._config.remote.agent_port,
                )
                fwd.connect(host=host, port=port, key_file=key_file)
                proxy = RemoteInjectorProxy(
                    host="127.0.0.1",
                    port=self._config.remote.agent_port,
                )
                with self._lock:
                    self._remote_forwarder = fwd
                    self._remote_injector = proxy
                    self._state.state = TrayState.REMOTE_ACTIVE
                log.info("Remote session active: %s", host)
            except Exception as exc:
                log.error("Remote connect failed: %s", exc)
                with self._lock:
                    self._state.state = TrayState.IDLE
                    self._state.last_error = str(exc)

        threading.Thread(target=_connect, name="remote-connect", daemon=True).start()
        return {"ok": True, "state": "connecting"}

    def _handle_remote_stop(self, _request: Request) -> dict[str, object]:
        with self._lock:
            fwd = self._remote_forwarder
            self._remote_forwarder = None
            self._remote_injector = None
            self._state.state = TrayState.IDLE
        if fwd is not None:
            try:
                fwd.disconnect()
            except Exception as exc:
                log.warning("Remote disconnect raised: %s", exc)
        return {"ok": True}

    def _handle_remote_status(self, _request: Request) -> dict[str, object]:
        with self._lock:
            connected = (
                self._remote_forwarder is not None
                and self._remote_forwarder.is_connected()
            )
            return {
                "connected": connected,
                "state": self._state.state.value,
            }

    def _handle_enroll_start(self, _request: Request) -> dict[str, object]:
        with self._lock:
            if self._state.state not in (TrayState.IDLE, TrayState.PAUSED):
                return {"ok": False, "reason": f"cannot enroll in state {self._state.state.value}"}
            self._state.state = TrayState.ENROLLING

        def _enroll() -> None:
            try:
                from yazses.accessibility.enroll import run_wizard
                run_wizard(config_path=self._platform.paths.config_file)
                # Reload config so the new thresholds take effect
                self._config = load_config(self._platform.paths.config_file)
                if self._padding_buffer is not None:
                    self._padding_buffer = PreSpeechRingBuffer(
                        padding_ms=self._config.accessibility.pre_speech_padding_ms,
                        sample_rate=self._config.audio.sample_rate,
                    )
            except Exception as exc:
                log.error("Enrollment error: %s", exc)
                with self._lock:
                    self._state.last_error = str(exc)
            finally:
                with self._lock:
                    if self._state.state == TrayState.ENROLLING:
                        self._state.state = TrayState.IDLE

        threading.Thread(target=_enroll, name="enroll", daemon=True).start()
        return {"ok": True, "state": "enrolling"}

    def _handle_streaming_enable(self, _request: Request) -> dict[str, object]:
        self._config.streaming.enabled = True
        if self._stream_engine is None and self._engine is not None:
            self._stream_engine = StreamingEngine(
                self._engine,
                self._config.streaming.partial_interval_ms,
            )
        return {"ok": True, "streaming_enabled": True}

    def _handle_streaming_disable(self, _request: Request) -> dict[str, object]:
        self._config.streaming.enabled = False
        return {"ok": True, "streaming_enabled": False}

    def _handle_mark_last_wrong(self, request: Request) -> dict[str, object]:
        if self._corpus is None:
            return {"ok": False, "reason": "learning capture is disabled"}
        params = request.params if isinstance(request.params, dict) else {}
        correction = params.get("correction")
        flagged = self._corpus.mark_last_wrong(correction)
        return {"ok": flagged}

    def _handle_ask_human(self, request: Request) -> dict[str, object]:
        """Ask the user a question out loud on an agent's behalf (ADR-020 §1, §4).

        Lives here rather than in the MCP server because this process owns the
        three things the feature turns on: the microphone, the knowledge of
        whether a hold is in progress, and the injector that must **not** fire —
        the answer travels back to the caller and is never typed into whatever the
        user had open.

        Every refusal is returned as data, never raised: the caller is an agent on
        the other side of a JSON-RPC socket, and it needs the reason to decide
        whether to ask again.
        """
        from yazses.mcp.ask import AskHumanService, Refusal

        params = request.params if isinstance(request.params, dict) else {}
        question = str(params.get("question") or "")
        caller = str(params.get("caller") or "an agent")
        timeout_s = float(params.get("timeout_s") or 30.0)

        service = AskHumanService(
            speaker=self._ask_human_speaker(),
            listener=self._ask_human_listener,
            max_per_hour=self._config.mcp.ask_human_per_hour,
            enabled=self._config.mcp.ask_human,
            # A hold means the user is speaking right now. `_state.state` is the
            # same field the tray reads, so this cannot drift from what the user
            # sees.
            is_holding=lambda: self._state.state == TrayState.RECORDING,
            clock=time.monotonic,
        )
        try:
            return {"ok": True, "answer": service.ask(question, caller=caller, timeout_s=timeout_s)}
        except Refusal as refusal:
            return {
                "ok": False,
                "reason": str(refusal),
                "retry_after_s": refusal.retry_after_s,
                "deferred": refusal.deferred,
            }

    def _ask_human_speaker(self):
        """The TTS backend, or one that raises if speech is unavailable.

        Raising is right: a question the user never heard must not be recorded as
        asked, and `AskHumanService` turns the failure into a refusal that does not
        spend the caller's budget.
        """
        tts = getattr(self, "_tts", None)
        if tts is not None:
            return tts

        class _Unavailable:
            def speak(self, text: str) -> None:
                raise RuntimeError(
                    "no text-to-speech backend is configured "
                    "(`yazses features enable read-back` installs one)"
                )

        return _Unavailable()

    def _ask_human_listener(self, timeout_s: float) -> str:
        """Record one answer and transcribe it, **without touching the injector**.

        Uses the recorder's own start/stop rather than the hold-to-talk path on
        purpose: `_on_hold_end` is where transcription becomes typing, and this
        answer must reach the caller instead. Reusing it would type the user's
        reply into whatever window happened to be focused.

        The recorder is always stopped, including on failure — leaving the stream
        open would hold the microphone against the next real dictation.
        """
        recorder, engine = self._recorder, self._engine
        if recorder is None or engine is None:
            # Both are built during startup. An empty answer is the honest result
            # when there is nothing to record with — the caller already treats ""
            # as "no answer given" and falls back accordingly.
            log.warning("Cannot ask for a spoken answer before capture and STT are ready.")
            return ""

        recorder.start()
        try:
            time.sleep(max(1.0, float(timeout_s)))
        finally:
            audio = recorder.stop()
        if audio is None or not len(audio):
            return ""
        return (engine.transcribe(audio) or "").strip()

    # ---- Signals & helpers -------------------------------------------------

    def _build_macro_context(self) -> MacroContext:
        """Resolve dynamic macro placeholders at injection time.

        date/time reflect the moment of dispatch. Clipboard capture is a P2
        item (left empty in P1), so ``${clipboard}`` resolves to "" for now.
        """
        from datetime import datetime
        now = datetime.now()
        return MacroContext(
            clipboard="",
            date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M"),
            author=self._config.macros.author,
        )

    def _configure_logging(self) -> None:
        level_name = self._config.general.log_level.upper()
        level = logging.getLevelNamesMapping().get(level_name)
        if level is None:
            raise ValueError(f"Invalid log_level in config: {self._config.general.log_level!r}")
        fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
        logging.basicConfig(level=level, format=fmt)

        # Persist a rotating diagnostic log so `yazses start` (detached, stdout
        # to /dev/null) still leaves a record. Metadata only at INFO — the
        # transcript text is logged at DEBUG only, never in the default file.
        from logging.handlers import RotatingFileHandler

        log_dir = self._platform.paths.log_dir
        target = log_dir / "daemon.log"
        # Adding to the root logger is additive and permanent, so a second call
        # writes every line twice and reaches the 1 MB rotation threshold twice as
        # fast -- halving how much history a bug report can carry. Measured: one
        # call gave one handler, two calls gave two, both on the same file.
        root = logging.getLogger()
        for existing in root.handlers:
            if getattr(existing, "baseFilename", None) == str(target.absolute()):
                existing.setLevel(level)
                return
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3)
            handler.setFormatter(logging.Formatter(fmt))
            handler.setLevel(level)
            logging.getLogger().addHandler(handler)
            log.info("Logging to %s", target)
        except OSError as exc:
            log.warning("Could not open log file in %s: %s", log_dir, exc)

    def _install_signal_handlers(self) -> None:
        def _cleanup(_signum: int, _frame: FrameType | None) -> None:
            self.shutdown()

        signal.signal(signal.SIGTERM, _cleanup)
        signal.signal(signal.SIGINT, _cleanup)

    def _resolved_hotkey(self) -> str:
        key = self._config.hotkey.key
        return self._platform.default_hotkey if key == "auto" else key

    def _shutdown(self) -> None:
        # Drop the sink first: it points at this instance, and notify() is module
        # level, so leaving it set would queue toasts onto a dead daemon (and keep
        # it alive) in any process that builds a second one — tests, most of all.
        try:
            from yazses.system.notify import set_fallback_sink

            set_fallback_sink(None)
        except Exception:
            log.debug("clearing the notification sink failed", exc_info=True)
        if self._stream_engine is not None:
            try:
                self._stream_engine.stop()  # join the decode loop before exit
            except Exception:
                log.exception("Streaming engine stop raised")
        if self._device_monitor is not None:
            try:
                self._device_monitor.stop()
            except Exception:
                log.exception("Device monitor stop raised")
        if self._target_detector is not None:
            tracker = getattr(self._target_detector, "_atspi", None)
            if tracker is not None:
                try:
                    tracker.stop()
                except Exception:
                    log.exception("AT-SPI tracker stop raised")
        if self._instance_lock is not None:
            try:
                self._instance_lock.release()
            except Exception:
                log.exception("Instance lock release raised")
        if self._overlay_proc is not None:
            try:
                self._overlay_proc.terminate()
            except Exception:
                log.exception("Overlay terminate raised")
        if self._tray_proc is not None:
            try:
                self._tray_proc.terminate()
            except Exception:
                log.exception("Tray terminate raised")
        if self._edit_watcher is not None:
            try:
                self._edit_watcher.cancel()
            except Exception:
                log.exception("Edit watcher cancel raised")
        if self._gaze_targeter is not None:
            try:
                self._gaze_targeter.close()  # release the camera
            except Exception:
                log.exception("Gaze targeter close raised")
        if self._meeting_recorder is not None:
            try:
                self._meeting_recorder.stop()
                if self._meeting_controller is not None:
                    self._meeting_controller.stop_capture()
            except Exception:
                log.exception("Meeting recorder stop raised")
        if self._corpus is not None:
            try:
                self._corpus.stop()
            except Exception:
                log.exception("Corpus writer stop raised")
        if self._remote_forwarder is not None:
            try:
                self._remote_forwarder.disconnect()
            except Exception:
                log.exception("Remote forwarder disconnect raised")
        if self._ipc_server is not None:
            try:
                self._ipc_server.shutdown()
            except Exception:
                log.exception("IPC server shutdown raised")
        try:
            self._platform.lifecycle.clear_pid()
        except Exception:
            log.exception("Lifecycle clear_pid raised")


def run() -> None:
    """Entry point used by `yazses-daemon` and `python -m yazses.main`."""
    try:
        # First run: seed a config that enables the recommended feature set so a
        # fresh install (snap/pipx/apt) gets the good experience out of the box.
        # No-op once a config exists — never overrides the user's choices.
        from yazses.system.firstrun import ensure_recommended_config

        ensure_recommended_config()
    except Exception:  # noqa: BLE001 — config seeding must never block startup
        pass
    _report_config_problems()
    try:
        Daemon().run()
    except KeyboardInterrupt:
        sys.exit(0)


def _report_config_problems() -> None:
    """Say out loud what was wrong with config.toml, before anything else is logged.

    The config loader repairs what it can and falls back for the rest, so the daemon runs
    either way — but silently running on a value the user did not write is how a config
    drifts for days without anyone noticing. Naming each fault at startup puts it in the
    log the user will read when something feels off, and `yazses doctor` shows the same
    list on demand.
    """
    try:
        from yazses.config import load_config_checked
        from yazses.platform import get_platform

        loaded = load_config_checked(get_platform().paths.config_file)
        if not loaded.problems:
            return
        repaired = sum(1 for p in loaded.problems if p.repaired)
        log.warning(
            "config.toml has %d problem(s) — %d repaired, %d fell back to defaults. "
            "Run `yazses doctor` for the list.",
            len(loaded.problems), repaired, len(loaded.problems) - repaired,
        )
        for problem in loaded.problems:
            log.warning("  config.toml: %s", problem)
    except Exception:  # noqa: BLE001 — diagnostics must never block startup
        pass
