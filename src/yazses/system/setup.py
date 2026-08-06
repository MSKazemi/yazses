"""`yazses setup` — provision all Linux runtime requirements in one command.

A Python wheel cannot install system libraries, desktop tools, or kernel/group
permissions, so a `pipx`/`uv`/`snap` install is missing the very things that make
dictation work. This module detects the session and computes (then applies) the
exact set of fixes for the three failure classes:

1. `libportaudio2` missing → daemon crashes on start
   (`OSError: PortAudio library not found`).
2. user not in the `input` group → the hold-to-talk hotkey can't be read from
   `/dev/input/event*` (and `ydotoold` can't open `/dev/uinput`).
3. on GNOME/KDE Wayland, keystroke injection needs `ydotool` + a running
   `ydotoold` (Mutter blocks `wtype`'s virtual-keyboard protocol).

The planning half (`build_plan`) is pure and unit-tested; `apply_plan` runs it.
"""

from __future__ import annotations

import ctypes.util
import os
import shutil
import subprocess

# NOTE: `grp` and `pwd` are Unix-only; imported lazily inside the functions that
# use them so this module (and `yazses setup`) stays importable on Windows.
from dataclasses import dataclass, field

# The robust superset of Debian/Ubuntu runtime packages. We install all of them
# so dictation works whether the user logs into X11 or Wayland later; at runtime
# YazSes auto-selects the right backend (inject/auto.py).
APT_PACKAGES = [
    "libportaudio2",  # audio capture (sounddevice) — always required
    "xdotool",        # X11 text injection
    "xclip",          # X11 clipboard fallback
    "wtype",          # Wayland (wlroots) text injection
    "ydotool",        # Wayland (any compositor) injection via /dev/uinput
    "wl-clipboard",   # Wayland clipboard fallback (wl-copy)
]

# Shipped at contrib/ydotoold.service too — kept in sync.
YDOTOOLD_SERVICE = """\
[Unit]
Description=ydotoold — virtual input daemon (required for Wayland keystroke injection)
Documentation=man:ydotoold(8)
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
# Socket at the path ydotool's client looks for by default, owned by the calling
# user so yazses (same user) can connect. /dev/uinput access comes from the
# user's membership in the `input` group.
ExecStart=/usr/bin/ydotoold --socket-path=%t/.ydotool_socket --socket-own=%U:%G
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
"""


@dataclass
class SetupPlan:
    """What `yazses setup` will do, computed from the environment."""

    apt_packages: list[str] = field(default_factory=list)
    add_to_input_group: bool = False
    setup_ydotoold: bool = False
    session: str = "unknown"  # "x11" | "wayland" | "headless"
    notes: list[str] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return not (self.apt_packages or self.add_to_input_group or self.setup_ydotoold)


def _portaudio_present() -> bool:
    return ctypes.util.find_library("portaudio") is not None


def _user_in_input_group(user: str) -> bool:
    """True if *user* is in the `input` group at the system level (/etc/group).

    Uses the group database rather than the live session so it reflects whether
    `usermod` has been run (a fresh login may still be pending).
    """
    import grp
    import pwd
    try:
        if user in grp.getgrnam("input").gr_mem:
            return True
        # primary group is unlikely to be `input`, but check for completeness
        return grp.getgrgid(pwd.getpwnam(user).pw_gid).gr_name == "input"
    except KeyError:
        return False


