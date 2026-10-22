"""`yazses mcp-server --help` lists exactly the tools the server registers (#641).

The help said `ask_human` "is not offered yet" for releases after
`mcp/server.py::build_tools` had started offering it whenever `[mcp] ask_human` is
on. Two hand-written descriptions of one fact drifted, which is the usual way
(ADR-032 §4).

So the tool list here is **derived from the server, never written down**:
`build_tools` is called once with the defaults (the tools that are always offered)
and once per boolean `[mcp]` switch (the tools that switch adds). The help must then
carry one bullet per derived tool, no more and no fewer, and each switched tool's
bullet must name the switch that turns it on. A third tool, a renamed tool or a
tool that moves behind a switch fails here on the commit that makes the change.

That `[mcp]` survives Rich rendering is not re-checked here:
`tests/test_cli_help_keeps_config_sections.py` walks every command and covers it.
"""
from __future__ import annotations

import dataclasses
import functools
import inspect
import re

from typer.testing import CliRunner

import yazses.cli as cli_mod
from yazses.config import Config
from yazses.mcp.server import build_tools

# Wide so Rich does not wrap a phrase mid-way, as tests/test_cli_help.py does.
WIDE = {"COLUMNS": "220", "TERM": "dumb"}

_BULLET = re.compile(r"^- `([a-z_]+)`")


def _config_with(**switches: bool) -> Config:
    cfg = Config()
    for name, value in switches.items():
        object.__setattr__(cfg.mcp, name, value)
    return cfg


def _tool_names(cfg: Config) -> set[str]:
    return {tool.name for tool in build_tools(cfg)}


@functools.lru_cache(maxsize=1)
def _registration() -> tuple[frozenset[str], dict[str, str]]:
    """(tools always offered, {switched tool: the `[mcp]` switch that adds it})."""
    always = _tool_names(Config())
    gated: dict[str, str] = {}
    defaults = Config().mcp
    for field in dataclasses.fields(defaults):
        if not isinstance(getattr(defaults, field.name), bool):
            continue
        for tool in _tool_names(_config_with(**{field.name: True})) - always:
            gated[tool] = field.name
    return frozenset(always), gated


def _help_text() -> str:
    """The command's help as written. `cli_help.apply` (run by `main()`, and by another
    test in the same process) escapes `[mcp]` to `\\[mcp]` for Rich; undo that here so
    this test reads the same text whichever ran first."""
    return inspect.cleandoc(cli_mod.mcp_server.__doc__ or "").replace("\\[", "[")


def _bullets(text: str) -> dict[str, str]:
    """`tool name` -> its whole bullet, continuation lines joined with spaces."""
    out: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _BULLET.match(line)
        if match:
            current = match.group(1)
            out[current] = line
        elif current is not None and line.startswith("  ") and line.strip():
            out[current] += " " + line.strip()
        else:
            current = None
    return out


def test_the_derivation_sees_an_always_on_tool_and_a_switched_one() -> None:
    """Otherwise every assertion below could pass on an empty set."""
    always, gated = _registration()
    assert "transcribe" in always
    assert gated.get("ask_human") == "ask_human", gated
    assert "ask_human" not in always, "ask_human must stay off by default"


def test_the_help_lists_exactly_the_registered_tools() -> None:
    always, gated = _registration()
    listed = set(_bullets(_help_text()))
    registered = set(always) | set(gated)
    assert listed == registered, (
        f"`yazses mcp-server --help` lists {sorted(listed)} but build_tools registers "
        f"{sorted(registered)} — update the bullets in cli.py::mcp_server"
    )


def test_each_switched_tool_names_its_switch() -> None:
    _, gated = _registration()
    bullets = _bullets(_help_text())
    for tool, switch in gated.items():
        assert f"`[mcp] {switch} = true`" in bullets.get(tool, ""), (
            f"the help does not say `{tool}` needs `[mcp] {switch} = true`: "
            f"{bullets.get(tool)!r}"
        )


def test_an_always_on_tool_is_not_described_as_switched() -> None:
    always, _ = _registration()
    bullets = _bullets(_help_text())
    for tool in always:
        assert "[mcp]" not in bullets.get(tool, ""), bullets.get(tool)


def test_the_help_no_longer_says_ask_human_is_not_offered() -> None:
    """The exact regression of #641."""
    assert "not offered yet" not in _help_text()


def test_the_rendered_help_shows_every_registered_tool() -> None:
    """What a user actually sees, not only the docstring."""
    always, gated = _registration()
    result = CliRunner().invoke(cli_mod.app, ["mcp-server", "--help"], env=WIDE)
    assert result.exit_code == 0, result.output
    for tool in set(always) | set(gated):
        assert tool in result.output, f"{tool} missing from the rendered help"
