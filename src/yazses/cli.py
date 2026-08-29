"""YazSes CLI. Talks to the daemon over IPC where possible, with a
PID-file fallback for status.
"""

import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Optional

import typer

from yazses import branding
from yazses.hotkeys.names import SETTABLE_HOTKEYS, SUPPORTED_HOTKEYS, canonical
from yazses.ipc.client import IpcUnreachableError
from yazses.platform import get_paths, get_platform
from yazses.system.logtail import tail_records
from yazses.system.outcomes import describe_outcomes
from yazses.system.relaunch import Mode, command_for

# `yazses.system.updater` is imported inside `update()` rather than here: it pulls
# `urllib.request` and `http.client` (~21 ms) for a network stack that only that one
# command uses, and every invocation — `status`, `stop`, each Tab-completion — was
# paying it. Guarded by tests/test_cli_startup_cost.py.

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


def _maybe_point_at_project(data_dir, *, succeeded: bool) -> None:
    """Show the one-time project pointer, if this is the moment for it.

    Wrapped here so no command has to know the policy. It never raises: a cosmetic
    message must not be able to fail a command that has already succeeded.
    """
    try:
        from yazses.system import nudge, streams

        if not nudge.should_show(
            data_dir, succeeded=succeeded, interactive=streams.stdout_isatty()
        ):
            return
        typer.echo("")
        typer.echo(nudge.message())
        nudge.mark_shown(data_dir)
    except Exception:  # noqa: BLE001 — never let a nicety break a working command
        pass


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
    help=branding.TAGLINE,
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


@app.command(
    rich_help_panel=_DICTATION,
)
def jump(
    target: str = typer.Argument(..., help="Spoken target to jump to (e.g. 'line 10' or 'main').")
) -> None:
    """Jump to a symbol or line in the active editor.

    Uses the configured LSP editor bridge (Neovim/VS Code) to resolve the
    target and move the cursor.
    """
    from yazses.commands.lsp_context import LspContextProvider
    from yazses.jump.target import plan_motion, resolve_target

    bridge = LspContextProvider(editor="auto").bridge
    if not bridge.connect():
        typer.echo(
            "Editor bridge not reachable. Start Neovim with `nvim --listen` "
            "(yazses reads $NVIM).\n"
            "VS Code cannot be used for jumping: its bridge supplies dictation context "
            "only and has no cursor motion, and no YazSes VS Code extension is published.",
            err=True,
        )
        raise typer.Exit(1)

    t = resolve_target(target)
    if t is None:
        typer.echo(f"Could not parse jump target from {target!r}.", err=True)
        raise typer.Exit(1)

    symbols = bridge.get_symbols()
    motion = plan_motion(t, symbols)
    if motion is None:
        typer.echo("Could not plan motion.", err=True)
        raise typer.Exit(1)

    if not bridge.apply_motion(motion.kind, motion.payload):
        typer.echo(f"Failed to apply motion {motion.kind} to {motion.payload}", err=True)
        raise typer.Exit(1)


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


@app.command("fileopen")
def fileopen(
    query: str = typer.Argument(..., help="The spoken query to match a file against."),
    dir: Path = typer.Option(Path("."), "--dir", "-d", help="Directory to search in."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Launch immediately without confirmation."),
) -> None:
    """Open a file by voice: fuzzy matches your spoken query against files in a directory."""
    import os

    from yazses.config import load_config
    from yazses.fileopen.launcher import launch_file
    from yazses.fileopen.match import resolve_open

    # `[fileopen] threshold` is a documented, user-facing key; reading it here is what
    # makes it real. `yazses transcribe` reads its own `[recimport]` section the same
    # way — a CLI one-shot takes its settings from config even though, unlike a voice
    # feature, it is not gated on `enabled` (typing the command *is* the opt-in).
    cfg = load_config(get_platform().paths.config_file)

    try:
        files = [f for f in os.listdir(dir) if os.path.isfile(os.path.join(dir, f))]
    except OSError as e:
        typer.echo(f"Could not read directory {dir}: {e}", err=True)
        raise typer.Exit(1)

    match = resolve_open(query, files, threshold=cfg.fileopen.threshold)
    if not match:
        typer.echo(
            f"No file matched '{query}' in {dir} "
            f"(threshold {cfg.fileopen.threshold:g} — lower `[fileopen] threshold` to match loosely).",
            err=True,
        )
        raise typer.Exit(1)

    if not yes:
        typer.echo(f"Best match: {match}")
        typer.confirm("Open this file?", abort=True)

    try:
        launch_file(dir / match)
    except Exception as e:
        typer.echo(f"Failed to open {match}: {e}", err=True)
        raise typer.Exit(1)
    # Always name what was opened, `--yes` included. This picks a file by fuzzy score,
    # so the one case where the user cannot see the choice being made is exactly the
    # case where they most need to be told which file it landed on.
    typer.echo(f"Opened {match}")


@meeting_app.command("start")
def meeting_start(
    speakers: int = typer.Option(
        0, "--speakers", "-s",
        help="How many people are in the room. On this backend it is an exact count, "
             "not a maximum, so leave it at 0 unless you know the number. "
             "0 = use [meeting] max_speakers."),
) -> None:
    """Start recording a meeting (hands-free — no key to hold).

    Requires `[meeting] enabled = true` (`yazses features enable meeting`). Records
    continuously, streams a live transcript, and — at `yazses meeting stop` — writes a
    speaker-attributed transcript (and opt-in notes) to a per-meeting folder. On-device;
    audio is deleted after the post-pass unless `[meeting] retain_audio = true`.

    `--speakers N` applies to this meeting only and is never written to config: the
    next meeting has a different number of people in it, which is exactly why editing
    `[meeting] max_speakers` between meetings was never going to happen.
    """
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        result = client.call("meeting_start", speakers=speakers)
    except IpcUnreachableError:
        typer.echo("Daemon is not running. Start it with: yazses start", err=True)
        raise typer.Exit(1)
    if result.get("ok"):
        if result.get("warning"):
            typer.echo(f"⚠ {result['warning']}", err=True)
        if result.get("hint"):
            typer.echo(f"Note: {result['hint']}", err=True)
        typer.echo(f"Recording meeting {result['meeting_id']}.")
        typer.echo(f"  Folder: {result['dir']}")
        # Named at start, not only at stop. The transcript is being written to this file
        # as the meeting runs, and a path handed over afterwards is a path the user could
        # not have followed along with -- which is the entire point of writing it live.
        live_md = f"{result['dir']}/live-transcript.md"
        typer.echo(f"  Live transcript (written as you speak): {live_md}")
        typer.echo(f"  Follow it: tail -f {live_md}")
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
        # A timeout and an absent daemon raise the same error, and stopping a
        # meeting routinely outlasts the 2 s IPC timeout: it waits for the
        # in-flight live decode to wind down before it answers. Reporting
        # "Daemon is not running" there tells someone they lost a meeting that
        # is, at that moment, finalizing successfully. Ask the lock — which is
        # held for the process lifetime and cannot be stale — before saying so.
        if platform.lifecycle.is_running():
            typer.echo(
                "The daemon did not answer in time — it is almost certainly still "
                "finalizing this meeting (stopping waits for the current decode)."
            )
            typer.echo("  Check progress: yazses meeting status")
            typer.echo("  Results land in: ~/.local/share/yazses/meetings/")
            raise typer.Exit(0)
        typer.echo("Daemon is not running.", err=True)
        raise typer.Exit(1)
    if result.get("ok"):
        typer.echo(f"Stopped meeting {result['meeting_id']}. Transcribing + finding speakers…")
        typer.echo(f"  Results will appear in: {result['dir']}")
        typer.echo("    transcript.md       — the batch transcript (speaker-labelled)")
        typer.echo("    live-transcript.md  — the live decode, written as you spoke")
        typer.echo("    summary.md          — what came out, and what to distrust")
        typer.echo("  Check progress: yazses meeting status")
        typer.echo(f"  Read the summary:  yazses meeting summary {result['meeting_id']}")
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
        # Only the last few utterances are shown above; the file holds all of them and
        # is being appended to right now. An older daemon does not send this key.
        if live_md := result.get("live_transcript_path"):
            typer.echo(f"  Full live transcript so far: {live_md}")
    elif result.get("finalizing"):
        typer.echo("Finalizing the last meeting (transcribing + diarizing)…")
    else:
        # `.get(..., True)` and not `.get(...)`: an older daemon does not send this key,
        # and reporting "off" from a key that is absent would be a claim invented from a
        # missing fact. Unknown behaves exactly as before.
        if not result.get("enabled", True):
            # Nothing below is actionable while the feature is off. The diarization
            # advice would open "Speaker labels are on but…" -- on a machine where
            # nothing is on -- and prescribe the very command printed here, so it would
            # be a second, contradictory sentence about the same fix.
            typer.echo("Meeting Mode is off — nothing will be recorded.")
            typer.echo("Turn it on with:  yazses features enable meeting")
            recent = result.get("recent", [])
            if recent:
                typer.echo("\nMeetings recorded earlier:")
                for m in recent:
                    typer.echo(
                        f"  {_meeting_row(m)}"
                    )
            return
        diar = result.get("diarization")
        if diar:
            # One implementation of "why not, and what to do", shared with the
            # daemon's `meeting start` warning. This used to recompute the cause
            # correctly and then recommend `--download-models` whichever it was —
            # a ~45 MB download that fixes nothing when the missing piece is a
            # Python package.
            from yazses.recimport.factory import diarization_advice

            # The advice opens with "Speaker labels are on but…", so it is printed
            # as-is; prefixing it produced "Speaker labels: unavailable — Speaker
            # labels are on but…".
            if advice := diarization_advice(diar):
                typer.echo(advice)
        recent = result.get("recent", [])
        if not recent:
            typer.echo("No meetings yet. Start one with: yazses meeting start")
            return
        typer.echo("Recent meetings:")
        for m in recent:
            typer.echo(
                f"  {_meeting_row(m)}"
            )


def _format_uptime(seconds) -> str:
    """Seconds as something a person reads at a glance.

    `uptime: 48176.17s` is how this printed a daemon that had been up thirteen
    hours -- nobody converts that in their head, and two decimal places on half a
    day is precision that was never measured. The value matters most when it is
    large: a long uptime is how you notice a daemon that predates the upgrade.
    """
    if seconds is None:
        return "unknown"
    total = int(float(seconds))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60}s"
    return f"{total // 3600}h {(total % 3600) // 60}m"


def _speaker_summary(m: dict) -> str:
    """How many speakers a meeting has, that it was never labelled, or that it never finished.

    "0 speaker(s)" reads as a failed transcription, and on an undiarized meeting
    it is answering a question nobody asked: speaker labelling was not attempted,
    which is a different statement from "nobody spoke". Measured on a real
    machine, an 8081-second meeting with a 1.7 MB transcript listed as
    `0 speaker(s)`.

    `is False` rather than a falsy test on purpose -- an older `meeting.json`
    without the key says nothing either way, and guessing would assert something
    the file does not contain.

    A meeting that never finalized has no `meeting.json` at all -- it is written
    once, at the end -- so every key here is absent and the fallback rendered it
    as `? speaker(s)`, which reads as "we counted and could not tell" rather than
    "this meeting never finished". The recovery line below says what happened;
    this must not contradict it.
    """
    # `recoverable` is no longer a synonym for "unfinished": a meeting that finished
    # and produced an unusable transcript is offered for recovery too, and calling it
    # unfinished is a false statement about a meeting that ran to the end. The status
    # is the fact; recoverability is a consequence, and only one of them belongs here.
    if m.get("recoverable") and m.get("status") != "done":
        return "unfinished"
    if m.get("diarized") is False:
        return "not diarized"
    count = f"{m.get('num_speakers', '?')} speaker(s)"
    # A bare "86 speaker(s)" reads as a fact about the meeting rather than a symptom.
    # The count is the very thing under suspicion here (ADR-v2-133), so it does not get
    # to stand alone -- printing it unqualified is how a four-person meeting listed as a
    # crowd and nobody looked twice.
    return f"{count} — attribution unreliable" if m.get("attribution_suspect") else count


def _meeting_row(m: dict) -> str:
    """One line describing a stored meeting. The single renderer for all three lists.

    There were three copies of this f-string — `meeting status` has two branches and
    `meeting list` has one — and that is why `duration_s` was missing from all of them:
    adding a column meant remembering three places, so nobody did. The columns are
    ordered by what tells meetings apart fastest: when, how long, who, what came out.
    """
    from yazses.meeting import store

    parts = [str(m.get("id", ""))]
    if length := store.duration_summary(m):
        parts.append(length)
    parts.append(_speaker_summary(m) + (" +notes" if m.get("has_notes") else ""))
    # Loud, and in the columns rather than only in the advice below the row: a meeting
    # whose transcript is not a record of the meeting must not read like the others in a
    # list that is skimmed.
    if m.get("quality_suspect"):
        parts.append("⚠ BAD TRANSCRIPT")
    parts.append(str(m.get("dir", "")))
    return "  ".join(parts)


@meeting_app.command("list")
def meeting_list(
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print meetings as a JSON array (machine-readable; empty list is []).",
    ),
) -> None:
    """List stored meetings on this machine (no daemon required)."""
    import json

    from yazses.config import load_config
    from yazses.meeting import store

    cfg = load_config(get_platform().paths.config_file)
    meetings = store.list_meetings(cfg.meeting)
    if as_json:
        typer.echo(json.dumps(meetings, ensure_ascii=False, default=str))
        return
    if not meetings:
        typer.echo("No meetings found.")
        return
    for m in meetings:
        typer.echo(_meeting_row(m))
        # `list_meetings` has always set `recoverable` on a meeting that never finalized
        # but left a live.jsonl, and this listing -- the only place it would be seen --
        # dropped it. The daemon streams that file all through a meeting for exactly this
        # case, so an hour-long meeting cut short by a crash had its partial transcript
        # sitting on disk with nothing in the product acknowledging it existed.
        #
        # The recording itself is the better artefact and was missed for longer: it is
        # deleted only after the post-pass succeeds, so a crash always leaves it, and
        # `yazses meeting recover` turns it back into a real transcript.
        if m.get("recoverable"):
            lines = store.read_live_lines(m.get("dir", ""))
            for advice in store.recovery_advice(m, len(lines)):
                typer.echo(advice)
        # A meeting whose audio held nothing. Listed here because `meeting stop`
        # returns before the post-pass runs, so this listing is the first surface
        # that can know -- and by default the audio is gone by now, leaving the
        # transcript as the only thing left to distrust.
        warning = store.capture_warning(m)
        if warning:
            typer.echo(f"    {warning}")


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


