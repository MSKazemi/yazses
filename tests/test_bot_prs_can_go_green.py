"""A gate only a human can satisfy must not sit on a bot's pull request.

`sbom.cdx.json` is generated from `uv.lock` and committed, and
`tests/test_sbom.py::test_committed_sbom_matches_the_lock_file` fails when the two
drift. That guard is right on its own terms -- docs/privacy-statement.md points
people at the file, and a stale SBOM is worse than none because it is trusted.

The half that was missing is what happens when the lockfile moves without a human
in the loop. `.github/dependabot.yml` runs a monthly `uv` sweep; Dependabot edits
`uv.lock` and nothing else, so **every** update PR it opens fails that one assertion
out of 13,805 the moment it is created. #320 (17 grouped updates) and #321 (evdev
2.0.0) both died there -- not on an incompatibility, on a generated file the bot
cannot regenerate. A PR that can only go green if a maintainer pushes a follow-up
commit does not land, and the dependency backlog builds while the automation still
looks like it is working.

These tests hold the pairing itself: as long as a bot opens lockfile PRs and a test
fails on a stale SBOM, something automated has to close the gap.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github/workflows"
DEPENDABOT = ROOT / ".github/dependabot.yml"
GENERATOR = "scripts/gen-sbom.py"

#: The lockfile a bot edits, and the committed file derived from it.
LOCKFILE = "uv.lock"
GENERATED = "sbom.cdx.json"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _workflows() -> list[tuple[Path, dict]]:
    return [(p, _load(p)) for p in sorted(WORKFLOWS.glob("*.yml"))]


def _triggers(doc: dict) -> dict:
    """`on:` is the YAML 1.1 boolean `True` after safe_load, not the string 'on'."""
    return doc.get(True) or doc.get("on") or {}


def _refresh_workflows() -> list[tuple[Path, dict]]:
    """Workflows that run the SBOM generator and push the result somewhere."""
    found = []
    for path, doc in _workflows():
        text = path.read_text(encoding="utf-8")
        if GENERATOR in text and "git push" in text:
            found.append((path, doc))
    return found


def test_the_premise_still_holds() -> None:
    """If either half goes away this module is measuring nothing, so say so loudly."""
    assert (ROOT / GENERATED).is_file(), f"{GENERATED} is no longer committed"
    assert (ROOT / GENERATOR).is_file(), f"{GENERATOR} is no longer there"
    ecosystems = {u["package-ecosystem"] for u in _load(DEPENDABOT)["updates"]}
    assert "uv" in ecosystems, (
        "Dependabot no longer opens uv lockfile PRs -- if that is deliberate, this "
        "whole module can go; if it is not, the monthly sweep has been lost."
    )


def test_a_lockfile_bot_pr_has_an_automated_way_to_go_green() -> None:
    refreshers = _refresh_workflows()
    assert refreshers, (
        f"Nothing regenerates {GENERATED} for a bot's lockfile PR, but "
        "tests/test_sbom.py fails when it is stale. Every Dependabot uv PR is "
        "therefore red on arrival and needs a hand-pushed commit to merge -- which "
        "is how #320 and #321 stalled."
    )


@pytest.mark.parametrize("case", _refresh_workflows(), ids=lambda c: c[0].name)
def test_the_refresh_fires_on_a_lockfile_change(case: tuple[Path, dict]) -> None:
    """A refresh that never triggers is the same as no refresh at all."""
    path, doc = case
    triggers = _triggers(doc)
    paths = [p for event in triggers.values() if isinstance(event, dict)
             for p in (event.get("paths") or [])]
    assert LOCKFILE in paths, (
        f"{path.name} regenerates {GENERATED} but does not trigger on {LOCKFILE}."
    )


@pytest.mark.parametrize("case", _refresh_workflows(), ids=lambda c: c[0].name)
def test_the_refresh_can_actually_push(case: tuple[Path, dict]) -> None:
    """`pull_request` hands a Dependabot-triggered run a read-only token, so a
    workflow that pushes must not be on that trigger -- it would compute the right
    file and then fail on the push, which reads as a broken fix rather than a
    missing permission."""
    path, doc = case
    triggers = _triggers(doc)
    assert "pull_request" not in triggers, (
        f"{path.name} pushes a commit but triggers on `pull_request`, which GitHub "
        "gives a read-only token on a Dependabot PR. Use `pull_request_target`."
    )
    assert doc.get("permissions", {}).get("contents") == "write", (
        f"{path.name} pushes a commit without `permissions: contents: write`."
    )


@pytest.mark.parametrize("case", _refresh_workflows(), ids=lambda c: c[0].name)
def test_a_pushing_workflow_is_gated_to_the_bot(case: tuple[Path, dict]) -> None:
    """`pull_request_target` runs in the base-branch context with a write token. The
    only thing standing between that and an outside contributor is the author gate,
    so its absence is a security defect rather than a tidiness one."""
    path, doc = case
    if "pull_request_target" not in _triggers(doc):
        pytest.skip(f"{path.name} does not use pull_request_target")
    gates = [str(job.get("if", "")) for job in doc["jobs"].values()]
    assert any("dependabot[bot]" in g and "pull_request.user.login" in g for g in gates), (
        f"{path.name} runs on pull_request_target with a write token and no "
        "`github.event.pull_request.user.login == 'dependabot[bot]'` gate."
    )


@pytest.mark.parametrize("case", _refresh_workflows(), ids=lambda c: c[0].name)
def test_the_commit_is_authored_by_the_maintainer(case: tuple[Path, dict]) -> None:
    """Every commit in this repository has one author, CI included."""
    path, _ = case
    text = path.read_text(encoding="utf-8")
    assert "mohsen.seyedkazemi@gmail.com" in text, (
        f"{path.name} commits without setting the repository's author identity; the "
        "commit would land as the Actions bot."
    )


@pytest.mark.parametrize("case", _refresh_workflows(), ids=lambda c: c[0].name)
def test_the_commit_names_what_it_commits(case: tuple[Path, dict]) -> None:
    """A bare `git commit` in a job that checked out a whole tree can sweep up
    anything else a step left behind. Name the file."""
    path, _ = case
    text = path.read_text(encoding="utf-8")
    assert f"-- {GENERATED}" in text, (
        f"{path.name} commits without a pathspec naming {GENERATED}."
    )


# --------------------------------------------------------------------------
# The fix could not reach the two pull requests it was written for
# --------------------------------------------------------------------------
#
# `pull_request_target` fires on a pull-request event. A PR opened *before* the
# refresh workflow existed will never see another one -- no rebase, no push, no
# trigger -- so #320 and #321 stayed red on the SBOM assertion the workflow was
# added to clear. The remedies without a manual entry point are a
# `@dependabot rebase` comment or closing and reopening, which discards the PR's
# review history.
#
# A manual path changes where the author gate has to live. On the
# `pull_request_target` path the job-level `if` establishes the author before
# anything runs; on a dispatch there is no pull request in the payload at all, only
# a number somebody typed, so the same job-level `if` passes unconditionally. The
# gate then has to be re-established inside the job, and it has to be established
# *before* the checkout, because that checkout keeps a push-capable token.


def _refresh_job(doc: dict) -> dict:
    (job,) = doc["jobs"].values()
    return job


@pytest.mark.parametrize("case", _refresh_workflows(), ids=lambda c: c[0].name)
def test_an_already_open_pr_can_be_refreshed_without_a_rebase(
    case: tuple[Path, dict],
) -> None:
    path, doc = case
    assert "workflow_dispatch" in _triggers(doc), (
        f"{path.name} can only be triggered by a pull-request event, so it cannot "
        "reach a PR that was already open when it was added -- which is the state "
        "#320 and #321 were in. Add a `workflow_dispatch` entry point."
    )


@pytest.mark.parametrize("case", _refresh_workflows(), ids=lambda c: c[0].name)
def test_a_manual_run_still_proves_the_pr_belongs_to_the_bot(
    case: tuple[Path, dict],
) -> None:
    """The job-level `if` cannot gate a dispatch: `github.event.pull_request` is
    null there, so the author half of the condition is vacuous. Something in the
    job body has to check it."""
    path, doc = case
    if "workflow_dispatch" not in _triggers(doc):
        pytest.skip(f"{path.name} has no manual entry point")
    body = "\n".join(str(step) for step in _refresh_job(doc)["steps"])
    assert "dependabot[bot]" in body, (
        f"{path.name} can be run manually against any pull request number, and "
        "nothing in the job re-checks that the PR is Dependabot's. The job-level "
        "`if` does not cover that path."
    )


@pytest.mark.parametrize("case", _refresh_workflows(), ids=lambda c: c[0].name)
def test_the_branch_is_authorised_before_it_is_checked_out(
    case: tuple[Path, dict],
) -> None:
    """`persist-credentials` keeps a push-capable token on the checked-out tree, so
    the order matters: authorise, then check out. Reversed, the token is on the
    branch before anything has established whose branch it is."""
    path, doc = case
    steps = _refresh_job(doc)["steps"]
    checkout = next(
        (i for i, s in enumerate(steps) if "actions/checkout" in str(s.get("uses", ""))),
        None,
    )
    assert checkout is not None, f"{path.name} pushes but never checks anything out"
    authorised = [
        i for i, s in enumerate(steps[:checkout]) if "dependabot[bot]" in str(s)
    ]
    if "workflow_dispatch" not in _triggers(doc):
        pytest.skip("no manual path; the job-level `if` is the gate")
    assert authorised, (
        f"{path.name} checks out the pull request's branch with "
        "`persist-credentials` before any step has established that the branch is "
        "Dependabot's. On the manual path that means a push-capable token on a "
        "branch named by whoever started the run."
    )
