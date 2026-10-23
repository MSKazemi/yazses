"""Platform abstraction layer — Protocols and dataclasses.

Concrete implementations live under platform/{linux,macos,windows}/. The factory
in platform/factory.py picks the right one based on sys.platform.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from yazses.cameraperm.contract import CameraPermission
from yazses.pointer.base import PointerSink

if TYPE_CHECKING:
    # Type-only: importing it at module level made every CLI start load the whole `gaze`
    # package (and, through it, `statistics`/`decimal`/`fractions`) for the sake of an annotation.
    from yazses.gaze.clicks import ClickObserver
    from yazses.grounding.contracts import Rect, SemanticCandidate

#: The value each bundle puts in `Platform.name`. These are `sys.platform`
#: strings, not friendly words, and anything that branches on `Platform.name`
#: must compare against one of them -- a comparison written against `"windows"`
#: or `"macos"` matches nothing and silently disables whatever it guards. That
#: is exactly how the "Elevated windows" row in `yazses doctor` came to be
#: unreachable on the only OS it exists for, while `docs/capability-matrix.md`
#: told the reader doctor would report it. They live here, next to `Platform`,
#: so the bundle and its readers cannot drift apart in the first place.
#:
#: BSD declares `sys.platform` itself ("freebsd14", "openbsd7"), so a check for
#: that family is a prefix match against `BSD_PREFIXES`, never an equality test.
LINUX_PLATFORM_NAME = "linux"
MACOS_PLATFORM_NAME = "darwin"
WINDOWS_PLATFORM_NAME = "win32"

#: The BSD `sys.platform` prefixes. This is a *name*, like the three above, and it
#: lives here for the reason they do — so that asking "is this platform a BSD?" does
#: not require importing a platform backend.
#:
#: It used to live in `platform/bsd/__init__.py`, and `system/doctor.py` imported it
#: from there. That module imports the Linux backend at module scope (BSD reuses it
#: wholesale), so a single tuple of strings dragged the entire Linux platform package
#: into `doctor` on every OS. From source that is invisible; inside a PyInstaller
#: macOS bundle, which correctly ships no Linux backend, `yazses doctor` died with
#: `No module named 'yazses.platform.linux'` — a shipped .app that crashed on a
#: documented command, caught only by the bundle smoke test.
BSD_PREFIXES = ("freebsd", "openbsd", "netbsd", "dragonfly")

#: The modifier an OS's own application shortcuts are built on -- undo, copy, paste,
#: save, select all. Ctrl on Linux, Windows and the BSDs; Cmd on macOS, where Ctrl is a
#: different modifier with different meanings (Ctrl+A moves to the start of the line in
#: a Cocoa text field, Ctrl+Up opens Mission Control). `Platform.primary_modifier` holds
#: one of these, and `commands/dispatch.py` picks its keymap from it, so the dispatcher
#: never has to ask which OS it is on.
PRIMARY_MODIFIER_CTRL = "ctrl"
PRIMARY_MODIFIER_CMD = "cmd"


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
    # The microphone actually in use. The daemon has always reported this over IPC,
    # but `TrayModel` had nowhere to put it, so every platform's tooltip rendered a
    # hardcoded "Mic: default" no matter which device was pinned or auto-healed to —
    # wrong precisely when the user is trying to find out why nothing is heard.
    input_device: str | None = None
    # Live input level and the silence gate it is judged against, for the tray's
    # level ring. Both are already published by the daemon for the overlay; the tray
    # needs them because a green "recording" badge says nothing about whether the
    # microphone is actually hearing anything, and that is the difference between
    # "speak now" and "you are speaking into a muted mic".
    audio_level: float = 0.0
    vad_threshold: float = 0.0
    # Meeting Mode, for the tray's Start/Stop entries. `state` covers the capturing
    # half; these cover the two it cannot express — the feature being off, and the
    # post-pass still running after capture ended. None means "this daemon did not say",
    # which `meeting_entries` reads as "assume it works" rather than greying the entry
    # out on an older daemon where it does.
    meeting_enabled: bool | None = None
    meeting_active: bool = False
    meeting_finalizing: bool = False


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
        """Actionable user-facing message describing how to grant permissions.

        This one answers a denied **keyboard capture**. It is the only remedy the
        protocol had, and `doctor` prints it on the keyboard row alone -- which
        left the microphone row with nothing to say on any OS, and on Windows put
        genuinely useful microphone advice behind a check that always answers OK.
        """

    def how_to_grant_microphone(self) -> str:
        """The same, for a microphone the OS is refusing or cannot see.

        Separate from :meth:`how_to_grant` because the two are different panes,
        different commands and, on macOS, different TCC services -- a reader sent
        to Accessibility for a microphone problem is sent to the wrong place.
        """

    def check_camera(self) -> CameraPermission:
        """The camera, for the gaze / face-switch / head-pointer features.

        A fourth grant and a fifth state, and neither is a copy of the microphone
        row. :class:`~yazses.cameraperm.contract.CameraPermission` splits apart
        three things `PermissionState` folds into ``UNKNOWN`` -- "the OS has not
        been asked yet", "there is no camera device", and "this probe could not
        answer" -- because the camera features are opt-in and experimental, so a
        user who turns one on and gets nothing needs to know *which* of those
        three happened before they can do anything about it.

        **An implementation that cannot determine the state returns
        ``NOT_DETERMINED``, never ``GRANTED``.** Camera access is the one grant
        where an optimistic default is indistinguishable from a working feature
        right up until the device is opened, and by then the caller has usually
        already told the user it is on.
        """

    def how_to_grant_camera(self) -> str:
        """How to grant, or why there is nothing to grant, on this OS.

        A separate remedy for the same reason ``how_to_grant_microphone`` is one:
        macOS gates the camera behind its own TCC service and its own pane,
        Windows behind its own privacy page, and Linux behind no per-app gate at
        all -- so one shared sentence would be wrong on at least two of the three.
        """


@runtime_checkable
class TrayBackend(Protocol):
    """Optional tray/menu-bar UI. None on Linux v0; required on Mac/Win MVP."""

    def run(self, on_quit: Callable[[], None]) -> None: ...

    def set_state(self, model: TrayModel) -> None: ...

    def stop(self) -> None: ...

    def notify(self, title: str, body: str) -> None:
        """Show a desktop toast, if this backend can.

        The daemon relays here only where the OS has no libnotify (Windows,
        macOS) — see ``system.notify.set_fallback_sink``. Defaulted to a no-op so
        a backend that cannot toast is silent rather than a crash, and so Linux,
        which already went out through ``notify-send``, does not double-show.
        """


@dataclass(frozen=True)
class HostInfo:
    """What a caller outside the platform layer may know about the OS it is running on.

    Facts, not behaviour: the point is that modules which only need to *describe* the host
    (the eye-control provenance collector, the camera packaging detector) do not read
    ``sys.platform`` themselves -- that is the branch AGENTS.md rule 6 keeps behind this
    layer. Every field is something an OS backend answers differently, and every one is safe
    to print: none identifies a person or a machine (no hostname, no user, no serial).
    """

    #: The OS's ``sys.platform`` string ("linux", "darwin", "win32", "freebsd14", ...), i.e.
    #: the same vocabulary as ``Platform.name`` and the ``*_PLATFORM_NAME`` constants above.
    platform_name: str
    #: A distribution/OS name and version, split so a table can group hosts by name.
    os_name: str
    os_version: str
    #: Installed RAM in GB, or ``None`` where this OS will not say. Never ``0.0``: a machine
    #: with no RAM does not exist, so a zero could only be a failed measurement.
    ram_gb: float | None = None
    #: A desktop-session bucket when the *OS itself* fixes it ("windows", "macos"), else
    #: ``None`` because it depends on the environment (X11 vs Wayland on Linux).
    fixed_session_type: str | None = None
    #: True when the running executable carries an MSIX package identity. Windows only.
    msix_packaged: bool = False


@runtime_checkable
class HostBackend(Protocol):
    """Describes the machine this process runs on. One implementation per OS family."""

    def describe(self) -> HostInfo:
        """Read the host now. May touch ``/etc``, ``/proc`` or the Win32 API; never the
        network, a subprocess, a camera or a microphone, and never an identifier."""
        ...


@runtime_checkable
class FileOpener(Protocol):
    """Opens a file with the user's default application. One implementation per OS family."""

    def open(self, path: str) -> None:
        """Hand *path* to the OS's own "open with the default app" mechanism.

        Raises whatever that mechanism raises (``CalledProcessError``, ``OSError``); the
        caller decides what a failure means. It never picks the application itself.
        """
        ...