def detect_session(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    if env.get("WAYLAND_DISPLAY"):
        return "wayland"
    if env.get("DISPLAY"):
        return "x11"
    return "headless"


def build_plan(
    env: dict[str, str] | None = None,
    *,
    which=shutil.which,
    portaudio_present=_portaudio_present,
    user: str | None = None,
    user_in_input_group=_user_in_input_group,
) -> SetupPlan:
    """Compute the provisioning plan for the current machine (pure / testable)."""
    env = os.environ if env is None else env
    user = user or _current_user()
    plan = SetupPlan(session=detect_session(env))

    # 1. Missing apt packages. libportaudio2 has no binary, probe the lib loader;
    #    the rest map 1:1 to a CLI binary of the same name.
    for pkg in APT_PACKAGES:
        if pkg == "libportaudio2":
            if not portaudio_present():
                plan.apt_packages.append(pkg)
        elif pkg == "wl-clipboard":
            if which("wl-copy") is None:
                plan.apt_packages.append(pkg)
        elif which(pkg) is None:
            plan.apt_packages.append(pkg)

    # 2. input group membership (hotkey capture + /dev/uinput for ydotoold).
    if not user_in_input_group(user):
        plan.add_to_input_group = True
        plan.notes.append(
            "You must log out and back in after joining the `input` group "
            "for it to take effect."
        )

    # 3. ydotoold on Wayland — works on every compositor via /dev/uinput, and is
    #    the ONLY option on GNOME/KDE Wayland (wtype is blocked there).
    if plan.session == "wayland":
        plan.setup_ydotoold = True

    return plan


def _current_user() -> str:
    import pwd
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or pwd.getpwuid(os.getuid()).pw_name


def input_group_pending_relogin(user: str | None = None) -> bool:
    """True when *user* is in the `input` group per /etc/group but the CURRENT
    process/session doesn't have it live.

    This is the classic post-`usermod` trap: `getent group input` lists the user,
    yet the running desktop session (and every terminal it spawns, including the
    daemon) started *before* the group change, so `/dev/input/event*` is still
    unreadable. A fresh login (or reboot) is the only fix; a new terminal tab is
    not enough. `sg input -c ...` is a same-session workaround for testing.
    """
    if os.name != "posix":
        return False
    user = user or _current_user()
    if not _user_in_input_group(user):
        return False  # not in the group at all — that's a `yazses setup` problem, not a relogin one
    try:
        import grp
        gid = grp.getgrnam("input").gr_gid
    except (KeyError, ImportError):
        return False
    return gid not in os.getgroups()


def snap_mic_pending(env: dict[str, str] | None = None, *, runner=subprocess.run) -> bool:
    """True when running inside the yazses snap with the microphone (`audio-record`)
    interface not yet connected.

    Strictly-confined snaps can't self-connect interfaces, and `audio-record` is
    not auto-connected by snapd, so a fresh `snap install yazses` has no mic until
    the user runs `snap connect yazses:audio-record`. We surface that as an install
    step instead of letting dictation silently capture nothing. Detected via
    `snapctl is-connected`, which is always available to a snap's own apps.
    """
    env = os.environ if env is None else env
    if env.get("SNAP_NAME") != "yazses":
        return False  # not the snap build — apt/pipx grant mic access directly
    try:
        r = runner(["snapctl", "is-connected", "audio-record"], capture_output=True)
    except (FileNotFoundError, OSError):
        return False
    return getattr(r, "returncode", 0) != 0


def preflight_hints(
    env: dict[str, str] | None = None,
    *,
    plan: SetupPlan | None = None,
    pending_relogin=None,
) -> list[str]:
    """Actionable one-line warnings about unmet runtime prerequisites.

    Called by `yazses start`/`restart` so a missing dependency or a pending
    re-login is surfaced the moment the user starts the daemon — instead of
    silently producing a daemon that can't hear the hotkey. Returns [] when the
    machine is fully provisioned.
    """
    if os.name != "posix":
        return []
    plan = build_plan(env) if plan is None else plan
    pending = input_group_pending_relogin() if pending_relogin is None else pending_relogin
    hints: list[str] = []

    # Snap-only: the microphone interface must be connected once after install.
    if snap_mic_pending(env):
        hints.append(
            "Microphone access isn't granted to the snap yet — dictation can't hear you.\n"
            "  Grant it once:  sudo snap connect yazses:audio-record"
        )

    if plan.apt_packages or plan.add_to_input_group or plan.setup_ydotoold:
        missing = []
        if plan.apt_packages:
            missing.append(f"packages ({', '.join(plan.apt_packages)})")
        if plan.add_to_input_group:
            missing.append("`input` group membership")
        if plan.setup_ydotoold:
            missing.append("ydotoold (Wayland injection)")
        hints.append(
            "Missing prerequisites: " + "; ".join(missing) + ".\n"
            "  Fix everything in one step:  yazses setup"
        )
    elif pending:
        # Fully provisioned, but this session predates the group change: the
        # daemon will start yet the hotkey won't fire until a real re-login.
        hints.append(
            "You're in the `input` group, but this login session started before that\n"
            "  change — so the hotkey can't read the keyboard yet. Log out and back in\n"
            "  (or reboot) to fix it permanently. To test right now without logging out:\n"
            "    sg input -c \"yazses restart\""
        )
    return hints


@dataclass
class ManualStep:
    """A step the user must do themselves — one that a Python process cannot (or
    must not) perform for them: connecting a confined snap interface, a re-login,
    a voice calibration, or starting the daemon. Rendered as an ordered install
    checklist by `yazses setup` (and reusable by first-run / install scripts)."""

    title: str      # short imperative, e.g. "Grant microphone access"
    command: str    # exact command to run, or "" when the step is an action (log out)
    why: str        # one-line reason


def next_steps(
    env: dict[str, str] | None = None,
    *,
    plan: SetupPlan | None = None,
    mic_pending: bool | None = None,
    pending_relogin: bool | None = None,
) -> list[ManualStep]:
    """The ordered list of manual actions the user must complete to finish
    installing — the single source of truth behind the `yazses setup` checklist.

    Order matches the install flow: grant the mic → join `input` → re-login →
    calibrate the voice → start dictating. Steps that don't apply to this machine
    (e.g. the snap mic connect on an apt install) are omitted.
    """
    env = os.environ if env is None else env
    plan = build_plan(env) if plan is None else plan
    mic_pending = snap_mic_pending(env) if mic_pending is None else mic_pending
    pending = input_group_pending_relogin() if pending_relogin is None else pending_relogin

    steps: list[ManualStep] = []

    # 1. Connect the microphone (snap only — confinement blocks self-connect).
    if mic_pending:
        steps.append(ManualStep(
            "Grant microphone access (connect your voice)",
            "sudo snap connect yazses:audio-record",
            "the strictly-confined snap can't hear you until this interface is connected.",
        ))

    # 2. Join the `input` group if not a member yet.
    if plan.add_to_input_group:
        steps.append(ManualStep(
            "Join the `input` group",
            "sudo usermod -aG input $USER",
            "needed to read the hold-to-talk hotkey and to inject keystrokes.",
        ))

    # 3. Re-login when membership won't be live until a fresh session (either we
    #    just added the user, or /etc/group lists them but this session predates it).
    if plan.add_to_input_group or pending:
        steps.append(ManualStep(
            "Log out and back in (or reboot)",
            "",
            "so the `input`-group change takes effect — a new terminal tab is not enough.",
        ))

    # 4. Calibrate the mic to the user's voice ("connect to voice"). Always worth
    #    doing on a fresh install so quiet speech isn't dropped by the VAD gate.
    steps.append(ManualStep(
        "Calibrate the mic to your voice",
        "yazses mic-level --set",
        "measures your speaking level and sets the VAD threshold so words aren't dropped.",
    ))

    # 5. Start dictating.
    steps.append(ManualStep(
        "Start dictating",
        "yazses start",
        "starts the daemon — then hold the hotkey, speak, and release to type anywhere.",
    ))

    return steps


def _has_apt() -> bool:
    return shutil.which("apt-get") is not None


def ydotoold_service_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "systemd", "user", "ydotoold.service")


