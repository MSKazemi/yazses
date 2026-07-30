"""YazSes CLI. Talks to the daemon over IPC where possible, with a
PID-file fallback for status.
"""

from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Optional

import typer

from yazses import branding
from yazses.ipc.client import IpcUnreachableError
from yazses.platform import get_platform
from yazses.system.updater import check_update, run_upgrade

# `-h` is accepted everywhere alongside `--help`. Sub-apps each need their own
# copy (Typer does not propagate context settings into added sub-typers).
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

# rich help-panel section titles — group related commands in `yazses --help`
# instead of one long flat list.
_DAEMON = "Daemon"
_DICTATION = "Dictation & correction"
_SETUP = "Setup & calibration"
_LEARNING = "Learning & tuning"
_REMOTE = "Remote"
_MAINT = "Updates & maintenance"

def _examples(*lines: str) -> str:
    """Build an Examples epilog. Lines are joined with blank lines so rich keeps
    each on its own row (a single newline would be collapsed into a space)."""
    return "[bold]Examples[/bold]\n\n" + "\n\n".join(lines)


_APP_EPILOG = (
    _examples(
        "yazses quickstart            new here? the 3 steps to get dictating",
        "yazses start                 start dictating — hold the hotkey, speak, release",
        "yazses status                is it running? show state, model, and hotkey",
        "yazses doctor                check mic, keyboard, and injection prerequisites",
        "yazses mic-level --set       calibrate the mic threshold to your voice",
        "yazses test                  type a test phrase to confirm injection works",
        "yazses features              browse every capability + what's on/off",
        "yazses features info <name>  what a capability does + a usage example",
    )
    + "\n\n[bold]Tab completion[/bold]\n\n"
    + "yazses --install-completion  enable <Tab> completion for your shell\n\n"
    + "yazses --show-completion     print the completion script to inspect/customise"
    + "\n\n[bold]Help & contact[/bold]\n\n"
    + "yazses about                 author, links, and where to report issues\n\n"
    + f"Report a bug or request a feature: {branding.ISSUES}\n\n"
    + f"Made by {branding.AUTHOR} <{branding.EMAIL}>"
)

app = typer.Typer(
    name="yazses",
    help="Local, offline voice dictation — hold a key, speak, release.",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,          # bare `yazses` shows help instead of an error
    rich_markup_mode="rich",
    epilog=_APP_EPILOG,
)

model_app = typer.Typer(
    name="model",
    help="Manage SLM intent-routing models (download / list).",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(model_app, rich_help_panel=_SETUP)

corpus_app = typer.Typer(
    name="corpus",
    help="Inspect or clear the local learning corpus.",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(corpus_app, rich_help_panel=_LEARNING)

meeting_app = typer.Typer(
    name="meeting",
    help="Hands-free meeting recording with who-said-what speaker labels + notes.",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(meeting_app, rich_help_panel=_DICTATION)


def _meeting_dir(meeting_id: str):
    """Resolve a stored meeting's folder from its id (works without the daemon)."""
    from yazses.config import load_config
    from yazses.meeting import store

    cfg = load_config(get_platform().paths.config_file)
    return store.meetings_dir(cfg.meeting) / meeting_id


def _parse_pairs(items):
    """Parse ``["a=b", "c=d"]`` into ``{"a": "b", "c": "d"}`` for --merge/--rename."""
    out = {}
    for item in items or []:
        if "=" not in item:
            raise typer.BadParameter(f"expected KEY=VALUE, got {item!r}")
        key, val = item.split("=", 1)
        out[key.strip()] = val.strip()
    return out


@meeting_app.command("start")
def meeting_start() -> None:
    """Start recording a meeting (hands-free — no key to hold).

    Requires `[meeting] enabled = true` (`yazses features enable meeting`). Records
    continuously, streams a live transcript, and — at `yazses meeting stop` — writes a
    speaker-attributed transcript (and opt-in notes) to a per-meeting folder. On-device;
    audio is deleted after the post-pass unless `[meeting] retain_audio = true`.
    """
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        result = client.call("meeting_start")
    except IpcUnreachableError:
        typer.echo("Daemon is not running. Start it with: yazses start", err=True)
        raise typer.Exit(1)
    if result.get("ok"):
        if result.get("warning"):
            typer.echo(f"⚠ {result['warning']}", err=True)
        typer.echo(f"Recording meeting {result['meeting_id']}.")
        typer.echo(f"  Folder: {result['dir']}")
        typer.echo("  Watch it:  yazses meeting status")
        typer.echo("  Finish it: yazses meeting stop")
    else:
        typer.echo(f"Could not start meeting: {result.get('reason')}", err=True)
        raise typer.Exit(1)


@meeting_app.command("stop")
def meeting_stop() -> None:
    """Stop the recording and generate the speaker-labelled transcript (and notes)."""
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        result = client.call("meeting_stop")
    except IpcUnreachableError:
        typer.echo("Daemon is not running.", err=True)
        raise typer.Exit(1)
    if result.get("ok"):
        typer.echo(f"Stopped meeting {result['meeting_id']}. Transcribing + finding speakers…")
        typer.echo(f"  Results will appear in: {result['dir']}")
        typer.echo("  Check progress: yazses meeting status")
    else:
        typer.echo(f"Could not stop meeting: {result.get('reason')}", err=True)
        raise typer.Exit(1)


@meeting_app.command("status")
def meeting_status() -> None:
    """Show the running meeting (elapsed + live transcript) or recent meetings."""
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        result = client.call("meeting_status")
    except IpcUnreachableError:
        typer.echo("Daemon is not running.", err=True)
        raise typer.Exit(1)
    if result.get("active"):
        typer.echo(f"● Recording {result['id']} — {result['elapsed_s']:.0f}s, "
                   f"{result['line_count']} utterances")
        for line in result.get("live_lines", []):
            typer.echo(f"    {line}")
    elif result.get("finalizing"):
        typer.echo("Finalizing the last meeting (transcribing + diarizing)…")
    else:
        diar = result.get("diarization")
        if diar and diar.get("requested") and not diar.get("ready"):
            what = "extra not installed" if not diar.get("extra_installed") else "models missing"
            typer.echo(f"Speaker labels: unavailable ({what}) — "
                       "run `yazses transcribe --download-models`.")
        recent = result.get("recent", [])
        if not recent:
            typer.echo("No meetings yet. Start one with: yazses meeting start")
            return
        typer.echo("Recent meetings:")
        for m in recent:
            spk = m.get("num_speakers", "?")
            note = " +notes" if m.get("has_notes") else ""
            typer.echo(f"  {m.get('id')}  {spk} speaker(s){note}  {m.get('dir', '')}")


@meeting_app.command("list")
def meeting_list() -> None:
    """List stored meetings on this machine (no daemon required)."""
    from yazses.config import load_config
    from yazses.meeting import store

    cfg = load_config(get_platform().paths.config_file)
    meetings = store.list_meetings(cfg.meeting)
    if not meetings:
        typer.echo("No meetings found.")
        return
    for m in meetings:
        spk = m.get("num_speakers", "?")
        note = " +notes" if m.get("has_notes") else ""
        typer.echo(f"{m.get('id')}  {spk} speaker(s){note}  {m.get('dir', '')}")


@meeting_app.command("relabel")
def meeting_relabel(
    meeting_id: str = typer.Argument(..., help="Meeting id (see `yazses meeting list`)."),
    merge: list[str] = typer.Option(
        None, "--merge", help="Fold one speaker into another: SPEAKER_2=speaker_1 (repeatable)."
    ),
    rename: list[str] = typer.Option(
        None, "--rename", help="Name a speaker: speaker_1=Alice (repeatable)."
    ),
    fmt: str = typer.Option("md", "--format", "-f", help="Transcript format to re-render."),
) -> None:
    """Fix speaker labels — merge two clusters and/or rename them — and re-render.

    Corrects an auto-count miscount without re-transcribing or re-diarizing (it only
    re-renders from the stored `transcript.json`). Runs locally, no daemon needed.
    """
    from yazses.meeting import store

    d = _meeting_dir(meeting_id)
    if not (d / "transcript.json").exists():
        typer.echo(f"No transcript for meeting {meeting_id} in {d}.", err=True)
        raise typer.Exit(1)
    written = store.relabel(
        d, merges=_parse_pairs(merge), renames=_parse_pairs(rename), fmt=fmt
    )
    typer.echo(f"Re-rendered {meeting_id}:")
    for name, path in written.items():
        typer.echo(f"  {name}: {path}")


@meeting_app.command("notes")
def meeting_notes(
    meeting_id: str = typer.Argument(..., help="Meeting id to (re)generate notes for."),
) -> None:
    """Generate meeting minutes (summary, decisions, action items) from the transcript.

    Needs `[meeting] notes = true` and a local `notes_model` GGUF (ADR-v2-128). Runs the
    model locally — expect this to take a while on CPU.
    """
    from yazses.config import load_config
    from yazses.meeting import store
    from yazses.meeting.notes import generate_minutes, render_minutes_md

    cfg = load_config(get_platform().paths.config_file)
    d = _meeting_dir(meeting_id)
    if not (d / "transcript.json").exists():
        typer.echo(f"No transcript for meeting {meeting_id} in {d}.", err=True)
        raise typer.Exit(1)
    view = store.load_result_view(d)
    typer.echo("Generating minutes locally… (this can take a few minutes)")
    minutes = generate_minutes(view.utterances, cfg.meeting, speaker_names=view.speaker_names)
    if minutes is None:
        typer.echo(
            "Notes are off or no local model is set. Enable `[meeting] notes` and set "
            "`[meeting] notes_model` to a local GGUF.", err=True,
        )
        raise typer.Exit(1)
    out = d / "notes.md"
    out.write_text(render_minutes_md(minutes), encoding="utf-8")
    typer.echo(f"Wrote {out}")


@meeting_app.command("enroll")
def meeting_enroll(
    meeting_id: str = typer.Argument(..., help="Meeting id (see `yazses meeting list`)."),
    speaker: str = typer.Option(..., "--speaker", help="Cluster id to enroll, e.g. speaker_1."),
    name: str = typer.Option(..., "--name", help="The person's name, e.g. Alice."),
) -> None:
    """Enroll a meeting speaker as a named voiceprint so they're auto-named next time.

    Takes that cluster's audio from the stored recording, embeds it, and saves an
    encrypted voiceprint locally (ADR-011/012 — biometric, on-device, never uploaded).
    Explicit and opt-in: it enrolls only the speaker you name. Requires the recording to
    still exist, i.e. the meeting was recorded with `[meeting] retain_audio = true`.
    """
    from yazses.config import load_config
    from yazses.learning.crypto import Cipher, load_or_create_key
    from yazses.meeting.participants import enroll_participant
    from yazses.voiceprint.factory import build_embedder

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    d = _meeting_dir(meeting_id)
    if not (d / "transcript.json").exists():
        typer.echo(f"No transcript for meeting {meeting_id} in {d}.", err=True)
        raise typer.Exit(1)
    embedder = build_embedder(cfg.voiceprint)
    if embedder is None:
        typer.echo(
            "Voiceprint embedder unavailable — install it with "
            "`yazses features enable voiceprint`.", err=True,
        )
        raise typer.Exit(1)
    cipher = Cipher(load_or_create_key(platform.paths.data_dir))
    try:
        path = enroll_participant(
            d, speaker, name, embedder=embedder, cipher=cipher, config=cfg.meeting,
            sample_rate=cfg.audio.sample_rate,
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"Could not enroll {name}: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Enrolled {name} (from {speaker}). Future meetings will auto-name them.")
    typer.echo(f"  Voiceprint: {path}  (encrypted, on-device — ADR-011/012)")


def _resolved_hotkey(platform) -> str:
    """The hotkey the daemon will actually bind: the configured ``[hotkey] key``
    when present, else the platform default. CLI messages should reflect what the
    user configured, not the bare platform default."""
    try:
        from yazses.config import load_config

        # Pass the path directly: load_config returns defaults when it doesn't
        # exist. (Passing None would fall back to the *default* user config path,
        # which may differ from this platform's config_file.)
        cfg = load_config(platform.paths.config_file)
        key = cfg.hotkey.key
        # "auto" (and the empty string) mean "use the platform default" — resolve
        # it so messages show the real key (e.g. right_alt), never the sentinel.
        if not key or key == "auto":
            return platform.default_hotkey
        return key
    except Exception:
        return platform.default_hotkey


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"yazses {_pkg_version('yazses')}")
        raise typer.Exit()


@app.command(
    rich_help_panel=_MAINT,
    epilog=_examples(
        "yazses about    author, version, links, and where to report a bug or request a feature",
    ),
)
def about() -> None:
    """Show author, version, links, and where to report issues or request features."""
    typer.echo(branding.banner())
    typer.echo("")
    for line in branding.contact_lines():
        typer.echo(line)
    typer.echo("")
    typer.echo(
        "Found a bug or want a new feature? Open an issue at the Issues link above, "
        f"or email {branding.EMAIL}."
    )


@app.callback()
def _main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-V",
        callback=_version_callback, is_eager=True, help="Show version and exit.",
    ),
) -> None:
    pass


def _kill_yazses_daemons(sig) -> int:
    """Linux: signal every yazses daemon process (systemd + detached `yazses.main`).

    Returns the count signalled. The detached `yazses start` path reparents to the
    systemd user manager and survives `systemctl stop`, so a clean restart must hunt
    them by command line, not just the PID file.
    """
    import os
    import subprocess
    import sys

    if sys.platform != "linux":
        return 0
    # Exclude this process AND the shell that launched us, so a command line that
    # happens to contain the pattern can never get itself killed.
    safe = {os.getpid(), os.getppid()}
    killed = 0
    # Precise patterns ([.] = literal dot) — match only the real daemon invocations
    # (`…/bin/yazses-daemon` and `python -m yazses.main`), never `yazses restart` etc.
    for pat in ("bin/yazses-daemon", "yazses[.]main"):
        try:
            out = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True)
        except Exception:
            continue
        for tok in out.stdout.split():
            try:
                pid = int(tok)
            except ValueError:
                continue
            if pid not in safe:
                try:
                    os.kill(pid, sig)
                    killed += 1
                except ProcessLookupError:
                    pass
    return killed


