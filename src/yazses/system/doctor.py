"""`yazses doctor` — diagnostics for the active platform.

Permission checks delegate to platform.permissions. Linux-specific extras
(X11/Wayland session, injection tool availability) remain inline here for now;
when Mac and Windows ship they grow their own extras blocks.
"""

from __future__ import annotations

import os
import shutil
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from yazses.platform import PermissionState, get_platform
from yazses.system import streams
from yazses.system.miclevel import LevelStats
from yazses.system.snap import in_strict_snap, keyboard_capture_advice

# (name, status, detail) — status is "OK" | "FAIL" | "SKIP" | "WARN"
_Check = tuple[str, str, str]


def _tool(label: str, *, required: bool) -> _Check:
    found = bool(shutil.which(label))
    if found:
        return (f"  {label}", "OK", "found")
    if required:
        return (f"  {label}", "FAIL", "not installed")
    return (f"  {label}", "SKIP", "not needed on this session type")


# Wayland compositors where `wtype` is blocked (no virtual-keyboard protocol),
# so keystroke injection requires ydotool + a running ydotoold.
_UINPUT_ONLY_DESKTOPS = ("gnome", "kde", "plasma", "cinnamon", "unity", "mate", "xfce", "lxqt")


def _binary_runs(cmd: list[str]) -> bool:
    """True when *cmd* executes and exits 0 within a short timeout.

    Distinguishes "the binary is on PATH" from "the binary actually runs" — a
    bundle that ships an executable without its shared libraries exits 127
    (loader error) even though ``shutil.which`` finds it.
    """
    import subprocess

    try:
        r = subprocess.run(cmd, capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def _injection_readiness(is_wayland: bool, is_x11: bool) -> list[_Check]:
    """Report whether keystroke injection will actually work, with the fix."""
    from yazses.inject.auto import ydotool_ready, ydotool_socket_path

    out: list[_Check] = []
    if is_wayland:
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        gnome_like = any(d in desktop for d in _UINPUT_ONLY_DESKTOPS)
        sock = ydotool_socket_path()
        if ydotool_ready():
            out.append(("ydotoold", "OK", f"running ({sock})"))
            out.append(("Injection", "OK", "ydotool — works on any Wayland compositor"))
        elif shutil.which("ydotool"):
            out.append(("ydotoold", "FAIL" if gnome_like else "WARN",
                        f"not running (no socket at {sock}) — run `yazses setup`"))
            if gnome_like:
                out.append(("Injection", "FAIL",
                            "GNOME/KDE Wayland needs ydotool+ydotoold (wtype is blocked) — run `yazses setup`"))
            elif shutil.which("wtype"):
                out.append(("Injection", "OK", "wtype — ydotoold off but fine on wlroots compositors"))
            else:
                out.append(("Injection", "FAIL", "no working backend — run `yazses setup`"))
        elif shutil.which("wtype"):
            if gnome_like:
                out.append(("Injection", "FAIL",
                            "wtype does not work on GNOME/KDE Wayland — run `yazses setup` (installs ydotool+ydotoold)"))
            else:
                out.append(("Injection", "OK", "wtype (wlroots)"))
        else:
            out.append(("Injection", "FAIL", "no Wayland injector installed — run `yazses setup`"))
    elif is_x11:
        if shutil.which("xdotool"):
            # Presence isn't enough: a snap that bundles the xdotool binary but
            # not its library (libxdo.so.3) exits 127 on every type() and injection
            # silently fails. Actually invoke it so a broken bundle is caught here.
            if _binary_runs(["xdotool", "getdisplaygeometry"]):
                out.append(("Injection", "OK", "xdotool (X11)"))
            elif shutil.which("xclip") and _binary_runs(["xclip", "-version"]):
                out.append(("Injection", "WARN",
                            "xdotool present but not runnable (missing libxdo.so.3?); "
                            "using clipboard paste"))
            else:
                out.append(("Injection", "FAIL",
                            "xdotool installed but fails to run — missing shared library "
                            "(libxdo.so.3). Reinstall/upgrade the package."))
        elif shutil.which("xclip"):
            out.append(("Injection", "WARN", "clipboard paste only (install xdotool for direct typing)"))
        else:
            out.append(("Injection", "FAIL", "no X11 injector — run `yazses setup`"))
    return out


def _prosody_check(enabled: bool) -> _Check | None:
    """Report whether the optional ``prosody`` extra (parselmouth) is importable.

    Only runs when ``[prosody] enabled`` (spec-prosody-ink). Absent is a WARN, not
    a FAIL: pause→paragraph still works with no dep; only emphasis→bold needs
    parselmouth and degrades to pause-only when it is missing.
    """
    if not enabled:
        return None
    try:
        import parselmouth  # type: ignore  # noqa: F401
    except Exception:
        return (
            "prosody extra (parselmouth)",
            "WARN",
            "not installed — emphasis disabled, pause→¶ still works "
            "(uv sync --extra prosody)",
        )
    return ("prosody extra (parselmouth)", "OK", "importable")


def _extra_check(label: str, enabled: bool, module: str, hint: str) -> _Check | None:
    """Generic optional-extra importability check (None when the feature is off)."""
    if not enabled:
        return None
    try:
        __import__(module)
    except Exception:
        return (label, "WARN", f"not installed — feature dormant ({hint})")
    return (label, "OK", "importable")


def _dysfluency_check(enabled: bool) -> _Check | None:
    """Report Dysfluency-Friendly Mode status (ADR-015). Skipped when off."""
    if not enabled:
        return None
    return (
        "Dysfluency-friendly mode",
        "OK",
        "on — collapsing repetitions/prolongations, wider onset padding",
    )


def _version_check() -> _Check:
    """Report the installed YazSes version (one-stop health check)."""
    try:
        return ("Version", "OK", f"yazses {_pkg_version('yazses')}")
    except PackageNotFoundError:
        return ("Version", "WARN", "yazses version metadata not found")


def _stale_daemon_note(daemon_version: str) -> str:
    """Is the running daemon a different build from the CLI asking? Pure.

    An upgrade replaces the files on disk and does not touch the process that is
    already running: the daemon keeps executing the build it started with until
    `yazses restart`. So after every upgrade there is a window in which `yazses
    --version` says one thing and the code actually handling your dictation is
    another, and until this check nothing in the product could see it. `doctor`
    printed the CLI's version beside the daemon's *liveness* and called it healthy,
    which is the exact shape of "exit 0 is not proof an upgrade happened".

    An **empty** version is itself the answer rather than a missing one: the field
    was added in 2.24.0, so a daemon that does not report one is necessarily older
    than the CLI reading this. Silence is evidence here, not an unknown.
    """
    try:
        installed = _pkg_version("yazses")
    except PackageNotFoundError:
        return ""  # nothing to compare against; _version_check already warns

    if not daemon_version:
        return (
            "the daemon predates version reporting, so it is older than this "
            "install — run `yazses restart` to pick up the upgrade"
        )
    if daemon_version != installed:
        return (
            f"daemon is running {daemon_version}, you have {installed} — "
            "run `yazses restart` so dictation uses the version you installed"
        )
    return ""


# The verdict line decides "is it already running?" from the daemon check's own
# detail rather than re-asking the OS, so the bottom line can never contradict the
# lines printed above it. Both sides go through this constant so they cannot drift.
_RUNNING_PREFIX = "running"


def _daemon_check(platform) -> _Check:
    """Report whether the daemon is running, with live state when IPC answers."""
    lifecycle = platform.lifecycle
    if not lifecycle.is_running():
        return ("Daemon", "WARN", "not running — start with `yazses start`")
    pid = lifecycle.read_pid()
    try:
        client = platform.ipc_client_factory(platform.paths.ipc_socket)
        info = client.call("status")
        bits = [b for b in (
            f"state {info.get('state')}" if info.get("state") else "",
            f"model {info.get('model')}" if info.get("model") else "",
        ) if b]
        suffix = (", " + ", ".join(bits)) if bits else ""

        stale = _stale_daemon_note(str(info.get("version") or ""))
        if stale:
            return ("Daemon", "WARN", f"{_RUNNING_PREFIX} (PID {pid}{suffix}) — {stale}")
        return ("Daemon", "OK", f"{_RUNNING_PREFIX} (PID {pid}{suffix})")
    except Exception:
        # Running but IPC not yet ready (still loading the model) or unreachable.
        return ("Daemon", "OK", f"{_RUNNING_PREFIX} (PID {pid}; IPC not ready)")


def _model_check(model: str, hf_cache: Path) -> _Check:
    """Report whether the configured STT model is available locally.

    Delegates the "is it here?" question to ``stt.download.is_cached``, which
    matches on the hub cache's directory name (no ``faster_whisper`` import) so
    doctor stays fast.
    """
    from yazses.stt.download import is_cached

    if Path(model).expanduser().exists():
        return ("STT model", "OK", f"{model} (local files)")
    if is_cached(model, hf_cache):
        return ("STT model", "OK", f"{model} (cached)")
    # Naming the command matters more than it looks: on a firewalled machine the
    # automatic fetch is precisely what fails, and this is the route that reports
    # why (#310).
    return (
        "STT model",
        "WARN",
        f"{model} not downloaded — fetched automatically on first dictation "
        f"(needs network once). To do it now: yazses model download {model}",
    )


def _autostart_check(platform) -> _Check | None:
    """Answer the question nobody thinks to ask until after a reboot: does it come back?

    Every other check here says whether YazSes works *now*. This one says whether it will
    be running the next time you sit down, which is the difference between a daemon and a
    program you must remember to launch. It is reported as a FAIL rather than a warning
    because "I have to run `yazses start` every morning" is the symptom people live with
    for months without realising it is fixable.

    It also has to be honest about the *other* half of "does it come back": what
    happens when the daemon crashes mid-session. systemd (``Restart=on-failure``)
    and launchd (``KeepAlive``) supervise it themselves; the Windows autostart is
    an ``HKCU\\Run`` value that fires once at login and never again, so there
    recovery comes from the tray poller instead — which means it is only covered
    while the tray is running. Reporting a bare "yes" on Windows implied a
    supervision that does not exist.
    """
    lifecycle = getattr(platform, "lifecycle", None)
    if lifecycle is None or not hasattr(lifecycle, "is_autostart_installed"):
        return None
    mechanism = {
        "linux": "systemd user service is enabled; it also restarts a crashed daemon",
        "darwin": "launchd agent is loaded; it also restarts a crashed daemon",
        "win32": (
            "HKCU\\Run entry — that covers login only. Windows has no service "
            "supervising the daemon, so a crash is recovered by the tray; keep the "
            "tray running (`yazses tray`) for that safety net"
        ),
    }.get(sys.platform)
    if mechanism is None:  # a platform with autostart we have nothing accurate to say about
        return None
    try:
        if lifecycle.is_autostart_installed():
            return ("Starts at login", "OK", f"yes — {mechanism}")
    except Exception as exc:  # noqa: BLE001 — never let a probe break doctor
        return ("Starts at login", "WARN", f"could not be determined ({exc})")
    return (
        "Starts at login", "FAIL",
        "no — YazSes will NOT come back after a reboot. Fix: `yazses autostart enable`",
    )


def _config_validity(config_file: Path) -> list[_Check]:
    """Report values the loader had to repair or fall back on.

    These never stop the daemon — that is the point — which is exactly why they need a
    place to be seen. A repaired value means the file says one thing and YazSes is doing
    another, and a defaulted value means a setting the user believes is applied is not.
    Both drift silently until something feels wrong and nobody can say when it started.
    """
    if not config_file.exists():
        return []
    try:
        from yazses.config import load_config_checked

        problems = load_config_checked(config_file).problems
    except Exception as exc:  # noqa: BLE001 — doctor must survive anything
        return [("Config validity", "WARN", f"could not be checked ({exc})")]
    if not problems:
        return [("Config validity", "OK", "every setting is a usable value")]

    out: list[_Check] = []
    defaulted = [p for p in problems if not p.repaired]
    status = "FAIL" if defaulted else "WARN"
    out.append((
        "Config validity", status,
        f"{len(problems)} problem(s): {len(problems) - len(defaulted)} repaired, "
        f"{len(defaulted)} using defaults — fix them in {config_file}",
    ))
    for problem in problems:
        verb = "repaired" if problem.repaired else "using default"
        out.append((f"  └ {verb}", "WARN" if problem.repaired else "FAIL", str(problem)))
    return out


def _llm_endpoint_check(cfg) -> list[_Check]:
    """Report where dictation cleanup would send transcribed text.

    Cleanup's Ollama backend is the only path that puts *text* on a socket, and
    the endpoint is a hand-edited string. A log line at daemon start is easy to
    miss; someone auditing an offline install runs `doctor`, so the answer to
    "does anything leave this machine" belongs here in one line.

    Silent when cleanup is off, which is the default — doctor should not grow a
    row per dormant feature.
    """
    disfluency = getattr(getattr(cfg, "filters", None), "disfluency", None)
    if disfluency is None or not getattr(disfluency, "llm_enabled", False):
        return []
    if getattr(disfluency, "llm_model", ""):
        return [("LLM cleanup", "OK", "local GGUF model — no network call")]

    from yazses.postprocess.llm_cleanup import is_loopback_endpoint

    endpoint = getattr(disfluency, "llm_endpoint", "")
    if not endpoint:
        return [("LLM cleanup", "WARN", "enabled but no model or endpoint configured")]
    if is_loopback_endpoint(endpoint):
        return [("LLM cleanup", "OK", f"{endpoint} (loopback — stays on this machine)")]
    if getattr(disfluency, "llm_allow_remote_endpoint", False):
        return [(
            "LLM cleanup", "WARN",
            f"{endpoint} is REMOTE and llm_allow_remote_endpoint = true — "
            "transcribed text is being sent off this machine",
        )]
    return [(
        "LLM cleanup", "WARN",
        f"disabled: {endpoint} is not loopback. Point it at localhost, or set "
        "llm_allow_remote_endpoint = true to send dictated text off this machine.",
    )]


def _config_summary(cfg, config_file: Path) -> list[_Check]:
    """Surface the active config file, resolved hotkey, and STT prompt status."""
    out: list[_Check] = []
    if config_file.exists():
        out.append(("Config file", "OK", str(config_file)))
    else:
        out.append((
            "Config file", "WARN",
            f"{config_file} (absent — using built-in defaults)",
        ))
    out.extend(_config_validity(config_file))
    out.extend(_llm_endpoint_check(cfg))
    out.append((
        "Hotkey", "OK",
        f"{cfg.hotkey.key} (hold {cfg.hotkey.hold_threshold_ms} ms)",
    ))
    pinned = (getattr(cfg.audio, "device", "") or "").strip()
    if pinned:
        out.append(("Input device", "OK", f"pinned: {pinned!r}"))
    else:
        try:
            from yazses.audio import devices as _devices

            default = _devices.current_default_input_name()
        except Exception:
            default = None
        # `default` names a route, not a microphone, so on a PipeWire desktop the
        # line above is the least useful true thing this command can say -- and this
        # is the surface the documentation points at first. Resolve it when we can:
        # on the machine that prompted this the alias pointed at an internal array at
        # 65% gain while another source sat at 100%, and every dictation for an hour
        # decoded to nothing with no way to see why from inside YazSes.
        behind = ""
        try:
            if _devices.is_routing_alias(default):
                found = _devices.default_source_behind_alias()
                if found:
                    behind = f" → {found[0]} (volume {found[1] * 100:.0f}%)"
        except Exception:  # pragma: no cover - best-effort, never breaks doctor
            behind = ""
        out.append((
            "Input device", "OK",
            f"OS default: {default or 'unknown'}{behind} "
            "(pin with `yazses audio use <name>`)",
        ))
    guard = getattr(cfg.injection, "target_guard", "off")
    if guard != "off":
        try:
            from yazses.inject.target import AtspiFocusTracker

            precise = AtspiFocusTracker.available()
        except Exception:
            precise = False
        detail = (
            f"{guard} (AT-SPI precise)" if precise
            else f"{guard} (best-effort; apt install python3-pyatspi gir1.2-atspi-2.0 for precision)"
        )
        out.append(("Text-target guard", "OK", detail))
    prompt = (cfg.stt.initial_prompt or "").strip()
    if prompt:
        preview = prompt if len(prompt) <= 40 else prompt[:37] + "..."
        out.append(("STT prompt", "OK", f"primed: {preview!r}"))
    else:
        out.append((
            "STT prompt", "OK",
            "app name only (set [stt] initial_prompt to add vocabulary)",
        ))
    return out


def _sample_mic(cfg, seconds: float) -> LevelStats:
    """Record a short ambient clip and return its level stats (seam for tests)."""
    from yazses.system.miclevel import analyze, record

    sr = cfg.audio.sample_rate
    return analyze(record(seconds, sr), sr)


def _mic_level_check(cfg, seconds: float = 2.0) -> _Check:
    """Passive ambient level vs the VAD gate (no speech needed).

    Warns when the resting room level already meets/exceeds ``vad_threshold`` —
    the gate would then pass noise through as spurious transcripts. A quiet room
    is OK; for speech-level calibration the detail points at ``yazses mic-level``.
    """
    try:
        stats = _sample_mic(cfg, seconds)
    except Exception as exc:
        return ("Mic level", "WARN", f"could not sample microphone ({exc})")
    thr = cfg.accessibility.vad_threshold
    # Compared against the user's gate and nothing else. This was also conditioned on
    # `not stats.is_silent`, and `is_silent` is measured against a FIXED floor
    # (miclevel._MIN_THRESHOLD, 0.002) unrelated to that gate -- so for any threshold
    # below the floor the warning was suppressed across exactly the band where the
    # gate sits under the room's noise, which is the case this check exists for.
    # Measured on a real machine: ambient 0.0010, vad_threshold 0.0005, reported
    # "[OK] ambient 0.0010 under vad_threshold 0.0005".
    #
    # `mean_abs > 0` keeps a dead microphone out of it: nothing captured at all is
    # the Microphone check's business, and with a gate of 0 this would otherwise
    # blame the gate for a mic that recorded nothing.
    if stats.mean_abs > 0 and stats.mean_abs >= thr:
        return (
            "Mic level", "WARN",
            f"ambient {stats.mean_abs:.4f} >= vad_threshold {thr} — the gate sits at "
            "or below the room's noise floor, so silence passes it and is transcribed "
            "as invented words; raise it or run `yazses mic-level --set`",
        )
    return (
        "Mic level", "OK",
        f"ambient {stats.mean_abs:.4f} under vad_threshold {thr} "
        "(speak-test with `yazses mic-level`)",
    )


def _input_group_pending_relogin() -> bool:
    """True when the user is in the `input` group per /etc/group but this session
    predates the change (so keyboard capture fails only because of a stale login).
    Best-effort; never raises."""
    try:
        from yazses.system.setup import input_group_pending_relogin

        return input_group_pending_relogin()
    except Exception:
        return False


def _keyboard_capture_check(perms, platform_name: str) -> _Check:
    """Report keyboard-capture access with an actionable permission fix."""
    state = perms.check_keyboard_capture()
    if state is PermissionState.OK:
        detail = state.value
    elif state is PermissionState.DENIED and in_strict_snap():
        # Check this BEFORE the `input` group advice below. Under strict
        # confinement snapd blocks the read outright, so the group advice is not
        # merely incomplete — it is impossible, and users followed it in circles
        # (issue #44).
        detail = f"{state.value} — {keyboard_capture_advice()}"
    elif _input_group_pending_relogin():
        # You ARE in the `input` group, but THIS process's session predates the
        # change, so the generic "add yourself to the group" advice is wrong and
        # confusing. Tell the truth: re-login (a running daemon started under
        # `sg input` is unaffected — this only reflects the shell running doctor).
        detail = (
            f"{state.value} — you're in the `input` group, but this session started before "
            "that change. Log out and back in (or reboot). A daemon started with "
            '`sg input -c "yazses restart"` already has access — this line only reflects '
            "the shell running doctor."
        )
    elif platform_name == "linux" and state is PermissionState.DENIED:
        detail = (
            f"{state.value} — run:\n"
            "    sudo usermod -aG input $USER\n"
            "Then log out and back in for the change to take effect."
        )
    else:
        detail = f"{state.value} — {perms.how_to_grant()}"
    return ("Keyboard capture", "OK" if state is PermissionState.OK else "FAIL", detail)


def _window_focus_check(is_wayland: bool, is_x11: bool) -> _Check | None:
    """Report whether "focus the browser" can work on this session (#39).

    Wayland deliberately forbids one client focusing another's window and no
    portal exposes it, so this is a permanent property of the session rather
    than something to install. Saying so here is the difference between a user
    concluding YazSes is broken and knowing the platform said no.
    """
    if not (is_wayland or is_x11):
        return None
    from yazses.windowctl.focus import wayland_limitation

    if is_wayland:
        return ("Voice window focus", "SKIP", wayland_limitation())
    if not shutil.which("xdotool"):
        return ("Voice window focus", "WARN",
                "needs xdotool to enumerate and raise windows — run `yazses setup`")
    return ("Voice window focus", "OK", "xdotool (X11) — \"focus the browser\" works")


def _modality_roles_check(cfg) -> _Check | None:
    """Report which modality owns each role (ADR-v2-011), or nothing when off.

    A role map is exactly the kind of state that is invisible until it
    misbehaves: with `[modality]` on, whether EMG runs in command or dictation
    mode stops being what `[emg] mode` says and starts being what the router
    decided. Printing the resolved map means a user can see that without
    reading config or the log.
    """
    if not getattr(cfg, "modality", None) or not cfg.modality.enabled:
        return None
    from yazses.modality.router import ModalityPolicy, resolve_roles

    available = ["voice", "keyboard"]
    if (cfg.emg.device_port or "").strip():
        available.append("emg")
    if cfg.gaze.enabled:
        available.append("gaze")
    roles = resolve_roles(
        available, ModalityPolicy.from_preset(cfg.modality.preset, cfg.modality.priority)
    )
    if not roles:
        return ("Modality roles", "WARN",
                f"preset {cfg.modality.preset!r} assigned nothing to the available "
                f"modalities ({', '.join(available)})")
    summary = ", ".join(f"{role}→{mod}" for role, mod in sorted(roles.items()))
    return ("Modality roles", "OK", f"preset {cfg.modality.preset}: {summary}")


def _elevation_check(platform_name: str) -> _Check | None:
    """Windows: report elevation and what it means for elevated windows.

    Informational, never a FAIL — running unelevated is the correct default and
    the *more* secure choice. The point is that the consequence is stated rather
    than discovered as "dictation randomly doesn't work in Task Manager".
    """
    if platform_name != "windows":
        return None
    try:
        from yazses.platform.windows.permissions import elevation_detail, is_elevated
    except Exception:  # pragma: no cover - defensive
        return None
    return ("Elevated windows", "OK", elevation_detail(is_elevated()))


def _hotkey_device_check(cfg) -> _Check | None:
    """Report which /dev/input device the hotkey will bind to (Linux/evdev).

    Catches the silent failure where the daemon binds to an injector's virtual
    uinput device (e.g. "ydotoold virtual device") instead of the real keyboard:
    that device only ever carries synthetic events, so holding the hotkey does
    nothing. Returns None off Linux or when evdev is unavailable.
    """
    if sys.platform != "linux":
        return None
    try:
        from yazses.hotkeys.evdev_hold import EvdevHoldListener, _is_virtual_device
        from yazses.platform.linux.hotkey import resolve_key_id
    except Exception:
        return None
    key_id = cfg.hotkey.key if cfg is not None else "space"
    try:
        _, code = resolve_key_id(key_id)
    except Exception:
        return ("Hotkey device", "WARN", f"unknown hotkey {key_id!r}")
    try:
        listener = EvdevHoldListener(200, lambda _l: None, lambda: None, key_code=code)
        devs = listener._find_keyboards()
    except Exception as exc:
        # Permission / no-device issues are already surfaced by "Keyboard capture".
        return ("Hotkey device", "SKIP", f"could not enumerate input devices ({exc})")
    real = [d for d in devs if not _is_virtual_device(d)]
    if not real:
        dev = devs[0]
        return (
            "Hotkey device", "FAIL",
            f"bound to virtual device {dev.name!r} — real keypresses are not seen. "
            "Ensure your keyboard is in /dev/input and you are in the 'input' group.",
        )
    # The listener watches every real keyboard, so the hotkey fires no matter
    # which one you type on. Report them all.
    return ("Hotkey device", "OK", ", ".join(f"{d.name} ({d.path})" for d in real))


def _yazses_paths_on_path() -> list[str]:
    """Distinct resolved paths of `yazses` executables found on PATH (which -a)."""
    seen: list[str] = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        cand = Path(d) / "yazses"
        if cand.exists():
            real = str(cand.resolve())
            if real not in seen:
                seen.append(real)
    return seen


def _systemd_execstart() -> str | None:
    """The ExecStart binary path of the `yazses` user service, or None.

    None when not systemd-managed (no unit / not Linux / systemctl unavailable).
    """
    import re
    import subprocess

    if sys.platform != "linux":
        return None
    try:
        r = subprocess.run(
            ["systemctl", "--user", "show", "yazses", "-p", "ExecStart", "--value"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    out = r.stdout.strip()
    if not out:
        return None
    m = re.search(r"path=([^\s;]+)", out)
    return m.group(1) if m else None


def _install_consistency_checks() -> list[_Check]:
    """Catch the deployment traps that make a daemon silently run wrong/old code:
    multiple installs on PATH, and a systemd ExecStart that points at a missing
    or different binary (the `203/EXEC` crash-loop)."""
    if sys.platform != "linux":
        return []
    out: list[_Check] = []

    paths = _yazses_paths_on_path()
    if len(paths) > 1:
        out.append((
            "Install", "WARN",
            "multiple yazses on PATH (" + ", ".join(paths) + ") — keep one "
            "(uninstall the extras) so updates can't leave stale copies behind",
        ))

    exec_path = _systemd_execstart()
    if exec_path is not None:
        if not Path(exec_path).exists():
            out.append((
                "systemd unit", "FAIL",
                f"ExecStart={exec_path} does not exist — the service crash-loops "
                "(status 203/EXEC) and `yazses start`/`restart` start nothing. "
                "Point the unit at your real binary or reinstall.",
            ))
        else:
            daemon = shutil.which("yazses-daemon")
            if daemon and str(Path(daemon).resolve()) != str(Path(exec_path).resolve()):
                out.append((
                    "systemd unit", "WARN",
                    f"ExecStart={exec_path} differs from the yazses-daemon on PATH "
                    f"({daemon}) — the service may run a different or older build",
                ))
            else:
                out.append(("systemd unit", "OK", f"ExecStart={exec_path}"))
    return out


# ANSI colours for the doctor report. Emitted only to a real terminal so piped
# or redirected output (logs, `yazses doctor | grep`) stays plain text.
_ANSI = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
    "bred": "\033[1;31m", "bgred": "\033[1;97;41m",
}


def _color_enabled() -> bool:
    # streams.stdout_isatty() rather than sys.stdout.isatty(): a windowed
    # PyInstaller build has no console, so sys.stdout is None and the raw call
    # raises AttributeError — turning `doctor` into a crash dialog on Windows.
    return streams.stdout_isatty() and os.environ.get("NO_COLOR") is None


def _c(text: str, *styles: str) -> str:
    if not _color_enabled():
        return text
    return "".join(_ANSI[s] for s in styles) + text + _ANSI["reset"]


def _format_check(name: str, status: str, detail: str) -> str:
    """Render one doctor line, colouring the status tag and — for failures —
    making the fix (and any `sudo …` command in it) stand out in red/bold."""
    tag_style = {
        "OK": ("green",), "FAIL": ("bgred",), "WARN": ("yellow", "bold"),
        "SKIP": ("dim",),
    }.get(status, ("bold",))
    tag = _c(f"[{status}]", *tag_style)
    # Highlight command lines (indented `sudo …`/tool invocations) so the one
    # action a user must take — e.g. `sudo usermod -aG input $USER` — is obvious.
    lines = detail.split("\n")
    styled = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith(("sudo ", "sg ", "yazses ")) or " sudo " in ln:
            styled.append(_c(ln, "bred", "bold") if status == "FAIL" else _c(ln, "bold"))
        elif status == "FAIL":
            styled.append(_c(ln, "red"))
        else:
            styled.append(ln)
    detail_out = "\n".join(styled)
    return f"  {tag} {name}: {detail_out}"


def microphone_detail(state: str, *, snap_pending: bool, no_portaudio: bool) -> str:
    """What to print beside a failing microphone check. Pure.

    Extracted so the branch can be tested without running the whole doctor, which is
    how this file already treats every other decision it makes.

    The ordering matters. Inside the snap, PortAudio ships with the package, so an
    un-connected `audio-record` interface is the cause and must win. Outside it, a
    missing PortAudio runtime is the commonest reason a fresh `pipx`/`uv tool` install
    has no microphone — nothing pulls `libportaudio2` in, `sounddevice` raises on
    import, and `check_microphone` reports the same `UNKNOWN` it reports for a machine
    with no input hardware. Those two need opposite actions, and this row used to
    render both as the bare word "unknown".

    Naming the package unconditionally would be as wrong as never naming it: a machine
    that has PortAudio and no microphone must not be sent to apt.
    """
    if snap_pending:
        return "not granted — run: sudo snap connect yazses:audio-record"
    if no_portaudio:
        return (
            "PortAudio is not installed, so no audio device can be opened — "
            "run: sudo apt install libportaudio2  (pipx/uv installs do not pull it in)"
        )
    return state


def run_doctor(check_mic: bool = False, mic_seconds: float = 2.0) -> None:
    platform = get_platform()
    perms = platform.permissions
    paths = platform.paths

    # Load config once up front so the version/daemon/model/config checks can use
    # it; a malformed config degrades to defaults rather than crashing doctor.
    cfg = None
    try:
        from yazses.config import load_config
        # load_config returns defaults when the path is absent; pass it directly
        # rather than None (None falls back to the default user config path).
        cfg = load_config(paths.config_file)
    except Exception:
        cfg = None

    checks: list[_Check] = []

    # An experimental backend must say so here, not only in the docs. `doctor` is
    # the one place a user checks before trusting the tool, and "it printed OK" on
    # a platform nobody has run is exactly how an overclaim reaches someone.
    if platform.extras.get("experimental"):
        checks.append((
            "Platform",
            "WARN",
            f"{platform.name} — experimental: wired up and unit-tested, but never run "
            f"on real {platform.extras.get('family', 'this')} hardware. Please report "
            f"what happens: https://github.com/MSKazemi/yazses/issues",
        ))
    else:
        checks.append(("Platform", "OK", platform.name))
    checks.append(_version_check())
    checks.append(_daemon_check(platform))
    autostart = _autostart_check(platform)
    if autostart is not None:
        checks.append(autostart)

    # Install/lifecycle sanity: duplicate installs + a systemd ExecStart that
    # points at a missing/different binary (the silent "restart starts nothing").
    checks.extend(_install_consistency_checks())

    # Keyboard capture
    checks.append(_keyboard_capture_check(perms, platform.name))

    # Windows only: "Keyboard capture: ok" is about installing the hook and says
    # nothing about elevated windows, which UIPI excludes either way. Without
    # this line doctor reads as "input works everywhere" while dictation into an
    # admin window silently goes nowhere.
    elevation = _elevation_check(platform.name)
    if elevation is not None:
        checks.append(elevation)

    # ADR-v2-011 role map, when [modality] is on. Absent otherwise.
    modality = _modality_roles_check(cfg)
    if modality is not None:
        checks.append(modality)

    # Which input device the hotkey actually binds to (real keyboard vs a virtual
    # injector device). Surfaces the dead-hotkey failure mode directly.
    hotkey_dev = _hotkey_device_check(cfg)
    if hotkey_dev is not None:
        checks.append(hotkey_dev)

    # Microphone
    mic = perms.check_microphone()
    mic_detail = mic.value
    if mic not in (PermissionState.OK, PermissionState.NOT_APPLICABLE):
        from yazses.system.setup import portaudio_missing, snap_mic_pending

        mic_detail = microphone_detail(
            mic.value, snap_pending=snap_mic_pending(), no_portaudio=portaudio_missing()
        )
    checks.append((
        "Microphone",
        "OK" if mic in (PermissionState.OK, PermissionState.NOT_APPLICABLE) else "FAIL",
        mic_detail,
    ))

    # Opt-in passive mic-level vs VAD threshold (records a short ambient clip).
    if check_mic and cfg is not None:
        checks.append(_mic_level_check(cfg, mic_seconds))

    # Linux-specific injection tools
    if sys.platform == "linux":
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        is_x11 = bool(os.environ.get("DISPLAY"))
        session = "Wayland" if is_wayland else ("X11" if is_x11 else "unknown")
        session_ok = is_wayland or is_x11
        checks.append(("Session type", "OK" if session_ok else "WARN", session))

        # Injection backends are informational (only one is needed per session);
        # the actual pass/fail signal is the "Injection" readiness check below.
        checks.append(_tool("xdotool", required=False))
        checks.append(_tool("ydotool", required=False))
        checks.append(_tool("wtype",   required=False))
        checks.append(_tool("xclip",   required=False))
        checks.append(_tool("wl-copy", required=False))

        checks.extend(_injection_readiness(is_wayland, is_x11))

        # Whether "focus the browser" can work here. Wayland cannot, by design.
        window_focus = _window_focus_check(is_wayland, is_x11)
        if window_focus is not None:
            checks.append(window_focus)

    # Model cache (Hugging Face)
    # Ask huggingface_hub rather than re-deriving: HF_HUB_CACHE and
    # XDG_CACHE_HOME both override HF_HOME, and a wrong path here sends anyone
    # placing the model by hand to a directory nothing reads.
    from yazses.stt.download import hub_cache_dir

    hf_cache = hub_cache_dir()
    checks.append(("Model cache", "OK" if hf_cache.exists() else "WARN", str(hf_cache)))

    # Configured STT model availability (downloaded vs fetched-on-first-use).
    if cfg is not None:
        checks.append(_model_check(cfg.stt.model, hf_cache))

    # Config dir — create it if absent (first-run scenario)
    if paths.config_dir.exists():
        checks.append(("Config dir", "OK", str(paths.config_dir)))
    else:
        try:
            paths.config_dir.mkdir(parents=True, exist_ok=True)
            checks.append(("Config dir", "OK", f"{paths.config_dir} (created)"))
        except OSError as exc:
            checks.append(("Config dir", "FAIL", f"could not create: {exc}"))

    # Active config file, hotkey, and STT prompt summary.
    if cfg is not None:
        checks.extend(_config_summary(cfg, paths.config_file))

    # EMG serial port (when configured)
    try:
        if cfg is None:
            raise RuntimeError("config unavailable")
        if cfg.emg.device_port:
            port = Path(cfg.emg.device_port)
            checks.append((
                "EMG serial port",
                "OK" if port.exists() else "FAIL",
                f"{port} {'accessible' if port.exists() else 'not found'}",
            ))
        if cfg.emg.ble_address:
            checks.append(("EMG BLE address", "OK", cfg.emg.ble_address))
        prosody = _prosody_check(cfg.prosody.enabled)
        if prosody is not None:
            checks.append(prosody)
        dysfluency = _dysfluency_check(cfg.accessibility.dysfluency_friendly)
        if dysfluency is not None:
            checks.append(dysfluency)
        # v2 cognitive-layer extras (report only when the feature is enabled).
        for chk in (
            _extra_check("tts extra (kokoro-onnx)", cfg.tts.enabled,
                         "kokoro_onnx", "uv sync --extra tts"),
            _extra_check("voiceprint extra (speechbrain)",
                         cfg.voiceprint.enabled or cfg.cocktail.enabled,
                         "speechbrain", "uv sync --extra voiceprint"),
            _extra_check("gaze extra (l2cs)", cfg.gaze.enabled,
                         "l2cs", "pip install l2cs mediapipe opencv-python"),
            _extra_check("agent extra (Spoken MCP)", cfg.agent.enabled,
                         "mcp", "uv sync --extra agent"),
            _extra_check("pilot (AT-SPI)", cfg.pilot.enabled,
                         "pyatspi", "apt install python3-pyatspi gir1.2-atspi-2.0"),
        ):
            if chk is not None:
                checks.append(chk)
        # v2 features gated on config (not a module): report when half-configured.
        if cfg.agent.enabled and not cfg.agent.slm_model_path:
            checks.append(("agent planner", "WARN",
                           "dormant — set [agent] slm_model_path"))
        if cfg.polyglot.enabled and not cfg.polyglot.adapter_path:
            checks.append(("polyglot adapter", "WARN",
                           "dormant — set [polyglot] adapter_path (out-of-band CS model)"))
        if cfg.bridge.enabled:
            checks.append(("glasses↔desktop bridge", "OK",
                           f"will listen on port {cfg.bridge.listen_port}"))
    except Exception:
        pass

    print(f"YazSes doctor ({platform.name}):")
    for name, status, detail in checks:
        print(_format_check(name, status, detail))

    # Bottom-line verdict — the one thing a user wants to know: "am I good, and
    # what do I do next?" Summarises the checks above into a single next step.
    print("")
    print(_verdict_line(checks, cfg, platform))

    # Contact footer — where to report a problem doctor surfaced, or ask for a
    # feature. Keep this in step with src/yazses/branding.py.
    from yazses import branding

    print("")
    print("Need help, hit a bug, or want a feature?")
    print(f"  Author: {branding.AUTHOR} <{branding.EMAIL}>")
    print(f"  Issues: {branding.ISSUES}")


def _verdict_line(checks: list[_Check], cfg, platform) -> str:
    """One-line summary of the doctor run + the concrete next command to run.

    ``✗`` when anything failed, ``▲`` when only optional warnings remain, ``✓``
    when everything passed. Coloured to match the check tags above.
    """
    fails = sum(1 for c in checks if c[1] == "FAIL")
    warns = sum(1 for c in checks if c[1] == "WARN")
    # NOT `tag == "OK"`: a stale daemon is running *and* WARN, and reading the
    # tag told a running daemon to `yazses start`.
    daemon = next((c for c in checks if c[0] == "Daemon"), None)
    running = daemon is not None and daemon[2].startswith(_RUNNING_PREFIX)
    stale = daemon is not None and running and daemon[1] == "WARN"
    # Resolve the hotkey for the "hold X to dictate" hint (sentinels → default).
    key = getattr(getattr(cfg, "hotkey", None), "key", "") or ""
    if key in ("", "auto"):
        key = getattr(platform, "default_hotkey", "your hotkey")
    dictate_hint = "hold %s to dictate" % key
    if fails:
        n = fails
        return _c(
            f"✗ {n} problem{'s' if n != 1 else ''} to fix — see the [FAIL] line"
            f"{'s' if n != 1 else ''} above, fix "
            f"{'them' if n != 1 else 'it'}, then re-run `yazses doctor`.",
            "bred", "bold",
        )
    if not running:
        start_hint = f"run `yazses start`, then {dictate_hint}"
    elif stale:
        start_hint = f"run `yazses restart` to pick up the upgrade, then {dictate_hint}"
    else:
        start_hint = "you're all set — " + dictate_hint
    if warns:
        n = warns
        return _c(
            f"▲ Good to go ({n} optional warning{'s' if n != 1 else ''} above) — {start_hint}.",
            "yellow", "bold",
        )
    return _c(f"✓ Everything looks good — {start_hint}.", "green", "bold")