@runtime_checkable
class FocusedAppProvider(Protocol):
    """Names the application that has the keyboard focus -- and nothing else about it.

    Read by the editor command profiles (`commands/profiles.py`) when a spoken command is
    dispatched with `[commands] profile = "auto"`, so "delete the last line" sends the
    focused editor's own keys. The answer is an *identifier* only: a bundle id on macOS
    (``com.microsoft.VSCode``), a process image name on Windows (``Code.exe``). Never a
    window title, a document name, a path, or any text on screen -- the same privacy line
    as the click observer, which reports a time and a place and nothing more.
    """

    def app_id(self) -> str:
        """The focused application's identifier now, or ``""`` when it cannot be read.

        Called once per dispatched command, on the daemon's thread: it must be cheap and
        must never raise.
        """
        ...


@dataclass(frozen=True)
class UpdateHandoff:
    """What a detached updater must do once YazSes itself has exited (ADR-027).

    An installer cannot replace files that the process which launched it still holds
    open, so a one-click update is a *hand-off*: YazSes describes the job here, an
    :class:`UpdateLauncher` starts it detached, and YazSes then shuts down. Built by the
    pure planner in ``system/installer_update.py``; carried out by the OS backend.
    """

    #: ``"installer"`` (a verified, downloaded .exe) or ``"package-manager"``
    #: (choco / winget / scoop running the upgrade it already knows).
    kind: str
    #: The program and its arguments. For ``"installer"`` the first element is the
    #: downloaded file, already checked against the release's SHA-256.
    argv: tuple[str, ...]
    #: Run with administrator rights (a UAC prompt): Chocolatey, and an ``"installer"``
    #: for an all-users install. The latter never elevates the downloaded file itself --
    #: the launcher elevates a job that first copies it somewhere only administrators can
    #: write and checks ``sha256`` there (ADR-027).
    elevate: bool
    #: Process ids to wait for before starting, so the files are free to replace.
    wait_pids: tuple[int, ...]
    #: How to start YazSes again afterwards — whether the update succeeded or not.
    relaunch: tuple[str, ...]
    #: Where the detached job writes what it did, and the exit code it got.
    log_file: Path
    result_file: Path
    #: Files to delete once the job has run (the downloaded installer).
    cleanup: tuple[Path, ...] = ()
    #: Capture the program's console output into ``log_file``. Not possible for an
    #: elevated run (Windows does not redirect across a UAC boundary).
    capture_output: bool = False
    #: The SHA-256 the installer was verified against. The detached job checks it once
    #: more immediately before running the file, so the window between "verified" and
    #: "run" (YazSes shutting down) cannot be used to swap it. Empty for package managers,
    #: which verify their own downloads.
    sha256: str = ""