def _systemd_managed() -> bool:
    import subprocess
    import sys

    if sys.platform != "linux":
        return False
    try:
        r = subprocess.run(
            ["systemctl", "--user", "list-unit-files", "yazses.service"],
            capture_output=True, text=True,
        )
        return "yazses.service" in r.stdout
    except Exception:
        return False


def _restart_daemon(platform) -> None:
    """Stop ALL daemons (no duplicates) and start exactly one."""
    import signal
    import time

    if _systemd_managed():
        try:
            __import__("subprocess").run(["systemctl", "--user", "stop", "yazses"])
        except Exception:
            pass
    pid = platform.lifecycle.read_pid()
    if pid:
        try:
            platform.lifecycle.stop_daemon(pid)
        except Exception:
            pass
    _kill_yazses_daemons(signal.SIGTERM)
    time.sleep(1)
    _kill_yazses_daemons(signal.SIGKILL)  # force any survivor
    try:
        (platform.paths.data_dir / "daemon.lock").unlink(missing_ok=True)
    except Exception:
        pass
    platform.lifecycle.clear_pid()
    _spawn_daemon(platform)


def _spawn_daemon(platform) -> None:
    """Launch exactly one daemon. When a systemd user unit is installed we start
    it through systemd so it is supervised and self-heals (``Restart=on-failure``);
    otherwise we fall back to a detached process."""
    if _systemd_managed():
        __import__("subprocess").run(["systemctl", "--user", "start", "yazses"])
    else:
        platform.lifecycle.start_daemon_detached()


def _wait_until_ready(platform, timeout: float = 20.0):
    """Poll the freshly-spawned daemon until it reports ready.

    The daemon writes its PID *before* loading the STT model / opening the mic,
    so a crash during startup (e.g. a PortAudio/ALSA abort) shows up as the PID
    appearing and then vanishing. Returns one of:

    - ``"ready"``   — daemon is up and listening for the hotkey.
    - ``"died"``    — the process exited during startup (crash / bad config).
    - ``"loading"`` — still alive but not ready before ``timeout`` (slow first-run
      model load); not an error, just informational.

    Second element is the last IPC ``status`` dict seen (or ``None``).
    """
    import time

    deadline = time.monotonic() + timeout
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    saw_pid = False
    last_info = None
    while time.monotonic() < deadline:
        running = platform.lifecycle.is_running()
        if running:
            saw_pid = True
        elif saw_pid:
            # The PID file appeared and then the process died → crashed on startup.
            return "died", last_info
        try:
            info = client.call("status")
            last_info = info
            state = str(info.get("state", "")).lower()
            if info.get("ready") or state in ("idle", "recording", "injecting"):
                return "ready", info
            if state == "error":
                return "died", info
        except IpcUnreachableError:
            pass  # IPC socket not up yet (or already gone) — keep polling
        time.sleep(0.25)
    return "loading", last_info


def _report_start_outcome(platform, outcome: str, info) -> None:
    """Print an honest, actionable message for a start/restart outcome and set a
    non-zero exit code when the daemon failed to come up."""
    hotkey = _resolved_hotkey(platform)
    if outcome == "ready":
        typer.echo(f"YazSes started. Hold {hotkey} to dictate.")
        return
    if outcome == "loading":
        typer.echo(
            "YazSes is starting — the speech model is still loading "
            "(first run can take 10–30s). It'll be ready shortly; "
            "check with `yazses status`."
        )
        return
    # died
    typer.echo("YazSes failed to start — the daemon exited during startup.", err=True)
    last_error = (info or {}).get("last_error") if isinstance(info, dict) else None
    if last_error:
        typer.echo(f"  reason: {last_error}", err=True)
    typer.echo(
        "  Run `yazses doctor` to check prerequisites and `yazses logs` for details.",
        err=True,
    )
    raise typer.Exit(1)


@app.command(
    rich_help_panel=_DAEMON,
    epilog=_examples("yazses start    start dictating — hold the hotkey, speak, release"),
)
def start() -> None:
    """Start the YazSes daemon (restarts cleanly if one is already running).

    Loads the speech model once and listens for the hotkey. If a daemon is already
    running this **restarts** it (killing any stray duplicates) rather than spawning
    a second one — so you never end up double-typing.
    """
    platform = get_platform()
    _warn_unmet_prereqs()
    if platform.lifecycle.is_running():
        typer.echo("YazSes is already running — restarting it cleanly...")
        _restart_daemon(platform)
    else:
        platform.lifecycle.clear_pid()
        _spawn_daemon(platform)
    outcome, info = _wait_until_ready(platform)
    _report_start_outcome(platform, outcome, info)


@app.command(
    rich_help_panel=_DAEMON,
    epilog=_examples("yazses restart    stop every daemon and start exactly one"),
)
def restart() -> None:
    """Restart the daemon — kills any stray/duplicate daemons and starts exactly one.

    Use this if dictation is being typed twice (a sign of duplicate daemons).
    """
    platform = get_platform()
    _warn_unmet_prereqs()
    _restart_daemon(platform)
    outcome, info = _wait_until_ready(platform)
    _report_start_outcome(platform, outcome, info)


def _warn_unmet_prereqs() -> None:
    """Print actionable warnings if system prerequisites are missing or a pending
    `input`-group re-login would leave the hotkey dead. Best-effort and silent
    when fully provisioned; never blocks startup."""
    import sys as _sys

    if _sys.platform != "linux":
        return
    try:
        from yazses.system.setup import preflight_hints

        for hint in preflight_hints():
            _echo_action_hint(hint)
    except Exception:
        pass  # a diagnostic must never prevent the daemon from starting


def _echo_action_hint(hint: str) -> None:
    """Print a preflight warning to stderr, red + bold, with any `sudo …`/`yazses …`
    command line highlighted so the one action the user must take is unmissable."""
    err = True
    typer.secho("⚠  ACTION NEEDED", fg=typer.colors.BRIGHT_RED, bold=True, err=err)
    for ln in hint.split("\n"):
        stripped = ln.strip()
        if stripped.startswith(("sudo ", "sg ", "yazses ")):
            # The actual command — brightest treatment (bold white on red).
            typer.secho(f"    {stripped}", fg=typer.colors.BRIGHT_WHITE,
                        bg=typer.colors.RED, bold=True, err=err)
        else:
            typer.secho(f"   {ln}" if not ln.startswith(" ") else ln,
                        fg=typer.colors.RED, err=err)


features_app = typer.Typer(
    name="features",
    help="See capabilities and turn them on/off (no config-editing needed).",
    context_settings=CONTEXT_SETTINGS,
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(features_app, rich_help_panel=_DAEMON)


@features_app.callback(
    invoke_without_command=True,
    epilog=_examples(
        "yazses features                  list every capability, grouped, + advice",
        "yazses features --on             show only what's currently enabled",
        "yazses features --tier rec       show only the recommended tier",
        "yazses features --category Multilingual   show one category",
        "yazses features info              describe ALL capabilities + usage examples",
        "yazses features info reflow       describe one + show a usage example",
        "yazses features enable read-back  turn one on",
        "yazses features disable cocktail  turn one off",
    ),
)
def features(
    ctx: typer.Context,
    on_only: bool = typer.Option(
        False, "--on", help="Show only capabilities that are currently ON."
    ),
    tier: Optional[str] = typer.Option(
        None, "--tier",
        help="Filter by advice tier: core, on, rec, opt, exp.",
    ),
    category: Optional[str] = typer.Option(
        None, "--category", "-c",
        help="Filter by category name (partial, case-insensitive), e.g. 'access'.",
    ),
) -> None:
    """Show every YazSes capability, grouped by what it does, with on/off + advice.

    Capabilities are clustered into functional groups (Core dictation, Accuracy &
    correction, Formatting & structure, …). Narrow the list with --on, --tier, or
    --category. Turn things on/off with `yazses features enable <name>` /
    `yazses features disable <name>` — then `yazses restart` to apply.
    """
    if ctx.invoked_subcommand is not None:
        return  # a subcommand (enable/disable) is running instead
    _echo_capabilities(get_platform(), on_only=on_only, tier=tier, category=category)


# Advice-tier synonyms accepted by `yazses features --tier`.
_TIER_ALIASES = {
    "core": "core", "on": "on", "default": "on", "default-on": "on",
    "rec": "rec", "recommended": "rec", "opt": "opt", "optional": "opt",
    "exp": "exp", "experimental": "exp",
}


def _echo_capabilities(
    platform,
    *,
    header: str | None = None,
    on_only: bool = False,
    tier: str | None = None,
    category: str | None = None,
) -> None:
    """Print every capability (● on / ○ off), grouped by category, with advice.

    Shared by `yazses features` and the post-install/`yazses setup` summary so a
    new user always sees the full feature set. Needs no running daemon — reads the
    config file, defaulting when it doesn't exist yet. Optional filters narrow the
    view by state (on_only), advice tier, or category name.
    """
    from yazses.config import load_config
    from yazses.system.features import grouped_features

    cfg = load_config(platform.paths.config_file)

    tier_key = None
    if tier is not None:
        tier_key = _TIER_ALIASES.get(tier.strip().lower())
        if tier_key is None:
            typer.echo(
                f"Unknown tier {tier!r}. Use one of: core, on, rec, opt, exp.",
                err=True,
            )
            raise typer.Exit(1)
    cat_needle = category.strip().lower() if category else None

    def _keep(f) -> bool:
        if on_only and not f.on:
            return False
        if tier_key is not None and f.tier != tier_key:
            return False
        return True

    groups = grouped_features(cfg)
    if cat_needle:
        groups = [g for g in groups if cat_needle in g[0].lower()]

    typer.echo(
        header
        or "YazSes capabilities — toggle with `yazses features enable/disable <name>`:\n"
    )
    total = 0
    for cat, blurb, feats in groups:
        shown = [f for f in feats if _keep(f)]
        if not shown:
            continue
        on_n = sum(1 for f in shown if f.on)
        typer.echo(f"┌─ {cat}  ({on_n}/{len(shown)} on)")
        if blurb:
            typer.echo(f"│  {blurb}")
        typer.echo(f"│  {'':5}  {'NAME':<32} {'TOGGLE NAME':<16} ADVICE")
        for f in shown:
            mark = "● ON " if f.on else "○ off"
            slug = f.slug if f.toggleable else "—"
            typer.echo(f"│  {mark}  {f.name:<32} {slug:<16} {f.tier_label}")
        typer.echo("└" + "─" * 40)
        total += len(shown)

    if total == 0:
        typer.echo("  No capabilities match that filter.")
        return
    typer.echo(
        f"\n  {total} shown.  ●/○ = on/off.  Apply changes with `yazses restart`."
        "\n  Tip: `yazses features enable dysfluency` (use the TOGGLE NAME column)."
        "\n  Filter:  --on · --tier rec · --category access"
        "\n  Describe ALL capabilities (use case + example): `yazses features info`."
        "\n  Just one: `yazses features info <name>`."
    )


def _echo_feature_card(feat, *, full: bool) -> None:
    """Print one capability. `full` adds the enable/disable/apply block (single view);
    the compact form (used by the catalog) is name + description + example only."""
    state = "● ON " if feat.on else "○ off"
    slug = feat.slug if feat.toggleable else "core"
    typer.echo(f"{state} {feat.name}  [{slug}]  ({feat.tier_label})")
    if feat.why:
        typer.echo(f"       {feat.why}")
    if feat.use_case:
        typer.echo(f"       Use when:  {feat.use_case}")
    if feat.example:
        label = "Example:" if full else "e.g.    "
        typer.echo(f"       {label}  {feat.example}")
    if full:
        if feat.toggleable:
            typer.echo(f"\n  Enable:   yazses features enable {feat.slug}")
            typer.echo(f"  Disable:  yazses features disable {feat.slug}")
            typer.echo("  Apply:    yazses restart")
        else:
            typer.echo("\n  Always on — not toggleable.")


@features_app.command(
    "info",
    epilog=_examples(
        "yazses features info            describe EVERY capability + a usage example",
        "yazses features info reflow     describe one capability + how to toggle it",
        "yazses features info | less     page the full catalog",
    ),
)
def features_info(
    name: Optional[str] = typer.Argument(
        None,
        help="Feature name, e.g. reflow. Omit to describe EVERY capability.",
    ),
) -> None:
    """Describe a capability — what it does, a usage example, and how to toggle it.

    With no name, prints the whole catalog (every capability + example) — the one
    place that shows all features and how to use them. Pipe to a pager for long
    output, e.g. `yazses features info | less`.
    """
    from yazses.config import load_config
    from yazses.system.features import feature_status, find_feature

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)

    if name is None:
        feats = feature_status(cfg)
        on = sum(1 for f in feats if f.on)
        typer.echo(
            f"YazSes capabilities ({len(feats)} total, {on} on) — what each does "
            "and how to use it:\n"
        )
        for feat in feats:
            _echo_feature_card(feat, full=False)
            typer.echo("")
        typer.echo(
            "Turn one on:  yazses features enable <name>   then  yazses restart\n"
            "One feature:  yazses features info <name>"
        )
        return

    feat = find_feature(cfg, name)
    if feat is None:
        known = ", ".join(f.slug for f in feature_status(cfg))
        typer.echo(f"Unknown feature {name!r}. Names: {known}", err=True)
        raise typer.Exit(1)
    _echo_feature_card(feat, full=True)


def _apply_feature_writes(config_file, writes) -> None:
    from yazses.system.configedit import set_config_key

    for section, key, value, quote in writes:
        set_config_key(config_file, section, key, value, quote=quote)


