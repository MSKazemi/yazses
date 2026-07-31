"""Cross-platform daemon orchestrator.

Wires the hotkey backend → audio recorder → STT engine → injector pipeline,
exposes a JSON-RPC IPC server for the CLI and tray, and manages PID/signal
lifecycle. All platform-specific concerns are reached through
:mod:`yazses.platform`.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping

import numpy as np
from dataclasses import dataclass
from types import FrameType

from yazses.audio.device_monitor import DeviceMonitor, SilentStreakTracker
from yazses.audio.padding import PreSpeechRingBuffer
from yazses.audio.recorder import AudioRecorder
from yazses.audio.vad_calibrated import is_silent_calibrated
from yazses.commands.dispatch import dispatch as cmd_dispatch
from yazses.commands.grammar import IntentType, classify
from yazses.commands.macros import MacroContext, build_macro_table
from yazses.commands.revise import DictationLedger, parse_revise
from yazses.config import Config, load_config
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
from yazses.stt.endpoint import EndpointAnticipator
from yazses.tts.factory import build_tts
from yazses.stt.faster_whisper import FasterWhisperEngine
from yazses.stt.filters.disfluency import filter_transcript
from yazses.stt.streaming import StreamingEngine

log = logging.getLogger(__name__)


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
        # Verbatim/autoformat mode (ADR-v2-078): a persistent gate toggled by the
        # spoken commands "dictate verbatim" / "resume formatting". Lazily created on
        # first use when [verbatim] enabled; holds mode across bursts. None = feature off.
        self._verbatim_gate = None
        self._injector: InjectorBackend | None = None
        self._engine: FasterWhisperEngine | None = None
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
        self._edit_watcher = None
        self._cleaner: LlmCleaner | None = None
        # Read-Back Loop TTS backend (None when [tts] disabled — dormant).
        self._tts = None
        # v2 cognitive layer: speaker embedder + enrolled voiceprint (Cocktail Filter).
        # None when [voiceprint]/[cocktail] dormant or unavailable.
        self._embedder = None
        self._voiceprint = None
        # Single-instance lock; prevents a second daemon (detached `yazses start`
        # vs the systemd unit) from grabbing the hotkey and double-injecting.
        self._instance_lock = None
        self._overlay_proc: subprocess.Popen | None = None
        self._tray_proc: subprocess.Popen | None = None
        # Say-Macro table (None when [macros] disabled — feature dormant).
        self._macro_table = build_macro_table(
            self._config, self._platform.paths.config_file.parent
        )
        # Mid-Thought Undo: ledger of injected dictation bursts for "scratch that".
        self._ledger = DictationLedger()
        # Meeting Mode (ADR-v2-127): active controller + its dedicated mic recorder,
        # None when no meeting is running. `_meeting_finalizing` guards the post-pass.
        self._meeting_controller = None
        self._meeting_recorder = None
        self._meeting_finalizing = False
        # Audio-input resilience: count consecutive silent-discards and watch the OS
        # default input device so a mic that silently switches (e.g. a USB-C monitor
        # stealing capture) is auto-healed to the last-good device + notified, instead
        # of dropping speech in silence. Built in _build_pipeline; monitor may be None.
        self._silent_streak = SilentStreakTracker()
        self._device_monitor: DeviceMonitor | None = None
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

        lifecycle = self._platform.lifecycle
        lifecycle.write_pid()
        with self._lock:
            self._state.started_at = time.monotonic()
            self._state.state = TrayState.LOADING
        try:
            # Start IPC FIRST so the tray and CLI see honest state immediately,
            # rather than getting "daemon not reachable" for the 5–10 seconds
            # the model takes to load on first run.
            self._start_ipc_server()
            self._build_pipeline()
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
            # Watch for the OS default input device changing under us.
            if self._device_monitor is not None:
                self._device_monitor.start()
                log.info("Watching for audio-input device changes.")
            self._hotkey.run()
        finally:
            self._shutdown()

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
                [sys.executable, "-m", "yazses.overlay.app"],
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
                [sys.executable, "-m", "yazses.tray.app"],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("Launched system-tray indicator (pid %d).", self._tray_proc.pid)
        except Exception:
            log.exception("Failed to launch tray; continuing without it")

    def shutdown(self) -> None:
        log.info("Shutting down.")
        if self._command_hotkey is not None:
            try:
                self._command_hotkey.stop()
            except Exception:
                log.exception("Command-hotkey stop raised")
        if self._hotkey is not None:
            try:
                self._hotkey.stop()
            except Exception:
                log.exception("Hotkey stop raised")
        # The rest happens in the finally block of run().

    # ---- Build phase -------------------------------------------------------

    def _build_pipeline(self) -> None:
        cfg = self._config
        log.info("Loading STT model %r...", cfg.stt.model)
        self._engine = FasterWhisperEngine(
            model_name=cfg.stt.model,
            device=cfg.stt.device,
            compute_type=cfg.stt.compute_type,
        )

        # [injection] backend selects the Linux injector (type | ydotool |
        # clipboard | wtype | auto). Bridged through the env var that
        # inject.auto.get_injector already honours, so no platform factory
        # signatures change; non-Linux platforms simply ignore it.
        backend = (self._config.injection.backend or "auto").strip().lower()
        if backend and backend != "auto":
            os.environ["YAZSES_INJECTOR"] = backend
        self._injector = self._platform.injector_factory()
        log.info("Injection backend: %s", self._injection_backend_name())

        if cfg.streaming.enabled:
            self._stream_engine = StreamingEngine(
                self._engine._model,
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
        self._gaze_targeter = self._build_gaze_targeter(cfg)

        # Opt-in self-improvement corpus (ADR-012). Dormant unless enabled.
        self._corpus = build_writer(self._platform.paths.data_dir, cfg.learning)

        # True Code-Switch routing (ADR-v2-008). Dormant unless [polyglot] is
        # fully configured with an out-of-band adapter; surface a hint otherwise.
        try:
            from yazses.polyglot.router import PolyglotRouter
            self._polyglot = PolyglotRouter.from_config(cfg.polyglot)
            if self._polyglot.active:
                log.info("Polyglot code-switch routing active (pair %s-%s).",
                         *self._polyglot.pair)
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

    def _build_gaze_targeter(self, cfg):
        """Build the look-to-pane targeter, or None when any piece is missing.

        Requires ``[gaze] enabled`` + ``route_dictation``, a saved calibration,
        an X11 desktop backend (xdotool), and the gaze deps. Any absent → None,
        so dictation simply stays on the focused window.
        """
        if not (cfg.gaze.enabled and cfg.gaze.route_dictation):
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

        # Glance-Type: focus the looked-at window now (while the user is looking
        # at their target) so this burst's injection lands there. Best-effort.
        if self._gaze_targeter is not None:
            try:
                self._gaze_targeter.retarget()
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
            self._poll_thread.join(timeout=1.0)
            self._poll_thread = None

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
                self._note_silent_discard()
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
                from yazses.translate.mode import translation_task
                stt_task = translation_task(self._config.translate)
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
            event["cleaned_text"] = text
            if not text:
                event["discard_reason"] = "empty"
                log.info("Empty transcription -- discarding.")
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
                    if self._config.commands.spoken_edit:
                        if stream_injector is not None:
                            stream_injector.cancel()
                        if self._try_spoken_edit(text, event):
                            return
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
                is_dictation = intent is None or intent.intent == IntentType.DICTATE

            # Mid-Thought Undo: a whole-utterance "scratch that" deletes the last
            # burst YazSes injected (backspaces), instead of typing it literally.
            if is_dictation and self._config.revise.enabled and parse_revise(text):
                if use_streaming and stream_injector is not None:
                    stream_injector.cancel()
                n = self._ledger.scratch_last()
                if n > 0:
                    injector.inject_key_sequence(["BackSpace"] * n)
                event["intent_type"] = "revise"
                event["revise_chars"] = n
                log.info("Mid-thought undo: scratched %d chars.", n)
                return

            # Verbatim/Autoformat mode (ADR-v2-078): the spoken commands "dictate
            # verbatim" / "resume formatting" toggle a persistent gate and type nothing;
            # while verbatim, all formatting transforms are bypassed (literal capture).
            verbatim_active = False
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
                verbatim_active = self._verbatim_gate.is_verbatim()

            if is_dictation:
                text = self._clean_dictation(text, event)
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
                if use_streaming:
                    assert stream_injector is not None
                    stream_injector.commit(text)
                else:
                    injector.inject(text)
                self._last_dictation_monotonic = time.monotonic()
                if self._config.revise.enabled:
                    self._ledger.record(text)
                # Read-Back Loop: speak the final transcript back (dictation only).
                self._maybe_read_back(text)

        except Exception as exc:
            log.warning("Pipeline error: %s", exc)
            with self._lock:
                self._state.last_error = str(exc)
            if stream_injector is not None:
                try:
                    stream_injector.cancel()
                except Exception:
                    pass
        finally:
            # Non-silent capture that produced a transcript means the mic is working:
            # reset the silent streak and remember this device as the auto-heal target.
            if event.get("raw_text") and not event.get("discard_reason"):
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
        try:
            from yazses.system import notify as notify_mod

            notify_mod.notify(
                title,
                body,
                urgency="critical",
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
            log.info("Auto-healed capture: '%s' -> '%s' (last-good).", active, last_good)

        if not self._config.audio.silent_streak_notify:
            return
        if healed:
            body = (
                f"Heard nothing on '{active}' {streak}× in a row.\n"
                f"Switched capture back to '{last_good}' (last worked).\n"
                "Not right? Pin a mic:  yazses audio use <name>"
            )
            self._notify_mic("🔇 Mic recovered", body)
        else:
            body = (
                f"Heard nothing {streak}× in a row — your mic may have changed.\n"
                "Fix it:  yazses mic-level --set   ·   yazses audio devices"
            )
            self._notify_mic("🔇 Dictation isn't hearing you", body)

    def _note_good_capture(self) -> None:
        """A clip produced usable audio — reset the streak, remember the device."""
        self._silent_streak.record_success()
        self._healed_this_streak = False
        name = getattr(self._recorder, "current_device_name", None)
        with self._lock:
            self._state.silent_streak = 0
            if name:
                self._state.last_good_device = name
                self._state.input_device = name

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

    def _partial_poll_loop(self, stop: threading.Event) -> None:
        """Background thread: drain partial hypotheses and inject them."""
        while not stop.is_set():
            partial = self._stream_engine.get_partial() if self._stream_engine else None
            if partial and partial.text and self._stream_injector is not None:
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

        def embed_frame(frame: np.ndarray) -> np.ndarray:
            return self._embedder.embed(frame, sr).vector

        try:
            return gate(
                audio, target, embed_frame,
                sample_rate=sr, window_ms=cfg.window_ms, threshold=cfg.target_threshold,
            )
        except Exception as exc:
            log.debug("Cocktail gate error: %s", exc)
            return audio

    def _clean_dictation(self, text: str, event: dict) -> str:
        """Apply optional LLM cleanup to dictation text; record it in *event*.

        Returns *text* unchanged when cleanup is dormant or its guards reject the
        reformatted output. Never raises — :meth:`LlmCleaner.cleanup` swallows
        backend errors internally.
        """
        if self._cleaner is None:
            return text
        cleaned = self._cleaner.cleanup(text)
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
            if not diar["ready"]:
                miss = "the diarization extra" if not diar["extra_installed"] else "the speaker models"
                resp["warning"] = (
                    f"Speaker labels are on but {miss} are missing — this meeting's "
                    "transcript will not be attributed. Install with `yazses features "
                    "enable meeting` and fetch models via `yazses transcribe --download-models`."
                )
        return resp

    def _handle_meeting_status(self, _request: Request) -> dict[str, object]:
        """IPC: report the running meeting, or list recent stored meetings."""
        with self._lock:
            controller = self._meeting_controller
            finalizing = self._meeting_finalizing
        if controller is not None:
            return {"ok": True, "active": True, "finalizing": finalizing, **controller.status()}
        try:
            from yazses.meeting import store

            recent = store.list_meetings(self._config.meeting)[:10]
        except Exception:
            recent = []
        from yazses.recimport.factory import diarization_status

        diar = diarization_status(self._config.meeting)
        return {"ok": True, "active": False, "finalizing": finalizing,
                "recent": recent, "diarization": diar}

    def _handle_meeting_stop(self, _request: Request) -> dict[str, object]:
        """IPC: stop capture and kick off the batch diarization post-pass."""
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
            if not cfg.retain_audio:
                try:
                    wav_path.unlink()
                except OSError:
                    pass
        except Exception as exc:
            log.exception("Meeting stop/capture failed")
            with self._lock:
                self._meeting_finalizing = False
                self._state.state = TrayState.IDLE
            return {"ok": False, "reason": f"could not stop meeting: {exc}"}

        def _finalize() -> None:
            try:
                info = controller.finalize(audio)
                log.info("Meeting finalized: %s (%d speakers)",
                         info["id"], info["num_speakers"])
            except Exception:
                log.exception("Meeting finalize failed")
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
        if self._injector is None:
            return None
        return getattr(self._injector, "backend_name", None) or type(self._injector).__name__

    def _handle_status(self, _request: Request) -> dict[str, object]:
        with self._lock:
            uptime = (time.monotonic() - self._state.started_at) if self._state.started_at else 0.0
            return {
                "state": self._state.state.value,
                "ready": self._state.ready,
                "model": self._config.stt.model,
                "hotkey": self._resolved_hotkey(),
                "injection_backend": self._injection_backend_name(),
                "last_error": self._state.last_error,
                "uptime_s": round(uptime, 2),
                "platform": self._platform.name,
                "streaming_enabled": self._config.streaming.enabled,
                "commands_enabled": self._config.commands.enabled,
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
                # Confidence Ink (ADR-v2-001): feature state + last-burst count.
                "confidence_enabled": self._config.confidence.enabled,
                "low_confidence_last": self._last_low_confidence_words,
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
                self._engine._model,
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
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                log_dir / "daemon.log", maxBytes=1_000_000, backupCount=3
            )
            handler.setFormatter(logging.Formatter(fmt))
            handler.setLevel(level)
            logging.getLogger().addHandler(handler)
            log.info("Logging to %s", log_dir / "daemon.log")
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
        if self._device_monitor is not None:
            try:
                self._device_monitor.stop()
            except Exception:
                log.exception("Device monitor stop raised")
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
    try:
        Daemon().run()
    except KeyboardInterrupt:
        sys.exit(0)
