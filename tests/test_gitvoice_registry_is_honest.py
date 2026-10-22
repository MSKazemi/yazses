"""`yazses features info gitvoice` must describe the command that exists, not a voice path.

The catalog said: "Drive git by voice ...; destructive ops (force-push, reset --hard) wait
for a spoken confirm and the undo is always spoken", with the example "Say 'force push'
and it waits for confirm". A 2026-10-21 docs audit found none of that is real:

* git by voice is reachable only as the CLI command `yazses gitvoice "<text>"`;
* it prints the argv and its undo, runs only under `--run`, and a destructive command
  also needs `--yes`;
* nothing is spoken, there is no spoken confirm, no dictation path runs git;
* nothing reads `[gitvoice] enabled` -- the command works with the toggle on or off.

These tests pin the text to that, and pin the last fact to the code, so wiring the
toggle later fails here and forces the text to be rewritten with it.
"""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from yazses.cli import app
from yazses.config import Config
from yazses.system.features import enable_caveat, find_feature

SRC = Path(__file__).resolve().parent.parent / "src" / "yazses"


def _gitvoice():
    feat = find_feature(Config(), "gitvoice")
    assert feat is not None, "gitvoice left the feature registry"
    return feat


def _all_text(feat) -> str:
    return " ".join((feat.why, feat.example, feat.use_case))


def test_the_catalog_names_the_command_and_its_gates():
    why = _gitvoice().why
    assert "yazses gitvoice" in why
    assert "--run" in why
    assert "--yes" in why


def test_the_catalog_promises_no_spoken_confirm_or_spoken_undo():
    """The overclaim. "no spoken confirm" is allowed; promising one is not."""
    text = _all_text(_gitvoice()).lower()
    assert "wait for a spoken confirm" not in text
    assert "waits for confirm" not in text
    assert "undo is always spoken" not in text
    assert "gated behind a spoken confirm" not in text
    assert not re.search(r"\bsay 'force push'", text), "the example tells you to SAY it"


def test_the_catalog_says_the_toggle_is_not_read():
    assert "nothing reads" in _gitvoice().why


def test_features_info_prints_the_honest_text(sandbox_paths):
    r = CliRunner().invoke(app, ["features", "info", "gitvoice"])
    assert r.exit_code == 0, r.output
    assert "yazses gitvoice" in r.output
    assert "spoken confirm and" not in r.output


def test_enabling_it_says_the_switch_changes_nothing():
    caveat = enable_caveat("gitvoice", Config())
    assert caveat, "`features enable gitvoice` would imply the daemon now listens for git"
    assert "nothing reads [gitvoice] enabled" in caveat
    assert "--run" in caveat and "--yes" in caveat


def test_nothing_in_src_reads_the_toggle_except_the_registry():
    """What makes "nothing reads [gitvoice] enabled" true.

    The registry's own lambda (`c.gitvoice.enabled`) is how `yazses features` shows the
    switch's state; it is not a consumer. Any other read means the toggle now does
    something, and the catalog text above must change in the same commit.
    """
    readers = sorted(
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if re.search(r"gitvoice\.enabled|\[\s*[\"']gitvoice[\"']\s*\]",
                     path.read_text(encoding="utf-8"))
    )
    assert readers == [str(Path("system") / "features.py")], readers


def test_the_command_runs_with_the_toggle_off(sandbox_paths):
    """The default config has it off, and the command works anyway."""
    assert Config().gitvoice.enabled is False
    r = CliRunner().invoke(app, ["gitvoice", "status"])
    assert r.exit_code == 0, r.output
    assert r.output.splitlines()[0] == "git status"
