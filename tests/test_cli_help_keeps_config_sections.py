"""`--help` must name the section a config key lives in.

`cli.py` builds its Typer app with `rich_markup_mode="rich"`, so Rich parses help
text for markup — and `[meeting]`, written exactly the way `docs/configuration.md`
writes it, is indistinguishable from a style tag. Rich drops it silently. Twelve
commands rendered as

    Requires ` enabled = true` (`yazses features enable meeting`).

Not a typo: a missing instruction, in the one place a user goes to find out where a
setting lives. `[tts]`, `[learning]`, `[gaze]`, `[overlay]`, `[voiceprint]`,
`[recall]`, `[punch_in]` and `[meeting]` all disappeared this way, from source that
reads perfectly.

The guard renders every command's `--help` and compares the section names present in
the *source* text against the rendered output, so it covers commands that do not
exist yet. That is the whole point: the failure is invisible at the source, the fix
lives somewhere else entirely, and the next person to write `[stt]` in a help string
has no reason to suspect either.

`_probe_all_commands` duck-types on `.commands` rather than `isinstance(cmd,
click.Group)`. Typer vendors its own click fork, so the isinstance check is False for
every real group — the first version of this probe walked no subcommands at all and
cheerfully reported zero problems while twelve were live.
"""
from __future__ import annotations

import inspect
import re

import pytest
import typer.main as tm

import yazses.cli as cli_mod
from yazses.cli_help import apply, config_section_names, escape_config_sections

SECTION_RE = re.compile(r"\[([a-z][a-z0-9_.]*)\]")


def _help_slots(app):
    """Every (object, attribute) `apply` writes to, for snapshot and restore."""
    slots = [(app.info, "help")]
    for command in getattr(app, "registered_commands", ()):
        slots.append((command, "help"))
        fn = getattr(command, "callback", None)
        if fn is not None:
            slots.append((fn, "__doc__"))
            slots += [(d, "help") for d in (fn.__defaults__ or ())
                      if hasattr(d, "help")]
    info = getattr(app, "registered_callback", None)
    if info is not None and getattr(info, "callback", None):
        fn = info.callback
        slots.append((fn, "__doc__"))
        slots += [(d, "help") for d in (fn.__defaults__ or ()) if hasattr(d, "help")]
    for group in getattr(app, "registered_groups", ()):
        slots.append((group, "help"))
        sub = getattr(group, "typer_instance", None)
        if sub is not None:
            slots += _help_slots(sub)
    return slots


@pytest.fixture(autouse=True)
def _restore_cli_help():
    """`apply` rewrites `__doc__` on the real command functions, and those functions
    are module-level singletons shared with every other test in the run.

    Without this, `test_gen_docs.py` and `test_gen_man.py` -- which regenerate their
    pages from these same docstrings and diff against the committed files -- fail or
    pass depending on whether this file ran first. A test that changes the outcome of
    another test is not a guard, it is a coin flip.
    """
    saved = [(obj, attr, getattr(obj, attr, None)) for obj, attr in
             _help_slots(cli_mod.app)]
    yield
    for obj, attr, value in saved:
        try:
            setattr(obj, attr, value)
        except (AttributeError, TypeError):
            pass


def _walk(cmd, path):
    yield cmd, path
    for name, sub in getattr(cmd, "commands", {}).items():
        yield from _walk(sub, path + [name])


def _source_sections() -> dict[str, set[str]]:
    """`command path` -> the config sections its unrendered help text names."""
    known = config_section_names()
    out: dict[str, set[str]] = {}
    for cmd, path in _walk(tm.get_command(cli_mod.app), []):
        texts = [cmd.help or ""] + [(p.help or "") for p in cmd.params]
        found = set(SECTION_RE.findall(" ".join(texts))) & known
        out[" ".join(path) or "(root)"] = found
    return out


def test_the_probe_finds_subcommands_at_all():
    """A guard that walks nothing passes on everything, and this one nearly did."""
    paths = [" ".join(p) for _, p in _walk(tm.get_command(cli_mod.app), [])]
    assert len(paths) > 50, f"only walked {len(paths)} commands"
    assert "meeting start" in paths, "the walk never descended into a subgroup"


def test_some_command_actually_names_a_config_section():
    """Otherwise the real assertion below is vacuous."""
    sections = _source_sections()
    naming = {k: v for k, v in sections.items() if v}
    assert len(naming) >= 8, naming


def test_every_config_section_in_a_help_string_survives_rendering():
    from typer.testing import CliRunner

    sections = _source_sections()
    apply(cli_mod.app)  # what `cli.main()` does before handing over to Typer
    runner = CliRunner()

    lost: dict[str, list[str]] = {}
    for cmd, path in _walk(tm.get_command(cli_mod.app), []):
        key = " ".join(path) or "(root)"
        wanted = sections.get(key) or set()
        if not wanted:
            continue
        output = runner.invoke(cli_mod.app, path + ["--help"]).output
        missing = sorted(s for s in wanted if f"[{s}]" not in output)
        if missing:
            lost[key] = missing

    assert not lost, (
        "these commands name a config section in their help and Rich eats it, so the "
        "user is told to set a key without being told where it lives:\n  "
        + "\n  ".join(f"yazses {k}: {v}" for k, v in sorted(lost.items()))
    )


def test_the_entry_point_applies_the_escape():
    """The fix is only real on the path a user runs. Rendering it in a test and not
    in `main()` would leave every installed copy exactly as broken."""
    src = inspect.getsource(cli_mod.main)
    assert "cli_help" in src and "escape_help_sections(app)" in src


def test_genuine_rich_markup_is_left_alone():
    """`cli.py` uses `[bold]` in three places; an escape broad enough to catch it
    would print the tag instead of applying it."""
    assert escape_config_sections("[bold]Examples[/bold]") == "[bold]Examples[/bold]"
    assert escape_config_sections("see [meeting] now") == "see \\[meeting] now"


def test_the_section_list_is_derived_from_the_config_dataclass():
    """A hand-written list covers the sections somebody remembered. `[recimport]`
    and `[punch_in]` were both live bugs and neither is an obvious name."""
    names = config_section_names()
    assert {"stt", "meeting", "recimport", "punch_in", "gaze"} <= names
    assert "filters.disfluency" in names, "nested sections are sections too"
    assert len(names) > 30


@pytest.mark.parametrize("text", ["", None, "no brackets here"])
def test_text_without_a_section_is_returned_unchanged(text):
    assert escape_config_sections(text) == text
