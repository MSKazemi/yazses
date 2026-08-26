"""The watcher that asks a second time whether a release actually shipped.

`release-complete.yml` asks at the tag push, when the slow channels have not had
time to answer. Nothing asked again, so on 2026-08-24 revisions #388/#389 of
2.31.0 sat APPROVED and unreleased in the Snap Store for two days behind a
wedged review queue, with no signal anywhere in the repository.

`channel-drift.yml` is the second question. What makes it worth having is the
grace period -- "behind an hour-old tag" is in flight and "behind a two-day-old
tag" is stalled, and a tag-time check cannot tell those apart. The tests here
guard that discriminator and the two shell footguns that would turn the watcher
into something that reports nothing or reports the same thing forever.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "channel-drift.yml"
CHECKER = ROOT / "scripts" / "check-release-channels.py"


@pytest.fixture(scope="module")
def doc() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def steps(doc: dict) -> list[dict]:
    return doc["jobs"]["watch"]["steps"]


def test_it_runs_on_a_schedule(doc: dict):
    """A watcher only reachable by hand is not a watcher.

    `on:` is the YAML boolean True once parsed -- `on` is a 1.1 boolean literal,
    which is why this reads the key rather than the string.
    """
    triggers = doc[True]
    assert "schedule" in triggers, "no cron -- nothing would ever ask the second time"
    assert triggers["schedule"], "an empty schedule list never fires"
    assert "workflow_dispatch" in triggers, "must be re-runnable after fixing a channel"


def test_the_grace_period_gates_both_the_check_and_the_report(steps: list[dict]):
    """The whole value of this workflow is not firing on an in-flight release.

    Without the gate it reports every newly tagged version as broken, every day,
    until the channels catch up -- and a watcher that cries wolf on every release
    is one whose issue gets closed unread, which is the failure it exists to
    prevent.
    """
    gated = [s for s in steps if "in_flight" in str(s.get("if", ""))]
    names = {s.get("name", s.get("uses", "")) for s in gated}
    assert len(gated) >= 2, f"only {names} are gated on the grace period"
    assert any("channel" in n.lower() for n in names)
    assert any("report" in n.lower() or "clear" in n.lower() for n in names)


def test_an_absent_issue_is_absent_and_not_the_string_null(text: str):
    """`jq '.[0].number'` on an empty array prints `null`, not nothing.

    `[ -n "null" ]` is true, so every run with no open issue would take the
    "update the existing one" branch and send `gh issue edit null`. Proven
    against the real jq below rather than asserted from memory.
    """
    assert "// empty" in text, "the empty-array case would read as issue number 'null'"


@pytest.mark.skipif(not __import__("shutil").which("jq"), reason="jq not installed")
def test_jq_really_does_print_null_for_an_empty_array():
    """The premise of the guard above, checked against jq itself."""
    naive = subprocess.run(
        ["jq", "-r", ".[0].number"], input="[]", capture_output=True, text=True
    )
    guarded = subprocess.run(
        ["jq", "-r", ".[0].number // empty"], input="[]", capture_output=True, text=True
    )
    assert naive.stdout.strip() == "null"
    assert guarded.stdout.strip() == ""


def test_the_issue_title_carries_no_version(doc: dict):
    """One issue kept current, not one per release left open forever."""
    title = doc["jobs"]["watch"]["env"]["ISSUE_TITLE"]
    assert "$" not in title and "{" not in title, f"interpolated title: {title!r}"


def test_the_body_is_edited_rather_than_commented_on(text: str):
    """A daily comment on a week-long stall is a thread nobody reads."""
    assert "gh issue edit" in text
    assert "--body-file body.md" in text


def test_it_closes_itself_when_the_channels_catch_up(text: str):
    """An issue that has to be closed by hand outlives the problem it describes."""
    assert "gh issue close" in text


def test_it_invokes_the_checker_the_way_the_checker_expects():
    """A renamed script or a changed flag turns this red on a schedule, not on a PR."""
    assert CHECKER.exists(), f"{CHECKER} is gone; the workflow calls it by path"
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--help"], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert "--version" in proc.stdout


def test_it_may_write_issues_and_may_not_write_the_repository(doc: dict):
    """The report is an issue; nothing here should be able to push."""
    perms = doc["jobs"]["watch"]["permissions"]
    assert perms["issues"] == "write"
    assert perms["contents"] == "read"


# --- the argument the whole design rests on ----------------------------------
#
# `--compare-with` is what separates "this channel went backwards" from "this
# project has never published to this channel". Without it the watcher files the
# same seven-channel issue every day -- six of them credential-gated and absent
# for every version -- and an issue that is always wrong about most of its
# contents is one whose reader stops opening it.
#
# These drive the real shell out of the real workflow rather than asserting on
# substrings, because the interesting cases are the two BRANCHES and a substring
# check passes on a fragment that never runs.


def _run_step(steps: list[dict], name_fragment: str, tmp_path, **outputs):
    """Execute one step's `run:` body with a recording `python3` on PATH.

    `${{ ... }}` expressions are substituted the way Actions would, which is
    textually and before bash sees them.
    """
    import os
    import re
    import stat

    body = next(
        s["run"] for s in steps if name_fragment.lower() in s.get("name", "").lower()
    )
    for key, value in outputs.items():
        body = re.sub(
            r"\$\{\{\s*steps\.target\.outputs\." + key + r"\s*\}\}", value, body
        )
    assert "${{" not in body, f"unsubstituted expression left in: {body}"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "python3"
    shim.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGV_LOG"\nexit 0\n')
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

    argv_log = tmp_path / "argv"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ARGV_LOG": str(argv_log),
        "GITHUB_OUTPUT": str(tmp_path / "out"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    proc = subprocess.run(
        ["bash", "-c", body], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    return argv_log.read_text().splitlines()


posix_only = pytest.mark.skipif(
    __import__("os").name != "posix", reason="runs the workflow's bash body"
)


@posix_only
def test_it_compares_against_the_previous_release(steps: list[dict], tmp_path):
    argv = _run_step(steps, "ask every channel", tmp_path, version="2.31.0", previous="2.29.0")
    assert "--compare-with" in argv
    assert argv[argv.index("--compare-with") + 1] == "2.29.0"
    assert argv[argv.index("--version") + 1] == "2.31.0"


@posix_only
def test_with_no_previous_release_it_falls_back_to_plain_completeness(
    steps: list[dict], tmp_path
):
    """The empty-collection trap: no previous release must not mean "all clear".

    An unset `--compare-with` would make `regressions()` compare against nothing
    and find nothing wrong -- a green verdict derived from having asked no
    question. The fallback asks the plain question instead.
    """
    argv = _run_step(steps, "ask every channel", tmp_path, version="2.31.0", previous="")
    assert "--compare-with" not in argv
    assert argv[argv.index("--version") + 1] == "2.31.0"
