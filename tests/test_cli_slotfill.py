"""CLI exposure for the schema slot-filling core (ADR-v2-063)."""
from __future__ import annotations

import json

from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


def test_slotfill_after_and_choices():
    r = runner.invoke(cli.app, [
        "slotfill", "set priority high and open firefox",
        "--slot", "priority:after=priority",
        "--slot", "browser:choices=firefox,chrome",
    ])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output) == {"priority": "high", "browser": "firefox"}


def test_slotfill_no_match_is_empty_object():
    r = runner.invoke(cli.app, ["slotfill", "nothing relevant", "--slot", "x:choices=a,b"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output) == {}


def test_slotfill_bad_spec_exits_nonzero():
    r = runner.invoke(cli.app, ["slotfill", "text", "--slot", "noequalsign"])
    assert r.exit_code == 1
    assert "bad --slot" in r.output.lower()


def test_slotfill_unknown_kind_exits_nonzero():
    r = runner.invoke(cli.app, ["slotfill", "text", "--slot", "x:regex=foo"])
    assert r.exit_code == 1
    assert "unknown slot kind" in r.output.lower()