@features_app.command(
    "enable",
    epilog=_examples(
        "yazses features enable read-back        turn a capability on",
        "yazses features enable cocktail --force  enable an experimental one",
        "yazses restart                          apply the change",
    ),
)
def features_enable(
    name: str = typer.Argument(..., help="Toggle name, e.g. read-back (see `yazses features`)."),
    force: bool = typer.Option(False, "--force", help="Allow enabling experimental features."),
    no_install: bool = typer.Option(
        False, "--no-install", help="Don't auto-install the feature's optional deps."
    ),
) -> None:
    """Turn a capability ON (writes your config), then `yazses restart` to apply.

    Use the TOGGLE NAME column from `yazses features`. Experimental features
    (e.g. cocktail, gaze) refuse to enable without --force. Any optional Python
    dependencies the feature needs are installed automatically (skip with
    --no-install).
    """
    from yazses.config import load_config
    from yazses.system.features import EXPERIMENTAL, find_feature, toggleable_slugs

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    feat = find_feature(cfg, name)
    if feat is None or not feat.toggleable:
        typer.echo(
            f"Unknown feature {name!r}. Toggle names: {', '.join(toggleable_slugs())}",
            err=True,
        )
        raise typer.Exit(1)
    if feat.tier == EXPERIMENTAL and not force:
        typer.echo(f"{feat.name} is experimental — {feat.why}", err=True)
        typer.echo("Enable anyway with: yazses features enable "
                   f"{feat.slug} --force", err=True)
        raise typer.Exit(1)
    _apply_feature_writes(platform.paths.config_file, feat.on_writes)
    typer.echo(f"Enabled {feat.name}.  {feat.why}")
    _install_feature_deps(feat, skip=no_install)
    typer.echo("Apply it:  yazses restart")


def _install_feature_deps(feat, *, skip: bool) -> None:
    """Install a feature's optional pip deps when any are missing."""
    if not feat.pip_packages:
        return
    from yazses.system.deps import install_packages, missing_modules

    missing = missing_modules(feat.check_modules) if feat.check_modules else list(feat.pip_packages)
    if not missing:
        return
    if skip:
        typer.echo(
            "Skipping dependency install (--no-install). This feature needs:\n  "
            + " ".join(feat.pip_packages)
        )
        return
    install_packages(feat.pip_packages, echo=typer.echo)


@features_app.command(
    "disable",
    epilog=_examples(
        "yazses features disable cocktail    turn a capability off",
        "yazses restart                      apply the change",
    ),
)
def features_disable(
    name: str = typer.Argument(..., help="Toggle name, e.g. cocktail (see `yazses features`)."),
) -> None:
    """Turn a capability OFF (writes your config), then `yazses restart` to apply."""
    from yazses.config import load_config
    from yazses.system.features import find_feature, toggleable_slugs

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    feat = find_feature(cfg, name)
    if feat is None or not feat.toggleable:
        typer.echo(
            f"Unknown feature {name!r}. Toggle names: {', '.join(toggleable_slugs())}",
            err=True,
        )
        raise typer.Exit(1)
    _apply_feature_writes(platform.paths.config_file, feat.off_writes)
    typer.echo(f"Disabled {feat.name}.")
    typer.echo("Apply it:  yazses restart")