def write_ydotoold_service() -> str:
    path = ydotoold_service_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(YDOTOOLD_SERVICE)
    return path


def apply_plan(plan: SetupPlan, *, runner=subprocess.run, echo=print) -> bool:
    """Execute *plan*. Returns True on success. Best-effort, idempotent."""
    if plan.is_noop:
        echo("All Linux requirements already satisfied — nothing to do.")
        return True

    ok = True

    if plan.apt_packages:
        if _has_apt():
            echo(f"Installing system packages: {' '.join(plan.apt_packages)}")
            runner(["sudo", "apt-get", "update", "-qq"], check=False)
            r = runner(["sudo", "apt-get", "install", "-y", *plan.apt_packages], check=False)
            if getattr(r, "returncode", 0) != 0:
                ok = False
                echo("  warning: some packages failed to install — see output above.")
        else:
            ok = False
            echo(
                "No apt-get found. Install these with your package manager:\n  "
                + " ".join(plan.apt_packages)
            )

    if plan.add_to_input_group:
        user = _current_user()
        echo(f"Adding {user} to the `input` group (keyboard + uinput access)...")
        r = runner(["sudo", "usermod", "-aG", "input", user], check=False)
        if getattr(r, "returncode", 0) != 0:
            ok = False
            echo("  warning: usermod failed.")

    if plan.setup_ydotoold:
        path = write_ydotoold_service()
        echo(f"Configured ydotoold user service: {path}")
        runner(["systemctl", "--user", "daemon-reload"], check=False)
        r = runner(["systemctl", "--user", "enable", "--now", "ydotoold.service"], check=False)
        if getattr(r, "returncode", 0) != 0:
            echo(
                "  note: could not start ydotoold now (likely needs a fresh login "
                "for `input`-group access to /dev/uinput). It will start on next login."
            )

    for note in plan.notes:
        echo(f"! {note}")

    return ok
