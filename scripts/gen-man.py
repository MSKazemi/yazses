#!/usr/bin/env python3
"""Generate the man page from the CLI, the same way scripts/gen-docs.py generates
docs/command-index.md — from the live Typer/Click app, never hand-edited. Run:

  uv run python scripts/gen-man.py

Writes man/yazses.1 (groff/troff, `man -l man/yazses.1` to preview locally).
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import click
import typer

from yazses import branding

ROOT = Path(__file__).resolve().parent.parent
MAN = ROOT / "man" / "yazses.1"
CHANGELOG = ROOT / "CHANGELOG.md"


def _release_date(ver: str) -> str:
    """The CHANGELOG date for the current version, so .TH doesn't drift with
    every regen the way `datetime.today()` would (the man page must stay
    byte-identical across CI runs until the code actually changes)."""
    text = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(ver)}\] - (\d{{4}}-\d{{2}}-\d{{2}})", text, re.M)
    return m.group(1) if m else "unreleased"


def _esc(text: str) -> str:
    """Escape a line of prose for groff: backslashes, and a leading `.` or `'`
    (either would otherwise be read as a request/macro)."""
    text = text.strip().replace("\\", "\\\\")
    if text.startswith(('.', "'")):
        text = "\\&" + text
    return text


def _first_para(help_text: str | None) -> str:
    if not help_text:
        return ""
    return help_text.strip().split("\n\n")[0].strip()


def _walk_click(cmd: click.Command, name: str, depth: int, out: io.StringIO) -> None:
    prefix = "yazses " + name if name else "yazses"
    args = [p for p in cmd.params if p.param_type_name == "argument"]
    opts = [p for p in cmd.params if p.param_type_name == "option" and p.name != "help"]

    if depth == 1:
        out.write(f'.SS "{prefix}"\n')
    else:
        usage = f"\\fB{prefix}\\fR"
        if args:
            usage += " " + " ".join(f"\\fI{a.name.upper()}\\fR" for a in args)
        out.write(f".TP\n{usage}\n")

    help_line = _first_para(cmd.help)
    if help_line:
        out.write(_esc(help_line) + "\n")

    if depth == 1 and args:
        out.write(".br\n")
        out.write("Arguments: " + ", ".join(f"\\fI{a.name}\\fR" for a in args) + "\n")

    if opts:
        out.write(".RS\n")
        for opt in opts:
            flags = ", ".join(opt.opts + opt.secondary_opts).replace("-", "\\-")
            help_txt = _esc((opt.help or "").strip())
            out.write(".TP\n")
            out.write(f"\\fB{flags}\\fR\n")
            if help_txt:
                out.write(help_txt + "\n")
        out.write(".RE\n")

    if hasattr(cmd, "commands"):
        for sub_name in sorted(cmd.commands):
            child = cmd.commands[sub_name]
            full = f"{name} {sub_name}".strip()
            _walk_click(child, full, depth + 1, out)


def gen_man() -> str:
    from yazses.cli import app

    click_app = typer.main.get_command(app)
    ver = branding.version()
    date = _release_date(ver)

    out = io.StringIO()
    out.write(f'.TH YAZSES 1 "{date}" "yazses {ver}" "User Commands"\n')
    out.write(".SH NAME\n")
    out.write(f"yazses \\- {_esc(branding.TAGLINE)}\n")
    out.write(".SH SYNOPSIS\n")
    out.write(".B yazses\n")
    out.write("[\\fICOMMAND\\fR] [\\fIARGS\\fR]... [\\fIOPTIONS\\fR]\n")
    out.write(".SH DESCRIPTION\n")
    out.write(_esc(_first_para(click_app.help)) + "\n")
    out.write(
        "Hold a key anywhere on the desktop, speak, release it, and the "
        "transcribed text is injected into whatever application is focused. "
        "Runs fully offline after the initial model download.\n"
    )
    out.write(".SH COMMANDS\n")
    out.write(
        "The complete command tree. For grouped, example-rich help run "
        "\\fByazses \\-\\-help\\fR or \\fByazses \\fICOMMAND\\fR \\-\\-help\\fR.\n"
    )
    assert hasattr(click_app, "commands")
    for sub_name in sorted(click_app.commands):
        _walk_click(click_app.commands[sub_name], sub_name, 1, out)

    out.write(".SH FILES\n")
    out.write(
        "\\fI~/.config/yazses/config.toml\\fR on Linux "
        "(\\fI~/Library/Application Support/yazses/\\fR on macOS, "
        "\\fI%APPDATA%\\\\yazses\\\\\\fR on Windows).\n"
    )
    out.write(".SH SEE ALSO\n")
    out.write(f"Full documentation: \\fI{branding.WEBSITE}\\fR\n")
    out.write(".SH AUTHOR\n")
    out.write(f"{_esc(branding.AUTHOR)} <{branding.EMAIL}>\n")
    out.write(".SH BUGS\n")
    out.write(f"Report issues at \\fI{branding.ISSUES}\\fR\n")
    return out.getvalue()


def main() -> None:
    MAN.parent.mkdir(exist_ok=True)
    content = gen_man()
    MAN.write_text(content, encoding="utf-8")
    print(f"wrote {MAN.relative_to(ROOT)}  ({content.count(chr(10))} lines)")
    print(f"YazSes {branding.version()} — man page regenerated.")


if __name__ == "__main__":
    main()