vocab_app = typer.Typer(
    name="vocab",
    help="Manage your personal dictionary (words STT mis-hears).",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(vocab_app, rich_help_panel=_SETUP)


@vocab_app.command(
    "add",
    epilog=_examples(
        "yazses vocab add YazSes             add one word/name",
        "yazses vocab add Kubernetes kubectl  add several at once",
        "yazses restart                      apply so STT spells them right",
    ),
)
def vocab_add(
    words: list[str] = typer.Argument(..., help="One or more words/names to add."),
) -> None:
    """Add words to the dictionary so YazSes spells them right (then `yazses restart`).

    Good for names, jargon, and acronyms that Whisper keeps mis-hearing. The
    words are primed into the STT prompt; they bias recognition, not force it.
    """
    from yazses.system.vocabulary import add_vocab, vocab_path

    platform = get_platform()
    path = vocab_path(platform.paths.config_file.parent)
    full = add_vocab(path, words)
    typer.echo(f"Added {', '.join(words)}. Dictionary now has {len(full)} word(s).")
    typer.echo("Apply it: yazses restart")


@vocab_app.command(
    "list",
    epilog=_examples("yazses vocab list    show every word in your personal dictionary"),
)
def vocab_list() -> None:
    """Show the words in your personal dictionary."""
    from yazses.system.vocabulary import load_vocab, vocab_path

    platform = get_platform()
    words = load_vocab(vocab_path(platform.paths.config_file.parent))
    if not words:
        typer.echo("Dictionary is empty. Add words with: yazses vocab add <word> ...")
        return
    for w in words:
        typer.echo(f"  {w}")


@vocab_app.command(
    "remove",
    epilog=_examples("yazses vocab remove kubectl    drop a word, then yazses restart"),
)
def vocab_remove(word: str = typer.Argument(..., help="The word to remove.")) -> None:
    """Remove a word from your personal dictionary (then `yazses restart`)."""
    from yazses.system.vocabulary import remove_vocab, vocab_path

    platform = get_platform()
    remaining = remove_vocab(vocab_path(platform.paths.config_file.parent), word)
    typer.echo(f"Removed {word!r}. Dictionary now has {len(remaining)} word(s).")


acronyms_app = typer.Typer(
    name="acronyms",
    help="Manage a persistent acronym glossary and expand acronyms in text — offline.",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(acronyms_app, rich_help_panel=_DICTATION)


def _acronyms_path():
    from yazses.acronyms.store import glossary_path

    return glossary_path(get_platform().paths.config_file.parent)


@acronyms_app.command(
    "add",
    epilog=_examples('yazses acronyms add API "Application Programming Interface"'),
)
def acronyms_add(
    acronym: str = typer.Argument(..., help="The acronym, e.g. API."),
    full: list[str] = typer.Argument(..., help="Its full form, e.g. Application Programming Interface."),
) -> None:
    """Register an acronym → full-form expansion in your glossary."""
    from yazses.acronyms.store import add_entry

    glossary = add_entry(_acronyms_path(), acronym, " ".join(full))
    typer.echo(f"Saved {acronym.upper()}. Glossary now has {len(glossary)} entr(y/ies).")


@acronyms_app.command("list", epilog=_examples("yazses acronyms list    show every stored acronym"))
def acronyms_list() -> None:
    """Show your stored acronym glossary."""
    from yazses.acronyms.store import load_glossary

    glossary = load_glossary(_acronyms_path())
    if not glossary:
        typer.echo("Glossary is empty. Add one with: yazses acronyms add <ACR> <full form>")
        return
    for acr, full in glossary.items():
        typer.echo(f"  {acr}\t{full}")


@acronyms_app.command("remove", epilog=_examples("yazses acronyms remove API    drop an entry"))
def acronyms_remove(acronym: str = typer.Argument(..., help="The acronym to remove.")) -> None:
    """Remove an acronym from your glossary."""
    from yazses.acronyms.store import remove_entry

    glossary = remove_entry(_acronyms_path(), acronym)
    typer.echo(f"Removed {acronym.upper()}. Glossary now has {len(glossary)} entr(y/ies).")


@acronyms_app.command(
    "expand",
    epilog=_examples(
        'yazses acronyms expand "The API and the API"   -> expands first use only',
        "cat notes.txt | yazses acronyms expand           read stdin",
    ),
)
def acronyms_expand(
    text: Optional[str] = typer.Argument(None, help="Text to expand (omit to read stdin)."),
) -> None:
    """Expand known acronyms on first use ('Full Name (ACR)'), contract after — offline.

    Use it when: you have a stored glossary and want a draft where every acronym is
    spelled out the first time it appears, per house style, without hand-editing.

    Uses your saved glossary (`yazses acronyms add`). Reads the TEXT argument, or
    standard input when omitted.
    """
    import sys as _sys

    from yazses.acronyms.glossary import expand_document
    from yazses.acronyms.store import load_glossary

    glossary = load_glossary(_acronyms_path())
    src = text if text is not None else _sys.stdin.read()
    typer.echo(expand_document(src, glossary))


wordgoal_app = typer.Typer(
    name="wordgoal",
    help="Track words written against a writing goal, across invocations — offline.",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(wordgoal_app, rich_help_panel=_DICTATION)


def _wordgoal_path():
    from yazses.wordgoal.store import wordgoal_path

    return wordgoal_path(get_platform().paths.config_file.parent)


@wordgoal_app.command(
    "add",
    epilog=_examples(
        'yazses wordgoal add "the words I just wrote"   add a chunk to the running count',
        "cat draft.txt | yazses wordgoal add             count a whole file",
    ),
)
def wordgoal_add(
    text: Optional[str] = typer.Argument(None, help="Text to count (omit to read stdin)."),
) -> None:
    """Add a chunk of text to your running word count and show progress."""
    import sys as _sys

    from yazses.wordgoal.store import load_state, save_state
    from yazses.wordgoal.tracker import count_words, render_progress

    src = text if text is not None else _sys.stdin.read()
    st = load_state(_wordgoal_path())
    st = save_state(_wordgoal_path(), count=st["count"] + count_words(src), goal=st["goal"])
    typer.echo(render_progress(st["count"], st["goal"]))


@wordgoal_app.command("status", epilog=_examples("yazses wordgoal status    show progress toward your goal"))
def wordgoal_status() -> None:
    """Show your current word count and goal progress."""
    from yazses.wordgoal.store import load_state
    from yazses.wordgoal.tracker import render_progress

    st = load_state(_wordgoal_path())
    typer.echo(render_progress(st["count"], st["goal"]))


@wordgoal_app.command("goal", epilog=_examples("yazses wordgoal goal 500    set a 500-word target"))
def wordgoal_goal(
    words: int = typer.Argument(..., help="Target word count (0 clears the goal)."),
) -> None:
    """Set (or clear, with 0) your writing goal."""
    from yazses.wordgoal.store import load_state, save_state
    from yazses.wordgoal.tracker import render_progress

    st = load_state(_wordgoal_path())
    st = save_state(_wordgoal_path(), count=st["count"], goal=words)
    typer.echo(render_progress(st["count"], st["goal"]))


@wordgoal_app.command("reset", epilog=_examples("yazses wordgoal reset    zero the count (keeps the goal)"))
def wordgoal_reset() -> None:
    """Reset the word count to zero (keeps the goal)."""
    from yazses.wordgoal.store import load_state, save_state

    st = load_state(_wordgoal_path())
    save_state(_wordgoal_path(), count=0, goal=st["goal"])
    typer.echo("Word count reset to 0.")


cliphistory_app = typer.Typer(
    name="cliphistory",
    help="A persistent clipboard history you can recall by voice-style reference — offline.",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(cliphistory_app, rich_help_panel=_DICTATION)


def _cliphistory_path():
    from yazses.cliphistory.store import cliphistory_path

    return cliphistory_path(get_platform().paths.config_file.parent)


@cliphistory_app.command(
    "add",
    epilog=_examples(
        'yazses cliphistory add "https://example.com"   remember a copied string',
        "cat snippet.txt | yazses cliphistory add          remember piped text",
    ),
)
def cliphistory_add(
    text: Optional[str] = typer.Argument(None, help="Text to remember (omit to read stdin)."),
) -> None:
    """Add an entry to your clipboard history (newest first, de-duplicated, capped)."""
    import sys as _sys

    from yazses.cliphistory.store import add_item

    src = text if text is not None else _sys.stdin.read()
    src = src.strip("\n")
    if not src:
        typer.echo("Nothing to add (empty input).", err=True)
        raise typer.Exit(1)
    items = add_item(_cliphistory_path(), src)
    typer.echo(f"Saved. History now has {len(items)} entr(y/ies).")


@cliphistory_app.command("list", epilog=_examples("yazses cliphistory list    show history, newest first"))
def cliphistory_list() -> None:
    """Show your clipboard history, newest first."""
    from yazses.cliphistory.store import load_items

    items = load_items(_cliphistory_path())
    if not items:
        typer.echo("Clipboard history is empty. Add one with: yazses cliphistory add <text>")
        return
    for i, it in enumerate(items, start=1):
        typer.echo(f"  {i}. {it}")


@cliphistory_app.command(
    "recall",
    epilog=_examples(
        'yazses cliphistory recall "the last url"     print the newest URL entry',
        'yazses cliphistory recall "the second one"    print entry #2',
    ),
)
def cliphistory_recall(
    query: str = typer.Argument(..., help="Spoken-style reference, e.g. 'the last url', 'number 3'."),
) -> None:
    """Print the history entry a spoken reference points to — offline.

    Understands url/link, email, ordinals (last/second/…), first/oldest, and 'number N';
    defaults to the most recent entry. Exits non-zero if nothing matches.
    """
    from yazses.cliphistory.history import resolve_reference
    from yazses.cliphistory.store import load_items

    hit = resolve_reference(query, load_items(_cliphistory_path()))
    if hit is None:
        typer.echo("No matching clipboard entry.", err=True)
        raise typer.Exit(1)
    typer.echo(hit)


outline_app = typer.Typer(
    name="outline",
    help="Build a nested outline incrementally and render it to Markdown/OPML — offline.",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(outline_app, rich_help_panel=_DICTATION)


def _outline_path():
    from yazses.outline.store import outline_path

    return outline_path(get_platform().paths.config_file.parent)


def _outline_apply_and_render(op: str, text: str = "") -> None:
    from yazses.outline.store import load_outline, save_outline
    from yazses.outline.tree import apply_outline_op, render

    state = apply_outline_op(load_outline(_outline_path()), op, text)
    save_outline(_outline_path(), state)
    rendered = render(state, "markdown")
    typer.echo(rendered if rendered else "(empty outline)")


@outline_app.command(
    "add",
    epilog=_examples(
        'yazses outline add "Chapter 1"    add an item at the current level',
        'yazses outline add "Intro" && yazses outline indent   nest the last item',
    ),
)
def outline_add(
    text: str = typer.Argument(..., help="The outline item text."),
) -> None:
    """Add an item after the cursor (same level) and show the outline."""
    _outline_apply_and_render("add", text)


@outline_app.command("indent", epilog=_examples("yazses outline indent    nest the last item one level deeper"))
def outline_indent() -> None:
    """Indent the current item one level deeper (max one deeper than the item above)."""
    _outline_apply_and_render("indent")


@outline_app.command("promote", epilog=_examples("yazses outline promote    move the last item one level shallower"))
def outline_promote() -> None:
    """Promote the current item one level shallower (floor 0)."""
    _outline_apply_and_render("promote")


@outline_app.command(
    "render",
    epilog=_examples(
        "yazses outline render               Markdown bullets",
        "yazses outline render --format opml  OPML for an outliner",
    ),
)
def outline_render(
    fmt: str = typer.Option("markdown", "--format", "-f", help="markdown | opml."),
) -> None:
    """Render the current outline to Markdown or OPML."""
    from yazses.outline.store import load_outline
    from yazses.outline.tree import render

    out = render(load_outline(_outline_path()), fmt)
    typer.echo(out if out else "(empty outline)")


@outline_app.command("clear", epilog=_examples("yazses outline clear    start a fresh outline"))
def outline_clear() -> None:
    """Discard the current outline and start fresh."""
    from yazses.outline.store import save_outline
    from yazses.outline.tree import new_outline

    save_outline(_outline_path(), new_outline())
    typer.echo("Outline cleared.")


srs_app = typer.Typer(
    name="srs",
    help="Capture facts as spaced-repetition flashcards and schedule reviews (SM-2) — offline.",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(srs_app, rich_help_panel=_DICTATION)


def _srs_path():
    from yazses.srscap.store import srscap_path

    return srscap_path(get_platform().paths.config_file.parent)


@srs_app.command(
    "capture",
    epilog=_examples(
        'yazses srs capture "remember that the capital of France is Paris"',
        "cat fact.txt | yazses srs capture    capture a fact from piped text",
    ),
)
def srs_capture(
    text: Optional[str] = typer.Argument(None, help="An utterance containing a fact (omit for stdin)."),
) -> None:
    """Capture a 'remember that X is Y' fact as a cloze flashcard — offline.

    Use it when: something worth remembering comes up mid-dictation and you want it as a
    review card without breaking flow. Exits non-zero if no fact is detected.
    """
    import sys as _sys

    from yazses.srscap.cards import detect_fact, to_cloze
    from yazses.srscap.store import add_card

    src = text if text is not None else _sys.stdin.read()
    fact = detect_fact(src)
    if fact is None:
        typer.echo(
            "No fact detected. Phrase it like 'remember that <X> is <Y>'.", err=True,
        )
        raise typer.Exit(1)
    card = to_cloze(fact)
    deck = add_card(_srs_path(), card)
    typer.echo(f"Captured card #{len(deck)}: {card.cloze}")


@srs_app.command("list", epilog=_examples("yazses srs list    show the deck + each card's interval"))
def srs_list() -> None:
    """Show your flashcard deck and each card's next-review interval (days)."""
    from yazses.srscap.store import load_cards

    cards = load_cards(_srs_path())
    if not cards:
        typer.echo("Deck is empty. Capture one with: yazses srs capture \"remember that ...\"")
        return
    for i, c in enumerate(cards, start=1):
        typer.echo(f"  {i}. {c.get('front')}  →  {c.get('back')}   "
                   f"[reps {c.get('reps', 0)}, interval {c.get('interval', 0)}d]")


@srs_app.command(
    "review",
    epilog=_examples(
        "yazses srs review 1 --grade 5    graded it easy → longer interval",
        "yazses srs review 1 --grade 2    lapsed (grade < 3) → back to 1 day",
    ),
)
def srs_review(
    card: int = typer.Argument(..., help="Card number (see `yazses srs list`)."),
    grade: int = typer.Option(..., "--grade", "-g", min=0, max=5, help="Recall quality 0–5 (<3 lapses)."),
) -> None:
    """Grade a card's recall (SM-2) and update its schedule."""
    from yazses.srscap.store import review_card

    try:
        updated = review_card(_srs_path(), card - 1, grade)
    except IndexError as exc:
        typer.echo(f"Could not review: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Card #{card} scheduled: review again in {updated['interval']} day(s) "
               f"(reps {updated['reps']}, ease {updated['ease']}).")


# Valid hold-to-talk keys (mirror platform/linux/hotkey.py keymap).
_HOTKEYS = [
    "right_alt", "left_alt", "right_ctrl", "left_ctrl",
    "right_shift", "left_shift", "right_meta", "left_meta", "space",
]

hotkey_app = typer.Typer(
    name="hotkey",
    help="Change the key you hold to talk.",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(hotkey_app, rich_help_panel=_SETUP)


@hotkey_app.command(
    "show",
    epilog=_examples("yazses hotkey show    print the hold-to-talk key, the command key, and the choices"),
)
def hotkey_show() -> None:
    """Show the current hold-to-talk key (and command key, if set)."""
    from yazses.config import load_config

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    typer.echo(f"Hold-to-talk key:  {_resolved_hotkey(platform)}  (dictation)")
    cmd = (cfg.hotkey.command_key or "").strip()
    if cmd:
        typer.echo(f"Command key:       {cmd}  (force command mode)")
    else:
        typer.echo("Command key:       (none) — commands auto-detected on the dictation key")
    typer.echo(f"Choices: {', '.join(_HOTKEYS)}")


@hotkey_app.command(
    "set",
    epilog=_examples(
        "yazses hotkey set right_ctrl    hold Right-Ctrl to dictate",
        "yazses restart                  apply the new key",
    ),
)
def hotkey_set(
    key: str = typer.Argument(..., help="The key to hold to talk (e.g. right_ctrl)."),
) -> None:
    """Set the key you hold to dictate, then `yazses restart` to apply.

    Pick a dedicated modifier (right_alt/right_ctrl/right_shift) so it doesn't
    collide with normal typing the way `space` can.
    """
    if key not in _HOTKEYS:
        typer.echo(
            f"Unknown key {key!r}. Choose one of: {', '.join(_HOTKEYS)}", err=True
        )
        raise typer.Exit(1)
    from yazses.system.configedit import set_config_key

    platform = get_platform()
    set_config_key(platform.paths.config_file, "hotkey", "key", key)
    typer.echo(f"Hold-to-talk key set to {key!r}. Apply it:  yazses restart")


@hotkey_app.command(
    "command",
    epilog=_examples(
        "yazses hotkey command right_ctrl    dictate on right_alt, commands on right_ctrl",
        "yazses hotkey command off           remove the command key",
        "yazses restart                      apply the change",
    ),
)
def hotkey_command(
    key: str = typer.Argument(
        ...,
        help="A second key to hold for command mode, or 'off' to disable.",
    ),
) -> None:
    """Set a dedicated *command* key, then `yazses restart` to apply.

    Hold this key (instead of the dictation key) to issue commands only: whatever
    you say is parsed as a command and never typed as text — an unrecognised
    phrase is ignored. Use a different key from your dictation key. `off` removes it.

    Example:  yazses hotkey command right_ctrl   (dictate on right_alt, command on right_ctrl)
    """
    from yazses.config import load_config
    from yazses.system.configedit import set_config_key

    platform = get_platform()
    if key.lower() in {"off", "none", "clear", "disable"}:
        set_config_key(platform.paths.config_file, "hotkey", "command_key", "")
        typer.echo("Command key removed (commands auto-detected on the dictation key).")
        typer.echo("Apply it:  yazses restart")
        return
    if key not in _HOTKEYS:
        typer.echo(
            f"Unknown key {key!r}. Choose one of: {', '.join(_HOTKEYS)}, or 'off'.",
            err=True,
        )
        raise typer.Exit(1)
    dictation = load_config(platform.paths.config_file).hotkey.key or platform.default_hotkey
    if key == dictation:
        typer.echo(
            f"Command key must differ from your dictation key ({dictation!r}). "
            f"Change one with `yazses hotkey set <key>`.",
            err=True,
        )
        raise typer.Exit(1)
    set_config_key(platform.paths.config_file, "hotkey", "command_key", key)
    typer.echo(
        f"Command key set to {key!r}. Hold {dictation} to dictate, {key} for commands."
    )
    typer.echo("Apply it:  yazses restart")


@app.command(
    rich_help_panel=_DAEMON,
    epilog=_examples("yazses stop    stop the running daemon (dictation off until you start again)"),
)
def stop() -> None:
    """Stop the running daemon.

    Dictation stays off until you `yazses start` again. To pick up a config or
    version change instead, use `yazses restart` (stop + start in one step).
    """
    platform = get_platform()
    pid = platform.lifecycle.read_pid()
    if pid is None or not platform.lifecycle.is_running():
        typer.echo("YazSes is not running — nothing to stop.")
        raise typer.Exit(1)
    platform.lifecycle.stop_daemon(pid)
    typer.echo("YazSes stopped. Start it again with `yazses start`.")


@app.command(
    rich_help_panel=_DAEMON,
    epilog=_examples("yazses status    show state, model, hotkey, and uptime"),
)
def status() -> None:
    """Show daemon status. Queries the daemon over IPC when reachable."""
    platform = get_platform()
    if not platform.lifecycle.is_running():
        typer.echo("YazSes is not running. Start it with `yazses start`.")
        typer.echo("New here? Run `yazses quickstart` for the 3-step setup.")
        return

    pid = platform.lifecycle.read_pid()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        info = client.call("status")
    except IpcUnreachableError:
        typer.echo(
            f"YazSes is running (PID {pid}) but still starting up — it's loading the "
            "speech model (first run can take 10–30s). Re-run `yazses status` shortly."
        )
        return

    typer.echo(f"YazSes is running (PID {pid}).")
    typer.echo(f"  state:    {info.get('state')}")
    typer.echo(f"  hotkey:   {info.get('hotkey')}")
    typer.echo(f"  model:    {info.get('model')}")
    typer.echo(f"  backend:  {info.get('injection_backend')}")
    typer.echo(f"  uptime:   {info.get('uptime_s')}s")
    if info.get("last_error"):
        typer.echo(f"  last err: {info['last_error']}")


@app.command(
    rich_help_panel=_SETUP,
    epilog=_examples("yazses quickstart    the 3 steps to get dictating, tailored to your machine"),
)
def quickstart() -> None:
    """Get dictating in 3 steps — a friendly guide tailored to your machine.

    Looks at what's already set up (prerequisites, whether the daemon is running,
    the speech model, your hotkey) and prints exactly what to do next. Safe to run
    anytime — it changes nothing.
    """
    import shutil
    import sys as _sys

    platform = get_platform()
    hotkey = _resolved_hotkey(platform)
    running = platform.lifecycle.is_running()

    typer.secho("Welcome to YazSes — offline, hold-to-talk voice dictation.\n", bold=True)
    typer.echo("Everything runs on your machine. No cloud, no account, nothing leaves your computer.\n")

    step = 1

    def _say_step(title: str, *body: str) -> None:
        nonlocal step
        typer.secho(f"  {step}. {title}", bold=True)
        for line in body:
            typer.echo(f"     {line}")
        typer.echo("")
        step += 1

    # Step 1 — prerequisites (Linux needs system packages + input-group).
    if _sys.platform == "linux":
        needs_setup = False
        try:
            from yazses.system import setup as _setup

            needs_setup = not _setup.build_plan().is_noop
        except Exception:
            needs_setup = False
        if needs_setup:
            _say_step(
                "Install the prerequisites",
                "Run:  yazses setup",
                "(installs audio + typing tools, adds you to the `input` group)",
                "Then log out and back in if it asks you to.",
            )
        else:
            _say_step("Prerequisites — already set up ✓", "Verify anytime with:  yazses doctor")
    else:
        _say_step("Check prerequisites", "Run:  yazses doctor")

    # Step 2 — start the daemon.
    if running:
        _say_step("Start YazSes — already running ✓", "Check it with:  yazses status")
    else:
        _say_step(
            "Start YazSes",
            "Run:  yazses start",
            "It loads the speech model once (first run can take 10–30s), then waits for your hotkey.",
        )

    # Step 3 — actually dictate.
    _say_step(
        "Dictate",
        f"Hold  {hotkey}  , speak, then release. Your words type into the focused window.",
        "Change the key with:  yazses hotkey set <key>",
    )

    typer.secho("Handy next steps", bold=True)
    typer.echo("  yazses test              type a test phrase (no speaking) to confirm typing works")
    typer.echo("  yazses mic-level --set   tune the mic to your voice if words get dropped")
    typer.echo("  yazses features          see everything YazSes can do, and turn things on/off")
    typer.echo("  yazses doctor            diagnose anything that isn't working")
    if not shutil.which("yazses"):  # pragma: no cover - defensive
        typer.echo("\n  (If `yazses` isn't found, restart your shell to refresh PATH.)")


@app.command(
    rich_help_panel=_SETUP,
    epilog=_examples(
        "yazses doctor          run this first if dictation isn't working",
        "yazses doctor --mic    also sample the mic and compare it to the VAD gate",
    ),
)
def doctor(
    mic: bool = typer.Option(
        False, "--mic",
        help="Also record a short ambient clip and compare its level to the VAD threshold.",
    ),
) -> None:
    """Check system prerequisites and report what's OK / missing.

    Reports the installed version and daemon status, then verifies the platform,
    keyboard-capture and microphone permissions, the session type (X11/Wayland)
    and its injection tools, the STT model and model cache, the active config and
    hotkey, and any configured extras (EMG port, prosody). With --mic it also
    samples the microphone. Each line is OK / WARN / FAIL / SKIP.
    """
    from yazses.system.doctor import run_doctor

    run_doctor(check_mic=mic)


@app.command(
    rich_help_panel=_MAINT,
    epilog=_examples(
        "yazses update           check for a newer version and offer to install it",
        "yazses update --check   only report what's available (don't install)",
        "yazses update --yes     install the update without asking",
    ),
)
def update(
    check: bool = typer.Option(
        False, "--check", help="Only report whether an update is available; don't install."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Install the update without prompting."
    ),
) -> None:
    """Check for a newer YazSes and update it (snap / uv tool / pipx / pip).

    Detects how YazSes was installed and checks the matching source — the tracked
    snap channel for snap installs, PyPI for the pip-family ones — then upgrades
    only when the available version is strictly newer (never a downgrade). After a
    snap/pip upgrade, restart the daemon to load the new code:
    `systemctl --user restart yazses` (or `yazses stop && yazses start`).
    """
    current = _pkg_version("yazses")
    status = check_update(current)
    typer.echo(f"Installed:  yazses {current}  (via {status.method})")

    if status.latest is None:
        typer.echo(f"Could not determine the latest version ({status.note}).", err=True)
        raise typer.Exit(1)

    typer.echo(f"Available:  yazses {status.latest}")

    if not status.available:
        typer.echo("You're on the latest version. ✓")
        return

    typer.echo(f"\nUpdate available: {current} → {status.latest}")
    typer.echo(f"Command: {' '.join(status.command)}")

    if check:
        typer.echo("\n(--check) Not installing. Re-run without --check to update.")
        return

    if not yes and not typer.confirm("Install it now?", default=True):
        typer.echo("Skipped.")
        return

    code = run_upgrade(status)
    if code == 0:
        typer.echo(f"\nUpdated to {status.latest}. Restart the daemon to load it:")
        typer.echo("  systemctl --user restart yazses   # or: yazses stop && yazses start")
    else:
        typer.echo(f"\nUpgrade command exited with code {code}.", err=True)
        raise typer.Exit(code or 1)


def _calibrate_mic(*, seconds: float = 4.0, set_threshold: bool = False) -> bool:
    """Record a short clip, report the speech level, and (optionally) write the
    recommended VAD threshold. Shared by `yazses mic-level` and `yazses setup`'s
    "connect to voice" step. Returns False when no speech was detected."""
    from yazses.config import load_config
    from yazses.system.miclevel import analyze, record, update_threshold_in_config

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    sr = cfg.audio.sample_rate

    typer.echo(f"Recording {seconds:.0f}s -- speak normally now...")
    stats = analyze(record(seconds, sr), sr)

    typer.echo(f"  mean level:            {stats.mean_abs:.4f}")
    typer.echo(f"  peak level:            {stats.peak:.4f}")
    typer.echo(f"  current vad_threshold: {cfg.accessibility.vad_threshold}")

    if stats.is_silent:
        typer.echo("No speech detected -- check the microphone and try again.")
        return False

    rec = stats.recommended_threshold
    typer.echo(f"  recommended:           {rec}")

    if set_threshold:
        msg = update_threshold_in_config(platform.paths.config_file, rec)
        typer.echo(f"Applied: {msg}")
        typer.echo("Restart to pick it up:  yazses stop && yazses start")
    else:
        typer.echo("Re-run with --set to apply, or put in config.toml:")
        typer.echo(f"  [accessibility]\n  vad_threshold = {rec}")
    return True


def _print_next_steps(steps) -> None:
    """Render the ordered install checklist from setup.next_steps() — the steps
    only the user can do (connect the mic, re-login, calibrate, start)."""
    typer.secho("\nFinish installing — a few steps only you can do:",
                fg=typer.colors.BRIGHT_CYAN, bold=True)
    for i, step in enumerate(steps, start=1):
        typer.secho(f"  {i}. {step.title}", fg=typer.colors.BRIGHT_WHITE, bold=True)
        if step.command:
            # Commands that need sudo (or undo a silent failure) stand out in red.
            urgent = step.command.startswith("sudo")
            typer.secho(f"       {step.command}",
                        fg=typer.colors.BRIGHT_WHITE,
                        bg=typer.colors.RED if urgent else typer.colors.BLUE, bold=True)
        else:
            typer.secho("       (log out of your desktop session, then log back in)",
                        fg=typer.colors.BRIGHT_RED, bold=True)
        typer.secho(f"       -> {step.why}", fg=typer.colors.BRIGHT_BLACK)


@app.command(
    name="mic-level",
    rich_help_panel=_SETUP,
    epilog=_examples(
        "yazses mic-level             measure and recommend a threshold",
        "yazses mic-level --set       measure and write it to config.toml",
        "yazses mic-level -s 6        record for 6 seconds instead of 4",
    ),
)
def mic_level(
    seconds: float = typer.Option(4.0, "--seconds", "-s", help="Seconds to record while you speak."),
    set_threshold: bool = typer.Option(False, "--set", help="Write the recommended vad_threshold to config."),
) -> None:
    """Measure mic speech level and recommend (or set) the VAD threshold.

    Speak in a normal voice for the whole countdown. The daemon discards a clip
    when its average level is below vad_threshold, so if dictation shows
    "Silent audio -- discarding", run this to find a level that fits your voice.
    """
    if not _calibrate_mic(seconds=seconds, set_threshold=set_threshold):
        raise typer.Exit(code=1)


@app.command(
    rich_help_panel=_SETUP,
    epilog=_examples(
        "yazses logs                  last 40 log lines",
        "yazses logs -n 100           last 100 lines",
        "yazses logs --path           just print the log file path",
    ),
)
def logs(
    lines: int = typer.Option(40, "--lines", "-n", help="Number of recent lines to show."),
    path_only: bool = typer.Option(False, "--path", help="Print the log file path and exit."),
) -> None:
    """Show the daemon's diagnostic log (metadata only -- no dictated text)."""
    platform = get_platform()
    log_file = platform.paths.log_dir / "daemon.log"
    if path_only:
        typer.echo(str(log_file))
        return
    if not log_file.exists():
        typer.echo(f"No log yet at {log_file} -- start the daemon first.")
        raise typer.Exit(code=1)
    content = log_file.read_text(errors="replace").splitlines()
    for line in content[-lines:]:
        typer.echo(line)
    typer.echo(f"\n({log_file} -- follow live with: tail -f {log_file})")


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples('yazses inject "hello world"    type it into the focused window'),
)
def inject(text: str = typer.Argument(..., help="Text to inject into the focused app.")) -> None:
    """Type text into the focused window without recording (tests the injector)."""
    platform = get_platform()
    injector = platform.injector_factory()
    typer.echo(f"Backend: {type(injector).__name__}")
    injector.inject(text)
    typer.echo(f"Injected: {text!r}")


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples('yazses say "hello there"    speak text aloud via offline TTS'),
)
def say(text: str = typer.Argument(..., help="Text to speak aloud.")) -> None:
    """Speak text aloud with the built-in offline voice.

    Requires `[tts] enabled = true` (install the voice with `uv sync --extra tts`).
    Routes through the running daemon so it reuses the loaded TTS backend.
    """
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        result = client.call("readback_speak", text=text)
    except IpcUnreachableError:
        typer.echo("Daemon is not running. Start it with: yazses start", err=True)
        raise typer.Exit(1)
    if result.get("ok"):
        typer.echo(f"Speaking via {result.get('backend')}...")
    else:
        typer.echo(f"Could not speak: {result.get('reason')}", err=True)
        raise typer.Exit(1)


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples("yazses overlay    preview the sonar voice-activity rings in the foreground"),
)
def overlay() -> None:
    """Run the sonar voice-activity overlay (needs the `overlay` extra: PySide6).

    Draws neon rings near the cursor that pulse with your voice while dictating.
    Normally auto-launched by the daemon when `[overlay] enabled = true`; run it
    here in the foreground to preview or debug it.
    """
    from yazses.overlay.app import run as run_overlay

    run_overlay()


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples(
        'yazses reflow "First, set up. Then test. I need to ship."   bulleted outline',
        "cat notes.txt | yazses reflow    reflow piped text (e.g. a transcript)",
    ),
)
def reflow(
    text: Optional[str] = typer.Argument(None, help="Text to reflow (omit to read stdin)."),
) -> None:
    """Reflow a monologue into a bulleted outline — fully offline.

    Use it when: you dictated or recorded a long rambling monologue (a meeting,
    a brain-dump, a transcript) and want it structured into scannable bullets and
    a to-do list without re-typing it.

    Splits on sentence boundaries; strips a leading discourse marker
    ('first', 'then', 'finally', …); sentences with an action phrase
    ('I need to', 'to do', 'follow up') become '- [ ]' checkboxes. Reads the
    TEXT argument, or standard input when omitted (pipe a transcript in).
    """
    import sys as _sys

    from yazses.reflow.outline import reflow as _reflow

    src = text if text is not None else _sys.stdin.read()
    typer.echo(_reflow(src))


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples(
        'yazses table "row: Ada, 1815, London next row Bob, 1990, Paris"   -> CSV rows',
        "yazses table --sep ';' \"a, b next row c, d\"    use a semicolon separator",
    ),
)
def table(
    text: Optional[str] = typer.Argument(None, help="Spoken-style rows (omit to read stdin)."),
    sep: str = typer.Option(",", "--sep", help="Field separator for the output (default: comma)."),
) -> None:
    """Turn spoken rows into delimited (CSV) lines — fully offline.

    Use it when: you want to capture tabular data by voice or from a transcript —
    dictate rows of a table and get CSV you can paste into a spreadsheet, instead
    of tabbing between cells by hand.

    Cells split on commas/semicolons or the word 'and'; rows split on 'next row'
    or newlines; a leading 'row:'/'entry:'/'record:' marker is stripped. Reads the
    TEXT argument, or standard input when omitted.
    """
    import sys as _sys

    from yazses.tablecsv.entry import rows_to_delimited

    src = text if text is not None else _sys.stdin.read()
    for line in rows_to_delimited(src, sep=sep):
        typer.echo(line)


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples(
        'yazses shellpipe "list files then filter for python then count lines"',
        "  -> ls | grep 'python' | wc -l   (printed, never executed)",
    ),
)
def shellpipe(
    text: Optional[str] = typer.Argument(None, help="Spoken pipeline (omit to read stdin)."),
) -> None:
    """Render a spoken pipeline into a shell command — fully offline.

    Use it when: you know what you want a shell pipeline to do but not the exact
    flags — describe it in words and get a ready-to-review command, without
    anything running until you decide to run it.

    Recognises stages like 'list files', 'filter for X', 'count lines', 'sort',
    'unique'. Prints the pipeline for you to review and run — it NEVER executes
    anything. Exits non-zero (emitting nothing) if a stage isn't recognised.
    """
    import sys as _sys

    from yazses.shellpipe.build import parse_stages, render_pipeline

    src = text if text is not None else _sys.stdin.read()
    pipeline = render_pipeline(parse_stages(src))
    if not pipeline:
        typer.echo("Could not map every stage to a command; nothing emitted.", err=True)
        raise typer.Exit(1)
    typer.echo(pipeline)


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples(
        'yazses braille "hello world"       -> ⠓⠑⠇⠇⠕ ⠺⠕⠗⠇⠙',
        'yazses braille --grade 1 "abc"     Grade 1 (uncontracted)',
    ),
)
def braille(
    text: Optional[str] = typer.Argument(None, help="Text to translate (omit to read stdin)."),
    grade: int = typer.Option(2, "--grade", help="UEB grade: 1 (uncontracted) or 2 (contracted)."),
) -> None:
    """Translate text to Unicode Braille (UEB subset) — fully offline.

    Use it when: you need to produce Braille output for a refreshable display or a
    DeafBlind reader from dictated or piped text, entirely on-device.

    Reads the TEXT argument, or standard input when omitted.
    """
    import sys as _sys

    from yazses.brailleout.ueb import to_braille

    src = text if text is not None else _sys.stdin.read()
    typer.echo(to_braille(src, grade=grade))


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples(
        'yazses case --style snake "myVariableName"    -> my_variable_name',
        'yazses case "make this kebab case: My Title"   detect the style from the words',
        "cat name.txt | yazses case --style constant     read stdin",
    ),
)
def case(
    text: Optional[str] = typer.Argument(None, help="Text to recase (omit to read stdin)."),
    style: Optional[str] = typer.Option(
        None, "--style",
        help="Target case: snake|kebab|camel|pascal|title|sentence|upper|lower|constant. "
             "Omit to detect a spoken 'make this … case' command in the text.",
    ),
) -> None:
    """Recase text to a naming convention — fully offline.

    Use it when: you dictated or pasted an identifier/phrase and want it in a
    specific case (snake_case, kebab-case, camelCase, CONSTANT_CASE, Title Case, …)
    without hand-editing it.

    With --style, recases the whole TEXT. Without it, detects a spoken style command
    ('make this snake case: …') and recases the remainder. Reads the TEXT argument,
    or standard input when omitted.
    """
    import sys as _sys

    from yazses.casetransform.transform import detect_style_command, transform_case

    src = text if text is not None else _sys.stdin.read()
    chosen = style
    payload = src
    if chosen is None:
        chosen = detect_style_command(src)
        if chosen is None:
            typer.echo(
                "No --style given and no spoken style command detected. "
                "Pass --style snake|kebab|camel|pascal|title|sentence|upper|lower|constant.",
                err=True,
            )
            raise typer.Exit(1)
        # strip a leading "make this … case:" command so only the payload is recased
        if ":" in src:
            payload = src.split(":", 1)[1]
    typer.echo(transform_case(payload.strip(), chosen))


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples(
        'yazses screenplay "scene: interior coffee shop, day"   -> INT. COFFEE SHOP - DAY',
        'yazses screenplay "Alice (character) hello there"       -> ALICE / dialogue',
        "cat lines.txt | yazses screenplay    format each line as Fountain",
    ),
)
def screenplay(
    text: Optional[str] = typer.Argument(None, help="Utterance(s) to format (omit to read stdin)."),
) -> None:
    """Format dictated lines as Fountain screenplay markup — fully offline.

    Use it when: you're drafting a script by voice and want scene headings,
    character cues, transitions, and smart-quoted dialogue formatted for you.

    Recognises 'scene: interior/exterior <place>, <time>' → 'INT./EXT. …',
    '<Name> (character) <dialogue>' → a character cue, and 'transition: cut to'
    → 'CUT TO:'; anything else becomes a smart-quoted action line. Each input line
    is formatted independently. Reads the TEXT argument, or standard input when omitted.
    """
    import sys as _sys

    from yazses.screenplay.fountain import to_fountain

    src = text if text is not None else _sys.stdin.read()
    lines = [ln for ln in src.splitlines()] or [src]
    out = [to_fountain(ln) for ln in lines if ln.strip()]
    typer.echo("\n\n".join(out))


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples(
        'yazses findreplace "replace every cat with dog" --in "the cat sat"   -> the dog sat',
        'echo "foo foo" | yazses findreplace "replace first foo with bar"      -> bar foo',
    ),
)
def findreplace(
    command: str = typer.Argument(..., help="Spoken find/replace, e.g. 'replace every X with Y'."),
    in_text: Optional[str] = typer.Option(
        None, "--in", help="Text to apply it to (omit to read stdin)."),
) -> None:
    """Apply a spoken find-and-replace to text — fully offline.

    Use it when: you want to preview or script a 'replace every X with Y' edit from
    words, without an editor — dictate the command, get the rewritten text.

    Parses commands like 'replace every/first X with Y' (add 'case-sensitive' to match
    case). Applies it to --in, or standard input when omitted. Exits non-zero if the
    command can't be parsed.
    """
    import sys as _sys

    from yazses.findreplace.parse import apply_replace, parse_replace_command

    op = parse_replace_command(command)
    if op is None:
        typer.echo(
            "Could not parse a find/replace command. Try: "
            "'replace every X with Y' (optionally 'case-sensitive').", err=True,
        )
        raise typer.Exit(1)
    src = in_text if in_text is not None else _sys.stdin.read()
    typer.echo(apply_replace(op, src))


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples(
        'yazses chords "press control shift P"   -> ctrl+shift+p',
        'yazses chords "escape twice"            -> Escape (one per line)',
    ),
)
def chords(
    text: Optional[str] = typer.Argument(None, help="Spoken key chord (omit to read stdin)."),
) -> None:
    """Turn a spoken key chord into injectable key combos — fully offline.

    Use it when: you want the exact key-combo string for a spoken shortcut
    ('press control shift P' → 'ctrl+shift+p') to review, script, or bind.

    Recognises modifiers (control/alt/shift/super), named keys (enter/escape/tab/…),
    F-keys, and a trailing repeat ('twice', 'three times'). Prints one combo per line.
    Reads the TEXT argument, or standard input when omitted; exits non-zero if unparsed.
    """
    import sys as _sys

    from yazses.chords.parse import parse_chord, render_chord

    src = text if text is not None else _sys.stdin.read()
    parsed = parse_chord(src)
    if not parsed:
        typer.echo(
            "Could not parse a key chord. Try: 'press control shift P' or 'escape twice'.",
            err=True,
        )
        raise typer.Exit(1)
    for chord in parsed:
        typer.echo(render_chord(chord))


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples(
        'yazses wordfind "finding something good by happy accident"   -> serendipity',
        "yazses wordfind \"smell after rain\" --limit 3               top 3 guesses",
    ),
)
def wordfind(
    description: str = typer.Argument(..., help="A description of the word you're reaching for."),
    limit: int = typer.Option(5, "--limit", "-n", help="Max candidates to show."),
    lexicon: Optional[str] = typer.Option(
        None, "--lexicon", help="Path to a JSON {word: definition} lexicon to merge in."),
) -> None:
    """Reverse dictionary: describe a word and get candidates — fully offline.

    Use it when: a word is on the tip of your tongue — describe what it means and get
    ranked guesses. Ships a small demo lexicon; extend it with --lexicon (a JSON object
    mapping words to definitions). Exits non-zero if nothing matches.
    """
    import json as _json
    import sys as _sys

    from yazses.wordfind.rank import rank_candidates

    user_lex = None
    if lexicon:
        try:
            user_lex = _json.loads(Path(lexicon).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            typer.echo(f"Could not read --lexicon: {exc}", err=True)
            raise typer.Exit(1)
    results = rank_candidates(description, user_lex, limit=limit)
    if not results:
        typer.echo("No candidates — try describing it differently.", err=True)
        raise typer.Exit(1)
    for word, score in results:
        typer.echo(f"  {word}\t({score})")
    _ = _sys  # (kept for symmetry with the other one-shots' stdin pattern)


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples(
        'yazses cite "vaswani 2017" --bib refs.bib             -> \\cite{vaswani2017}',
        'yazses cite "attention 2017" --bib refs.bib --style apa  -> Vaswani et al. (2017)',
    ),
)
def cite(
    query: str = typer.Argument(..., help="Spoken 'author year' reference, e.g. 'vaswani 2017'."),
    bib: str = typer.Option(..., "--bib", help="Path to a BibTeX (.bib) file."),
    style: str = typer.Option("latex", "--style", help="latex | plain | apa."),
) -> None:
    """Resolve a spoken 'author year' reference against a .bib file — fully offline.

    Use it when: you're writing and want the right citation key/label without leaving
    your flow — say the author and year, get the formatted citation. Exits non-zero if
    the file can't be read or no entry matches confidently.
    """
    from yazses.cite.library import format_citation, parse_bibtex, resolve_citation

    try:
        text = Path(bib).read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"Could not read --bib: {exc}", err=True)
        raise typer.Exit(1)
    hit = resolve_citation(query, parse_bibtex(text))
    if hit is None:
        typer.echo("No confident citation match. Try 'surname year'.", err=True)
        raise typer.Exit(1)
    typer.echo(format_citation(hit, style))


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples(
        'yazses slotfill "set priority high, open firefox" '
        '--slot priority:after=priority --slot browser:choices=firefox,chrome',
        "  -> {\"browser\": \"firefox\", \"priority\": \"high\"}",
    ),
)
def slotfill(
    text: str = typer.Argument(..., help="The utterance to extract fields from."),
    slot: list[str] = typer.Option(
        ..., "--slot",
        help="A field spec (repeatable): NAME:after=kw1,kw2  or  NAME:choices=a,b,c.",
    ),
) -> None:
    """Extract structured fields from one utterance by a schema — fully offline.

    Use it when: you want to turn a spoken sentence into structured values (a form, a
    command's arguments) — define each field as a trigger keyword ('after') or an enum
    ('choices') and get back JSON of the matched fields.

    ``after`` captures the token following a trigger keyword ('priority high' → 'high');
    ``choices`` picks the first enum member present. Prints a JSON object of matched fields.
    """
    import json as _json

    from yazses.slotfill.fill import Slot, fill_slots

    slots = []
    for spec in slot:
        if ":" not in spec or "=" not in spec:
            typer.echo(f"Bad --slot {spec!r}. Use NAME:after=... or NAME:choices=...", err=True)
            raise typer.Exit(1)
        name, rest = spec.split(":", 1)
        kind, raw = rest.split("=", 1)
        values = tuple(v.strip() for v in raw.split(",") if v.strip())
        kind = kind.strip().lower()
        if kind == "after":
            slots.append(Slot(name.strip(), after=values))
        elif kind == "choices":
            slots.append(Slot(name.strip(), choices=values))
        else:
            typer.echo(f"Unknown slot kind {kind!r}; use 'after' or 'choices'.", err=True)
            raise typer.Exit(1)
    result = fill_slots(text, slots)
    typer.echo(_json.dumps(result, ensure_ascii=False, sort_keys=True))


