"""CLI exposure for the case-transform (ADR-v2-087) and screenplay (ADR-v2-110) cores.

Built + tested pure cores with no runtime entry point; here they are driven through the
real `yazses case` / `yazses screenplay` commands.
"""
from __future__ import annotations

from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


# ---- yazses case ------------------------------------------------------------

def test_case_explicit_style():
    r = runner.invoke(cli.app, ["case", "--style", "snake", "myVariableName here"])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "my_variable_name_here"


def test_case_constant_and_kebab():
    assert runner.invoke(cli.app, ["case", "--style", "constant", "my var"]).output.strip() == "MY_VAR"
    assert runner.invoke(cli.app, ["case", "--style", "kebab", "My Variable Name"]).output.strip() == "my-variable-name"


def test_case_detects_spoken_style_command():
    r = runner.invoke(cli.app, ["case", "make this snake case: My Title Here"])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "my_title_here"


def test_case_errors_without_style_or_command():
    r = runner.invoke(cli.app, ["case", "just some plain words"])
    assert r.exit_code == 1
    assert "no spoken style command" in r.output.lower()


def test_case_reads_stdin():
    r = runner.invoke(cli.app, ["case", "--style", "pascal"], input="hello world\n")
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "HelloWorld"


# ---- yazses screenplay ------------------------------------------------------

def test_screenplay_scene_heading():
    r = runner.invoke(cli.app, ["screenplay", "scene: interior coffee shop, day"])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "INT. COFFEE SHOP - DAY"


def test_screenplay_character_cue():
    r = runner.invoke(cli.app, ["screenplay", "Alice (character) hello there"])
    assert r.exit_code == 0, r.output
    assert "ALICE" in r.output
    assert "hello there" in r.output


def test_screenplay_transition_and_action():
    assert runner.invoke(cli.app, ["screenplay", "transition: cut to"]).output.strip() == "CUT TO:"
    # a plain line becomes a smart-quoted action line
    r = runner.invoke(cli.app, ["screenplay", "she walks quote hello unquote"])
    assert "“hello”" in r.output


def test_screenplay_formats_each_line_from_stdin():
    r = runner.invoke(cli.app, ["screenplay"], input="scene: exterior park, night\nAlice (character) hi\n")
    assert r.exit_code == 0, r.output
    assert "EXT. PARK - NIGHT" in r.output
    assert "ALICE" in r.output
