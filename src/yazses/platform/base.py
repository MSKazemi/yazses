"""Platform abstraction layer — Protocols and dataclasses.

Concrete implementations live under platform/{linux,macos,windows}/. The factory
in platform/factory.py picks the right one based on sys.platform.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class UnsupportedPlatformError(RuntimeError):
    """Raised when the current sys.platform has no YazSes backend."""


class PermissionState(str, Enum):
    OK = "ok"
    DENIED = "denied"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class TrayState(str, Enum):
    LOADING = "loading"          # daemon up, model still loading
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    INJECTING = "injecting"
    READBACK = "readback"            # speaking the transcript back via offline TTS
    PAUSED = "paused"
    ERROR = "error"
    REMOTE_SETUP = "remote_setup"    # establishing SSH tunnel
    REMOTE_ACTIVE = "remote_active"  # tunnel up, forwarding voice to remote
    ENROLLING = "enrolling"          # accessibility enrollment wizard running
    MEETING = "meeting"              # hands-free meeting-mode capture in progress


@dataclass(frozen=True)
class TrayModel:
    """Snapshot of daemon state shown in the tray UI."""

    state: TrayState = TrayState.IDLE
    hotkey: str = "auto"
    model: str = "tiny.en"
    last_error: str | None = None
    uptime_s: float = 0.0
    # Audio/target health that colours the tray icon: a live silent-streak (→ red) and
    # whether the current burst has a text target (False → yellow "no place to type").
    silent_streak: int = 0
    target_ok: bool | None = None
    # True while the dedicated command key is held (command mode → purple icon).
    command_mode: bool = False


@dataclass(frozen=True)
class Paths:
    """Platform-specific directory layout. Resolved once at startup."""

    config_dir: Path
    state_dir: Path
    cache_dir: Path
    log_dir: Path
    # Durable per-user data (the learning corpus lives here). Unlike state_dir,
    # which on Linux is the runtime tmpfs and is wiped on reboot, this is a
    # persistent location (~/.local/share/yazses on Linux).
    data_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def pid_file(self) -> Path:
        return self.state_dir / "daemon.pid"

    @property
    def ipc_socket(self) -> Path:
        # On Windows this is reinterpreted as a named-pipe identifier; the
        # path object is just a stable handle.
        return self.state_dir / "daemon.sock"


@runtime_checkable
class HotkeyBackend(Protocol):
    """Detects a configured hold-to-talk key and emits start/end callbacks.

    The HoldDetector is owned by the backend so each platform can apply
    platform-specific logic (e.g. Linux's leaked-character counting under
    monitor-mode evdev). On Mac/Win with non-character modifiers, the leaked
    count is always 0.
    """

    def run(self) -> None:
        """Block, dispatching key events. Called on the daemon's main thread
        (or its runloop thread on macOS)."""

    def stop(self) -> None:
        """Signal run() to exit cleanly."""


@runtime_checkable
class InjectorBackend(Protocol):
    """Types text into the focused application."""

    def inject(self, text: str) -> None: ...

    def inject_backspaces(self, count: int) -> None: ...

    def inject_key_sequence(self, keys: list[str]) -> None:
        """Send a sequence of key combos (e.g. ["ctrl+z"], ["shift+Left"]).

        Each element is a key combo string. Modifiers are separated by '+'.
        Special keys: Return, Left, Right, Up, Down, BackSpace, Tab, Escape.
        Modifier names: ctrl, shift, alt, meta (platform-normalised).
        """
        ...


@runtime_checkable
class LifecycleBackend(Protocol):
    """Owns the daemon process lifecycle and autostart registration."""

    def write_pid(self) -> None: ...

    def clear_pid(self) -> None: ...

    def read_pid(self) -> int | None: ...

    def is_running(self) -> bool: ...

    def start_daemon_detached(self) -> None:
        """Spawn the daemon as a detached child process."""

    def stop_daemon(self, pid: int) -> None:
        """Send a termination signal to the daemon."""

    def install_autostart(self) -> None:
        """Register autostart for the user's session (systemd/launchd/Run key)."""

    def uninstall_autostart(self) -> None: ...

    def is_autostart_installed(self) -> bool: ...


@runtime_checkable
class IpcServer(Protocol):
    """Bidirectional JSON-RPC server bound to a Unix socket or named pipe."""

    def register(self, method: str, handler: Callable[..., Any]) -> None: ...

    def serve_in_thread(self) -> None: ...

    def shutdown(self) -> None: ...


@runtime_checkable
class IpcClient(Protocol):
    """Client for daemon IPC. Used by the CLI and tray."""

    def call(self, method: str, **params: Any) -> Any: ...

    def is_reachable(self) -> bool: ...


@runtime_checkable
class PermissionsBackend(Protocol):
    """Probes OS permissions required for keyboard capture and microphone."""

    def check_keyboard_capture(self) -> PermissionState: ...

    def check_microphone(self) -> PermissionState: ...

    def request_keyboard_capture(self) -> None:
        """May trigger an OS prompt. No-op on platforms without a prompt."""

    def how_to_grant(self) -> str:
        """Actionable user-facing message describing how to grant permissions."""


@runtime_checkable
class TrayBackend(Protocol):
    """Optional tray/menu-bar UI. None on Linux v0; required on Mac/Win MVP."""

    def run(self, on_quit: Callable[[], None]) -> None: ...

    def set_state(self, model: TrayModel) -> None: ...

    def stop(self) -> None: ...


HotkeyFactory = Callable[[str, int, Callable[[int], None], Callable[[], None]], HotkeyBackend]
"""Args: key_id, threshold_ms, on_hold_start(leaked_count), on_hold_end."""

InjectorFactory = Callable[[], InjectorBackend]
IpcServerFactory = Callable[[Path], IpcServer]
IpcClientFactory = Callable[[Path], IpcClient]
TrayFactory = Callable[[], TrayBackend]


@dataclass(frozen=True)
class Platform:
    """Bundle of concrete backends for the current OS."""

    name: str
    default_hotkey: str
    paths: Paths
    permissions: PermissionsBackend
    lifecycle: LifecycleBackend
    hotkey_factory: HotkeyFactory
    injector_factory: InjectorFactory
    ipc_server_factory: IpcServerFactory
    ipc_client_factory: IpcClientFactory
    tray_factory: TrayFactory | None = None
    tray_default_enabled: bool = False
    extras: dict[str, Any] = field(default_factory=dict)
