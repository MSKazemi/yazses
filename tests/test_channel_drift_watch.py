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


def _run_step(steps: list[dict], name_fragment: str, tmp_path, checker_exit=0, **outputs):
    """Execute one step's `run:` body with a recording `python3` on PATH.

    `${{ ... }}` expressions are substituted the way Actions would, which is
    textually and before bash sees them.

    Two details here are load-bearing rather than incidental, and both were wrong
    in the first version of this harness -- which is why it could not see the
    defect that made the watcher silent for 17 days:

    * **The body runs under `bash -e`**, because that is literally how Actions
      invokes it (`/usr/bin/bash -e {0}`). Running it as a plain `bash -c` makes
      every `-e` interaction untestable, and `-e` is exactly what broke the step.
    * **`checker_exit` is settable**, because the checker signals drift by exiting
      1. A stub hardcoded to `exit 0` can only ever exercise the path where there
      is nothing to report, so the reporting path was never run by any test.
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
    shim.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGV_LOG"\nexit {checker_exit}\n',
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

    argv_log = tmp_path / "argv"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ARGV_LOG": str(argv_log),
        "GITHUB_OUTPUT": str(tmp_path / "out"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    # `-e` and a file argument, exactly as Actions runs it.
    script = tmp_path / "step.sh"
    script.write_text(body, encoding="utf-8")
    proc = subprocess.run(
        ["/usr/bin/bash", "-e", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"the step died (exit {proc.returncode}). Under Actions this skips every "
        f"downstream step, so nothing is reported.\nstderr: {proc.stderr}"
    )
    return argv_log.read_text(encoding="utf-8").splitlines()


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


# --- the footgun that actually silenced the watcher --------------------------
#
# The checker exits 1 to *mean* "a channel is behind". The step is written to
# capture that into an output rather than die on it, and the comment in the
# workflow says so explicitly. But Actions runs the body as `/usr/bin/bash -e`,
# and `set -uo pipefail` does not clear a `-e` that arrived with the invocation.
# So the step died on the exact input it exists to handle, "Report or clear" was
# skipped as downstream of a failure, and the watcher filed nothing at all in its
# first 17 days -- going green whenever there was no drift and red-and-silent the
# single day there was.


@posix_only
def test_a_reporting_checker_does_not_kill_the_step(steps: list[dict], tmp_path):
    """Exit 1 from the checker is a finding to record, never a dead step."""
    _run_step(
        steps,
        "ask every channel",
        tmp_path,
        checker_exit=1,
        version="2.36.0",
        previous="2.35.0",
    )
    outputs = (tmp_path / "out").read_text(encoding="utf-8")
    assert "drift=1" in outputs, (
        "the checker reported drift and the step did not record it; "
        f"GITHUB_OUTPUT was {outputs!r}"
    )


@posix_only
def test_the_report_reaches_the_step_summary_when_there_is_drift(
    steps: list[dict], tmp_path
):
    """`cat report.md` is after the capture, so it dies with it.

    The report is the only human-readable half of the finding. A step that exits
    before this line reports a number and no reason.
    """
    _run_step(
        steps,
        "ask every channel",
        tmp_path,
        checker_exit=1,
        version="2.36.0",
        previous="2.35.0",
    )
    assert (tmp_path / "summary").exists(), "no step summary written on the drift path"


def test_the_step_clears_e_rather_than_only_setting_u_and_pipefail(steps: list[dict]):
    """Pin the mechanism, not just the behaviour.

    `set -uo pipefail` reads like it establishes the step's error handling and
    silently does not clear `-e`. Someone tidying this back to the shorter form
    would reintroduce a bug whose only symptom is a watcher that never reports,
    which is indistinguishable from a watcher with nothing to report.
    """
    body = next(
        s["run"] for s in steps if "ask every channel" in s.get("name", "").lower()
    )
    assert "set +e" in body, (
        "the step must clear `-e` explicitly; Actions invokes this body as "
        "`/usr/bin/bash -e {0}` and the checker exits 1 by design"
    )
