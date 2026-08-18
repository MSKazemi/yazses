"""CLI exposure for the clipboard-history core (ADR-v2-060) — persistent store."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


@pytest.fixture()
def hist(tmp_path, monkeypatch):
    path = tmp_path / "cliphistory.json"
    monkeypatch.setattr(cli, "_cliphistory_path", lambda: path)
    return path


def test_add_list(hist):
    runner.invoke(cli.app, ["cliphistory", "add", "alpha"])
    runner.invoke(cli.app, ["cliphistory", "add", "beta"])
    out = runner.invoke(cli.app, ["cliphistory", "list"]).output
    # newest first
    assert out.index("beta") < out.index("alpha")


def test_recall_url_and_ordinal(hist):
    runner.invoke(cli.app, ["cliphistory", "add", "just some text"])
    runner.invoke(cli.app, ["cliphistory", "add", "https://example.com"])
    assert runner.invoke(cli.app, ["cliphistory", "recall", "the last url"]).output.strip() == "https://example.com"
    assert runner.invoke(cli.app, ["cliphistory", "recall", "the second one"]).output.strip() == "just some text"


def test_recall_no_match_exits_nonzero(hist):
    r = runner.invoke(cli.app, ["cliphistory", "recall", "anything"])
    assert r.exit_code == 1
    assert "no matching" in r.output.lower()


def test_add_empty_exits_nonzero(hist):
    r = runner.invoke(cli.app, ["cliphistory", "add"], input="\n")
    assert r.exit_code == 1


def test_add_reads_stdin(hist):
    runner.invoke(cli.app, ["cliphistory", "add"], input="piped value\n")
    assert runner.invoke(cli.app, ["cliphistory", "list"]).output.strip().endswith("piped value")


# ---------------------------------------------------------------------------
# The numbering sets a trap that only labels can remove
# ---------------------------------------------------------------------------
#
# `list` is newest-first and numbered, so #1 is the most recent. But
# `recall "the first thing I copied"` deliberately means the OLDEST — that is the
# right reading of that sentence, and `test_spreadsheet_cliphistory` asserts it.
# The two are both correct and point opposite ways, so a bare "1. …" invites "the
# first one" and hands back the other end.
#
# The semantics are deliberately NOT changed here: English is genuinely ambiguous,
# and the tested reading is the natural one. What is fixed is the surface that
# implies a contradiction without ever stating the rule.


def _labelled(items, tmp_path, monkeypatch):
    """Run `cliphistory list` over *items*, isolated by patching the path directly.

    Not by setting XDG_* in the runner's env: `get_platform()` memoizes, so the first
    call in the process fixes the paths for every later one. My first version did that
    and the three cases leaked into each other — a fresh `TemporaryDirectory` per call
    that every call then ignored. (It never reached the real config: verified, the
    user's history was still empty.) Patching the accessor is the isolation that
    actually holds.
    """
    from typer.testing import CliRunner

    from yazses import cli as cli_mod

    store = tmp_path / "cliphistory.json"
    monkeypatch.setattr(cli_mod, "_cliphistory_path", lambda: store)
    runner = CliRunner()
    for text in items:
        runner.invoke(cli_mod.app, ["cliphistory", "add", text])
    return runner.invoke(cli_mod.app, ["cliphistory", "list"]).output


def test_the_list_names_which_end_is_which(tmp_path, monkeypatch):
    out = _labelled(["AAA", "BBB", "CCC"], tmp_path, monkeypatch)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert "most recent" in lines[0], f"newest end unlabelled: {lines[0]!r}"
    assert "oldest" in lines[-1], f"oldest end unlabelled: {lines[-1]!r}"


def test_the_labels_sit_on_the_right_rows(tmp_path, monkeypatch):
    """Newest-first, so the label must be on #1 — reversing it would be worse than none."""
    out = _labelled(["AAA", "BBB", "CCC"], tmp_path, monkeypatch)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert "CCC" in lines[0] and "most recent" in lines[0]
    assert "AAA" in lines[-1] and "oldest" in lines[-1]


def test_a_single_entry_is_not_labelled_at_both_ends(tmp_path, monkeypatch):
    """One item is both newest and oldest; saying so twice is noise, not information."""
    out = _labelled(["ONLY"], tmp_path, monkeypatch)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert "most recent" not in lines[0] and "oldest" not in lines[0]


def test_the_help_states_which_end_first_and_last_mean():
    """The rule existed only in the code. A user cannot infer it from a numbered list."""
    from typer.testing import CliRunner

    from yazses.cli import app

    out = CliRunner().invoke(app, ["cliphistory", "recall", "-h"]).output
    assert "NEWEST" in out and "OLDEST" in out