@app.command(
    rich_help_panel=_REMOTE,
    epilog=_examples(
        "yazses remote dev.example.com           forward voice typing over SSH",
        "yazses remote dev.example.com -p 2222   use a non-default SSH port",
        "yazses remote dev.example.com --stop    disconnect the session",
    ),
)
def remote(
    host: str = typer.Argument(..., help="SSH host to forward voice typing to."),
    port: int = typer.Option(22, "--port", "-p", help="SSH port."),
    key_file: str = typer.Option("", "--key-file", "-i", help="Path to SSH private key."),
    stop: bool = typer.Option(False, "--stop", help="Disconnect active remote session."),
) -> None:
    """Forward voice typing to a remote host over SSH."""
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        if stop:
            result = client.call("remote_stop")
            typer.echo("Remote session disconnected." if result.get("ok") else f"Error: {result}")
        else:
            result = client.call("remote_start", host=host, port=port, key_file=key_file)
            if result.get("ok"):
                typer.echo(f"Connecting to {host}:{port}... (use --stop to disconnect)")
            else:
                typer.echo(f"Error: {result.get('reason', result)}", err=True)
                raise typer.Exit(1)
    except IpcUnreachableError:
        typer.echo("Daemon is not running. Start it with: yazses start", err=True)
        raise typer.Exit(1)