@meeting_app.command("recover")
def meeting_recover(
    meeting_id: str = typer.Argument(..., help="Meeting id (see `yazses meeting list`)."),
    force: bool = typer.Option(
        False, "--force",
        help="Re-run even a meeting that finished cleanly (its outputs are archived, "
             "never overwritten).",
    ),
) -> None:
    """Re-run the post-pass on a meeting whose finalize never completed.

    The recording is deleted only after a successful post-pass, so a crash, a kill or an
    out-of-memory notes model leaves the whole meeting on disk. This transcribes it,
    diarizes it, and writes the same outputs. Heavy: expect it to take a while
    on CPU. The recording is never deleted here.

    One difference from the live path, stated rather than discovered: enrolled
    voiceprints are not applied, so speakers come back as `speaker_N`. Naming them needs
    the daemon's cipher and embedder; use `yazses meeting relabel <id>` afterwards.
    """
    from yazses.config import load_config
    from yazses.meeting import store
    from yazses.meeting.recover import recover_meeting, recovery_refusal

    cfg = load_config(get_platform().paths.config_file)
    d = _meeting_dir(meeting_id)
    if (reason := recovery_refusal(d, store.read_meta(d), force=force)):
        typer.echo(reason, err=True)
        raise typer.Exit(1)
    typer.echo(f"Recovering {meeting_id} from {d / 'audio.wav'}… (this can take a while)")
    info = recover_meeting(d, cfg.meeting)
    if archived := info.get("archived_previous"):
        typer.echo(f"Previous outputs archived to {archived} (nothing was deleted).")
    for name, path in info["files"].items():
        typer.echo(f"Wrote {path}  ({name})")
    typer.echo("")
    for line in info.get("summary", []):
        typer.echo(line)
    if (warning := store.capture_warning(info)):
        typer.echo(f"\n{warning}", err=True)
    # A retry can collapse the same way the first pass did — the input has not changed.
    # Exiting 0 on that would report a repair that did not happen.
    if info.get("quality_suspect"):
        typer.echo(f"\n{info.get('quality_warning', '')}", err=True)
        raise typer.Exit(1)


@meeting_app.command("summary")
def meeting_summary(
    meeting_id: str = typer.Argument(
        "", help="Meeting id (see `yazses meeting list`). Omit for the most recent."
    ),
) -> None:
    """Show what a meeting produced, where each file is, and what not to trust.

    The answer to "I had a meeting — where are the notes?". Rendered from
    `meeting.json` + `quality.json` through the same function that writes `summary.md`
    at finalize, rather than by printing that file: a meeting recorded before summaries
    existed has no `summary.md` and is still described exactly like a new one, and the
    two surfaces cannot drift into describing one meeting differently.
    """
    from yazses.config import load_config
    from yazses.meeting import store

    cfg = load_config(get_platform().paths.config_file)
    meetings = store.list_meetings(cfg.meeting)
    if not meetings:
        typer.echo("No meetings found.")
        raise typer.Exit(1)
    if meeting_id:
        match = [m for m in meetings if m.get("id") == meeting_id]
        if not match:
            typer.echo(f"No meeting {meeting_id}. See `yazses meeting list`.", err=True)
            raise typer.Exit(1)
        meta = match[0]
    else:
        meta = meetings[0]

    d = _meeting_dir(str(meta.get("id", "")))
    # `ensure_quality`, not `read_quality`: a meeting recorded before the quality check
    # existed has no verdict, and the meeting that motivated the check is one of them.
    # It is computed from the stored transcript here and written back, so asking about
    # an old meeting repairs its record instead of reporting a blank.
    quality = store.ensure_quality(d, meta)
    # Rendering an old meeting must not describe it as healthy just because its
    # `meeting.json` predates the field; the freshly computed verdict wins.
    meta = {**meta, "quality_suspect": bool(quality.get("suspect"))} if quality else meta
    if store.write_live_transcript(d, str(meta.get("id", ""))):
        meta["live_transcript_path"] = str(d / "live-transcript.md")
    lines = store.summary_lines(
        meta, live_lines=len(store.read_live_lines(d)), quality=quality,
    )
    store.write_summary(d, lines)
    for line in lines:
        typer.echo(line)
    # Exit non-zero on a meeting whose transcript is not a record of the meeting, so a
    # script that checks meetings does not have to parse prose to notice.
    if meta.get("quality_suspect"):
        raise typer.Exit(2)


@meeting_app.command("notes")
def meeting_notes(
    meeting_id: str = typer.Argument(..., help="Meeting id to (re)generate notes for."),
    force: bool = typer.Option(
        False, "--force", help="Write notes even for a recording that holds no speech."
    ),
) -> None:
    """Generate meeting minutes (summary, decisions, action items) from the transcript.

    Needs `[meeting] notes = true` and a local `notes_model` GGUF (ADR-v2-128). Runs the
    model locally — expect this to take a while on CPU.
    """
    from yazses.config import load_config
    from yazses.meeting import store
    from yazses.meeting.notes import (
        generate_minutes,
        notes_unavailable_reason,
        render_minutes_md,
    )

    cfg = load_config(get_platform().paths.config_file)
    d = _meeting_dir(meeting_id)
    if not (d / "transcript.json").exists():
        typer.echo(f"No transcript for meeting {meeting_id} in {d}.", err=True)
        raise typer.Exit(1)
    # A transcript produced from a recording with no speech in it is Whisper
    # answering noise, and minutes are the one output nobody can tell apart from a
    # real write-up afterwards. `finalize` already skips the notes pass for these;
    # this is the same rule on the path that regenerates them by hand. Overridable,
    # because a speech detector can be wrong about a very quiet talker and the
    # transcript is right there to judge.
    # Same rule as the capture check below and for the same reason: minutes generated
    # from a collapsed decode are a confident write-up of a meeting that did not happen,
    # and no reader can tell them from a real one. `finalize` already skips the notes
    # pass for these; this is that rule on the by-hand path.
    quality_note = store.read_quality(d)
    if quality_note.get("suspect") and not force:
        from yazses.meeting.quality import warning_from_dict

        typer.echo(
            warning_from_dict(quality_note)
            or "⚠ this transcript did not pass its quality check.", err=True,
        )
        typer.echo(
            "\nRefusing to write minutes from it. Read the transcript first; pass "
            "--force if it really does hold the meeting.", err=True,
        )
        raise typer.Exit(1)

    capture_note = store.capture_warning(store.read_meta(d))
    if capture_note and not force:
        typer.echo(f"{capture_note}\n", err=True)
        typer.echo(
            "Refusing to write minutes from it — a summary of invented words reads "
            "exactly like a real one. Read the transcript first; pass --force if it "
            "does hold speech.",
            err=True,
        )
        raise typer.Exit(1)

    view = store.load_result_view(d)
    # Checked BEFORE the announcement. This printed "Generating minutes locally… (this
    # can take a few minutes)" and then, immediately, that notes were off — promising
    # work that had already been ruled out. The precondition costs nothing to ask.
    if (reason := notes_unavailable_reason(cfg.meeting, utterances=view.utterances)):
        typer.echo(reason, err=True)
        raise typer.Exit(1)
    typer.echo("Generating minutes locally… (this can take a few minutes)")
    minutes = generate_minutes(view.utterances, cfg.meeting, speaker_names=view.speaker_names)
    if minutes is None:
        # Everything checkable up front passed, so this is the model itself: it loaded and
        # returned nothing usable for any window. Saying "notes are off" here would send
        # the user to a setting that is already correct.
        typer.echo(
            "The local model produced no usable minutes for this transcript. See "
            "`yazses logs` for the per-window failures.", err=True,
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

    paths = get_paths()
    cfg = load_config(paths.config_file)
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
    cipher = Cipher(load_or_create_key(paths.data_dir))
    # Replacing an enrollment is allowed -- better audio gives a better voiceprint -- but
    # it destroys biometric data the user deliberately enrolled, and a second person with
    # the same name is indistinguishable from a re-enrollment from in here. Say which
    # happened rather than letting it look like a fresh one.
    from yazses.meeting.participants import existing_participant

    replacing = existing_participant(name, cfg.meeting)
    try:
        path = enroll_participant(
            d, speaker, name, embedder=embedder, cipher=cipher, config=cfg.meeting,
            sample_rate=cfg.audio.sample_rate,
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"Could not enroll {name}: {exc}", err=True)
        raise typer.Exit(1)
    if replacing:
        typer.echo(f"Replaced the existing voiceprint for {name} ({replacing}).")
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


def _configured_model(platform) -> str:
    """The STT checkpoint the daemon will load, or ``""`` if it cannot be read."""
    try:
        from yazses.config import load_config

        return load_config(platform.paths.config_file).stt.model or ""
    except Exception:
        return ""


def _model_is_downloaded(model: str) -> bool:
    """Whether *model* needs the network before the first dictation.

    Goes through ``stt.download.is_cached``, which is also what `doctor` and
    `model list` answer with -- a second opinion here is a second answer, and the
    two screens would disagree in front of the user on the machine where it matters.
    ``is_cached`` already resolves a local directory path, so this is the whole
    predicate, not half of it.
    """
    if not model:
        return True  # nothing configured to check; say nothing rather than guess
    try:
        from yazses.stt.download import is_cached

        return is_cached(model)
    except Exception:
        return True  # never turn a cosmetic check into a scary claim


def _live_hotkey(platform) -> str:
    """The key the running daemon is *actually* listening on, or ``""``.

    The daemon binds its hotkey once, at start, and never re-reads the file. So
    `yazses hotkey set` without a `yazses restart` leaves the configured key and the
    live key disagreeing, and every surface that reads only the config then tells the
    user to hold a key that does nothing — the one failure a new user cannot diagnose,
    because the tools they are told to run all agree with each other and not with the
    machine.

    Best-effort by design, and it must stay that way: no daemon, an older daemon, a
    socket that will not answer — all mean "no second opinion", never an error. A
    diagnostic that fails because a diagnosis was unavailable is worse than one that
    quietly says less.
    """
    try:
        client = platform.ipc_client_factory(platform.paths.ipc_socket)
        if not client.is_reachable():
            return ""
        return str(
            client.call("status", consume_notifications=False).get("hotkey") or ""
        )
    except Exception:
        return ""


def _live_vad_threshold(platform) -> float | None:
    """The gate the running daemon is *actually* applying, or ``None``.

    Best-effort and silent, like `_live_hotkey`: a calibration command must still
    work with no daemon running, which is the ordinary case during first setup.
    """
    try:
        client = platform.ipc_client_factory(platform.paths.ipc_socket)
        if not client.is_reachable():
            return None
        value = client.call("status", consume_notifications=False).get("vad_threshold")
        return float(value) if value is not None else None
    except Exception:  # noqa: BLE001
        return None


def _hotkey_drift_note(platform) -> str:
    """The one-line warning when config and daemon disagree, else ``""``.

    The rule lives in `system/doctor.py` and is shared rather than restated: `doctor`,
    `hotkey show` and `quickstart` are three surfaces answering the same question, and
    three copies of a comparison is how two of them end up saying different things.
    """
    from yazses.system.doctor import hotkey_drift_note

    try:
        from yazses.config import load_config

        configured = (load_config(platform.paths.config_file).hotkey.key or "auto").strip()
    except Exception:
        return ""
    return hotkey_drift_note(
        configured,
        _live_hotkey(platform),
        default=getattr(platform, "default_hotkey", ""),
    ) or ""



def _installed_version() -> str:
    """The package version, or a marker — never an exception.

    ``--version`` is the first thing anyone runs and the first thing a bug report
    quotes, so it must not be the command that crashes. It did: the PyInstaller
    bundle carries no ``.dist-info``, so ``version("yazses")`` raised
    ``PackageNotFoundError`` and `yazses --version` died with a traceback on every
    Windows .exe install. The spec now ships the metadata (``copy_metadata``);
    this keeps the command answering even if that regresses.

    Every other call site already guarded this (``__init__``, ``branding``,
    ``doctor``); the CLI was the one that did not.
    """
    try:
        return _pkg_version("yazses")
    except PackageNotFoundError:
        return "0.0.0+unknown"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"yazses {_installed_version()}")
        raise typer.Exit()


def _show_intro_banner(*, animate: bool = True) -> None:
    """Print the logo banner, optionally preceded by the settling sound-wave.

    Only `quickstart` animates: it is the one screen a user meets before they
    know what the tool does, and the wave says "this listens" before the text
    does. Lookup commands (`about`, `status`, `features`) stay instant — nobody
    wants a 0.4 s animation in front of a version number they are grepping for.
    The ripple is skipped entirely off a TTY, under NO_COLOR, and in CI.
    """
    if animate and branding.should_animate():
        import sys as _sys
        import time

        def _write(chunk: str) -> None:
            _sys.stdout.write(chunk)
            _sys.stdout.flush()

        branding.play_ripple(write=_write, sleep=time.sleep, depth=branding.color_depth())
    typer.echo(branding.banner())
    typer.echo("")


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
            info = client.call("status", consume_notifications=False)
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


