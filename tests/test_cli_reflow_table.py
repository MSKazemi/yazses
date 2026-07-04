"""CLI exposure for the reflow (ADR-v2-038) and table/CSV (ADR-v2-091) cores.

These were built + tested pure cores with no runtime entry point; here they are
driven through the real `yazses reflow` / `yazses table` commands.
"""
from __future__ import annotations

from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


# ---- yazses reflow ----------------------------------------------------------

def test_reflow_arg_makes_bulleted_outline():
    r = runner.invoke(cli.app, ["reflow", "First, set up the repo. Then run the tests."])
    assert r.exit_code == 0, r.output
    assert "- set up the repo" in r.output
    assert "- run the tests" in r.output


def test_reflow_marks_action_items_as_checkboxes():
    # Action markers trigger a checkbox; the phrase itself stays in the bullet body
    # (only leading *discourse* markers like 'first'/'then' are stripped).
    r = runner.invoke(cli.app, ["reflow", "I need to ship the release."])
    assert r.exit_code == 0, r.output
    assert "- [ ] I need to ship the release" in r.output


def test_reflow_reads_stdin_when_no_arg():
    r = runner.invoke(cli.app, ["reflow"], input="First, plan. Then build.\n")
    assert r.exit_code == 0, r.output
    assert "- plan" in r.output
    assert "- build" in r.output


# ---- yazses table -----------------------------------------------------------

def test_table_converts_spoken_rows_to_csv():
    r = runner.invoke(cli.app, ["table", "row: Ada, 1815, London next row Bob, 1990, Paris"])
    assert r.exit_code == 0, r.output
    lines = [ln for ln in r.output.splitlines() if ln.strip()]
    assert "Ada,1815,London" in lines
    assert "Bob,1990,Paris" in lines


def test_table_custom_separator():
    r = runner.invoke(cli.app, ["table", "--sep", ";", "a, b next row c, d"])
    assert r.exit_code == 0, r.output
    lines = [ln for ln in r.output.splitlines() if ln.strip()]
    assert "a;b" in lines
    assert "c;d" in lines


def test_table_reads_stdin_when_no_arg():
    r = runner.invoke(cli.app, ["table"], input="row: x, y, z\n")
    assert r.exit_code == 0, r.output
    assert "x,y,z" in r.output


# ---- yazses shellpipe -------------------------------------------------------

def test_shellpipe_renders_recognised_pipeline():
    r = runner.invoke(cli.app, ["shellpipe", "list files then count lines"])
    assert r.exit_code == 0, r.output
    assert "ls" in r.output and "wc -l" in r.output and "|" in r.output


def test_shellpipe_exits_nonzero_on_unknown_stage():
    r = runner.invoke(cli.app, ["shellpipe", "do something completely unrecognisable"])
    assert r.exit_code == 1


# ---- yazses braille ---------------------------------------------------------

def test_braille_translates_text():
    r = runner.invoke(cli.app, ["braille", "hello"])
    assert r.exit_code == 0, r.output
    assert "⠓⠑⠇⠇⠕" in r.output


def test_braille_grade1_flag_accepted():
    r = runner.invoke(cli.app, ["braille", "--grade", "1", "abc"])
    assert r.exit_code == 0, r.output
    assert r.output.strip()  # produced some braille cells


# ---- help renders (all carry Examples) -------------------------------------

def test_new_text_commands_help_have_examples():
    for cmd in ("reflow", "table", "shellpipe", "braille"):
        r = runner.invoke(cli.app, [cmd, "-h"])
        assert r.exit_code == 0
        assert "Examples" in r.output