@app.command(
    rich_help_panel=_SETUP,
    epilog=_examples("yazses setup    install audio + injection deps, join input group, set up ydotoold"),
)
def setup(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be installed/changed without doing it."
    ),
) -> None:
    """Provision all Linux runtime requirements so dictation works out of the box.

    Installs the audio + injection system packages (libportaudio2, xdotool,
    ydotool, wtype, xclip, wl-clipboard), adds you to the `input` group (needed
    for the hotkey and for ydotool's /dev/uinput access), and on Wayland sets up
    the `ydotoold` user service (required for injection on GNOME/KDE Wayland,
    where wtype is blocked). Safe to re-run — it only fixes what's missing.
    """
    import sys as _sys

    if _sys.platform != "linux":
        typer.echo("yazses setup currently provisions Linux only; nothing to do.")
        return

    from yazses.system import setup as _setup

    plan = _setup.build_plan()
    mic_pending = _setup.snap_mic_pending()
    typer.echo(f"Session: {plan.session}")
    if plan.is_noop and not mic_pending:
        typer.echo("All Linux requirements already satisfied.")
        # Nothing to provision, but a fresh user still benefits from calibrating
        # their voice and starting the daemon — surface those as next steps.
        _print_next_steps(_setup.next_steps(plan=plan, mic_pending=mic_pending))
        raise typer.Exit(0)

    typer.echo("Plan:")
    if plan.apt_packages:
        typer.echo(f"  • install packages: {' '.join(plan.apt_packages)}")
    if plan.add_to_input_group:
        typer.echo("  • add you to the `input` group (sudo)")
    if plan.setup_ydotoold:
        typer.echo("  • set up + enable the ydotoold user service (Wayland injection)")
    if mic_pending:
        # The snap can't self-connect interfaces; this is the one manual step and
        # must be run outside confinement, so we print it rather than auto-apply.
        typer.echo("  • grant the snap microphone access (run this yourself, once):")
        typer.secho("      sudo snap connect yazses:audio-record",
                    fg=typer.colors.BRIGHT_WHITE, bg=typer.colors.RED, bold=True)

    if dry_run:
        typer.echo("\n(dry run — no changes made)")
        _print_next_steps(_setup.next_steps(plan=plan, mic_pending=mic_pending))
        return

    typer.echo("")
    ok = _setup.apply_plan(plan)
    typer.echo("")
    typer.echo("Verifying with `yazses doctor`...\n")
    from yazses.system.doctor import run_doctor

    run_doctor()
    if not ok:
        typer.echo("\nSome steps need attention — see warnings above.", err=True)

    # Ordered checklist of everything the user must still do themselves (the parts
    # a confined/unprivileged process can't do): connect the mic, re-login, tune
    # the voice, start dictating. Single source of truth: setup.next_steps().
    _print_next_steps(_setup.next_steps(plan=plan, mic_pending=mic_pending))

    # Offer to "connect to voice" now — run the mic calibration interactively when
    # we have a terminal and nothing blocks recording (mic granted, no re-login due).
    can_calibrate = not mic_pending and not (plan.add_to_input_group or _setup.input_group_pending_relogin())
    if can_calibrate and _sys.stdin.isatty() and typer.confirm(
        "\nCalibrate the mic to your voice now?", default=True
    ):
        try:
            _calibrate_mic(seconds=4.0, set_threshold=True)
        except Exception as exc:  # never let calibration failure fail setup
            typer.secho(f"  (skipped — {exc}; run `yazses mic-level --set` later)",
                        fg=typer.colors.YELLOW)

    if not ok:
        raise typer.Exit(1)
    typer.echo("\nSetup complete.")
    typer.echo("")
    _echo_capabilities(
        get_platform(),
        header="What YazSes can do — every capability (● on / ○ off):\n",
    )


@app.command(
    rich_help_panel=_SETUP,
    epilog=_examples("yazses enroll    calibrate the mic/VAD thresholds to your voice (20 short utterances)"),
)
def enroll() -> None:
    """Run the accessibility enrollment wizard to calibrate VAD thresholds.

    Records 20 short utterances to derive vad_threshold and min_silence_ms
    values tuned to your voice and microphone. Results are written to config.toml.
    """
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    if client.is_reachable():
        try:
            result = client.call("enroll_start")
            if result.get("ok"):
                typer.echo("Enrollment started. Follow the prompts in the daemon terminal.")
            else:
                typer.echo(f"Error: {result.get('reason', result)}", err=True)
                raise typer.Exit(1)
        except IpcUnreachableError:
            pass
    else:
        # Run wizard locally when daemon is not running
        from yazses.accessibility.enroll import run_wizard
        run_wizard(config_path=platform.paths.config_file)


