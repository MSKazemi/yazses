"""YazSes CLI. Talks to the daemon over IPC where possible, with a
PID-file fallback for status.
"""

from importlib.metadata import version as _pkg_version
from typing import Optional

import typer

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
    if _systemd_managed():
        __import__("subprocess").run(["systemctl", "--user", "start", "yazses"])
    else:
        platform.lifecycle.start_daemon_detached()


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
    if platform.lifecycle.is_running():
        typer.echo("YazSes is already running — restarting it cleanly...")
        _restart_daemon(platform)
        typer.echo(f"YazSes restarted. Hold {_resolved_hotkey(platform)} to dictate.")
        return
    platform.lifecycle.clear_pid()
    platform.lifecycle.start_daemon_detached()
    typer.echo(f"YazSes started. Hold {_resolved_hotkey(platform)} to dictate.")


@app.command(
    rich_help_panel=_DAEMON,
    epilog=_examples("yazses restart    stop every daemon and start exactly one"),
)
def restart() -> None:
    """Restart the daemon — kills any stray/duplicate daemons and starts exactly one.

    Use this if dictation is being typed twice (a sign of duplicate daemons).
    """
    platform = get_platform()
    _restart_daemon(platform)
    typer.echo(f"YazSes restarted. Hold {_resolved_hotkey(platform)} to dictate.")


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
        "yazses features                  list every capability + advice",
        "yazses features info reflow       describe one + show a usage example",
        "yazses features enable read-back  turn one on",
        "yazses features disable cocktail  turn one off",
    ),
)
def features(ctx: typer.Context) -> None:
    """Show every YazSes capability, whether it's on/off, and what's advised.

    Turn things on or off with `yazses features enable <name>` /
    `yazses features disable <name>` — then `yazses restart` to apply.
    """
    if ctx.invoked_subcommand is not None:
        return  # a subcommand (enable/disable) is running instead
    from yazses.config import load_config
    from yazses.system.features import feature_status

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    typer.echo("YazSes capabilities — toggle with `yazses features enable/disable <name>`:\n")
    typer.echo(f"  {'':5}  {'NAME':<32} {'TOGGLE NAME':<14} ADVICE")
    for f in feature_status(cfg):
        mark = "● ON " if f.on else "○ off"
        slug = f.slug if f.toggleable else "—"
        typer.echo(f"  {mark}  {f.name:<32} {slug:<14} {f.tier_label}")
    typer.echo(
        "\n  ●/○ = on/off.  Apply changes with `yazses restart`."
        "\n  Tip: `yazses features enable dysfluency` (use the TOGGLE NAME column)."
        "\n  Details + a usage example for any capability: `yazses features info <name>`."
    )


@features_app.command("info")
def features_info(
    name: str = typer.Argument(..., help="Feature name, e.g. reflow (see `yazses features`)."),
) -> None:
    """Show one capability's description, how to use it, and how to turn it on/off."""
    from yazses.config import load_config
    from yazses.system.features import feature_status, find_feature

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    feat = find_feature(cfg, name)
    if feat is None:
        known = ", ".join(f.slug for f in feature_status(cfg))
        typer.echo(f"Unknown feature {name!r}. Names: {known}", err=True)
        raise typer.Exit(1)
    state = "● ON" if feat.on else "○ off"
    typer.echo(f"{feat.name}  [{feat.slug}]   {state}   ({feat.tier_label})")
    if feat.why:
        typer.echo(f"\n  {feat.why}")
    if feat.example:
        typer.echo(f"\n  Example:  {feat.example}")
    if feat.toggleable:
        typer.echo(f"\n  Enable:   yazses features enable {feat.slug}")
        typer.echo(f"  Disable:  yazses features disable {feat.slug}")
        typer.echo("  Apply:    yazses restart")
    else:
        typer.echo("\n  Always on — not toggleable.")


def _apply_feature_writes(config_file, writes) -> None:
    from yazses.system.configedit import set_config_key

    for section, key, value, quote in writes:
        set_config_key(config_file, section, key, value, quote=quote)


@features_app.command("enable")
def features_enable(
    name: str = typer.Argument(..., help="Toggle name, e.g. read-back (see `yazses features`)."),
    force: bool = typer.Option(False, "--force", help="Allow enabling experimental features."),
) -> None:
    """Turn a capability ON (writes your config), then `yazses restart` to apply."""
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
    typer.echo("Apply it:  yazses restart")


@features_app.command("disable")
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


@vocab_app.command("add")
def vocab_add(
    words: list[str] = typer.Argument(..., help="One or more words/names to add."),
) -> None:
    """Add words to the dictionary so YazSes spells them right (then `yazses restart`)."""
    from yazses.system.vocabulary import add_vocab, vocab_path

    platform = get_platform()
    path = vocab_path(platform.paths.config_file.parent)
    full = add_vocab(path, words)
    typer.echo(f"Added {', '.join(words)}. Dictionary now has {len(full)} word(s).")
    typer.echo("Apply it: yazses restart")


@vocab_app.command("list")
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