def _ensure_autostart(platform) -> None:
    """Make a successful `yazses start` survive the next reboot.

    ``install_autostart()`` was written so that a pipx / uv-tool / pip install gets a
    login service like the packaged installs do — but nothing ever called it except
    ``yazses autostart enable``, a command you only find if you already know it exists.
    So the ordinary path was: install, `yazses start`, dictate happily, reboot, and the
    daemon is gone with nothing anywhere saying why. A daemon you must remember to
    launch is not a daemon.

    Best-effort by design: this runs only after the daemon actually came up, and any
    failure is reported in one line and otherwise ignored — not being set up for next
    login must never turn a working start into a failed command. Already-installed is
    silent; only the transition says anything, and it names the way back out.
    """
    lifecycle = getattr(platform, "lifecycle", None)
    if lifecycle is None or not hasattr(lifecycle, "install_autostart"):
        return
    try:
        if lifecycle.is_autostart_installed():
            return
    except Exception:  # noqa: BLE001 — an unanswerable question is not a reason to act
        return
    try:
        lifecycle.install_autostart()
    except Exception as exc:  # noqa: BLE001 — report, never fail the start
        typer.echo(
            f"  (note: could not set YazSes to start at login: {exc}\n"
            "   dictation is running now; `yazses autostart enable` retries it.)"
        )
        return
    typer.echo("  Also set to start automatically at login (`yazses autostart disable` to undo).")


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
def start(
    no_autostart: bool = typer.Option(
        False,
        "--no-autostart",
        help="Don't also set YazSes to start at login.",
    ),
) -> None:
    """Start the YazSes daemon (restarts cleanly if one is already running).

    Loads the speech model once and listens for the hotkey. If a daemon is already
    running this **restarts** it (killing any stray duplicates) rather than spawning
    a second one — so you never end up double-typing.

    Once the daemon is up, YazSes also sets itself to start at login, so it is running
    when you next sit down instead of silently absent after a reboot. Pass
    `--no-autostart` to skip that, or undo it later with `yazses autostart disable`.
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
    # "loading" counts: the process is alive and merely still fetching the model, which
    # is exactly the first run this is meant to catch. "died" does not — a daemon that
    # cannot start is not one to wire into every login. _report_start_outcome raises
    # Exit(1) in that case, so this runs after it only for the outcomes that survive.
    _report_start_outcome(platform, outcome, info)
    if not no_autostart and outcome in ("ready", "loading"):
        _ensure_autostart(platform)


def _finalizing_meeting(platform) -> bool:
    """True when the daemon is mid post-pass for a meeting that has just stopped.

    Stopping the daemon here destroys work that cannot be redone. `_handle_meeting_stop`
    runs diarization and the notes inline after setting `meeting_finalizing`, the SIGTERM
    handler does not wait for it, and `yazses restart` sends SIGKILL one second later. The
    rolling `live.jsonl` survives, but the accurate batch diarization and the minutes do
    not -- and there is no `yazses meeting recover` to redo them.

    The daemon has published `meeting_finalizing` since Meeting Mode reached the tray. The
    tray reads it, to grey out "Start meeting"; nothing on the stop path did, so the one
    surface that can prevent the loss was the one not asking. Best-effort by design: an
    unreachable or older daemon answers False and the command proceeds, because refusing
    to stop a daemon you cannot query would be worse than the loss it guards against.
    """
    try:
        client = platform.ipc_client_factory(platform.paths.ipc_socket)
        if not client.is_reachable():
            return False
        return bool(
            client.call("status", consume_notifications=False).get("meeting_finalizing")
        )
    except Exception:
        return False


def _refuse_while_finalizing(platform, action: str, force: bool) -> None:
    """Stop the caller when a meeting post-pass is running, unless --force."""
    if force or not _finalizing_meeting(platform):
        return
    typer.echo(
        f"A meeting is still being written up — diarization and the notes are running.\n"
        f"{action} now loses them: the live transcript survives, the speaker labels and "
        f"minutes do not.\n"
        f"Wait for `yazses meeting status` to report it done, or re-run with --force.",
        err=True,
    )
    raise typer.Exit(1)


@app.command(
    rich_help_panel=_DAEMON,
    epilog=_examples("yazses restart    stop every daemon and start exactly one"),
)
def restart(
    force: bool = typer.Option(
        False, "--force", help="Restart even while a meeting is still being written up."
    ),
) -> None:
    """Restart the daemon — kills any stray/duplicate daemons and starts exactly one.

    Use this if dictation is being typed twice (a sign of duplicate daemons).
    """
    platform = get_platform()
    _refuse_while_finalizing(platform, "Restarting", force)
    _warn_unmet_prereqs()
    _restart_daemon(platform)
    outcome, info = _wait_until_ready(platform)
    _report_start_outcome(platform, outcome, info)


@app.command(
    rich_help_panel=_DAEMON,
    epilog=_examples(
        "yazses tray                show the top-bar icon (blocks; Ctrl-C to stop)",
        "yazses tray --background   launch it detached and return",
    ),
)
def tray(
    background: bool = typer.Option(
        False, "--background", "-b", help="Launch detached instead of blocking."
    ),
) -> None:
    """Show the system-tray / top-bar icon with a click-menu (mic + daemon controls).

    Pick or pin your microphone, re-calibrate, and start/stop the daemon from the menu.
    The daemon also launches this automatically when a desktop is present; run this to
    show it right now without a restart. Needs a system tray (on GNOME, the AppIndicator
    extension — standard on Ubuntu).
    """
    if background:
        import subprocess

        subprocess.Popen(
            command_for(Mode.TRAY),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        typer.echo("Tray launched. Look for the microphone icon in your top bar.")
        return
    from yazses.tray.app import run as run_tray

    run_tray()


@app.command(
    rich_help_panel=_DAEMON,
    epilog=_examples(
        "yazses settings    open the settings window (needs a graphical session)",
    ),
)
def settings(
    install_launcher: bool = typer.Option(
        False, "--install-launcher",
        help="Add 'YazSes Settings' to your desktop app grid, then exit."),
    uninstall_launcher: bool = typer.Option(
        False, "--uninstall-launcher",
        help="Remove the app-grid entry and its icons, then exit."),
) -> None:
    """Open the Settings window — every capability as a toggle, grouped by category.

    Reads and writes the same config keys as `yazses features enable/disable`, so
    the two never disagree. Needs a graphical session (no system tray required);
    on a headless or SSH machine use `yazses features` instead. Restart the daemon
    after applying changes: `yazses restart`.

    `--install-launcher` puts an entry in your application menu. A .deb or snap
    does this for you; a pipx or uv-tool install cannot write outside its own
    virtualenv, which left those users with a settings window and no way to reach
    it except by typing this command.
    """
    import os

    data_home = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))

    if uninstall_launcher:
        from yazses.system.launcher import uninstall_launcher as _remove

        removed = _remove(data_home)
        typer.echo(f"Removed {len(removed)} file(s)." if removed else "Nothing to remove.")
        return

    if install_launcher:
        from yazses.system.launcher import install_launcher as _install

        result = _install(data_home)
        typer.echo(result.describe())
        raise typer.Exit(0 if result.installed else 1)

    from yazses.settingsui.app import run as run_settings

    run_settings()


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


#: Width of the catalogue's DOWNLOAD column. Mirrors
#: `depsize.SIZE_COLUMN_WIDTH`, which is what the labels are sized against;
#: `tests/test_cli_features_grouped.py` fails if the two drift apart. Not
#: imported at module scope because `yazses features` must not pay for an import
#: it may not need.
_SIZE_W = 9
#: Width of the NAME column. A cap rather than a measurement: the longest display
#: name is 41 characters, and sizing to it would widen every one of 147 rows by 9
#: columns to accommodate two. Prose, so it is safe to clip -- unlike TOGGLE NAME.
_NAME_W = 32


def _clip(text: str, width: int) -> str:
    """*text* trimmed to *width* columns, with an ellipsis when it did not fit."""
    return text if len(text) <= width else text[: width - 1] + "\u2026"



def _catalogue_size(feat) -> str:
    """What *feat* downloads on a fresh install, for the catalogue, or ``""``.

    Never raises: a size is a courtesy, and `yazses features` failing because one
    could not be computed would be a bad trade (same rule as
    `_feature_download_note`).
    """
    try:
        from yazses.system.depsize import catalogue_size_label

        return catalogue_size_label(feat.slug, bool(getattr(feat, "pip_packages", None)))
    except Exception:  # pragma: no cover - a size must never break the catalogue
        return ""


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
    # Column widths, measured across every row the whole table will show rather than
    # per group, so the groups line up with each other too. `:<32` and `:<16` were
    # minimums, and any longer value pushed DOWNLOAD and ADVICE right for that row
    # alone -- 10 of 147 rows were ragged, and adding one 22-character slug made it
    # 11. The two columns are treated differently on purpose:
    #
    #   TOGGLE NAME is *copied* into `yazses features enable <name>`, so it grows to
    #   fit and is never truncated. A shortened slug is a command that does not run.
    #   NAME is prose and may be clipped; `yazses features info` carries the full text.
    all_shown = [f for _, _, feats in groups for f in feats if _keep(f)]
    slug_w = max([16, *(len(f.slug) for f in all_shown if f.toggleable)])

    for cat, blurb, feats in groups:
        shown = [f for f in feats if _keep(f)]
        if not shown:
            continue
        on_n = sum(1 for f in shown if f.on and not f.inert)
        typer.echo(f"┌─ {cat}  ({on_n}/{len(shown)} on)")
        if blurb:
            typer.echo(f"│  {blurb}")
        typer.echo(
            f"│  {'':5}  {'NAME':<{_NAME_W}} {'TOGGLE NAME':<{slug_w}} "
            f"{'DOWNLOAD':<{_SIZE_W}} ADVICE"
        )
        for f in shown:
            mark = "◌ set" if f.inert else ("● ON " if f.on else "○ off")
            slug = f.slug if f.toggleable else "—"
            size = _catalogue_size(f)
            typer.echo(
                f"│  {mark}  {_clip(f.name, _NAME_W):<{_NAME_W}} {slug:<{slug_w}} "
                f"{size:<{_SIZE_W}} {f.tier_label}"
            )
        typer.echo("└" + "─" * 40)
        total += len(shown)

    if total == 0:
        typer.echo("  No capabilities match that filter.")
        return
    if any(f.inert for f in all_shown):
        # Only when one is actually on screen: a third glyph in the legend is
        # noise on the overwhelming majority of machines, whose configs are clean.
        typer.echo(
            "\n  ◌ = your config turns it on but nothing in this build reads it,"
            " so it does nothing."
            "\n      Clear a stale key with `yazses features disable <name>`."
        )
    typer.echo(
        f"\n  {total} shown.  ●/○ = on/off.  Apply changes with `yazses restart`."
        "\n  DOWNLOAD = what a fresh install fetches in total — packages when you"
        "\n      enable it, plus any model files the first time it runs;"
        " blank = nothing."
        "\n      A trailing + means the model files are not sized here, so the"
        "\n      figure is a floor, not the total."
        "\n  Tip: `yazses features enable dysfluency` (use the TOGGLE NAME column)."
        "\n  Filter:  --on · --tier rec · --category access"
        "\n  Describe ALL capabilities (use case + example): `yazses features info`."
        "\n  Just one: `yazses features info <name>`."
    )


def _echo_feature_card(feat, *, full: bool) -> None:
    """Print one capability. `full` adds the enable/disable/apply block (single view);
    the compact form (used by the catalog) is name + description + example only."""
    state = "◌ set" if feat.inert else ("● ON " if feat.on else "○ off")
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
        if not feat.wired:
            typer.echo(
                "\n  Designed but not yet wired into this build — it cannot be "
                "enabled yet.\n  It stays listed so contributors can pick it up; "
                "see the matching design/adr/ entry."
            )
            if feat.on:
                # Printed directly under a line that said "● ON" until this pass.
                typer.echo(
                    "  Your config turns it on anyway — nothing reads that key, so"
                    " it is doing nothing."
                    f"\n  Clear it:  yazses features disable {feat.slug}"
                )
        elif feat.toggleable:
            # What it will cost, before it is spent (ADR-018). `speechbrain` alone
            # resolves to torch plus the NVIDIA CUDA stack, and until this line
            # existed the only way to find that out was to watch it download.
            note = _feature_download_note(feat)
            if note:
                typer.echo(f"\n  Cost:     {note}")
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

    found = find_feature(cfg, name)
    if found is None:
        known = ", ".join(f.slug for f in feature_status(cfg))
        typer.echo(f"Unknown feature {name!r}. Names: {known}", err=True)
        raise typer.Exit(1)
    _echo_feature_card(found, full=True)


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
    from yazses.system.features import (
        EXPERIMENTAL,
        enable_caveat,
        find_feature,
        toggleable_slugs,
    )

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    feat = find_feature(cfg, name)
    if feat is None:
        typer.echo(
            f"Unknown feature {name!r}. Toggle names: {', '.join(toggleable_slugs())}",
            err=True,
        )
        raise typer.Exit(1)
    if not feat.toggleable:
        # Was folded into the "Unknown feature" branch above, which is false: the
        # capability exists, `yazses features` lists it and `features info` describes
        # it. Only `enable`/`disable` claimed it did not exist -- and answered with a
        # dump of every other name, which is no help to someone who typed a real one.
        typer.echo(
            f"{feat.name} is always on and cannot be toggled — it is what YazSes does. "
            f"See `yazses features info {feat.slug}`.",
            err=True,
        )
        raise typer.Exit(1)
    if not feat.wired:
        typer.echo(
            f"{feat.name} is designed but not yet wired into this build — "
            "enabling it would change nothing (no runtime code reads its "
            "config yet).",
            err=True,
        )
        typer.echo(
            "It stays listed so contributors can pick it up; see the matching "
            "design/adr/ entry.",
            err=True,
        )
        raise typer.Exit(1)
    if feat.tier == EXPERIMENTAL and not force:
        typer.echo(f"{feat.name} is experimental — {feat.why}", err=True)
        typer.echo("Enable anyway with: yazses features enable "
                   f"{feat.slug} --force", err=True)
        raise typer.Exit(1)
    blocked = _feature_deps_blocked(feat)
    if blocked is not None:
        # Refuse *before* writing config. Enabling a capability whose libraries
        # can never arrive would leave a config key that nothing can honour —
        # the same lie `features enable` already refuses for unwired features.
        typer.echo(f"Can't enable {feat.name}: {blocked}", err=True)
        raise typer.Exit(1)
    _apply_feature_writes(platform.paths.config_file, feat.on_writes)
    typer.echo(f"Enabled {feat.name}.  {feat.why}")
    caveat = enable_caveat(feat.slug, cfg)
    if caveat:
        typer.echo(f"\n{caveat}\n")
    _install_feature_deps(feat, skip=no_install)
    typer.echo("Apply it:  yazses restart")


def _feature_download_note(feat) -> str:
    """What enabling *feat* will fetch on this machine, or ``""`` (ADR-018).

    Never raises into the catalogue: a size is a courtesy, and `yazses features`
    failing because a size could not be computed would be a bad trade.
    """
    if not getattr(feat, "pip_packages", None):
        return ""
    try:
        from yazses.system.depsize import download_note

        return download_note(feat.slug, _missing_feature_deps(feat))
    except Exception:  # pragma: no cover - a size must never break the catalogue
        return ""


def _missing_feature_deps(feat) -> list[str]:
    """The feature's optional pip deps that are not importable right now."""
    if not feat.pip_packages:
        return []
    from yazses.system.deps import missing_modules

    if not feat.check_modules:
        return list(feat.pip_packages)
    return missing_modules(feat.check_modules)


def _feature_deps_blocked(feat) -> str | None:
    """Why this environment can never supply *feat*'s libraries, or ``None``.

    Only a genuinely impossible install counts. A snap whose payload already
    bundles the libraries reports nothing here, so every capability that fits
    inside the snap still enables normally.
    """
    if not _missing_feature_deps(feat):
        return None
    from yazses.system.deps import install_blocked_reason

    return install_blocked_reason(feat.pip_packages)


def _install_feature_deps(feat, *, skip: bool) -> None:
    """Install a feature's optional pip deps when any are missing."""
    if not feat.pip_packages:
        return
    from yazses.system.deps import install_packages

    if not _missing_feature_deps(feat):
        return
    # Say what this costs before spending it (ADR-018). Printed even when the
    # install proceeds: a download that turns out to be gigabytes is one the user
    # should have been able to cancel, and knowing mid-download still beats
    # knowing afterwards.
    note = _feature_download_note(feat)
    if note:
        from yazses.system.depsize import is_a_large_download

        loud = is_a_large_download(feat.slug, _missing_feature_deps(feat))
        prefix = "\n⚠  Large download — " if loud else "\n"
        typer.echo(f"{prefix}this {note}.")
        if loud:
            typer.echo(
                "   Ctrl-C now to stop. `--no-install` prints the packages instead "
                "of fetching them."
            )
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
    if feat is None:
        typer.echo(
            f"Unknown feature {name!r}. Toggle names: {', '.join(toggleable_slugs())}",
            err=True,
        )
        raise typer.Exit(1)
    if not feat.toggleable:
        # Was folded into the "Unknown feature" branch above, which is false: the
        # capability exists, `yazses features` lists it and `features info` describes
        # it. Only `enable`/`disable` claimed it did not exist -- and answered with a
        # dump of every other name, which is no help to someone who typed a real one.
        typer.echo(
            f"{feat.name} is always on and cannot be toggled — it is what YazSes does. "
            f"See `yazses features info {feat.slug}`.",
            err=True,
        )
        raise typer.Exit(1)
    _apply_feature_writes(platform.paths.config_file, feat.off_writes)
    typer.echo(f"Disabled {feat.name}.")
    if not feat.wired:
        typer.echo(
            f"Note: {feat.name} was never wired into this build — this only "
            "cleans up the config key an older version may have written."
        )
    typer.echo("Apply it:  yazses restart")