@app.command(
    name="enroll-voice",
    rich_help_panel=_SETUP,
    epilog=_examples("yazses enroll-voice    record a sample → save your speaker voiceprint"),
)
def enroll_voice() -> None:
    """Record a short voiceprint so YazSes can recognise your voice.

    Records a short sample of your voice, computes a speaker embedding, and stores
    it encrypted on this machine (never leaves the machine). Requires
    `[voiceprint] enabled = true` and the voiceprint extra
    (`uv sync --extra voiceprint`). Run once; re-run to re-enroll.
    """
    from yazses.config import load_config
    from yazses.learning.crypto import Cipher, load_or_create_key
    from yazses.system.miclevel import record
    from yazses.voiceprint.enroll import enroll as do_enroll
    from yazses.voiceprint.factory import build_embedder
    from yazses.voiceprint.store import save_voiceprint

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    embedder = build_embedder(cfg.voiceprint)
    if embedder is None:
        typer.echo(
            "Voiceprint unavailable. Set `[voiceprint] enabled = true` and install "
            "the extra:\n  uv sync --extra voiceprint",
            err=True,
        )
        raise typer.Exit(1)

    secs = cfg.voiceprint.enroll_seconds
    typer.echo(f"Recording {secs:.0f}s — speak normally now...")
    emb = do_enroll(record, embedder, seconds=secs, sample_rate=cfg.audio.sample_rate)
    cipher = Cipher(load_or_create_key(platform.paths.data_dir))
    save_voiceprint(emb, platform.paths.data_dir / "voiceprint.enc", cipher)
    typer.echo("Voiceprint saved (encrypted). Restart the daemon to use it:")
    typer.echo("  systemctl --user restart yazses")


gaze_app = typer.Typer(name="gaze", help="Aim dictation with your gaze — type into whichever pane you look at.")
app.add_typer(gaze_app, rich_help_panel=_SETUP)


@gaze_app.command(
    "calibrate",
    epilog=_examples("yazses gaze calibrate    fit the webcam gaze → screen-zone mapping (look at each point)"),
)
def gaze_calibrate(
    no_install: bool = typer.Option(
        False, "--no-install", help="Don't auto-install the gaze deps (mediapipe, opencv)."
    ),
) -> None:
    """Calibrate the webcam so your gaze maps to screen zones.

    Requires `[gaze] enabled = true` and an X11 session with `xdotool`. The webcam
    gaze deps (mediapipe + opencv) are installed automatically on first run into
    the running environment (skip with --no-install). You look at each on-screen
    point in turn; the fitted map is saved so the daemon can route dictation to
    the pane you look at (set `[gaze] route_dictation`).
    """
    import importlib

    from yazses.config import load_config
    from yazses.gaze.calibrate import collect_samples, default_targets, fit_calibration
    from yazses.gaze.desktop import build_desktop
    from yazses.gaze.factory import build_gaze
    from yazses.gaze.store import save_calibration
    from yazses.system.features import find_feature

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)

    # Auto-install the webcam gaze deps on first run (same path as
    # `yazses features enable gaze`), so calibration is turnkey.
    feat = find_feature(cfg, "gaze")
    if feat is not None:
        _install_feature_deps(feat, skip=no_install)
        importlib.invalidate_caches()  # let build_gaze import the freshly-installed deps

    backend = build_gaze(cfg.gaze)
    if backend is None:
        typer.echo(
            "Gaze backend unavailable. Ensure `[gaze] enabled = true` and that the "
            "webcam deps installed:\n  yazses features enable gaze --force",
            err=True,
        )
        raise typer.Exit(1)
    desktop = build_desktop()
    if desktop is None:
        typer.echo(
            "Gaze routing needs an X11 session with `xdotool` installed "
            "(Wayland forbids external window focus).",
            err=True,
        )
        raise typer.Exit(1)

    width, height = desktop.screen_size()
    targets = default_targets(width, height, cfg.gaze.calibration_points)
    typer.echo(
        f"Gaze backend '{backend.name}' ready — {len(targets)} points on a "
        f"{width}x{height} screen.\nLook at each point and press Enter (hold your gaze steady).\n"
    )

    def before_point(label: str, xy: tuple[int, int]) -> None:
        typer.prompt(
            f"  Look at the {label} of your screen {xy}, then press Enter",
            default="", show_default=False,
        )

    try:
        samples = collect_samples(backend, targets, before_point)
    finally:
        backend.close()

    if len(samples) < 3:
        typer.echo(
            f"Only {len(samples)} point(s) captured a face — need at least 3. "
            "Improve lighting / camera framing and retry.",
            err=True,
        )
        raise typer.Exit(1)

    cal = fit_calibration(samples)
    path = save_calibration(cal, platform.paths.data_dir)
    typer.echo(
        f"\n✓ Calibrated on {len(samples)}/{len(targets)} points → {path}\n"
        "Enable routing with `yazses features enable gaze` (already on if you set "
        "[gaze] route_dictation), then `yazses restart`."
    )


@gaze_app.command(
    "status",
    epilog=_examples("yazses gaze status    show gaze deps, X11/xdotool, and calibration state"),
)
def gaze_status() -> None:
    """Show whether look-to-pane is ready: deps, desktop backend, calibration."""
    from yazses.config import load_config
    from yazses.gaze.desktop import build_desktop
    from yazses.gaze.factory import build_gaze
    from yazses.gaze.store import calibration_path, load_calibration

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)

    def mark(ok: bool) -> str:
        return "✓" if ok else "✗"

    import dataclasses

    enabled = cfg.gaze.enabled
    # Probe deps regardless of the enabled flag so the row means "deps present",
    # not "feature on" (the factory returns None when disabled).
    backend = build_gaze(dataclasses.replace(cfg.gaze, enabled=True))
    if backend is not None:
        backend.close()
    desktop = build_desktop()
    cal = load_calibration(platform.paths.data_dir)

    typer.echo("Glance-Type (look-to-pane) status:")
    typer.echo(f"  {mark(enabled)} [gaze] enabled = {enabled}")
    typer.echo(f"  {mark(cfg.gaze.route_dictation)} route_dictation = {cfg.gaze.route_dictation}")
    typer.echo(f"  {mark(backend is not None)} gaze backend/deps ({cfg.gaze.backend})")
    typer.echo(f"  {mark(desktop is not None)} X11 desktop backend (xdotool)")
    typer.echo(f"  {mark(cal is not None)} calibration ({calibration_path(platform.paths.data_dir)})")
    ready = all((enabled, cfg.gaze.route_dictation, backend is not None, desktop is not None, cal is not None))
    if ready:
        typer.echo("\nReady — dictation will land in the window you look at.")
    elif backend is None:
        typer.echo(
            "\nNext: install the webcam deps — `yazses features enable gaze --force` "
            "(or run `yazses gaze calibrate`, which auto-installs them)."
        )
    elif cal is None and desktop is not None:
        typer.echo("\nNext: run `yazses gaze calibrate`.")


@model_app.command(
    "list",
    epilog=_examples("yazses model list    show SLM intent-router models + which are downloaded"),
)
def model_list() -> None:
    """List available SLM models and their download status."""
    from yazses.commands.model_manager import list_models, local_path

    for info in list_models():
        path = local_path(info.id)
        status = f"installed: {path}" if path else f"not downloaded ({info.size_mb} MB)"
        typer.echo(f"  {info.id:<24}  {info.description}")
        typer.echo(f"  {'':24}  [{status}]")
        typer.echo("")


@model_app.command(
    "download",
    epilog=_examples("yazses model download qwen2.5-0.5b    download an SLM for intent routing"),
)
def model_download(
    model_id: str = typer.Argument(..., help="Model ID (see `yazses model list`)."),
) -> None:
    """Download a GGUF model for Tier 2 SLM intent routing."""
    from yazses.commands.model_manager import download_model

    try:
        path = download_model(model_id)
        typer.echo("\nDone. Add this to your config.toml:")
        typer.echo("  [commands]")
        typer.echo(f'  slm_model_path = "{path}"')
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    except Exception as exc:
        typer.echo(f"Download failed: {exc}", err=True)
        raise typer.Exit(1)


@app.command(
    name="mark-wrong",
    rich_help_panel=_LEARNING,
    epilog=_examples(
        "yazses mark-wrong                      flag the last dictation as wrong",
        'yazses mark-wrong -c "kubernetes pod"  flag it and attach the correct text',
    ),
)
def mark_wrong(
    correction: str = typer.Option(
        "", "--correction", "-c", help="What you actually said (optional)."
    ),
) -> None:
    """Flag the last dictation as a misrecognition (a learning signal).

    Requires `[learning] enabled = true`. Routes through the running daemon so
    the flag lands on the event it just captured.
    """
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        result = client.call("mark_last_wrong", correction=correction or None)
    except IpcUnreachableError:
        typer.echo("Daemon is not running. Start it with: yazses start", err=True)
        raise typer.Exit(1)
    if result.get("ok"):
        typer.echo("Flagged the last dictation as wrong. `yazses tune` will use it.")
    else:
        typer.echo(f"Could not flag: {result.get('reason', 'no recent event')}", err=True)
        raise typer.Exit(1)


@app.command(
    rich_help_panel=_LEARNING,
    epilog=_examples(
        "yazses coach            speaking-style stats from your recent dictations",
        "yazses coach -n 200     analyse the last 200 dictations",
    ),
)
def coach(
    limit: int = typer.Option(
        100, "--limit", "-n", help="How many recent dictations to analyse."
    ),
) -> None:
    """Show private speaking-style analytics (filler rate, words-per-minute, vocabulary).

    Reads only your local encrypted learning corpus (requires `[learning] enabled = true`).
    Nothing leaves the machine.
    """
    from yazses.coach.analytics import aggregate_stats
    from yazses.learning.capture import open_store

    platform = get_platform()
    data_dir = platform.paths.data_dir
    if not (data_dir / "corpus.db").exists():
        typer.echo("No corpus yet. Enable it with: yazses features enable learning")
        return
    store = open_store(data_dir)
    try:
        events = store.events()
    finally:
        store.close()
    # Only real dictations (injected, non-discarded) carry meaningful style signal.
    samples = [
        (e.final_text, e.audio_secs or 0.0)
        for e in events
        if e.injected and not e.discard_reason and e.final_text
    ]
    samples = samples[-max(1, limit):]
    if not samples:
        typer.echo("No dictations captured yet to analyse.")
        return
    s = aggregate_stats(samples)
    typer.echo(f"Speaking Coach — last {len(samples)} dictation(s):\n")
    typer.echo(f"  words:              {s.words}")
    typer.echo(f"  filler words:       {s.filler_count}  ({s.filler_rate * 100:.1f}% of words)")
    if s.wpm:
        typer.echo(f"  speaking pace:      {s.wpm:.0f} words/min")
    typer.echo(f"  vocabulary variety: {s.type_token_ratio * 100:.0f}% unique words")
    typer.echo("\n  Private + on-device. `yazses corpus destroy` forgets everything.")


@app.command(
    rich_help_panel=_LEARNING,
    epilog=_examples(
        "yazses recall kubernetes deploy   search past dictations for those words",
        "yazses recall                     show your most recent dictations",
    ),
)
def recall(
    query: Optional[list[str]] = typer.Argument(
        None, help="Words to search your past dictations for (omit for most recent)."
    ),
) -> None:
    """Search your past dictations.

    Requires `[learning] enabled = true` and `[recall] enabled = true`. Reads the
    local encrypted corpus only — nothing leaves the machine.
    """
    q = " ".join(query or [])
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        result = client.call("recall", query=q)
    except IpcUnreachableError:
        typer.echo("Daemon is not running. Start it with: yazses start", err=True)
        raise typer.Exit(1)
    if not result.get("ok"):
        typer.echo(f"Recall unavailable: {result.get('reason')}", err=True)
        raise typer.Exit(1)
    hits = result.get("hits", [])
    if not hits:
        typer.echo("No matching dictations.")
        return
    for h in hits:
        typer.echo(f"  • {h['text']}")


@app.command(
    rich_help_panel=_LEARNING,
    epilog=_examples(
        "yazses scratch          list your ambient note-to-self notes",
        "yazses scratch clear    delete all scratch notes",
    ),
)
def scratch(
    action: str = typer.Argument("list", help="list | clear"),
) -> None:
    """Show or clear your ambient scratch notes (spoken "note to self …").

    Notes are captured in command mode when `[recall] scratch = true` and stored in
    a plain local file.
    """
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        result = client.call("scratch", action=action)
    except IpcUnreachableError:
        typer.echo("Daemon is not running. Start it with: yazses start", err=True)
        raise typer.Exit(1)
    if not result.get("ok"):
        typer.echo(f"Scratch unavailable: {result.get('reason')}", err=True)
        raise typer.Exit(1)
    if action == "clear":
        typer.echo(f"Cleared {result.get('cleared', 0)} note(s).")
        return
    notes = result.get("notes", [])
    if not notes:
        typer.echo("No scratch notes yet. Say \"note to self …\" in command mode.")
        return
    for n in notes:
        typer.echo(f"  • {n['text']}")


@app.command(
    name="punch-in",
    rich_help_panel=_DICTATION,
    epilog=_examples(
        "yazses punch-in              re-speak the phrase; correct the best match",
        "yazses punch-in --dry-run    list candidate spans without editing",
        "yazses punch-in --choose 1   apply the 2nd-ranked candidate",
    ),
)
def punch_in(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List candidate spans without editing (confirm first)."
    ),
    choose: int = typer.Option(
        0, "--choose", "-n", help="Apply the candidate at this rank (0 = best)."
    ),
) -> None:
    """Correct the last dictation by re-speaking just the wrong phrase.

    Requires `[punch_in] enabled = true`. The daemon records a short window, aligns
    the respoken phrase against the last burst it typed, then deletes that burst and
    retypes it corrected. Use --dry-run to review candidate spans first, then re-run
    with --choose N to apply a specific one.
    """
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        result = client.call("punch_in", choose=choose, apply=not dry_run)
    except IpcUnreachableError:
        typer.echo("Daemon is not running. Start it with: yazses start", err=True)
        raise typer.Exit(1)
    cands = result.get("candidates") or []
    if result.get("ok"):
        typer.echo(f"Corrected: {result['old']!r} -> {result['new']!r}")
        return
    if dry_run and cands:
        typer.echo("Candidate spans (re-run with --choose N to apply):")
        for i, c in enumerate(cands):
            typer.echo(f"  [{i}] {c['old']!r} -> {c['new']!r}  (score {c['score']})")
        return
    typer.echo(f"Punch-In failed: {result.get('reason', 'no candidates')}", err=True)
    raise typer.Exit(1)