@runtime_checkable
class UpdateLauncher(Protocol):
    """Runs a one-click update after YazSes has exited. One implementation per OS that
    has one; ``Platform.update_launcher`` is ``None`` everywhere else (ADR-027)."""

    def staging_dir(self) -> Path:
        """A per-user directory for the download, the log and the result file."""
        ...

    def native_arch(self) -> str:
        """The machine's own architecture, normalised ("x64", "arm64", ...)."""
        ...

    def relaunch_command(self) -> list[str] | None:
        """argv that starts YazSes again, or ``None`` when that cannot be known."""
        ...

    def install_scope(self) -> str:
        """``"user"`` for a per-user install, ``"machine"`` for an all-users one, or
        ``"unknown"``. ``"user"`` runs the installer unelevated, ``"machine"`` through the
        elevated admin-only-copy job, and ``"unknown"`` gets no one-click at all."""
        ...

    def query_package_manager(self, method: str) -> str | None:
        """What ``method``'s package manager reports about YazSes (its own feed), as
        text for ``installer_update.parse_feed_version``; ``None`` if it cannot be asked."""
        ...

    def hand_off(self, handoff: UpdateHandoff) -> None:
        """Start ``handoff`` detached and return at once. Raises ``OSError`` if it could
        not be started — the caller must then stay running and fall back."""
        ...


#: File name of the pack index CI copies into a frozen bundle's data directory
#: (``_internal/`` on Windows) before the installer is built (ADR-028 §3).
PACK_INDEX_NAME = "yazses-packs-index.json"


