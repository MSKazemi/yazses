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
from collections.abc import Mapping
from dataclasses import dataclass, field

from yazses.system.snap import in_strict_snap

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
    # True inside a strictly confined snap, where every lever below belongs to
    # snapd rather than to us. Carried separately from `is_noop` because "there
    # is nothing I am allowed to do" and "this machine is already provisioned"
    # are opposite facts that would otherwise print the same reassuring line.
    confined: bool = False

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


def detect_session(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    if env.get("WAYLAND_DISPLAY"):
        return "wayland"
    if env.get("DISPLAY"):
        return "x11"
    return "headless"


def build_plan(
    env: Mapping[str, str] | None = None,
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

    # 0. Strict snap confinement invalidates all three fixes below, so the honest
    #    plan is an empty one plus the reason.
    #
    #    * `sudo` cannot be exec'd at all — AppArmor denies it, which is the
    #      `PermissionError: [Errno 13] Permission denied: 'sudo'` a real install
    #      hit on Ubuntu;
    #    * the package manager is not in the snap's mount namespace, and neither
    #      is the host's /usr/bin — so `which` here answers about the snap's own
    #      read-only payload, never about the machine, and a host install would
    #      not be visible to us even if we could perform one;
    #    * `/dev/input` is gated by snapd, not by the `input` group. Proposing
    #      `usermod -aG input` sends the user round a loop that cannot succeed
    #      (issue #44) — the loop `system/snap.py` was written to eliminate, and
    #      which this planner reintroduced by never asking it.
    #
    #    Classic/devmode snaps are deliberately excluded: they have the host
    #    filesystem and no sandbox, so the ordinary plan is correct there.
    if in_strict_snap(env):
        plan.confined = True
        plan.notes.append(
            "This is a strictly confined snap, so `yazses setup` cannot provision "
            "this machine: it has no package manager, cannot run `sudo`, and cannot "
            "grant itself device access."
        )
        plan.notes.append(
            "What the snap needs instead is its interfaces connected — see the "
            "checklist below. Joining the `input` group cannot grant the hotkey "
            "inside confinement, so `yazses setup` no longer suggests it."
        )
        return plan

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
    """The login name to provision for. **Total** -- it never raises.

    The last resort used to be `pwd.getpwuid(os.getuid()).pw_name`, which raises
    `KeyError` when the running uid has no `/etc/passwd` entry. That is not an exotic
    case: it is what an OCI container started with `--user 4242:4242` looks like, and
    what Kubernetes produces whenever `runAsUser` is set to an arbitrary uid. YazSes
    ships a Docker image, so the path is reachable by design rather than by accident.

    It mattered because `build_plan` is the *first* thing two commands do:

    * `yazses setup` called it unguarded and exited with a raw `KeyError` traceback --
      on the one command whose entire job is to fix a machine's prerequisites;
    * `yazses quickstart` caught the exception and fell back to `needs_setup = False`,
      printing **"Prerequisites -- already set up ✓"**. That is a false statement on the
      first screen a new user ever sees, and it is worst exactly where it is wrong:
      inside a fresh container almost nothing *is* set up.

    Falling back to the numeric uid is honest rather than merely quiet. Group
    membership is stored by name, so `_user_in_input_group("4242")` answers `False`,
    which is the true answer for a uid the system has no account for.
    """
    import pwd
    named = (
        os.environ.get("SUDO_USER")
        or os.environ.get("USER")
        or os.environ.get("LOGNAME")
    )
    if named:
        return named
    uid = os.getuid()
    try:
        return pwd.getpwuid(uid).pw_name
    except (KeyError, OSError):
        return str(uid)


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


def snap_interface_pending(
    interface: str, env: Mapping[str, str] | None = None, *, runner=subprocess.run
) -> bool:
    """True when running inside the yazses snap with *interface* not connected.

    Strictly-confined snaps cannot self-connect interfaces, and the two YazSes
    depends on are not auto-connected by snapd, so a fresh `snap install yazses`
    has neither a microphone nor a hotkey until the user connects them. Detected
    via `snapctl is-connected`, which is always available to a snap's own apps.
    """
    env = os.environ if env is None else env
    if env.get("SNAP_NAME") != "yazses":
        return False  # not the snap build — apt/pipx grant these directly
    try:
        r = runner(["snapctl", "is-connected", interface], capture_output=True)
    except (FileNotFoundError, OSError):
        return False
    return getattr(r, "returncode", 0) != 0


def portaudio_state() -> str:
    """`"ok"` | `"missing"` | `"uninitialised"` — why `sounddevice` will not import.

    `sounddevice` calls `Pa_Initialize()` at **module scope**, so a failed import
    carries two completely different facts and the exception type is what separates
    them:

    * `OSError: PortAudio library not found` — the runtime is genuinely absent. This
      is failure class 1 at the top of this module and the single most likely reason a
      `pipx`/`uv tool` install has no microphone: nothing pulls `libportaudio2` in.
    * `sounddevice.PortAudioError` — the library **loaded and then failed to start**.
      It cannot be missing; it is the thing that raised.

    Collapsing the two is not hypothetical. Windows Server 2022 with no audio device
    raises `PortAudioError(..., -9986)` from the import, and the doctor row built on the
    old boolean answered *"this means a broken or partial install — run: pip install
    --force-reinstall sounddevice"* on a machine where the install is perfect and the
    reinstall cannot help. Confirmed on real hardware, not reasoned about.

    `system/diagnosis.py` had already been narrowed for exactly this — its comment says
    a `PortAudioError` proves PortAudio loaded, and its test names `-9986` among the
    codes that must not be diagnosed as a missing library. This function is the other
    guard, with the other vocabulary, which is how the two disagreed.
    """
    try:
        import sounddevice  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        names = {cls.__name__ for cls in type(exc).__mro__}
        return "uninitialised" if "PortAudioError" in names else "missing"
    return "ok"


def portaudio_missing() -> bool:
    """True when the PortAudio runtime is absent, so `sounddevice` cannot load.

    Distinguished from "no input device" *and* from "PortAudio started and failed" on
    purpose. All three surface as an unusable microphone, and only one of them is fixed
    by an apt command — reporting the symptom without the cause is what sent people to
    check their hardware.
    """
    return portaudio_state() == "missing"


def portaudio_uninitialised() -> bool:
    """True when PortAudio loaded and `Pa_Initialize()` failed — no audio system."""
    return portaudio_state() == "uninitialised"


def snap_mic_pending(env: Mapping[str, str] | None = None, *, runner=subprocess.run) -> bool:
    """True in the snap when `audio-record` is not connected — no microphone."""
    return snap_interface_pending("audio-record", env, runner=runner)


def snap_rawinput_pending(env: Mapping[str, str] | None = None, *, runner=subprocess.run) -> bool:
    """True in the snap when `raw-input` is not connected — no hold-to-talk key.

    The counterpart to the microphone check, and the more confusing failure of
    the two: with a mic but no `raw-input` the daemon starts, reports healthy,
    and simply never notices the hotkey. Joining the `input` group cannot fix it
    inside confinement — only this interface can (issue #44).
    """
    return snap_interface_pending("raw-input", env, runner=runner)


def preflight_hints(
    env: Mapping[str, str] | None = None,
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

    # Snap-only: both interfaces must be connected once after install. Neither is
    # auto-connected, and between them they cover the two ways a fresh snap
    # install appears broken — it cannot hear you, and it cannot see the hotkey.
    if snap_mic_pending(env):
        hints.append(
            "Microphone access isn't granted to the snap yet — dictation can't hear you.\n"
            "  Grant it once:  sudo snap connect yazses:audio-record"
        )
    if snap_rawinput_pending(env):
        hints.append(
            "Hold-to-talk isn't granted to the snap yet — the hotkey will do nothing.\n"
            "  Grant it once:  sudo snap connect yazses:raw-input"
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
    env: Mapping[str, str] | None = None,
    *,
    plan: SetupPlan | None = None,
    mic_pending: bool | None = None,
    rawinput_pending: bool | None = None,
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
    rawinput_pending = (
        snap_rawinput_pending(env) if rawinput_pending is None else rawinput_pending
    )
    pending = input_group_pending_relogin() if pending_relogin is None else pending_relogin
    snap_name = env.get("SNAP_INSTANCE_NAME") or env.get("SNAP_NAME") or "yazses"

    steps: list[ManualStep] = []

    # 1. Connect the microphone (snap only — confinement blocks self-connect).
    if mic_pending:
        steps.append(ManualStep(
            "Grant microphone access (connect your voice)",
            f"sudo snap connect {snap_name}:audio-record",
            "the strictly-confined snap can't hear you until this interface is connected.",
        ))

    # 1b. Connect the hotkey (snap only). The counterpart to the microphone and
    #     the more confusing of the two: with a mic but no `raw-input` the daemon
    #     starts, reports healthy, and simply never notices the key. `preflight_hints`
    #     had warned about it since issue #44 while this checklist — the place a
    #     user is actually told what to do — omitted it entirely and offered
    #     `usermod -aG input` instead, which cannot grant it inside confinement.
    if rawinput_pending:
        steps.append(ManualStep(
            "Grant hold-to-talk access (connect the hotkey)",
            f"sudo snap connect {snap_name}:raw-input",
            "inside confinement only this interface can read the key — the `input` group cannot.",
        ))

    # 2. Join the `input` group if not a member yet. Never inside a strict snap:
    #    there the group is not the barrier, so the advice is a loop (issue #44).
    if plan.add_to_input_group and not plan.confined:
        steps.append(ManualStep(
            "Join the `input` group",
            "sudo usermod -aG input $USER",
            "needed to read the hold-to-talk hotkey and to inject keystrokes.",
        ))

    # 3. Re-login when membership won't be live until a fresh session (either we
    #    just added the user, or /etc/group lists them but this session predates it).
    if (plan.add_to_input_group or pending) and not plan.confined:
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


def apply_plan(
    plan: SetupPlan, *, runner=subprocess.run, echo=print, has_apt=_has_apt
) -> bool:
    """Execute *plan*. Returns True on success. Best-effort, idempotent, total.

    **Never raises.** `check=False` suppresses a non-zero *exit status*; it does
    nothing about a command that cannot be executed in the first place, because
    `Popen` fails before any exit status exists. That distinction is not academic:
    a strictly confined snap gets `PermissionError: [Errno 13]` on `sudo` from
    AppArmor, and a minimal container gets `FileNotFoundError`. Either one used to
    escape as a full traceback out of the single command whose entire job is
    repairing a machine that does not work yet.

    `snap_interface_pending` in this same module had guarded its `snapctl` call
    with `except (FileNotFoundError, OSError)` all along — the guard existed, just
    not on the function that runs everything.
    """
    if plan.confined:
        # Nothing here is ours to do; the caller prints the manual checklist.
        for note in plan.notes:
            echo(f"! {note}")
        return False

    if plan.is_noop:
        echo("All Linux requirements already satisfied — nothing to do.")
        return True

    ok = True

    def run(argv: list[str], *, why: str) -> bool:
        """Run *argv*, returning True only on a clean exit. Absorbs exec failure."""
        try:
            r = runner(argv, check=False)
        except OSError as exc:
            detail = getattr(exc, "strerror", None) or str(exc)
            echo(f"  warning: could not run `{' '.join(argv)}` — {detail}.")
            echo(f"  {why}")
            return False
        return getattr(r, "returncode", 0) == 0

    if plan.apt_packages:
        if has_apt():
            echo(f"Installing system packages: {' '.join(plan.apt_packages)}")
            unprivileged = (
                "Run it yourself with the privileges it needs, or install the "
                "packages with your package manager."
            )
            run(["sudo", "apt-get", "update", "-qq"], why=unprivileged)
            if not run(
                ["sudo", "apt-get", "install", "-y", *plan.apt_packages],
                why=unprivileged,
            ):
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
        if not run(
            ["sudo", "usermod", "-aG", "input", user],
            why=f"Add yourself by hand:  sudo usermod -aG input {user}",
        ):
            ok = False
            echo("  warning: could not join the `input` group.")

    if plan.setup_ydotoold:
        try:
            path = write_ydotoold_service()
        except OSError as exc:
            ok = False
            echo(f"  warning: could not write the ydotoold user service — {exc}.")
        else:
            echo(f"Configured ydotoold user service: {path}")
            run(["systemctl", "--user", "daemon-reload"], why="Reload it yourself later.")
            if not run(
                ["systemctl", "--user", "enable", "--now", "ydotoold.service"],
                why="Start it yourself:  systemctl --user enable --now ydotoold.service",
            ):
                echo(
                    "  note: could not start ydotoold now (likely needs a fresh login "
                    "for `input`-group access to /dev/uinput). It will start on next login."
                )

    for note in plan.notes:
        echo(f"! {note}")

    return ok