@app.command(
    rich_help_panel=_LEARNING,
    epilog=_examples(
        "yazses tune                     dry-run: print proposed config changes",
        "yazses tune --apply             review and write approved changes",
        "yazses tune --no-retranscribe   skip the slower re-transcription pass",
    ),
)
def tune(
    apply: bool = typer.Option(False, "--apply", help="Review and apply proposals interactively."),
    retranscribe: bool = typer.Option(
        True, "--retranscribe/--no-retranscribe",
        help="Re-transcribe captured audio with a larger model to find errors.",
    ),
) -> None:
    """Analyze the learning corpus and propose accuracy improvements.

    Dry-run by default: prints proposed config changes (vocabulary, VAD
    threshold, model, disfluency rules, SLM few-shots). Use --apply to choose
    which to write to config.toml.
    """
    from yazses.config import load_config
    from yazses.learning.capture import open_store
    from yazses.learning.tuner import run_tune

    platform = get_platform()
    data_dir = platform.paths.data_dir
    if not (data_dir / "corpus.db").exists():
        typer.echo(
            "No corpus yet. Enable it with `[learning] enabled = true` in "
            f"{platform.paths.config_file}, then dictate for a while.",
            err=True,
        )
        raise typer.Exit(1)

    cfg = load_config(platform.paths.config_file)
    store = open_store(data_dir)

    transcribe_fn = None
    if retranscribe:
        from yazses.stt.faster_whisper import FasterWhisperEngine

        typer.echo(f"Loading re-transcription model '{cfg.learning.tune_model}'...")
        engine = FasterWhisperEngine(
            model_name=cfg.learning.tune_model,
            device=cfg.stt.device,
            compute_type=cfg.stt.compute_type,
        )
        transcribe_fn = engine.transcribe

    try:
        run_tune(
            store,
            cfg,
            platform.paths.config_file,
            data_dir / "few_shots.toml",
            do_apply=apply,
            do_retranscribe=retranscribe,
            transcribe_fn=transcribe_fn,
            echo=typer.echo,
            confirm=typer.confirm,
        )
    finally:
        store.close()


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples(
        "yazses transcribe talk.mp3                          transcribe → talk.txt beside it",
        "yazses transcribe talk.mp3 -o notes.txt             choose the output path",
        "yazses transcribe lecture.mp3 --format srt          subtitle file with timestamps",
        "yazses transcribe lecture.mp3 -f md                 Markdown (also: vtt, json)",
        "yazses transcribe talk.mp3 --model small.en         more accurate, slower model",
        "yazses transcribe talk.fr.m4a --language translate  any language → English text",
        "yazses transcribe mtg.m4a --diarize                 tag speakers: 'Speaker 1: …'",
        "yazses transcribe mtg.m4a --diarize --speakers 3    force an exact speaker count",
        "yazses transcribe mtg.wav --diarize --names 'Alice,Bob,Carol'   name them in order",
        "yazses transcribe mtg.wav --diarize --rename speaker_0=Alice    name one speaker",
        "yazses transcribe mtg.m4a --download-models         fetch the ~15 MB diarize models, then exit",
    ),
)
def transcribe(
    audio_file: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True,
        help="Audio file to transcribe (wav/mp3/m4a/ogg/flac/opus/mp4…).",
    ),
    fmt: str = typer.Option(
        "txt", "--format", "-f",
        help="Output format: txt (default) | md | srt | vtt | json (srt/vtt add timestamps)."),
    diarize: Optional[bool] = typer.Option(
        None, "--diarize/--no-diarize",
        help="Tag who said what with local speaker models (needs the diarization extra)."),
    speakers: int = typer.Option(
        0, "--speakers", help="Force an exact speaker count (0 = auto-detect)."),
    min_speakers: int = typer.Option(
        0, "--min-speakers", help="Lower bound on the auto-detected speaker count."),
    max_speakers: int = typer.Option(
        0, "--max-speakers", help="Upper bound on the auto-detected speaker count."),
    names: Optional[str] = typer.Option(
        None, "--names",
        help="Comma list mapped to speakers in order of first appearance: 'Alice,Bob,Carol'."),
    rename: Optional[list[str]] = typer.Option(
        None, "--rename",
        help="Explicit speaker→name map, repeatable: --rename speaker_0=Alice --rename speaker_1=Bob."),
    language: Optional[str] = typer.Option(
        None, "--language",
        help="'en' (default) or 'translate' to render any-language audio into English text."),
    model: Optional[str] = typer.Option(
        None, "--model",
        help="STT model override, e.g. base.en (fast) or small.en (more accurate). Default: your config model."),
    out: Optional[str] = typer.Option(
        None, "--out", "-o", help="Output file path (default: sidecar <audio_file>.<format>)."),
    download_models: bool = typer.Option(
        False, "--download-models",
        help="Download the ~15 MB sherpa diarization models, then exit (no transcription)."),
) -> None:
    """Transcribe an audio file to text — fully offline, on your machine.

    Runs faster-whisper (the same local Whisper STT engine as live dictation)
    over any audio/video file and writes a sidecar next to it (talk.mp3 →
    talk.txt). No cloud, no network, no account — the audio and the transcript
    never leave this computer.

    Input formats: wav, mp3, m4a, ogg, flac, opus, mp4 and most other
    ffmpeg-decodable media (decoded to 16 kHz mono; no extra dependency).

    Output formats (-f / --format): txt (default), md, srt, vtt, json.
    srt/vtt carry timestamps for subtitles. The model defaults to your STT
    config; override per-run with --model (e.g. small.en for better accuracy).
    --language translate transcribes non-English audio into English text.

    With --diarize it also tags who said what, using local sherpa-onnx speaker
    models (install the `diarization` extra; the first run downloads ~15 MB, or
    pre-fetch with --download-models). Each utterance is then prefixed by a
    speaker label; provide --names (positional) or --rename (explicit map) to use
    real names, cap the count with --speakers / --min-speakers / --max-speakers,
    or let an enrolled voiceprint name you ("You"). Everything stays on this
    machine; speaker naming stores no new data and never enrolls anyone
    automatically.
    """
    import dataclasses

    from yazses.config import load_config
    from yazses.recimport.render import VALID_FORMATS, render_transcript

    fmt = (fmt or "txt").lower()
    if fmt not in VALID_FORMATS:
        typer.echo(f"Unknown --format {fmt!r}; expected one of {', '.join(VALID_FORMATS)}.", err=True)
        raise typer.Exit(1)

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    ri = cfg.recimport

    if download_models:
        from yazses.recimport.download import download_models as _dl

        try:
            _dl(ri, echo=typer.echo)
        except Exception as exc:  # pragma: no cover - network/tooling dependent
            typer.echo(f"Model download failed: {exc}", err=True)
            raise typer.Exit(1)
        return

    want_diarize = ri.diarize if diarize is None else diarize
    eff = dataclasses.replace(
        ri,
        diarize=want_diarize,
        max_speakers=speakers or max_speakers or ri.max_speakers,
        min_speakers=min_speakers or ri.min_speakers,
        output_format=fmt,
        model=model or ri.model,
        language=language or ri.language,
    )

    # Build the STT engine from the configured [stt] settings.
    from yazses.stt.faster_whisper import FasterWhisperEngine

    typer.echo(f"Loading model '{eff.model or cfg.stt.model}'…", err=True)
    engine = FasterWhisperEngine(
        model_name=eff.model or cfg.stt.model,
        device=cfg.stt.device,
        compute_type=cfg.stt.compute_type,
    )

    # Speaker naming: parse explicit maps; load the enrolled voiceprint (→ "You").
    name_list = [n.strip() for n in names.split(",")] if names else None
    rename_map: dict = {}
    for item in rename or []:
        if "=" in item:
            key, val = item.split("=", 1)
            rename_map[key.strip()] = val.strip()
    embedder, profiles = None, None
    if want_diarize and eff.name_from_voiceprints:
        embedder, profiles = _load_voiceprints(cfg, platform)
        if profiles:
            typer.echo(
                "Speaker naming uses voiceprints stored only on this machine; "
                "unrecognised speakers stay labelled 'Speaker N'.", err=True)

    from yazses.recimport.pipeline import transcribe_file

    if want_diarize:
        typer.echo("Transcribing and diarizing… (first diarized run downloads ~15 MB of models)", err=True)
    else:
        typer.echo("Transcribing…", err=True)
    try:
        result = transcribe_file(
            str(audio_file), eff,
            names=name_list, renames=rename_map,
            engine=engine, embedder=embedder, profiles=profiles,
        )
    except Exception as exc:
        typer.echo(f"Transcription failed: {exc}", err=True)
        raise typer.Exit(1)

    if want_diarize and not result.diarized:
        typer.echo(
            "Note: diarization was unavailable (install the `diarization` extra and run "
            "`yazses transcribe --download-models`); wrote a plain transcript.", err=True)

    text = render_transcript(result, fmt)
    out_path = Path(out) if out else Path(audio_file).with_suffix("." + fmt)
    out_path.write_text(text, encoding="utf-8")
    n_spk = len({u.speaker for u in result.utterances if u.speaker})
    summary = f" ({n_spk} speaker{'s' if n_spk != 1 else ''})" if result.diarized else ""
    typer.echo(f"Wrote {out_path}{summary}")


def _load_voiceprints(cfg, platform):
    """Return (embedder, {name: embedding}) from the enrolled voiceprint, or (None, None)."""
    try:
        from yazses.learning.crypto import Cipher, load_or_create_key
        from yazses.voiceprint.factory import build_embedder
        from yazses.voiceprint.store import load_voiceprint

        embedder = build_embedder(cfg.voiceprint)
        if embedder is None:
            return None, None
        cipher = Cipher(load_or_create_key(platform.paths.data_dir))
        emb = load_voiceprint(platform.paths.data_dir / "voiceprint.enc", cipher)
        if emb is None:
            return embedder, None
        return embedder, {"You": emb.vector}
    except Exception:  # pragma: no cover - optional/beckend dependent
        return None, None


@corpus_app.command(
    "status",
    epilog=_examples("yazses corpus status    show corpus location, event counts, size, and date range"),
)
def corpus_status() -> None:
    """Show the learning corpus size, event counts, and date range."""
    import datetime as _dt

    from yazses.learning.capture import open_store

    platform = get_platform()
    data_dir = platform.paths.data_dir
    if not (data_dir / "corpus.db").exists():
        typer.echo("No corpus yet (learning capture is off or unused).")
        return
    store = open_store(data_dir)
    try:
        s = store.stats()
    finally:
        store.close()

    def _fmt(ts):
        return _dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else "-"

    typer.echo(f"  location:  {data_dir}")
    typer.echo(f"  events:    {s.count} ({s.discarded} discarded, {s.wrong} flagged wrong)")
    typer.echo(f"  size:      {s.size_bytes / 1_048_576:.1f} MB")
    typer.echo(f"  range:     {_fmt(s.oldest_ts)} → {_fmt(s.newest_ts)}")


@corpus_app.command(
    "forget",
    epilog=_examples("yazses corpus forget -m 10    delete the last 10 minutes of events"),
)
def corpus_forget(
    minutes: float = typer.Option(..., "--minutes", "-m", help="Delete events from the last N minutes."),
) -> None:
    """Delete recently captured events (e.g. after dictating something private)."""
    from yazses.learning.capture import open_store

    platform = get_platform()
    if not (platform.paths.data_dir / "corpus.db").exists():
        typer.echo("No corpus to forget from.")
        return
    store = open_store(platform.paths.data_dir)
    try:
        n = store.forget(minutes)
    finally:
        store.close()
    typer.echo(f"Forgot {n} event(s) from the last {minutes:g} minute(s).")


@corpus_app.command(
    "destroy",
    epilog=_examples("yazses corpus destroy --i-mean-it    irreversibly wipe the whole corpus (DB + clips)"),
)
def corpus_destroy(
    confirm: bool = typer.Option(False, "--i-mean-it", help="Required: confirm irreversible wipe."),
) -> None:
    """Irreversibly delete the entire learning corpus (database + audio clips)."""
    from yazses.learning.capture import open_store

    platform = get_platform()
    if not confirm:
        typer.echo("Refusing without --i-mean-it (this is irreversible).", err=True)
        raise typer.Exit(1)
    if not (platform.paths.data_dir / "corpus.db").exists():
        typer.echo("No corpus to destroy.")
        return
    store = open_store(platform.paths.data_dir)
    store.destroy()
    typer.echo("Learning corpus destroyed.")


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples("yazses test    focus an editor first, then watch for 'YazSes OK'"),
)
def test() -> None:
    """End-to-end self-test: confirm the injector works without speaking.

    Focus a text editor first; this command types `YazSes OK` into the
    focused window. If you see those words appear, injection is working.
    """
    platform = get_platform()
    typer.echo(f"Platform: {platform.name}")
    typer.echo(f"Hotkey:   {_resolved_hotkey(platform)}")
    typer.echo(f"Config:   {platform.paths.config_file}")
    typer.echo("")
    typer.echo("Focus a text editor or browser address bar.")
    typer.echo("Typing 'YazSes OK' into the focused window in 3 seconds...")
    import time

    for i in range(3, 0, -1):
        typer.echo(f"  {i}...")
        time.sleep(1)

    # If the daemon's running, route through it (closer to real hold-to-talk
    # path); otherwise fall back to a local injector.
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    if client.is_reachable():
        typer.echo("Routing through running daemon over IPC.")
        try:
            from yazses.ipc.client import IpcCallError

            result = client.call("inject", text="YazSes OK")
            typer.echo(f"Result: {result}")
            return
        except IpcCallError as exc:
            typer.echo(f"Daemon inject failed ({exc}); falling back to local.")

    injector = platform.injector_factory()
    typer.echo(f"Local injector: {type(injector).__name__}")
    injector.inject("YazSes OK")
    typer.echo("Done. If you saw 'YazSes OK' appear, injection works.")
