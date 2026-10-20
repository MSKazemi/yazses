"""Explain why the daemon is not running — from the service manager, not from the daemon.

`system/diagnosis.py` explains failures the *running* daemon catches. It cannot help
with the ones that happen before there is a daemon: a systemd unit whose binary is
missing, a crash loop that systemd gave up on, a Qt or PortAudio library the import
needs, `/dev/input` unreadable. Those leave no `last_error`; the only evidence is the
unit's state and the last lines of its journal. Before this module `yazses start` read
neither, printed "still loading", and `yazses status` said "not running" — measured on
a pipx install next to the apt package, where the unit named a binary that did not exist.

Pure where it can be, so every rule is testable without systemd:

* :func:`classify_service` — unit state -> findings.
* :func:`classify_log` — journal/log text -> one finding (falls through to
  :func:`yazses.system.diagnosis.diagnose` for the rules that already live there).
* :func:`install_command` — a package, spelled for the distro actually running.

A finding is advice, never a decision: nothing here changes what the daemon does.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    """One problem: what is wrong, why, and the exact commands that fix it."""

    slug: str
    problem: str
    cause: str
    commands: tuple[str, ...] = ()
    #: Shown after the commands — things a command cannot do (log out and back in).
    note: str = ""


@dataclass(frozen=True)
class ServiceState:
    """What `systemctl --user show yazses.service` and its journal said."""

    load_state: str = ""
    active_state: str = ""
    sub_state: str = ""
    result: str = ""
    exec_status: int = 0
    n_restarts: int = 0
    exec_path: str | None = None
    exec_exists: bool = True
    journal: tuple[str, ...] = field(default_factory=tuple)


# ---- packages, spelled per distro ------------------------------------------------

#: package key -> {family: package name}. One place to fix a package name.
_PACKAGES: dict[str, dict[str, str]] = {
    "portaudio": {"debian": "libportaudio2", "fedora": "portaudio", "arch": "portaudio", "suse": "portaudio"},
    "xcb-cursor": {"debian": "libxcb-cursor0", "fedora": "xcb-util-cursor", "arch": "xcb-util-cursor", "suse": "libxcb-cursor0"},
    "ffmpeg": {"debian": "ffmpeg", "fedora": "ffmpeg-free", "arch": "ffmpeg", "suse": "ffmpeg"},
    "ydotool": {"debian": "ydotool", "fedora": "ydotool", "arch": "ydotool", "suse": "ydotool"},
    "wl-clipboard": {"debian": "wl-clipboard", "fedora": "wl-clipboard", "arch": "wl-clipboard", "suse": "wl-clipboard"},
}

_INSTALLERS = {
    "debian": "sudo apt install {pkg}",
    "fedora": "sudo dnf install {pkg}",
    "arch": "sudo pacman -S {pkg}",
    "suse": "sudo zypper install {pkg}",
}


def distro_family(os_release: str) -> str:
    """`debian` / `fedora` / `arch` / `suse` / `unknown` from /etc/os-release text."""
    ids: list[str] = []
    for line in os_release.splitlines():
        key, _, value = line.partition("=")
        if key in ("ID", "ID_LIKE"):
            ids += value.strip().strip('"').lower().split()
    for candidate, family in (
        ("debian", "debian"), ("ubuntu", "debian"), ("fedora", "fedora"), ("rhel", "fedora"),
        ("centos", "fedora"), ("arch", "arch"), ("suse", "suse"), ("opensuse", "suse"),
    ):
        if candidate in ids:
            return family
    return "unknown"


def install_command(package: str, family: str) -> str:
    """The shell command that installs *package* on *family*; a hint when unknown."""
    name = _PACKAGES.get(package, {}).get(family)
    if name is None or family not in _INSTALLERS:
        known = _PACKAGES.get(package, {})
        spelled = ", ".join(f"{n} ({f})" for f, n in known.items()) or package
        return f"install with your package manager: {spelled}"
    return _INSTALLERS[family].format(pkg=name)


def read_distro_family() -> str:
    try:
        return distro_family(Path("/etc/os-release").read_text(encoding="utf-8"))
    except OSError:
        return "unknown"


# ---- journal / log signatures ----------------------------------------------------

def _pkg(key: str, family: str) -> tuple[str, ...]:
    return (install_command(key, family),)


def classify_log(text: str, family: str = "unknown") -> Finding | None:
    """The most specific known cause in *text* (a journal or daemon.log tail), or None.

    Ordered most specific first. Matched case-insensitively. Returns None for text it
    does not recognise — the caller decides what to say then, because a guess presented
    as a diagnosis is worse than "see the log".
    """
    low = text.lower()

    if "permission denied" in low and "/dev/input" in low:
        return Finding(
            "input-permission", "Cannot read the keyboard",
            "Your user is not allowed to read /dev/input/*, so the hotkey cannot be heard.",
            ("sudo usermod -aG input $USER", "yazses setup"),
            "Then log out and back in — group changes only apply to new sessions.",
        )
    if "libxcb-cursor" in low or "could not load the qt platform plugin" in low:
        return Finding(
            "qt-xcb-missing", "The overlay/tray cannot start (Qt needs a system library)",
            "Qt's xcb platform plugin needs libxcb-cursor, which this system lacks.",
            _pkg("xcb-cursor", family),
            "Or run `yazses features disable overlay tray` — dictation does not need them.",
        )
    if "libportaudio" in low or "portaudio library not found" in low:
        return Finding(
            "portaudio-missing", "No audio library",
            "PortAudio is not installed, so no microphone can be opened.",
            _pkg("portaudio", family),
        )
    if "ydotool" in low and any(m in low for m in ("failed to connect", "socket", "no such file")):
        return Finding(
            "ydotoold-down", "Typing helper is not running",
            "ydotoold (Wayland keystroke injection) is not reachable.",
            ("yazses setup", "systemctl --user enable --now ydotoold"),
        )
    if "ffmpeg" in low and ("not found" in low or "no such file" in low):
        return Finding(
            "ffmpeg-missing", "ffmpeg is missing",
            "Importing or transcribing audio files needs ffmpeg.",
            _pkg("ffmpeg", family),
        )
    if "address already in use" in low or "another instance" in low or "already running" in low:
        return Finding(
            "already-running", "Another YazSes is already running",
            "A second daemon cannot take the same lock/socket.",
            ("yazses stop", "yazses start"),
        )
    match = re.search(r"no module named '?([\w.]+)", low)
    if match:
        return Finding(
            "module-missing", f"A Python module is missing ({match.group(1)})",
            "The install is incomplete or was changed underneath the daemon.",
            ("pipx reinstall yazses", "yazses doctor"),
        )
    if "tomldecodeerror" in low or ("invalid" in low and "config.toml" in low):
        return Finding(
            "config-invalid", "The config file cannot be read",
            "~/.config/yazses/config.toml has a syntax or value error.",
            ("yazses doctor",),
            "Move the file aside to fall back to defaults: mv ~/.config/yazses/config.toml{,.bad}",
        )

    # Everything the running daemon already knows how to explain (memory, mic busy, …).
    from yazses.system.diagnosis import diagnose

    diag = diagnose(text)
    if not diag.slug.startswith("unknown-"):
        return Finding(diag.slug, diag.title, diag.what, (), diag.fix)
    return None


# ---- unit state -------------------------------------------------------------------

def classify_service(state: ServiceState, family: str = "unknown") -> list[Finding]:
    """Why the unit is not running, most fundamental cause first. Empty when healthy."""
    findings: list[Finding] = []
    root = classify_log("\n".join(state.journal), family) if state.journal else None

    if (state.exec_path and not state.exec_exists) or state.exec_status == 203:
        findings.append(Finding(
            "exec-missing", "The service points at a program that does not exist",
            f"ExecStart={state.exec_path or '?'} is missing, so systemd cannot launch the "
            "daemon (status 203/EXEC). Typical when a packaged unit meets a pipx/curl install.",
            ("yazses autostart enable",),
            "That rewrites the unit to the install you run it from.",
        ))
    if state.result == "start-limit-hit":
        findings.append(Finding(
            "start-limit", "systemd gave up restarting it",
            "It failed 5 times within 60 seconds, so systemd stopped retrying on purpose "
            "(so a broken setup cannot spin forever).",
            ("systemctl --user reset-failed yazses.service", "yazses logs", "yazses start"),
            "Fix the cause above first, or it will fail again.",
        ))
    elif state.active_state == "failed" and not findings:
        findings.append(Finding(
            "unit-failed", "The service failed",
            f"systemd reports result '{state.result or 'unknown'}'"
            + (f", exit status {state.exec_status}" if state.exec_status else "") + ".",
            ("yazses logs", "yazses doctor"),
        ))
    elif state.sub_state == "auto-restart" or (state.active_state == "activating" and state.n_restarts):
        findings.append(Finding(
            "crash-loop", f"The daemon keeps crashing (restart #{state.n_restarts})",
            "It starts, dies, and systemd restarts it every few seconds.",
            ("yazses logs",),
        ))
    elif state.active_state == "inactive" and state.load_state == "loaded":
        findings.append(Finding(
            "not-started", "The service is installed but not running",
            "Nothing has started it in this session.",
            ("yazses start",),
        ))

    if root is not None and findings:
        findings.insert(0, root)  # the cause, before the symptoms it produced
    return findings


def render(findings: Sequence[Finding]) -> str:
    """The text a user reads: problem, cause, then the commands to copy."""
    blocks = []
    for f in findings:
        lines = [f"  ✗ {f.problem}", f"    why: {f.cause}"]
        if f.commands:
            lines.append("    fix:")
            lines += [f"      {c}" for c in f.commands]
        if f.note:
            lines.append(f"    note: {f.note}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ---- collection (the only impure part) -------------------------------------------

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def collect_service_state(run: Runner = subprocess.run, unit: str = "yazses.service") -> ServiceState | None:
    """Ask systemd. None when there is no systemd user manager to ask (not an error)."""
    try:
        shown = run(
            ["systemctl", "--user", "show", unit, "-p",
             "LoadState,ActiveState,SubState,Result,ExecMainStatus,NRestarts,ExecStart"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if shown.returncode != 0 or not shown.stdout.strip():
        return None
    kv = dict(line.partition("=")[::2] for line in shown.stdout.splitlines() if "=" in line)
    if kv.get("LoadState") in (None, "not-found"):
        return None
    path_match = re.search(r"path=([^\s;]+)", kv.get("ExecStart", ""))
    exec_path = path_match.group(1) if path_match else None
    try:
        journal = run(
            ["journalctl", "--user", "-u", unit, "-n", "40", "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        journal = []

    def _int(key: str) -> int:
        try:
            return int(kv.get(key, "0") or 0)
        except ValueError:
            return 0

    return ServiceState(
        load_state=kv.get("LoadState", ""),
        active_state=kv.get("ActiveState", ""),
        sub_state=kv.get("SubState", ""),
        result=kv.get("Result", ""),
        exec_status=_int("ExecMainStatus"),
        n_restarts=_int("NRestarts"),
        exec_path=exec_path,
        exec_exists=Path(exec_path).exists() if exec_path else True,
        journal=tuple(journal),
    )


def explain_service_failure(run: Runner = subprocess.run) -> str:
    """Collect, classify, render — "" when healthy or when there is nothing to ask."""
    state = collect_service_state(run)
    if state is None:
        return ""
    return render(classify_service(state, read_distro_family()))