@vocab_app.command("remove")
def vocab_remove(word: str = typer.Argument(..., help="The word to remove.")) -> None:
    """Remove a word from your personal dictionary (then `yazses restart`)."""
    from yazses.system.vocabulary import remove_vocab, vocab_path

    platform = get_platform()
    remaining = remove_vocab(vocab_path(platform.paths.config_file.parent), word)
    typer.echo(f"Removed {word!r}. Dictionary now has {len(remaining)} word(s).")


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


@hotkey_app.command("show")
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


@hotkey_app.command("set")
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


@hotkey_app.command("command")
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


@app.command(rich_help_panel=_DAEMON)
def stop() -> None:
    """Stop the running daemon."""
    platform = get_platform()
    pid = platform.lifecycle.read_pid()
    if pid is None or not platform.lifecycle.is_running():
        typer.echo("YazSes is not running.")
        raise typer.Exit(1)
    platform.lifecycle.stop_daemon(pid)
    typer.echo("YazSes stopped.")


@app.command(
    rich_help_panel=_DAEMON,
    epilog=_examples("yazses status    show state, model, hotkey, and uptime"),
)
def status() -> None:
    """Show daemon status. Queries the daemon over IPC when reachable."""
    platform = get_platform()
    if not platform.lifecycle.is_running():
        typer.echo("YazSes is not running.")
        return

    pid = platform.lifecycle.read_pid()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        info = client.call("status")
    except IpcUnreachableError:
        typer.echo(f"YazSes is running (PID {pid}); IPC not yet ready.")
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
        raise typer.Exit(code=1)

    rec = stats.recommended_threshold
    typer.echo(f"  recommended:           {rec}")

    if set_threshold:
        msg = update_threshold_in_config(platform.paths.config_file, rec)
        typer.echo(f"Applied: {msg}")
        typer.echo("Restart to pick it up:  yazses stop && yazses start")
    else:
        typer.echo("Re-run with --set to apply, or put in config.toml:")
        typer.echo(f"  [accessibility]\n  vad_threshold = {rec}")


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
    """Speak text aloud through the offline TTS voice (Read-Back Loop).

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


@app.command(rich_help_panel=_DICTATION)
def overlay() -> None:
    """Run the sonar voice-activity overlay (needs the `overlay` extra: PySide6).

    Draws neon rings near the cursor that pulse with your voice while dictating.
    Normally auto-launched by the daemon when `[overlay] enabled = true`; run it
    here in the foreground to preview or debug it.
    """
    from yazses.overlay.app import run as run_overlay

    run_overlay()


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
    typer.echo(f"Session: {plan.session}")
    if plan.is_noop:
        typer.echo("All Linux requirements already satisfied — nothing to do.")
        raise typer.Exit(0)

    typer.echo("Plan:")
    if plan.apt_packages:
        typer.echo(f"  • install packages: {' '.join(plan.apt_packages)}")
    if plan.add_to_input_group:
        typer.echo("  • add you to the `input` group (sudo)")
    if plan.setup_ydotoold:
        typer.echo("  • set up + enable the ydotoold user service (Wayland injection)")

    if dry_run:
        typer.echo("\n(dry run — no changes made)")
        return

    typer.echo("")
    ok = _setup.apply_plan(plan)
    typer.echo("")
    typer.echo("Verifying with `yazses doctor`...\n")
    from yazses.system.doctor import run_doctor

    run_doctor()
    if not ok:
        typer.echo("\nSome steps need attention — see warnings above.", err=True)
        raise typer.Exit(1)
    typer.echo("\nSetup complete. If you were just added to the `input` group, log out and back in.")


@app.command(rich_help_panel=_SETUP)
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
    """Create your speaker voiceprint (for Cocktail Filter + Voiceprint Mind).

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


gaze_app = typer.Typer(name="gaze", help="Look-to-pane gaze targeting (Glance-Type).")
app.add_typer(gaze_app, rich_help_panel=_SETUP)


@gaze_app.command("calibrate")
def gaze_calibrate() -> None:
    """Calibrate webcam gaze → screen zones (Glance-Type look-to-pane).

    Requires `[gaze] enabled = true` and a webcam, with the gaze deps installed
    (`pip install l2cs mediapipe opencv-python`). You look at a few on-screen
    points to fit the gaze→screen mapping.
    """
    from yazses.config import load_config
    from yazses.gaze.factory import build_gaze

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    backend = build_gaze(cfg.gaze)
    if backend is None:
        typer.echo(
            "Gaze unavailable. Set `[gaze] enabled = true` and install the deps:\n"
            "  pip install l2cs mediapipe opencv-python",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(
        f"Gaze backend '{backend.name}' ready ({cfg.gaze.calibration_points} points). "
        "Interactive calibration UI is in progress; see design/v2-cognitive-layer/03-glance-type.md."
    )


@model_app.command("list")
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
    """Search your past dictations (Spoken Recall).

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
    """Correct the last dictation by re-speaking just the wrong phrase (spec-punch-in).

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


@corpus_app.command("status")
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


@corpus_app.command("destroy")
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