@features_app.command(
    "reset",
    epilog=_examples(
        "yazses features reset --dry-run   show what would change, write nothing",
        "yazses features reset             restore defaults (asks first)",
        "yazses restart                    apply the change",
    ),
)
def features_reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List what would change and write nothing."
    ),
    no_install: bool = typer.Option(
        False, "--no-install", help="Don't auto-install optional deps for what it turns on."
    ),
) -> None:
    """Restore every capability to the state a fresh install ships with.

    The same "Restore defaults" the settings window offers, for machines with no
    graphical session — an SSH box, a server, or a distribution too old for
    PySide6. Only capabilities that are off their default are written, so your
    config file (and its comments) is not churned to change three lines.

    Your hotkey, microphone, vocabulary and any hand-edited settings are left
    alone: this resets the feature switches, not the whole file.
    """
    from yazses.config import load_config
    from yazses.system.features import default_drift

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    drift = default_drift(cfg)

    if not drift:
        typer.echo("Every capability is already at its default. Nothing to do.")
        return

    turning_on = [f for f, desired in drift if desired]
    turning_off = [f for f, desired in drift if not desired]
    typer.echo(f"{len(drift)} capabilit{'y' if len(drift) == 1 else 'ies'} differ(s) "
               "from the defaults:\n")
    for feat in turning_on:
        typer.echo(f"  ○ → ● ON   {feat.name}  [{feat.slug}]")
    for feat in turning_off:
        typer.echo(f"  ● → ○ off  {feat.name}  [{feat.slug}]")

    if dry_run:
        typer.echo("\nDry run — nothing was written. Drop --dry-run to apply.")
        return
    if not yes and not typer.confirm("\nRestore these to their defaults?"):
        typer.echo("Cancelled — nothing was written.")
        raise typer.Exit(1)

    written = 0
    for feat, desired in drift:
        # A default-on capability whose libraries this environment can never
        # supply (a read-only snap, say) is skipped rather than written: the same
        # refusal `features enable` makes, for the same reason — a config key
        # nothing can honour is a lie, not a default.
        if desired and (blocked := _feature_deps_blocked(feat)) is not None:
            typer.echo(f"  Skipped {feat.name}: {blocked}", err=True)
            continue
        _apply_feature_writes(
            platform.paths.config_file, feat.on_writes if desired else feat.off_writes
        )
        written += 1
        if desired:
            _install_feature_deps(feat, skip=no_install)
    typer.echo(f"\nRestored {written} capabilit{'y' if written == 1 else 'ies'} "
               "to their defaults.")
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
        "yazses vocab list                   check what is in the dictionary",
    ),
)
def vocab_add(
    words: list[str] = typer.Argument(..., help="One or more words/names to add."),
) -> None:
    """Add words to the dictionary so YazSes spells them right — no restart needed.

    Good for names, jargon, and acronyms that Whisper keeps mis-hearing. The
    words are primed into the STT prompt; they bias recognition, not force it.
    """
    from yazses.system.vocabulary import add_vocab, vocab_path

    platform = get_platform()
    path = vocab_path(platform.paths.config_file.parent)
    full = add_vocab(path, words)
    typer.echo(f"Added {', '.join(words)}. Dictionary now has {len(full)} word(s).")
    typer.echo("In effect from your next dictation — no restart needed.")


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
    epilog=_examples("yazses vocab remove kubectl    drop a word; no restart needed"),
)
def vocab_remove(word: str = typer.Argument(..., help="The word to remove.")) -> None:
    """Remove a word from your personal dictionary — no restart needed."""
    from yazses.system.vocabulary import remove_vocab, vocab_path

    platform = get_platform()
    remaining = remove_vocab(vocab_path(platform.paths.config_file.parent), word)
    typer.echo(f"Removed {word!r}. Dictionary now has {len(remaining)} word(s).")
    typer.echo("In effect from your next dictation — no restart needed.")


@vocab_app.command(
    "export",
    epilog=_examples(
        "yazses vocab export                       print the dictionary to stdout",
        "yazses vocab export -o vocab.txt          save it to a file",
        "yazses vocab export | ssh box 'yazses vocab import -'   copy it to another machine",
    ),
)
def vocab_export(
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write here instead of stdout."),
) -> None:
    """Print your personal dictionary, one entry per line.

    Defaults to stdout so it pipes and redirects like any other tool.
    """
    from yazses.system.vocabulary import export_vocab, vocab_path

    platform = get_platform()
    text = export_vocab(vocab_path(platform.paths.config_file.parent))
    if output is None:
        # No trailing blank line: typer.echo would add a second newline to text
        # that already ends in one, and the round-trip has to be byte-exact.
        from yazses.system import streams

        if not streams.write_out(text):
            raise typer.Exit(1)  # no console (windowed build): fail loudly, not silently
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    typer.echo(f"Wrote {len(text.splitlines())} word(s) to {output}.")


@vocab_app.command(
    "import",
    epilog=_examples(
        "yazses vocab import team-jargon.txt       merge into your dictionary",
        "yazses vocab import -                     read from stdin",
        "yazses vocab import backup.txt --replace  discard yours and use theirs",
    ),
)
def vocab_import(
    source: str = typer.Argument(..., help="File to import, or '-' for stdin."),
    merge: bool = typer.Option(
        True, "--merge/--replace",
        help="Merge into the existing dictionary (default), or replace it entirely."),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation for --replace."),
) -> None:
    """Add entries from a file (or stdin) to your personal dictionary.

    Merging is the default and de-duplicates, because repeated imports would
    otherwise grow the file and dilute the STT prompt — every entry is primed into
    the decoder, and prompt length is not free.
    """
    from yazses.system.vocabulary import import_vocab, vocab_path

    if source == "-":
        text = sys.stdin.read()
    else:
        path = Path(source)
        if not path.is_file():
            typer.echo(f"No such file: {source}", err=True)
            raise typer.Exit(1)
        text = path.read_text(encoding="utf-8")

    platform = get_platform()
    target = vocab_path(platform.paths.config_file.parent)

    if not merge:
        # Destructive, and one keystroke away from --merge. Confirm unless the
        # user has said they mean it.
        from yazses.system.vocabulary import load_vocab

        current = len(load_vocab(target))
        if current and not yes:
            typer.confirm(
                f"--replace discards your {current} existing word(s). Continue?",
                abort=True,
            )

    full, added = import_vocab(target, text, replace=not merge)
    if merge:
        typer.echo(
            f"Imported {added} new word(s); dictionary now has {len(full)}."
            + (" (the rest were already there)" if added < len(full) else "")
        )
    else:
        typer.echo(f"Replaced the dictionary with {len(full)} word(s).")
    typer.echo("In effect from your next dictation — no restart needed.")


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
        'yazses acronyms add API "Application Programming Interface"   (needed first)',
        'yazses acronyms expand "The API and the API"',
        "  -> The Application Programming Interface (API) and the API",
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
    if not glossary:
        # Without this the command echoes its input back unchanged and says nothing,
        # which reads as "there was nothing to expand" rather than "the glossary this
        # works from is empty". On stderr so a pipe still receives only the text.
        typer.echo(
            "Glossary is empty, so nothing was expanded. Add an entry with: "
            "yazses acronyms add <ACR> <full form>",
            err=True,
        )
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