@runtime_checkable
class PackRuntime(Protocol):
    """The OS facts the add-on pack loader needs (ADR-028 §2). Nothing under
    ``yazses/packs/`` branches on ``sys.platform``; it asks this instead.

    Obtained with ``platform.factory.get_pack_runtime()``, which imports only this
    backend — the runtime hook runs before ``main`` and must not build a ``Platform``.
    """

    def supported(self) -> bool:
        """True where this OS has a pack loader at all (Windows, Phase 1)."""
        ...

    def is_elevated(self) -> bool:
        """True when this process has administrator rights — **or when that cannot be
        determined**. Packs are user-writable, so loading them elevated would turn a
        same-user file write into elevation; an unknown answer must fail closed."""
        ...

    def add_native_dir(self, path: Path) -> object:
        """Add ``path`` to the native-library search path and return the handle that
        keeps it there. The caller keeps the handle alive for the life of the process:
        closing it removes the directory (``os.add_dll_directory``)."""
        ...

    def embedded_index_path(self) -> Path | None:
        """Where the frozen bundle carries its pack index, or ``None`` when not frozen."""
        ...

    def probe_command(self, name: str, staged: Path) -> list[str] | None:
        """argv that runs ``yazses packs probe <name> --staged <dir>`` in a child of
        this same app, or ``None`` when that cannot be built."""
        ...

    # -- binding a pack to the base's own copy of a shared DLL (ADR-028 M1) -----------
    # Called only for a pack whose pack.json lists ``bind_to_base``, and only on that
    # pack's first use (``yazses.packs.bind``), never at start-up.

    def base_native_candidates(self, name: str) -> list[Path]:
        """Every file named ``name`` (case-insensitive) inside the frozen app's own
        folder. Empty when not frozen or unsupported. Never searches anywhere else."""
        ...

    def load_base_native(self, path: Path) -> tuple[object, str | None]:
        """Load the library at the absolute ``path`` so its module name is in this
        process's loaded-module list; return ``(handle, version or None)``. Raises
        ``OSError`` when it does not load. The caller keeps the handle alive."""
        ...

    def loaded_native_paths(self, name: str) -> list[Path] | None:
        """The file of every loaded module named ``name``, or ``None`` when this cannot
        be determined."""
        ...


@runtime_checkable
class AccessibilityBackend(Protocol):
    """Read the focused window's accessibility tree; act on one node of the last read.

    The producer behind Screen-Grounded Dictation and the Voice Pilot (#164). Linux
    implements it over AT-SPI (`platform/linux/accessibility.py`); macOS (AX) and
    Windows (UI Automation) have no implementation yet, so `Platform.accessibility_factory`
    is ``None`` there and both features stay dormant with a stated reason.

    `snapshot` is ADR-v2-151's ``SemanticSource.snapshot``: it returns *copies*
    (`SemanticCandidate`), never a live node, and its ``entity_id`` values are valid only
    until this same instance's next `snapshot`. `perform` is the one method that changes
    anything on screen, and it acts only on a node of the latest snapshot -- an id from an
    older one, or one the backend does not know, is refused rather than guessed.

    A candidate's ``checked`` is ``True``/``False`` only when the backend read the state
    of a checkable control, and ``None`` otherwise. The Voice Pilot's "check X" and
    "uncheck X" act only when it differs from the asked state, and hold for a spoken
    confirm when it is ``None`` -- so a backend must never report ``False`` for a state
    it merely did not see.
    """

    def snapshot(
        self,
        *,
        window_id: str | None = None,
        region: Rect | None = None,
    ) -> Sequence[SemanticCandidate]:
        """Labelled, showing nodes of the focused window, bounded; empty when unknown."""
        ...

    def perform(self, entity_id: str, action: str) -> bool:
        """Run *action* (a backend action name, or ``"focus"``) on one node. True on success."""
        ...


#: Why `Platform.accessibility_factory` is ``None`` when a backend sets no reason of its
#: own: the OS simply has no accessibility-tree backend yet.
NO_ACCESSIBILITY_BACKEND_REASON = (
    "this OS has no accessibility-tree backend yet (only Linux AT-SPI is implemented), "
    "so nothing on screen can be read or clicked"
)


HotkeyFactory = Callable[[str, int, Callable[[int], None], Callable[[], None]], HotkeyBackend]
"""Args: key_id, threshold_ms, on_hold_start(leaked_count), on_hold_end."""

InjectorFactory = Callable[[], InjectorBackend]
IpcServerFactory = Callable[[Path], IpcServer]
IpcClientFactory = Callable[[Path], IpcClient]
TrayFactory = Callable[[], TrayBackend]

PointerSinkFactory = Callable[[], PointerSink]
"""Builds this platform's pointer output — ADR-v2-146, `design/specs/eye-pointer-output.md`.

A factory rather than an instance, and optional, for two reasons. Pointer permission is
requested only when a pointer consumer is enabled, so nothing may be constructed while
`get_platform()` merely runs; and not every platform has a backend yet, so `None` here is
the honest answer for one that does not rather than a sink that accepts everything and
moves nothing.
"""


AccessibilityFactory = Callable[[], AccessibilityBackend]
"""Builds one accessibility backend (#164). A factory, and optional, for the pointer's
reasons: nothing may touch the accessibility bus while `get_platform()` merely runs, and
each consumer builds its *own* instance so the two never share a snapshot's handle map.
"""


ClickObserverFactory = Callable[[], "ClickObserver"]
"""Builds this platform's desktop click observer for implicit gaze calibration (#397).

A factory, and optional, for the pointer's reasons: a click hook is an input-monitoring
permission, so nothing may be constructed while `get_platform()` merely runs, and no
platform ships one yet. `None` is the honest answer for "not here" -- the daemon says so
and implicit refinement stays dormant, rather than a no-op observer that never delivers a click.
"""

FocusedAppFactory = Callable[[], FocusedAppProvider]
"""Builds this platform's focused-application provider for the editor command profiles.

A factory, and optional, for the pointer's reasons: nothing OS-specific is imported while
`get_platform()` merely runs, and a platform with no provider says so with `None` rather
than one that always answers "". It may raise when the OS facility it needs is missing
(macOS without the AppKit bridge); the message is the reason the daemon logs.
"""

InputBlockProbe = Callable[[], str | None]
"""Says why the focused window will not receive synthetic input, or returns None.

The answer is a short reason slug (Windows: ``"elevated"``). Called once per dictation,
off the hot path. It must be cheap and must never raise; None also covers "cannot tell",
because the guard it feeds must fire only on a specific, checkable signal (ADR-021).
"""


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
    # None where this OS has no pointer backend yet. A consumer must check, not assume:
    # ADR-v2-146 would rather a feature say "no pointer output here" than hand a user a
    # cursor that never moves.
    pointer_factory: PointerSinkFactory | None = None
    # None where this OS/session has no click backend. Linux sets it on an X11 session
    # (`platform/linux/click_observer_x11.py`, #607) and leaves it None on Wayland, where
    # there is no global click stream; #397 shipped the seam and the CI fake.
    click_observer_factory: ClickObserverFactory | None = None
    # Why `click_observer_factory` is None, in a sentence the daemon log, `doctor` and
    # `gaze status` can repeat -- or None when it is not None, or when the platform has
    # simply never had a backend (the generic "no click observer yet" reason then applies).
    click_observer_unavailable_reason: str | None = None
    # None where an update cannot be handed to a detached installer (everything except
    # Windows today). `yazses update` and the tray then keep the manual steps (ADR-027).
    update_launcher: UpdateLauncher | None = None
    # None where this OS/session cannot read an accessibility tree (#164). Linux sets it
    # when a desktop session exists and the AT-SPI bindings are installed; everywhere
    # else Screen-Grounded Dictation and the Voice Pilot stay dormant and say why.
    accessibility_factory: AccessibilityFactory | None = None
    # Why `accessibility_factory` is None, in a sentence the daemon log can repeat -- or
    # None when it is set, or when the OS never had a backend
    # (`NO_ACCESSIBILITY_BACKEND_REASON` then applies).
    accessibility_unavailable_reason: str | None = None
    # Why the focused window will not receive what YazSes types, or None when nothing
    # stops it (or this OS cannot tell). Windows sets it: UIPI drops input into a window
    # running above our integrity level, and SendInput reports success while it does.
    # The "no text target" guard reads it, so the words go to the clipboard instead.
    input_block_probe: InputBlockProbe | None = None
    # Builds the provider that names the focused application (`FocusedAppProvider`), for
    # `[commands] profile = "auto"`. macOS (NSWorkspace) and Windows (the foreground
    # window's process) set it. Linux and the BSDs leave it None on purpose: there the
    # daemon reads the focused application through the text-target guard's detector
    # (AT-SPI, else X11 xdotool), which already existed before this seam did.
    focused_app_factory: FocusedAppFactory | None = None
    # Why `focused_app_factory` is None where a platform knows it cannot have one, in a
    # sentence the daemon log can repeat -- or None when it is set, or when the platform
    # reads the focused application some other way (Linux, above).
    focused_app_unavailable_reason: str | None = None
    # The modifier this OS's application shortcuts use (`PRIMARY_MODIFIER_CTRL` or
    # `PRIMARY_MODIFIER_CMD`). macOS sets Cmd; every other bundle keeps the Ctrl default,
    # which is what keeps their spoken-command keys exactly what they always were.
    primary_modifier: str = PRIMARY_MODIFIER_CTRL
    extras: dict[str, Any] = field(default_factory=dict)