staged_app = typer.Typer(
    name="staged",
    help="Speak, review, then commit — dictation lands in a buffer instead of typing.",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(staged_app, rich_help_panel=_DICTATION)


def _staged_call(action: str) -> dict | None:
    """Talk to the daemon's staged buffer, or explain why we cannot."""
    platform = get_platform()
    if not platform.lifecycle.is_running():
        typer.echo("YazSes is not running — there is no staged buffer. Start it with `yazses start`.")
        return None
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        return client.call("staged", action=action)
    except IpcUnreachableError:
        typer.echo("YazSes is starting up — try again in a moment.")
        return None


@staged_app.command("status", epilog=_examples("yazses staged status    what is waiting to be typed"))
def staged_status() -> None:
    """Show what is pending review, and whether staged mode is on."""
    info = _staged_call("status")
    if info is None:
        raise typer.Exit(1)
    pending = info.get("pending") or {}
    if not pending.get("enabled"):
        typer.echo("Staged mode is OFF — dictation types straight into the focused app.")
        typer.echo("Turn it on with `yazses features enable staged`.")
    typer.echo(pending.get("summary") or "Nothing pending.")
    preview = pending.get("preview")
    if preview:
        typer.echo("")
        typer.echo(f"  {preview}")


@staged_app.command("commit", epilog=_examples("yazses staged commit    type everything pending"))
def staged_commit() -> None:
    """Type everything pending into the focused app and clear the buffer."""
    info = _staged_call("commit")
    if info is None:
        raise typer.Exit(1)
    if not info.get("committed"):
        # "Nothing staged" is not a failure to report as one, but it is not a
        # success either — the user asked for text to appear and none did.
        typer.echo(f"Nothing typed — {info.get('detail', 'nothing staged')}.")
        raise typer.Exit(1)
    words = len(str(info.get("text", "")).split())
    typer.echo(f"Committed {words} word{'s' if words != 1 else ''}.")


@staged_app.command("discard", epilog=_examples("yazses staged discard    drop everything pending"))
def staged_discard() -> None:
    """Drop everything pending without typing it."""
    info = _staged_call("discard")
    if info is None:
        raise typer.Exit(1)
    dropped = int(info.get("discarded_words") or 0)
    typer.echo(f"Discarded {dropped} word{'s' if dropped != 1 else ''}.")


@staged_app.command("undo", epilog=_examples("yazses staged undo    remove the last burst you staged"))
def staged_undo() -> None:
    """Remove the most recent staged burst (the same as saying "scratch that")."""
    info = _staged_call("undo")
    if info is None:
        raise typer.Exit(1)
    if not info.get("ok"):
        typer.echo("Nothing staged to remove.")
        raise typer.Exit(1)
    typer.echo((info.get("pending") or {}).get("summary") or "Removed.")


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
    # The ends are labelled because the numbering alone sets a trap. This list is
    # newest-first, so #1 is the most recent -- but `recall "the first thing I copied"`
    # deliberately means the OLDEST, which is the right reading of that sentence and is
    # tested as such. A bare "1. …" invites "the first one" and returns the other end.
    # Naming the ends costs two words and removes the ambiguity at the only place the
    # user meets it.
    last = len(items)
    for i, it in enumerate(items, start=1):
        if i == 1 and last > 1:
            typer.echo(f"  {i}. {it}   ← most recent")
        elif i == last and last > 1:
            typer.echo(f"  {i}. {it}   ← oldest")
        else:
            typer.echo(f"  {i}. {it}")


@cliphistory_app.command(
    "recall",
    epilog=_examples(
        'yazses cliphistory recall "the last url"     print the newest URL entry',
        'yazses cliphistory recall "the second one"    print entry #2 (list order)',
        'yazses cliphistory recall "the first thing I copied"   the OLDEST entry',
    ),
)
def cliphistory_recall(
    query: str = typer.Argument(..., help="Spoken-style reference, e.g. 'the last url', 'number 3'."),
) -> None:
    """Print the history entry a spoken reference points to — offline.

    Understands url/link, email, ordinals, and 'number N'; defaults to the most
    recent entry. Exits non-zero if nothing matches.

    Which end is which, because the two natural readings point opposite ways:
    'last', 'latest', 'most recent' mean the NEWEST entry (#1 in `list`), while
    'first' and 'oldest' mean the OLDEST -- 'the first thing I copied' is the right
    reading of that sentence. Numbered ordinals ('second', 'third', 'number 3')
    follow the `list` numbering, which is newest-first.
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



@app.command(
    rich_help_panel=_SETUP,
    epilog=_examples(
        "yazses verify               speak for 3s and prove the whole pipeline works",
        "yazses verify --seconds 5   record for longer",
        "yazses verify --type        also type the result into the focused window",
    ),
)
def verify(
    seconds: float = typer.Option(3.0, "--seconds", "-s", help="How long to record."),
    do_type: bool = typer.Option(
        False, "--type", help="Also type the transcript into the focused window."
    ),
) -> None:
    """Record, transcribe, and prove dictation works end to end on this machine.

    `yazses doctor` checks prerequisites — a mic exists, xdotool is installed. All of those
    can pass while dictation still produces nothing. This runs the real chain and names the
    link that breaks.
    """
    from yazses.config import load_config
    from yazses.system import miclevel
    from yazses.system.verify import verify as run_verify

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    threshold = cfg.accessibility.vad_threshold

    typer.echo(f"Speak normally for {seconds:.0f} seconds — starting now…")

    def _record():
        return miclevel.record(seconds, cfg.audio.sample_rate, device=cfg.audio.device or None)

    def _level(audio) -> float:
        return float(miclevel.analyze(audio, cfg.audio.sample_rate).mean_abs)

    def _transcribe(audio) -> str:
        # Through the factory, not straight to `FasterWhisperEngine`. This command's
        # whole claim is that it runs *the chain the daemon runs*, and the daemon builds
        # its engine here (`core/daemon.py`: `build_engine(cfg.stt)`). Constructing the
        # concrete class instead silently dropped two settings: `[stt] engine`, so a
        # Parakeet user was certified on faster-whisper, and `[stt] language`, which
        # only reaches the decoder through the constructor and defaults to `"en"` — so
        # a Persian install was verified in English and told "the model returned
        # nothing… try a larger one", which is the wrong knob.
        from yazses.stt.factory import build_engine

        return build_engine(cfg.stt).transcribe(audio)

    def _holds_no_speech(audio) -> bool | None:
        """Whether the recording holds no speech at all. Never raises; None = unknown.

        The detector ships inside faster-whisper (a bundled 1.2 MB ONNX asset), so this
        downloads nothing and sends nothing. An import or runtime failure must not break
        a diagnostic command — it means the question cannot be answered, which `verify`
        already handles by leaving its behaviour exactly as it was.
        """
        try:
            from yazses.recimport.audio_io import holds_no_speech

            return holds_no_speech(audio, cfg.audio.sample_rate)
        except Exception:  # noqa: BLE001 — a diagnostic must not fail while diagnosing
            return None

    # The same bridge the daemon applies. Without it `--type` proved a backend the
    # daemon does not use -- and this command's whole claim is that it runs the
    # daemon's chain.
    from yazses.inject.auto import apply_injection_config

    apply_injection_config(cfg.injection)
    injector = platform.injector_factory().inject if do_type else None
    result = run_verify(
        record=_record, level_of=_level, threshold=threshold,
        transcribe=_transcribe, inject=injector, holds_no_speech=_holds_no_speech,
    )

    for step in result.steps:
        typer.echo(f"  [{'OK' if step.ok else 'FAIL'}] {step.name}: {step.detail}")
    typer.echo("")
    if result.ok:
        # The verdict used to be unconditional, and it is the line people read. verify
        # proves the chain RAN; only the user can say the words are the ones they spoke.
        # Recording silence in a quiet room still clears the gate on room noise and gets
        # a confident invented word back, so an unqualified tick certified a mic that
        # was never hearing anyone.
        heard = next((s for s in result.steps if s.name == "Transcription"), None)
        typer.echo("✓ The whole chain ran: captured, heard, cleaned"
                   + (", typed." if do_type else "."))
        if heard is not None:
            typer.echo(f"  It {heard.detail} — if that is not what you said, the mic is "
                       "the problem, not the pipeline:")
            typer.echo("      yazses mic-level --set   ·   yazses audio status")
        _maybe_point_at_project(platform.paths.data_dir, succeeded=True)
        return
    failure = result.failure
    name = failure.name if failure is not None else "Something"
    typer.echo(f"✗ {name} is what's broken — fix that first.", err=True)
    raise typer.Exit(1)


@app.command(
    rich_help_panel=_SETUP,
    epilog=_examples(
        "yazses report                 write a diagnostic file you can attach to an issue",
        "yazses report --print         show it instead of writing it",
        "yazses report -o /tmp/r.json  choose where it goes",
    ),
)
def report(
    out: Optional[str] = typer.Option(None, "--output", "-o", help="Where to write it."),
    show: bool = typer.Option(False, "--print", help="Print it instead of writing a file."),
    log_lines: int = typer.Option(200, "--log-lines", help="How much log tail to include."),
) -> None:
    """Collect a diagnostic report locally — nothing is uploaded.

    Includes versions, the daemon's state, your settings with paths, identifiers and
    anything you typed yourself removed, and the tail of the metadata-only log. Your
    dictated text and the learning corpus are never included. Read it, then attach it to
    an issue yourself if you want to.
    """
    from yazses.system import report as report_mod

    platform = get_platform()
    try:
        client = platform.ipc_client_factory(platform.paths.ipc_socket)
        status = client.call("status", consume_notifications=False)
    except Exception:  # noqa: BLE001 — a dead daemon is exactly when this is needed
        status = None

    data = report_mod.collect(
        config_file=platform.paths.config_file,
        log_file=platform.paths.log_dir / "daemon.log",
        data_dir=platform.paths.data_dir,
        status=status,
        log_lines=log_lines,
    )
    if show:
        import json

        typer.echo(json.dumps(data, indent=2, sort_keys=True, default=str))
        return

    target = Path(out) if out else platform.paths.data_dir / "yazses-report.json"
    bundle = report_mod.write(data, target)
    typer.echo(f"Wrote {bundle.path}")
    typer.echo(f"  {bundle.summary}")
    typer.echo("\nNothing was sent anywhere. Read it, then attach it to an issue if you like:")
    typer.echo("  https://github.com/MSKazemi/yazses/issues/new")


autostart_app = typer.Typer(
    name="autostart",
    help="Start YazSes automatically at login, so it survives a reboot.",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(autostart_app, rich_help_panel=_SETUP)


@autostart_app.command(
    "enable",
    epilog=_examples("yazses autostart enable    start YazSes automatically at login"),
)
def autostart_enable() -> None:
    """Install and enable the login service, so YazSes is running when you sit down.

    Works for every install method — pipx, uv tool, pip, apt. The service is written to
    point at this exact install, and rewritten if an upgrade moves it.
    """
    platform = get_platform()
    try:
        platform.lifecycle.install_autostart()
    except Exception as exc:  # noqa: BLE001 — report, don't traceback at the user
        typer.echo(f"Could not enable autostart: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo("YazSes will now start automatically at login.")
    typer.echo("Verify any time with:  yazses doctor")


@autostart_app.command(
    "disable",
    epilog=_examples("yazses autostart disable   stop launching YazSes at login"),
)
def autostart_disable() -> None:
    """Stop starting YazSes at login. The daemon keeps running until you stop it."""
    platform = get_platform()
    try:
        platform.lifecycle.uninstall_autostart()
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Could not disable autostart: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo("YazSes will no longer start at login.")


@autostart_app.command(
    "status",
    epilog=_examples("yazses autostart status    will YazSes come back after a reboot?"),
)
def autostart_status() -> None:
    """Say whether YazSes will be running after the next reboot."""
    platform = get_platform()
    try:
        installed = platform.lifecycle.is_autostart_installed()
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Could not determine autostart state: {exc}", err=True)
        raise typer.Exit(1) from exc
    if installed:
        typer.echo("Enabled — YazSes starts automatically at login.")
        return
    typer.echo("Not enabled — YazSes will NOT come back after a reboot.")
    typer.echo("Enable it with:  yazses autostart enable")
    raise typer.Exit(1)


audio_app = typer.Typer(
    name="audio",
    help="See and pin the input microphone (fixes a mic that silently switches).",
    context_settings=CONTEXT_SETTINGS,
    no_args_is_help=True,
)
app.add_typer(audio_app, rich_help_panel=_SETUP)


@audio_app.command(
    "devices",
    epilog=_examples("yazses audio devices    list microphones (● = OS default, ★ = pinned)"),
)
def audio_devices() -> None:
    """List capture-capable audio input devices."""
    from yazses.audio.devices import list_input_devices
    from yazses.config import load_config

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    pinned = (cfg.audio.device or "").strip().lower()
    try:
        devices = list_input_devices()
    except Exception as exc:  # pragma: no cover - hardware/backend dependent
        typer.echo(f"Could not list audio devices: {exc}")
        raise typer.Exit(1) from exc
    if not devices:
        typer.echo("No input devices found. Is a microphone connected?")
        return
    typer.echo("Input devices:")
    for dev in devices:
        default_mark = "●" if dev.is_default else " "
        pin_mark = "★" if pinned and pinned in dev.name.lower() else " "
        typer.echo(f"  {default_mark}{pin_mark} [{dev.index}] {dev.name}")
    typer.echo("\n  ● = OS default   ★ = pinned in config")
    if pinned:
        typer.echo(f"  Pinned to: {cfg.audio.device!r}")
    else:
        typer.echo("  Not pinned — follows the OS default. Pin with `yazses audio use <name>`.")


@audio_app.command(
    "use",
    epilog=_examples(
        "yazses audio use 'AT Translated'    pin the built-in laptop mic (name substring)",
        "yazses audio use --clear            unpin; follow the OS default again",
        "yazses restart                      apply the change",
    ),
)
def audio_use(
    name: str = typer.Argument("", help="Microphone name (case-insensitive substring)."),
    clear: bool = typer.Option(False, "--clear", help="Unpin; follow the OS default."),
) -> None:
    """Pin the input microphone by name so a monitor/headset can't steal capture.

    The name is a case-insensitive substring, resolved fresh on every recording, so it
    survives a hotplug that renumbers devices. Run `yazses audio devices` to see names.
    """
    from yazses.audio.devices import is_routing_alias, list_input_devices, match_input_devices
    from yazses.system.configedit import set_config_key

    platform = get_platform()
    if clear:
        set_config_key(platform.paths.config_file, "audio", "device", "")
        typer.echo("Unpinned — capture will follow the OS default input device.")
        typer.echo("Apply it:  yazses restart")
        return
    if not name.strip():
        typer.echo("Give a microphone name (or --clear). See `yazses audio devices`.")
        raise typer.Exit(2)
    try:
        matches = match_input_devices(name, list_input_devices())
    except Exception:  # pragma: no cover - hardware/backend dependent
        matches = []

    # More than one device answers to this name, and the pin would resolve to whichever
    # PortAudio enumerates first. That order is not stable across a hotplug or a reboot --
    # it is the exact thing pinning exists to defeat -- so the pin would look like a
    # guarantee and not be one. Refuse while the user is still at the prompt: their intent
    # is genuinely underdetermined, and this machine's own capture list makes it easy to
    # hit (three entries share the prefix `sof-hda-dsp: -`).
    if len(matches) > 1:
        typer.echo(f"{name!r} matches {len(matches)} input devices:")
        for dev in matches:
            typer.echo(f"    {dev.name}")
        typer.echo("")
        typer.echo("Pinning it would select whichever the sound system happens to list")
        typer.echo("first, which can change on a reboot. Name one of them exactly:")
        typer.echo(f'    yazses audio use "{matches[0].name}"')
        raise typer.Exit(2)

    if not matches:
        typer.echo(
            f"No input device matches {name!r}. Run `yazses audio devices` to see names."
        )
        typer.echo("Pinning it anyway — it will apply if that device appears later.")

    set_config_key(platform.paths.config_file, "audio", "device", name)
    # Echo the device, not the string that was typed. A substring pin is meant to be
    # loose, and the only confirmation that it caught the intended microphone is naming
    # the one it resolved to.
    if matches:
        typer.echo(f"Pinned input microphone to {name!r} → {matches[0].name}")
    else:
        typer.echo(f"Pinned input microphone to {name!r}.")

    # Pinning a route pins nothing. `default`/`pipewire`/`sysdefault` forward to whatever
    # the sound server currently points at, so the device behind the name can change with
    # the name unchanged -- the failure this command exists to prevent. `audio status`
    # already refuses to *advise* an alias; accepting one here without a word left the two
    # halves of the same guarantee disagreeing.
    if matches and is_routing_alias(matches[0].name):
        typer.echo(
            f"⚠ {matches[0].name!r} is a route, not a microphone — the device behind it can\n"
            "  change without this name changing, so this pin cannot hold capture in place.\n"
            "  Pin a hardware name from `yazses audio devices` to be sure."
        )
    typer.echo("Apply it:  yazses restart")


@audio_app.command(
    "status",
    epilog=_examples("yazses audio status    show pinned vs default mic + live capture health"),
)
def audio_status() -> None:
    """Show the pinned mic, the OS default, and (if running) live capture health."""
    from yazses.audio.devices import (
        current_default_input_name,
        default_source_behind_alias,
        is_routing_alias,
    )
    from yazses.config import load_config

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    pinned = (cfg.audio.device or "").strip()
    typer.echo(f"Pinned mic:    {pinned or '(none — follows OS default)'}")
    try:
        default_name = current_default_input_name()
        typer.echo(f"OS default:    {default_name or '(unknown)'}")
        # `default`/`pipewire` name a route, not a microphone. The device-change
        # watcher spots a switch by comparing this name over time, so against an
        # alias it compares "default" with "default" for ever and never fires --
        # the mic behind it can change with nothing on screen changing. Worth
        # saying here, because this is the page someone opens when dictation
        # stopped working and they are trying to find out what it is listening to.
        if not pinned and is_routing_alias(default_name):
            # Naming the alias is not enough on the screen someone opens when
            # dictation stopped: they need to know *which* microphone it currently
            # points at. Best-effort via wpctl, absent without complaint.
            behind = default_source_behind_alias()
            behind_name = None
            if behind:
                behind_name, vol = behind
                typer.echo(f"               → {behind_name}  (volume {vol * 100:.0f}%)")
            typer.echo(
                "               ⚠ that is a routing alias, not a microphone — the "
                "device behind it\n"
                "                 can change without this name changing."
            )
            # The advice used to be a fixed "yazses audio use <name>", printed directly
            # under the resolved device name -- which reads as "type that name", and on a
            # PipeWire desktop that name is not in the capture list at all. `audio use`
            # warns and pins it anyway (for hotplug), so the pin never resolves and
            # capture quietly follows the alias again. Derived from the name now.
            from yazses.audio.devices import alias_pin_advice, list_input_devices

            try:
                advice = alias_pin_advice(behind_name, list_input_devices())
            except Exception:  # pragma: no cover - hardware/backend dependent
                advice = "Pin one of the names from `yazses audio devices`."
            typer.echo(f"                 {advice}")
    except Exception:  # pragma: no cover - hardware/backend dependent
        typer.echo("OS default:    (unavailable)")
    if not platform.lifecycle.is_running():
        typer.echo("Daemon:        not running")
        return
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        info = client.call("status", consume_notifications=False)
    except IpcUnreachableError:
        typer.echo("Daemon:        starting up")
        return
    typer.echo(f"Live capture:  {info.get('input_device') or '(default)'}")
    typer.echo(f"Last-good mic: {info.get('last_good_device') or '(none yet)'}")
    streak = info.get("silent_streak") or 0
    if streak:
        from yazses.audio.device_monitor import silent_streak_advice

        # The count is already the line's subject, so only the remedies are borrowed
        # -- the headline would repeat it.
        _headline, remedies = silent_streak_advice(streak)
        typer.echo(f"⚠ silent clips in a row: {streak}")
        for line in remedies:
            typer.echo(f"               {line}")


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
    # This command's whole job is to answer "which key do I hold?", and until now it
    # answered from the file while the daemon answered from memory. On a machine mid-drift
    # it printed the two keys with their labels swapped -- naming the key that actually
    # dictates as the command key -- which is worse than saying nothing.
    drift = _hotkey_drift_note(platform)
    if drift:
        typer.secho(f"\n⚠ {drift}", fg=typer.colors.YELLOW)
    typer.echo(f"Choices: {', '.join(SETTABLE_HOTKEYS)}")


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
    # SETTABLE, not SUPPORTED: `auto` is a real choice — it is the shipped default
    # and means "the usual key for this OS". Offering only bindable keys made
    # picking one a door that closed behind you, with no way back to the default
    # short of editing TOML.
    if key not in SETTABLE_HOTKEYS:
        typer.echo(
            f"Unknown key {key!r}. Choose one of: {', '.join(SETTABLE_HOTKEYS)}", err=True
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
    from yazses.system.configedit import set_config_key

    platform = get_platform()
    if key.lower() in {"off", "none", "clear", "disable"}:
        set_config_key(platform.paths.config_file, "hotkey", "command_key", "")
        typer.echo("Command key removed (commands auto-detected on the dictation key).")
        typer.echo("Apply it:  yazses restart")
        return
    # SUPPORTED, not SETTABLE: `auto` means "the platform's default dictation
    # key", which is meaningless for a *command* key and would silently alias
    # onto the dictation key on most machines.
    if key not in SUPPORTED_HOTKEYS:
        typer.echo(
            f"Unknown key {key!r}. Choose one of: {', '.join(SUPPORTED_HOTKEYS)}, or 'off'.",
            err=True,
        )
        raise typer.Exit(1)
    # `_resolved_hotkey` rather than the raw config value: the default is the
    # sentinel "auto", which never equals a real key name, so the clash below was
    # invisible on exactly the config every new install starts with.
    #
    # Compared through `canonical()` because right_option and right_alt are one
    # physical key under two names — a string comparison waves that clash through
    # and command mode then swallows every dictation burst.
    dictation = _resolved_hotkey(platform)
    if canonical(key) == canonical(dictation):
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
def stop(
    force: bool = typer.Option(
        False, "--force", help="Stop even while a meeting is still being written up."
    ),
) -> None:
    """Stop the running daemon.

    Dictation stays off until you `yazses start` again. To pick up a config or
    version change instead, use `yazses restart` (stop + start in one step).
    """
    platform = get_platform()
    _refuse_while_finalizing(platform, "Stopping", force)
    pid = platform.lifecycle.read_pid()
    if pid is None or not platform.lifecycle.is_running():
        typer.echo("YazSes is not running — nothing to stop.")
        raise typer.Exit(1)
    platform.lifecycle.stop_daemon(pid)
    typer.echo("YazSes stopped. Start it again with `yazses start`.")


@app.command(
    rich_help_panel=_DAEMON,
    epilog=_examples(
        "yazses status         show state, model, hotkey, and uptime",
        "yazses status --json  dump status as JSON for scripts and status bars",
    ),
)
def status(
    json_output: bool = typer.Option(
        False, "--json", help="Output status as JSON for scripts and status bars."
    ),
) -> None:
    """Show daemon status. Queries the daemon over IPC when reachable."""
    import json as _json

    from yazses.stt.latency import render_status_lines

    platform = get_platform()
    if not platform.lifecycle.is_running():
        if json_output:
            typer.echo(_json.dumps({"running": False, "state": "stopped", "pid": None, "ready": False}))
            return
        typer.echo("YazSes is not running. Start it with `yazses start`.")
        typer.echo("New here? Run `yazses quickstart` for the 3-step setup.")
        return

    pid = platform.lifecycle.read_pid()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        info = client.call("status", consume_notifications=False)
    except IpcUnreachableError:
        if json_output:
            typer.echo(_json.dumps({"running": True, "state": "starting", "pid": pid, "ready": False}))
            return
        typer.echo(
            f"YazSes is running (PID {pid}) but still starting up — it's loading the "
            "speech model (first run can take 10–30s). Re-run `yazses status` shortly."
        )
        return

    if json_output:
        data = dict(info)
        data["running"] = True
        data["pid"] = pid
        if "ready" not in data:
            state = str(data.get("state", "")).lower()
            data["ready"] = state in ("idle", "recording", "injecting")
        typer.echo(_json.dumps(data))
        return

    typer.echo(f"YazSes is running (PID {pid}).")
    typer.echo(f"  state:    {info.get('state')}")
    typer.echo(f"  hotkey:   {info.get('hotkey')}")
    typer.echo(f"  model:    {info.get('model')}")
    typer.echo(f"  backend:  {info.get('injection_backend')}")
    # Whether dictation is leaving this machine. The daemon has published
    # `remote_connected` all along and nothing read it -- not `status`, not the tray -- so
    # after the first burst of a remote session no surface said so. `state` cannot stand
    # in: it is REMOTE_ACTIVE only until the next hold, which ends at IDLE.
    #
    # ADR-011 promises nothing leaves the machine and ADR-019 enumerates the two
    # exceptions; this is one of them, running. It is worth a line even though the user
    # started it themselves, because a session survives a reboot of their attention.
    if info.get("remote_connected"):
        typer.echo("  remote:   ON — dictation is being sent to the host you connected to")
    if info.get("input_device"):
        typer.echo(f"  mic:      {info.get('input_device')}")
    typer.echo(f"  uptime:   {_format_uptime(info.get('uptime_s'))}")
    # Decode latency, per model, over a bounded recent window (#296). Absent on a
    # daemon that has not decoded anything yet, and on an older daemon — a status
    # command that errors against a running daemon is worse than a missing line.
    for line in render_status_lines(info.get("decode_latency")):
        typer.echo(line)
    # How often dictation actually produced text. Absent until there is enough to
    # mean something, and absent on an older daemon that does not send the field.
    for outcome_line in describe_outcomes(info.get("outcomes")):
        typer.echo(outcome_line)
    if info.get("silent_streak"):
        typer.echo(
            f"  ⚠ mic:    {info['silent_streak']} silent clips in a row — "
            "run `yazses audio status`"
        )
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

    _show_intro_banner()
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
        # Three outcomes, not two. `build_plan` is defensive here because this is the
        # first screen a new user meets and it must not traceback -- but "we could not
        # find out" is not the same fact as "everything is fine", and collapsing the
        # two printed a ✓ that had checked nothing. `None` keeps them apart, and the
        # unknown case borrows the wording the non-Linux branch already uses.
        needs_setup: bool | None = None
        confined = False
        try:
            from yazses.system import setup as _setup

            _plan = _setup.build_plan()
            confined = _plan.confined
            if confined:
                # A fourth outcome. Inside a strict snap the plan is empty by
                # design -- nothing there is ours to do -- so `is_noop` is True
                # while the machine may be entirely unusable. Its prerequisites
                # are the two interfaces, which the plan cannot express.
                needs_setup = _setup.snap_mic_pending() or _setup.snap_rawinput_pending()
            else:
                needs_setup = not _plan.is_noop
        except Exception:
            needs_setup = None
        if needs_setup is None:
            _say_step("Check prerequisites", "Run:  yazses doctor")
        elif needs_setup and confined:
            _say_step(
                "Grant the snap its permissions",
                "Run:  yazses setup",
                "(prints the `snap connect` commands — a confined snap cannot grant itself access)",
            )
        elif needs_setup:
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
    #
    # The model state is checked here because this screen's own docstring promises it
    # ("prerequisites, whether the daemon is running, the speech model, your hotkey")
    # and, until this was added, three of those four were read and the model was not.
    # It printed "first run can take 10-30s" unconditionally -- which is the *load*
    # time for a checkpoint already on disk, and says nothing at all about the case
    # that goes wrong: a checkpoint that is not there yet.
    #
    # That case is #310, the first bug reported by a real user: a firewall blocked the
    # automatic fetch, so `yazses start` sat there with nothing to read. Naming the
    # download as its own step moves the failure to a command whose entire job is to
    # download, where it can be reported.
    if running:
        _say_step("Start YazSes — already running ✓", "Check it with:  yazses status")
    else:
        model = _configured_model(platform)
        if _model_is_downloaded(model):
            body = ["Run:  yazses start"]
            if model:
                body.append(f"The speech model ({model}) is already downloaded ✓")
            body.append("It loads the model, then waits for your hotkey.")
            _say_step("Start YazSes", *body)
        else:
            _say_step(
                "Get the speech model, then start YazSes",
                f"⚠ {model} is not downloaded yet — this is the one step that needs the network.",
                f"Run:  yazses model download {model}",
                "Then: yazses start",
                "(`yazses start` fetches it on its own too, but if the network blocks it",
                " that happens mid-start with nothing to read. Downloading it here reports why.)",
            )

    # Step 3 — actually dictate.
    #
    # The key printed here is the one that *works right now*, not the one in the file.
    # This is the first screen a new user reads, and its instruction is a single
    # imperative: hold this key. If the daemon is bound to a different key -- which is
    # what `yazses hotkey set` without a restart leaves behind -- then following the
    # instruction does nothing at all, and there is no error anywhere to explain why.
    live = _live_hotkey(platform)
    drift = _hotkey_drift_note(platform)
    press = live or hotkey
    body = [
        f"Hold  {press}  , speak, then release. Your words type into the focused window.",
    ]
    if drift:
        body.append(f"⚠ {drift}")
    body.append("Change the key with:  yazses hotkey set <key>")
    _say_step("Dictate", *body)

    typer.secho("Handy next steps", bold=True)
    typer.echo("  yazses test              type a test phrase (no speaking) to confirm typing works")
    typer.echo("  yazses mic-level --set   tune the mic to your voice if words get dropped")
    typer.echo("  yazses features          see everything YazSes can do, and turn things on/off")
    typer.echo("  yazses doctor            diagnose anything that isn't working")
    if not shutil.which("yazses"):  # pragma: no cover - defensive
        typer.echo("\n  (If `yazses` isn't found, restart your shell to refresh PATH.)")

    # Asked once, here, and nowhere else. A tool nobody has heard of is found by
    # word of mouth or not at all, and this is the only moment the user is looking
    # at the project rather than at their own work. It never repeats and never
    # blocks — `quickstart` is read-only and explicitly invoked.
    typer.secho("\nIf YazSes turns out to be useful", bold=True)
    typer.echo("  A star is how other people find it — there is no company or ad budget behind this:")
    typer.echo("    https://github.com/MSKazemi/yazses")
    typer.echo("  Not working, or missing something you need? Open an issue — a human reads them.")


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


def _echo_steps(steps: list[str]) -> None:
    """Print manual update instructions as an indented block (blank lines kept)."""
    if not steps:
        return
    typer.echo("")
    for step in steps:
        typer.echo(f"  {step}" if step else "")


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
    """Check for a newer YazSes and update it (snap / uv / pipx / pip / Windows).

    Detects how YazSes was installed and checks the matching source — the tracked
    snap channel for snap, the GitHub release for the Windows installer, Chocolatey,
    winget and Scoop (that is where the .exe lives), PyPI for the pip-family ones —
    then upgrades only when the available version is strictly newer (never a
    downgrade). Where there is no one-command upgrade, or the network is blocked,
    it prints the steps to update by hand instead of just failing. After an upgrade,
    restart the daemon to load the new code: `yazses restart`.
    """
    from yazses.system.updater import (
        check_update,
        manual_update_steps,
        pinned_install_hint,
        run_upgrade_checked,
    )

    current = _installed_version()
    status = check_update(current)
    typer.echo(f"Installed:  yazses {current}  (via {status.method})")

    if status.latest is None:
        # The check needs the network; dictation does not. A blocked check is not
        # a broken YazSes, so say what still works and hand over the manual steps
        # rather than leaving the user with an error and no way forward.
        typer.echo(f"Could not check for updates — {status.note}.", err=True)
        _echo_steps(status.steps)
        raise typer.Exit(1)

    typer.echo(f"Available:  yazses {status.latest}")

    if not status.available:
        typer.echo("You're on the latest version. ✓")
        return

    typer.echo(f"\nUpdate available: {current} → {status.latest}")
    if not status.command:
        # No command for this method — the Windows installer and the macOS .app
        # are the live cases (the upgrade is a downloaded .exe or .dmg, with
        # nothing safe to shell out to).
        # Exact steps for a channel we recognise is a success; for a method we
        # have no recipe for, the generic advice is still printed but the exit
        # code stays non-zero, because we genuinely could not do what was asked.
        from yazses.system.updater import GITHUB_METHODS

        known = status.method in GITHUB_METHODS
        if known:
            typer.echo(f"There's no one-command upgrade for a {status.method} install. Do this:")
        else:
            typer.echo(
                f"No automatic upgrade is available for a {status.method!r} install.", err=True
            )
        _echo_steps(status.steps)
        if not known:
            raise typer.Exit(1)
        return
    typer.echo(f"Command: {' '.join(status.command)}")

    if check:
        typer.echo("\n(--check) Not installing. Re-run without --check to update.")
        return

    if not yes and not typer.confirm("Install it now?", default=True):
        typer.echo("Skipped.")
        return

    # Verified, not assumed: `uv tool upgrade` exits 0 and changes nothing when the
    # install carries an exact version pin, and this used to print "Updated to X"
    # over the top of the package manager's own "Nothing to upgrade".
    outcome = run_upgrade_checked(status)
    if outcome.ok:
        typer.echo(f"\nUpdated to {outcome.after}. Restart the daemon to load it:")
        typer.echo("  systemctl --user restart yazses   # or: yazses stop && yazses start")
        return
    if outcome.code != 0:
        typer.echo(f"\nUpgrade command exited with code {outcome.code}.", err=True)
        # A failed upgrade leaves the user exactly where the offline path does:
        # still running an old version, still needing a way forward. On the
        # Windows installer channel there is no command that could have worked in
        # the first place, so the steps are the only actionable thing we have.
        _echo_steps(status.steps or manual_update_steps(status.method))
        raise typer.Exit(outcome.code or 1)
    if outcome.after is None:
        typer.echo(
            "\nThe upgrade command finished, but the installed version could not be "
            "read — check with `yazses --version`.",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(
        f"\nThe upgrade command finished without an error, but yazses is still "
        f"{outcome.after}.\n{pinned_install_hint(outcome.method, outcome.command)}",
        err=True,
    )
    raise typer.Exit(1)


def _calibrate_mic(*, seconds: float = 4.0, set_threshold: bool = False) -> bool:
    """Measure the room, then measure the voice, and put the gate between them.

    Shared by `yazses mic-level` and `yazses setup`'s "connect to voice" step. Returns
    False when the two recordings cannot produce a usable gate.

    This used to record ONCE and assume the clip was speech. It cannot know that --
    recording an empty room measured 0.0036-0.0050 and confidently recommended a
    threshold below its own room noise, and no acoustic property of a single clip
    separates the two populations. So it asks for the room explicitly, and the
    ambient/speech gap becomes a measurement rather than an assumption.
    """
    from yazses.config import load_config
    from yazses.system.miclevel import (
        analyze,
        calibrate,
        live_threshold_note,
        record,
        update_threshold_in_config,
    )

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    sr = cfg.audio.sample_rate
    # The room needs less time than the voice: it is stationary, while a speech average
    # is only representative once it has covered a few words and the gaps between them.
    ambient_seconds = max(1.0, seconds / 2)

    typer.secho(f"1/2  Stay quiet — measuring the room for {ambient_seconds:.0f}s...",
                fg=typer.colors.BRIGHT_CYAN, bold=True)
    ambient = analyze(record(ambient_seconds, sr, device=cfg.audio.device or None), sr)
    typer.echo(f"  room level:            {ambient.mean_abs:.4f}")

    typer.secho(f"\n2/2  Now speak normally for {seconds:.0f}s...",
                fg=typer.colors.BRIGHT_CYAN, bold=True)
    speech = analyze(record(seconds, sr, device=cfg.audio.device or None), sr)

    typer.echo(f"  speech level:          {speech.mean_abs:.4f}")
    typer.echo(f"  peak level:            {speech.peak:.4f}")
    typer.echo(f"  vad_threshold in config: {cfg.accessibility.vad_threshold}")
    drift = live_threshold_note(cfg.accessibility.vad_threshold, _live_vad_threshold(platform))
    if drift:
        typer.secho(f"  ⚠ {drift}", fg=typer.colors.YELLOW)

    result = calibrate(ambient, speech)
    if not result.ok:
        # Refusing costs a re-run. Writing costs a gate on the wrong side of the room,
        # where room tone clears it, reaches the decoder, and returns an invented word.
        typer.secho(f"  cannot calibrate: {result.reason}.",
                    fg=typer.colors.YELLOW)
        if speech.is_silent:
            typer.echo(
                "Nothing was captured in the second recording — check the microphone:  "
                "yazses audio status"
            )
        else:
            typer.echo(
                "Re-run and speak at your normal dictation volume during step 2. If the "
                "two stay this close while you speak, the microphone is not hearing you:  "
                "yazses audio status"
            )
        return False

    rec = result.recommended_threshold
    typer.echo(f"  recommended:           {rec}")
    typer.echo(
        f"That sits {rec / ambient.mean_abs:.1f}x above your room and "
        f"{speech.mean_abs / rec:.1f}x below your voice."
        if ambient.mean_abs > 0
        else f"Your room measured silent, so the gate is the floor ({rec})."
    )

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
        "yazses mic-level -s 6        speak for 6 seconds instead of 4",
    ),
)
def mic_level(
    seconds: float = typer.Option(4.0, "--seconds", "-s", help="Seconds to record while you SPEAK (the room is measured for half this)."),
    set_threshold: bool = typer.Option(False, "--set", help="Write the recommended vad_threshold to config."),
) -> None:
    """Measure your room and your voice, and put the VAD threshold between them.

    Two recordings: stay quiet for the first, then speak normally for the second.
    The daemon discards a clip when its average level is below vad_threshold, so if
    dictation shows "Silent audio -- discarding", run this to find a level that fits
    your voice.

    Measuring the room is what makes the answer trustworthy: with only one recording
    the command cannot tell speech from room tone, and recording a quiet room used to
    yield a confident threshold BELOW that room's own noise. When the two recordings
    are too close together, it now says so instead of recommending a number.
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
    """Show the daemon's diagnostic log (metadata only unless log_level is DEBUG)."""
    platform = get_platform()
    log_file = platform.paths.log_dir / "daemon.log"
    if path_only:
        typer.echo(str(log_file))
        return
    if not log_file.exists():
        typer.echo(f"No log yet at {log_file} -- start the daemon first.")
        raise typer.Exit(code=1)
    content = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    kept, note = tail_records(content, lines)
    if note:
        typer.echo(note)
    for line in kept:
        typer.echo(line)
    typer.echo(f"\n({log_file} -- follow live with: tail -f {log_file})")


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples('yazses inject "hello world"    type it into the focused window'),
)
def inject(text: str = typer.Argument(..., help="Text to inject into the focused app.")) -> None:
    """Type text into the focused window without recording (tests the injector)."""
    from yazses.config import load_config
    from yazses.inject.auto import apply_injection_config, describe_injector

    platform = get_platform()
    # Configured backend, not `auto`: a command that exists to test the injector must
    # test the one that will run. And the name printed is the concrete backend, not
    # the selector wrapping it -- "LinuxInjector" is true on every Linux box and tells
    # nobody anything, least of all whether it matches `yazses status`.
    apply_injection_config(load_config(platform.paths.config_file).injection)
    injector = platform.injector_factory()
    typer.echo(f"Backend: {describe_injector(injector)}")
    injector.inject(text)
    typer.echo(f"Injected: {text!r}")


@app.command(
    rich_help_panel=_DICTATION,
    epilog=_examples('yazses say "hello there"    speak text aloud via offline TTS'),
)
def say(text: str = typer.Argument(..., help="Text to speak aloud.")) -> None:
    """Speak text aloud with the built-in offline voice.

    Requires `yazses features enable read-back`, which writes `[tts] enabled = true`
    and installs the voice.
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
    Normally auto-launched by the daemon when `[overlay] enabled = true`
    (`yazses features enable overlay`); run it
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
        "  -> ls | grep python | wc -l   (printed, never executed)",
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
        "yazses gitvoice \"commit with message fix the parser\"   -> git commit -m 'fix the parser'",
        'yazses gitvoice "create branch feature slash login"     -> git checkout -b feature/login',
        'yazses gitvoice "push to origin main"                  -> git push origin main',
        'yazses gitvoice "force push" --run                     refuses: destructive, needs --yes',
    ),
)
def gitvoice(
    text: Optional[str] = typer.Argument(None, help="Spoken git command (omit to read stdin)."),
    run: bool = typer.Option(False, "--run", help="Run the command instead of only printing it."),
    yes: bool = typer.Option(False, "--yes", help="Confirm a destructive command so --run will run it."),
) -> None:
    """Turn a spoken git command into a git command — fully offline.

    Use it when: you want to drive git hands-free — 'commit with message …', 'create
    branch …', 'push', 'status', 'discard changes in …' — and either review the exact
    command first or run it on the spot.

    Always prints the resolved command and how to undo it. Destructive commands
    (force-push, hard reset, branch -D, discarding uncommitted changes, ...) are never
    run — even with --run — without --yes. Reads the TEXT argument, or standard input
    when omitted; exits non-zero if unparsed.
    """
    import shlex as _shlex
    import subprocess as _subprocess
    import sys as _sys

    from yazses.gitvoice.plan import build_git_argv, reversibility, undo_hint

    src = text if text is not None else _sys.stdin.read()
    argv = build_git_argv(src)
    if not argv:
        typer.echo(
            "Could not parse a git command. Try: 'commit with message …', 'create branch …', "
            "'push', 'status', 'discard changes in …'.",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(_shlex.join(argv))
    hint = undo_hint(argv)
    if hint:
        typer.echo(f"undo: {hint}")

    if not run:
        return
    if reversibility(argv) == "confirm" and not yes:
        typer.echo("Destructive — re-run with --yes to actually run it.", err=True)
        raise typer.Exit(1)

    try:
        result = _subprocess.run(argv)
    except FileNotFoundError:
        typer.echo("git is not installed or not on PATH — nothing was run.", err=True)
        raise typer.Exit(127) from None
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


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
    ('make this snake case …') and recases the remainder. The colon is optional --
    it cannot be dictated. Reads the TEXT argument,
    or standard input when omitted.
    """
    import sys as _sys

    from yazses.casetransform.transform import split_style_command, transform_case

    src = text if text is not None else _sys.stdin.read()
    chosen = style
    payload = src
    if chosen is None:
        chosen, payload = split_style_command(src)
        if chosen is None:
            typer.echo(
                "No --style given and no spoken style command detected. "
                "Pass --style snake|kebab|camel|pascal|title|sentence|upper|lower|constant.",
                err=True,
            )
            raise typer.Exit(1)

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

    Recognises 'scene interior/exterior <place> <time>' → 'INT./EXT. …',
    (the colon and comma are optional — neither can be dictated),
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
        "yazses remote --stop                    disconnect the session",
    ),
)
def remote(
    host: str = typer.Argument("", help="SSH host to forward voice typing to. Omit with --stop."),
    port: int = typer.Option(22, "--port", "-p", help="SSH port."),
    key_file: str = typer.Option("", "--key-file", "-i", help="Path to SSH private key."),
    stop: bool = typer.Option(False, "--stop", help="Disconnect active remote session."),
) -> None:
    """Forward voice typing to a remote host over SSH."""
    # `--stop` needs no host -- the daemon knows which session it holds -- and requiring
    # one meant retyping it to close a tunnel that is already open.
    if not stop and not host:
        typer.echo("Error: a host is required (e.g. yazses remote dev.example.com).", err=True)
        raise typer.Exit(1)
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        if stop:
            result = client.call("remote_stop")
            if result.get("ok"):
                typer.echo("Remote session disconnected.")
            else:
                # Matches the start branch below: a failed teardown may have left the
                # tunnel up, so it must not exit 0 on stdout like a success.
                typer.echo(f"Error: {result.get('reason', result)}", err=True)
                raise typer.Exit(1)
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

    from yazses.system import streams as _streams

    if _sys.platform != "linux":
        typer.echo("yazses setup currently provisions Linux only; nothing to do.")
        return

    from yazses.system import setup as _setup

    plan = _setup.build_plan()
    mic_pending = _setup.snap_mic_pending()
    rawinput_pending = _setup.snap_rawinput_pending()
    typer.echo(f"Session: {plan.session}")

    # A strictly confined snap: there is nothing to apply and nothing to ask
    # about. Printing a plan we cannot execute is what produced a `sudo`
    # traceback on a real install; the interfaces are the whole answer here.
    if plan.confined:
        for note in plan.notes:
            typer.secho(f"\n{note}", fg=typer.colors.YELLOW)
        _print_next_steps(_setup.next_steps(
            plan=plan, mic_pending=mic_pending, rawinput_pending=rawinput_pending,
        ))
        raise typer.Exit(0)

    if plan.is_noop and not mic_pending and not rawinput_pending:
        typer.echo("All Linux requirements already satisfied.")
        # Nothing to provision, but a fresh user still benefits from calibrating
        # their voice and starting the daemon — surface those as next steps.
        _print_next_steps(_setup.next_steps(
            plan=plan, mic_pending=mic_pending, rawinput_pending=rawinput_pending,
        ))
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
    if rawinput_pending:
        typer.echo("  • grant the snap hold-to-talk access (run this yourself, once):")
        typer.secho("      sudo snap connect yazses:raw-input",
                    fg=typer.colors.BRIGHT_WHITE, bg=typer.colors.RED, bold=True)

    if dry_run:
        typer.echo("\n(dry run — no changes made)")
        _print_next_steps(_setup.next_steps(
            plan=plan, mic_pending=mic_pending, rawinput_pending=rawinput_pending,
        ))
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
    _print_next_steps(_setup.next_steps(
            plan=plan, mic_pending=mic_pending, rawinput_pending=rawinput_pending,
        ))

    # Offer to "connect to voice" now — run the mic calibration interactively when
    # we have a terminal and nothing blocks recording (mic granted, no re-login due).
    can_calibrate = not mic_pending and not (plan.add_to_input_group or _setup.input_group_pending_relogin())
    if can_calibrate and _streams.stdin_isatty() and typer.confirm(
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

    Requires `[gaze] enabled = true` (`yazses features enable gaze --force`) and an
    X11 session with `xdotool`. The webcam
    gaze deps (mediapipe + opencv) are installed automatically on first run into
    the running environment (skip with --no-install). You look at each on-screen
    point in turn; the fitted map is saved so the daemon can route dictation to
    the pane you look at (set `[gaze] route_dictation`).
    """
    import importlib

    from yazses.config import load_config
    from yazses.gaze.calibrate import (
        calibration_blocker,
        collect_samples,
        default_targets,
        fit_calibration,
    )
    from yazses.gaze.desktop import build_desktop
    from yazses.gaze.factory import build_gaze
    from yazses.gaze.store import save_calibration
    from yazses.system.features import find_feature

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)

    # Ask the free questions first. Both are answerable without fetching anything -- one
    # is a config flag, the other an `xdotool` probe -- and asking them *after* the
    # install is how this command came to download ~219 MB on a default install and then
    # refuse, and to download the same 219 MB on Wayland, where nothing can make it work.
    desktop = build_desktop()
    blocked = calibration_blocker(enabled=cfg.gaze.enabled, desktop_ok=desktop is not None)
    if blocked is not None:
        typer.echo(blocked, err=True)
        raise typer.Exit(1)

    # Auto-install the webcam gaze deps on first run (same path as
    # `yazses features enable gaze`), so calibration is turnkey.
    feat = find_feature(cfg, "gaze")
    if feat is not None:
        _install_feature_deps(feat, skip=no_install)
        importlib.invalidate_caches()  # let build_gaze import the freshly-installed deps

    backend = build_gaze(cfg.gaze)
    if backend is None:
        # Reaching here now means the dependencies themselves -- the one case an
        # install can repair, and the only one left after the checks above.
        typer.echo(
            "The webcam gaze deps are still unavailable after the install step.\n"
            "  Try:  yazses features enable gaze --force",
            err=True,
        )
        raise typer.Exit(1)
    assert desktop is not None  # calibration_blocker refused a None desktop above

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
    elif not enabled:
        # `gaze calibrate` refuses while the feature is off, so naming it here as the
        # alternative would send the user to a command that cannot run yet.
        typer.echo(
            "\nNext: turn it on — `yazses features enable gaze --force` "
            "(this installs the webcam deps too), then `yazses gaze calibrate`."
        )
    elif backend is None:
        typer.echo(
            "\nNext: install the webcam deps — `yazses features enable gaze --force` "
            "(or run `yazses gaze calibrate`, which auto-installs them)."
        )
    elif cal is None and desktop is not None:
        typer.echo("\nNext: run `yazses gaze calibrate`.")


@model_app.command(
    "list",
    epilog=_examples("yazses model list    show speech + intent-router models, and which are present"),
)
def model_list() -> None:
    """List available models (speech-to-text and SLM) and their status."""
    from yazses.commands.model_manager import list_models, local_path
    from yazses.stt.download import WHISPER_MODELS, hub_cache_dir, is_cached

    cache = hub_cache_dir()
    typer.echo("Speech-to-text (`[stt] model`):\n")
    for name in sorted(WHISPER_MODELS):
        state = "downloaded" if is_cached(name, cache) else "not downloaded"
        typer.echo(f"  {name:<24}  [{state}]")
    typer.echo(f"\n  Cache: {cache}")

    typer.echo("\nIntent routing (`[commands] slm_model_path`):\n")
    for info in list_models():
        path = local_path(info.id)
        status = f"installed: {path}" if path else f"not downloaded ({info.size_mb} MB)"
        typer.echo(f"  {info.id:<24}  {info.description}")
        typer.echo(f"  {'':24}  [{status}]")
        typer.echo("")


@model_app.command(
    "download",
    epilog=_examples(
        "yazses model download base.en          fetch the speech model ahead of first use",
        "yazses model download qwen2.5-0.5b     download an SLM for intent routing",
    ),
)
def model_download(
    model_id: str = typer.Argument(..., help="Model ID (see `yazses model list`)."),
) -> None:
    """Download a model: a speech-to-text checkpoint, or a GGUF for intent routing.

    The speech model is normally fetched on the daemon's first run. Doing it here
    instead makes it an explicit, watchable step — which is the only workable
    route on a machine behind a firewall, where the implicit download fails with
    nothing useful on screen (#310).
    """
    from yazses.stt.download import is_cached, is_whisper_model, whisper_model_url

    if is_whisper_model(model_id):
        from yazses.stt.download import download_stt_model

        if is_cached(model_id):
            typer.echo(f"{model_id} is already downloaded — nothing to do.")
            return
        try:
            path = download_stt_model(model_id, echo=typer.echo)
        except Exception as exc:
            from yazses.stt.errors import model_unavailable_message

            typer.echo("", err=True)
            typer.echo(model_unavailable_message(model_id, exc), err=True)
            raise typer.Exit(1)
        typer.echo("\nDone. This is the model `[stt] model` selects:")
        typer.echo("  [stt]")
        typer.echo(f'  model = "{model_id}"')
        typer.echo(f"\nStored in {path}")
        return

    from yazses.commands.model_manager import download_model

    try:
        path = download_model(model_id)
        typer.echo("\nDone. Add this to your config.toml:")
        typer.echo("  [commands]")
        typer.echo(f'  slm_model_path = "{path}"')
    except ValueError as exc:
        # Unknown to the GGUF registry — but the user may have meant a speech
        # model and mistyped it, so name that possibility rather than just
        # listing SLMs.
        typer.echo(str(exc), err=True)
        if whisper_model_url(model_id) is None:
            typer.echo(
                "\nIf you meant a speech-to-text model, `yazses model list` "
                "shows the valid names.",
                err=True,
            )
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

    Requires `[learning] enabled = true` (`yazses features enable learning`). Routes
    through the running daemon so
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

    Reads only your local encrypted learning corpus (requires `[learning] enabled = true`,
    i.e. `yazses features enable learning`).
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

    Requires `[learning] enabled = true` and `[recall] enabled = true`
    (`yazses features enable learning`, then `yazses features enable recall`). Reads the
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

    Requires `[punch_in] enabled = true` (`yazses features enable punch-in`). The
    daemon records a short window, aligns
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
        "yazses tune --limit 200         only the 200 most recent clips (much faster)",
        "yazses tune --no-retranscribe   skip the slower re-transcription pass",
    ),
)
def tune(
    apply: bool = typer.Option(False, "--apply", help="Review and apply proposals interactively."),
    retranscribe: bool = typer.Option(
        True, "--retranscribe/--no-retranscribe",
        help="Re-transcribe captured audio with a larger model to find errors.",
    ),
    limit: int = typer.Option(
        0, "--limit", min=0,
        help="Re-transcribe only the N most recent clips (0 = all). Budget roughly "
             "10 s per clip on a laptop CPU — measured at 9.6 s with small.en — and a "
             "corpus at the default 500 MB cap holds ~1500, so a full run is several "
             "hours, not one. This is the middle ground between that and "
             "--no-retranscribe.",
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
            "No corpus yet. Enable it with `yazses features enable learning` "
            f"(writes `[learning] enabled = true` to {platform.paths.config_file}), "
            "then dictate for a while.",
            err=True,
        )
        raise typer.Exit(1)

    cfg = load_config(platform.paths.config_file)
    # The patterns matter here specifically: --retranscribe writes `retx_text`, a fresh
    # transcription of the same audio the user added them to scrub.
    store = open_store(data_dir, tuple(cfg.learning.redact_patterns))

    transcribe_fn = None
    if retranscribe:
        from yazses.stt.faster_whisper import FasterWhisperEngine

        typer.echo(f"Loading re-transcription model '{cfg.learning.tune_model}'...")
        engine = FasterWhisperEngine(
            model_name=cfg.learning.tune_model,
            device=cfg.stt.device,
            compute_type=cfg.stt.compute_type,
            # `[stt] language` reaches the decoder only through this argument, and it
            # defaults to "en". Without it, a re-transcription meant to be *ground
            # truth* was decoded in the wrong language, and every proposal `tune` drew
            # from it — vocabulary, thresholds, the model itself — was drawn from noise.
            language=cfg.stt.language,
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
            # 0 means "all", which `retranscribe` spells as None. Passing 0 through
            # would mean "re-transcribe nothing" and look like a silent no-op.
            limit=limit or None,
        )
    finally:
        store.close()


@app.command(
    name="mcp-server",
    rich_help_panel=_REMOTE,
    epilog=_examples(
        "yazses mcp-server        speak MCP on stdin/stdout (for an agent to spawn)",
    ),
)
def mcp_server() -> None:
    """Expose YazSes to another agent over MCP, on stdin/stdout (ADR-020).

    Not a service you leave running: an MCP client *spawns* this as a child
    process and talks to it over pipes. There is no port, no bind address and
    nothing another machine can reach — the same structural property as YazSes's
    own Unix-socket IPC, which is why ADR-020 chose stdio over HTTP for a daemon
    that holds a live microphone.

    One tool today: `transcribe`, which turns an audio file into text on this
    machine. `ask_human` — an agent asking you a question out loud — is specified
    in ADR-020 and needs the daemon, so it is not offered yet rather than offered
    and broken.

    Point an MCP client at it with:

        {"command": "yazses", "args": ["mcp-server"]}
    """
    from yazses.config import load_config
    from yazses.mcp.server import serve

    platform = get_platform()
    raise typer.Exit(serve(load_config(platform.paths.config_file)))


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
        "yazses transcribe mtg.m4a --download-models         fetch the ~45 MB diarize models, then exit",
    ),
)
def transcribe(
    audio_file: Optional[Path] = typer.Argument(
        None, exists=True, dir_okay=False, readable=True,
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
        0, "--min-speakers",
        help="Ignored by the default sherpa diarizer — only the pyannote backend "
             "reads a lower bound (optional `diarization-pyannote` extra). The run "
             "warns and continues. Use --speakers to constrain the count."),
    max_speakers: int = typer.Option(
        0, "--max-speakers",
        help="Force exactly this many speakers on the shipped diarizer (same as "
             "--speakers). 0 = auto-detect."),
    names: Optional[str] = typer.Option(
        None, "--names",
        help="Comma list mapped to speakers in order of first appearance: 'Alice,Bob,Carol'."),
    rename: Optional[list[str]] = typer.Option(
        None, "--rename",
        help="Explicit speaker→name map, repeatable: --rename speaker_0=Alice --rename speaker_1=Bob."),
    language: Optional[str] = typer.Option(
        None, "--language",
        help="Spoken language as a Whisper code -- 'en' (default), 'fa', 'de'; '' auto-detects; "
             "'translate' renders any-language audio into English text. A non-English code "
             "needs a multilingual model (drop the .en suffix)."),
    model: Optional[str] = typer.Option(
        None, "--model",
        help="STT model override, e.g. base.en (fast) or small.en (more accurate). Default: your config model."),
    out: Optional[str] = typer.Option(
        None, "--out", "-o", help="Output file path (default: sidecar <audio_file>.<format>)."),
    download_models: bool = typer.Option(
        False, "--download-models",
        help="Download the ~45 MB sherpa diarization models, then exit (no transcription)."),
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
    models (install the `diarization` extra; the first run downloads ~45 MB, or
    pre-fetch with --download-models). Each utterance is then prefixed by a
    speaker label; provide --names (positional) or --rename (explicit map) to use
    real names, force the count with --speakers,
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

    # get_paths(), not get_platform(): transcribing a file needs a config
    # location and nothing else from the platform layer. Routing it through the
    # backend made it raise UnsupportedPlatformError on an OS without one —
    # while that very error told the user `yazses transcribe` still worked here.
    paths = get_paths()
    cfg = load_config(paths.config_file)
    ri = cfg.recimport

    if download_models:
        # Optional above, required here. `--download-models` exits before any
        # transcription and is what the tool tells you to run when diarization is
        # unavailable — with a required argument, that advice could not be
        # followed at all ("Missing argument 'audio_file'").
        from yazses.recimport.download import download_models as _dl

        try:
            _dl(ri, echo=typer.echo)
        except Exception as exc:  # pragma: no cover - network/tooling dependent
            typer.echo(f"Model download failed: {exc}", err=True)
            raise typer.Exit(1)
        return

    if audio_file is None:
        typer.echo(
            "Missing argument 'audio_file'. Pass a file to transcribe, or use "
            "`yazses transcribe --download-models` to fetch the diarization models.",
            err=True,
        )
        raise typer.Exit(2)

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

    # `--min-speakers` is read only by recimport/pyannote_backend.py, which ships
    # behind the optional `diarization-pyannote` extra rather than by default. (An
    # earlier version of this comment said the adapter was not shipped at all, and
    # so did the message below -- it has shipped since 90c801f. Telling someone no
    # backend honours a floor stops them installing the one that does.) The default
    # `sherpa` diarizer reads max_speakers alone, so a lower bound silently does
    # nothing -- said here, before a long transcription, rather than after it.
    if want_diarize and min_speakers and (eff.backend or "sherpa").strip().lower() != "pyannote":
        typer.echo(
            f"Note: --min-speakers is ignored by the '{eff.backend}' diarizer; only the "
            "pyannote backend honours a lower bound. Install the optional "
            "'diarization-pyannote' extra and set [recimport] backend = \"pyannote\" "
            "to use one, or use --speakers to force an exact count.", err=True)

    # Said here rather than after the transcription, for the same reason as the note
    # above: on a long recording the run is measured in minutes, and advice that
    # arrives with the result costs a second pass.
    from yazses.recimport.factory import speaker_count_advice

    if hint := speaker_count_advice(
        eff, "Pass `--speakers N` if you know how many people are on the recording."
    ):
        typer.echo(f"Note: {hint}", err=True)

    # Built by the pipeline's own builder rather than here, so this path cannot drift
    # from the one `yazses meeting` uses. It also carries `--language` into the decoder,
    # which this call site did not: the flag set `task` for "translate" and was
    # otherwise inert, so `--language fa` transcribed Persian audio as English.
    from yazses.recimport.pipeline import _build_engine

    typer.echo(f"Loading model '{eff.model or cfg.stt.model}'…", err=True)
    engine = _build_engine(dataclasses.replace(eff, model=eff.model or cfg.stt.model))

    # Speaker naming: parse explicit maps; load the enrolled voiceprint (→ "You").
    name_list = [n.strip() for n in names.split(",")] if names else None
    rename_map: dict = {}
    for item in rename or []:
        if "=" in item:
            key, val = item.split("=", 1)
            rename_map[key.strip()] = val.strip()
    embedder, profiles = None, None
    if want_diarize and eff.name_from_voiceprints:
        embedder, profiles = _load_voiceprints(cfg, paths)
        if profiles:
            typer.echo(
                "Speaker naming uses voiceprints stored only on this machine; "
                "unrecognised speakers stay labelled 'Speaker N'.", err=True)

    from yazses.recimport.pipeline import transcribe_file

    if want_diarize:
        typer.echo("Transcribing and diarizing… (first diarized run downloads ~45 MB of models)", err=True)
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

    # A --rename naming a speaker who is not in the recording renamed nobody. Silently
    # doing nothing leaves the user reading "Speaker 1" and guessing why, so name the
    # keys that matched nothing and list the ones that exist.
    if rename_map:
        from yazses.recimport.naming import unmatched_renames

        stray = unmatched_renames(result.utterances, rename_map)
        if stray:
            present = sorted({u.speaker for u in result.utterances if u.speaker})
            typer.echo(
                f"Note: --rename {', '.join(stray)} matched no speaker in this recording"
                + (f"; it has {', '.join(present)}." if present else "."),
                err=True,
            )

    text = render_transcript(result, fmt)
    out_path = Path(out) if out else Path(audio_file).with_suffix("." + fmt)
    out_path.write_text(text, encoding="utf-8")
    n_spk = len({u.speaker for u in result.utterances if u.speaker})
    summary = f" ({n_spk} speaker{'s' if n_spk != 1 else ''})" if result.diarized else ""
    typer.echo(f"Wrote {out_path}{summary}")

    # Nothing was recognised. Say so: "Wrote transcript.txt" over an empty file is the
    # silent failure this project spends its earcons and guards avoiding, and it lands
    # on the surface where most people meet YazSes working for the first time.
    #
    # Tested on `result.utterances` rather than on the rendered text, because the text
    # is not empty for every format -- a VTT with no cues is still "WEBVTT\n", so a
    # check on the string would stay quiet for exactly one of the five.
    if not result.utterances:
        typer.echo(
            f"Note: no speech was recognised, so {out_path.name} is empty. Common "
            "causes: the file holds music or silence; it is speech in another language "
            "while the model is English-only (`[stt] model` ending in `.en`); or the "
            "audio decoded to nothing. `yazses doctor` reports the configured model.",
            err=True,
        )

    # Silence that produced *words* -- the case the note above cannot see, because the
    # transcript is not empty. Two seconds of digital silence decodes to "You", with a
    # start and an end time, and nothing about that output marks it as invented. The
    # evidence is in the input, so that is where it is measured.
    elif result.silent_input:
        typer.echo(
            f"Note: the audio carries no signal, so the text in {out_path.name} was "
            "produced from silence and is not trustworthy -- speech models answer "
            "silence with confident invented words rather than nothing. Common causes: "
            "the microphone was muted, another application held the input device, or "
            "the wrong device was recorded. `yazses audio devices` lists the inputs.",
            err=True,
        )

    # Sound was recorded and none of it is speech. The peak test above cannot see
    # this -- a quiet room sits far above its floor -- yet it hallucinates just the
    # same: four seconds of faint hiss decodes to the single word "You". Kept apart
    # from the note above because the remedy is different: nothing here is wrong
    # with the input device, the file simply does not hold speech.
    elif result.no_speech:
        typer.echo(
            f"Note: sound was recorded but a speech detector found no speech in it, so "
            f"the text in {out_path.name} was invented rather than heard -- speech "
            "models answer non-speech audio with confident words rather than nothing. "
            "Common causes: the file holds music or room noise, the recording captured "
            "the wrong source, or the speech is too faint to detect. Play the file back "
            "to check before trusting the transcript.",
            err=True,
        )

    # A separate `if`, deliberately outside the chain above: this is not a fourth way
    # for a transcript to be empty or invented. The words are real and correctly heard;
    # only the names attached to them are wrong, so it can and must be reported
    # alongside a transcript that is otherwise worth keeping.
    if result.attribution_suspect:
        typer.echo(
            f"Note: {result.attribution_suspect} Re-run with `--speakers N` to give the "
            "number of people who spoke -- on this backend that is an exact cluster "
            "count, so it replaces the estimate rather than capping it. The words "
            f"themselves are unaffected; only the speaker labels in {out_path.name} are.",
            err=True,
        )

    # `transcribe` is where most people meet this project working for the first time --
    # it is the one path that needs no microphone, no hotkey and no re-login, so it is
    # also what the container and Codespace trials run. An empty transcript is not the
    # moment to ask them for a star.
    _maybe_point_at_project(
        paths.data_dir,
        succeeded=bool(result.utterances) and not result.silent_input and not result.no_speech,
    )


def _load_voiceprints(cfg, paths):
    """Return (embedder, {name: embedding}) from the enrolled voiceprint, or (None, None).

    Takes `paths`, not a `Platform`: it only ever needed the data directory, and
    depending on a backend for that made `yazses transcribe` unusable on an OS
    without one.
    """
    try:
        from yazses.learning.crypto import Cipher, load_or_create_key
        from yazses.voiceprint.factory import build_embedder
        from yazses.voiceprint.store import load_voiceprint

        embedder = build_embedder(cfg.voiceprint)
        if embedder is None:
            return None, None
        cipher = Cipher(load_or_create_key(paths.data_dir))
        emb = load_voiceprint(paths.data_dir / "voiceprint.enc", cipher)
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

    # The size used to print bare, with nothing to compare it against -- so a corpus
    # sitting exactly on its cap, evicting the oldest events on every capture, looked
    # identical to one with room to spare.
    from yazses.config import load_config
    from yazses.learning.store import capacity_line

    lc = load_config(platform.paths.config_file).learning
    size_text, warning = capacity_line(s.size_bytes, lc.max_corpus_mb, lc.retention_days)

    typer.echo(f"  location:  {data_dir}")
    typer.echo(f"  events:    {s.count} ({s.discarded} discarded, {s.wrong} flagged wrong)")
    typer.echo(f"  size:      {size_text}")
    if warning:
        typer.echo(f"  ⚠          {warning}")
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

    from yazses.config import load_config
    from yazses.inject.auto import apply_injection_config, describe_injector

    apply_injection_config(load_config(platform.paths.config_file).injection)
    injector = platform.injector_factory()
    typer.echo(f"Local injector: {describe_injector(injector)}")
    injector.inject("YazSes OK")
    typer.echo("Done. If you saw 'YazSes OK' appear, injection works.")


def main() -> None:
    """Console-script entry point.

    Wraps the Typer app solely to turn `UnsupportedPlatformError` into a readable
    message instead of a traceback. On a system with no backend — Solaris, Haiku,
    anything unforeseen — the pure-CPU half of YazSes still works (`transcribe`,
    the text commands), and a stack trace tells the user none of that. Click's
    standalone mode only converts its own exception types, so this has to sit
    outside it.
    """
    from yazses.cli_help import apply as escape_help_sections
    from yazses.platform.base import UnsupportedPlatformError
    from yazses.system.streams import ensure_printable_streams

    # Before anything prints. On Windows a redirected stdout is cp1252, which cannot
    # encode the arrow, the warning sign or the box rule this CLI prints everywhere --
    # so `yazses doctor > log.txt` and `yazses features | findstr x` aborted with
    # UnicodeEncodeError on a real Windows host. See the function's own docstring.
    ensure_printable_streams()

    # Rich parses `[meeting]` in a help string as a style tag and drops it, so twelve
    # commands named a config key without naming its section. Escaped here rather
    # than in the source strings, so the generators that read those strings raw --
    # the docs page and the man page -- keep seeing what was written.
    escape_help_sections(app)

    try:
        app()
    except UnsupportedPlatformError as exc:
        typer.secho(f"\n{exc}\n", fg=typer.colors.RED, err=True)
        raise SystemExit(2) from None


if __name__ == "__main__":  # pragma: no cover - exercised by `python -m yazses.cli`
    # `python -m yazses.cli --version` printed nothing and exited 0 without this.
    #
    # That matters more than it looks: `-m yazses.cli` is the documented last-resort
    # launch path -- the one `tray/launch.py` and `settingsui/app.py::_run_restart`
    # fall back to when there is no console script to be found -- and it silently did
    # nothing on every install that actually needed it. A fallback that fails quietly
    # is worse than no fallback, because the code above it reports success.
    main()
