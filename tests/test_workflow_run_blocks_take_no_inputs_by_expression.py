"""No `run:` script receives a caller-supplied value through `${{ }}` interpolation.

CI_POLICY.md §7 rule 4: text that somebody chose must reach a shell through an
environment variable or a file, never by expression. `${{ inputs.x }}` is expanded by the
runner into the script *source* before the shell starts, so a value of `1"; curl ... #`
is not data to the shell, it is more script. `env: X: ${{ inputs.x }}` and `"$X"` is the
same value as data, and costs one line.

The four `workflow_dispatch` inputs that were interpolated this way (`apt-repo.yml`,
`channel-drift.yml`, `publish-channels.yml`, `snap.yml`) are reachable only by someone
with write access, so none was an outside-attacker hole. That is exactly why this is
worth pinning now: a rule held by "the only people who can reach it are trusted" stops
holding the day a dispatch is wired to a comment, a label or a bot.

Scope, stated plainly. This guard covers the expressions a caller or an event author
controls: `inputs.*`, `github.event.inputs.*`, and any `github.event.*` field not on the
short allow-list of numbers and enums below, plus `github.head_ref` and
`github.ref_name`. It does not cover `steps.*.outputs.*` or `matrix.*`, which carry
values the workflow computed itself; those are reviewed by reading, and a value that
originates in a branch or tag name is the case to look for there.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent / ".github"
FILES = sorted([*(ROOT / "workflows").glob("*.yml"), *ROOT.glob("actions/*/action.yml")])

_EXPR = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_CALLER = re.compile(
    r"(?<![\w.])(?:inputs\.|github\.event\.|github\.head_ref|github\.ref_name)"
)
#: Event fields that are a number, a fixed enum or a boolean -- not text anyone typed.
_SAFE = (
    "github.event_name",
    "github.event.pull_request.number",
    "github.event.workflow_run.id",
    "github.event.workflow_run.conclusion",
    "github.event.number",
)


def _run_scripts(doc: dict) -> list[tuple[str, str]]:
    """(location, script) for every `run:` in a workflow or a composite action."""
    found: list[tuple[str, str]] = []
    jobs = doc.get("jobs") or {}
    for job_name, job in jobs.items():
        for i, step in enumerate((job or {}).get("steps") or []):
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                found.append((f"{job_name}[{i}] {step.get('name', '')!r}", step["run"]))
    for i, step in enumerate((doc.get("runs") or {}).get("steps") or []):
        if isinstance(step, dict) and isinstance(step.get("run"), str):
            found.append((f"composite[{i}] {step.get('name', '')!r}", step["run"]))
    return found


def _violations(script: str) -> list[str]:
    bad = []
    for expr in _EXPR.findall(script):
        body = expr.strip()
        if not _CALLER.search(body):
            continue
        if any(s in body for s in _SAFE) and not re.search(
            r"inputs\.|github\.head_ref|github\.ref_name", body
        ):
            continue
        bad.append(body)
    return bad


def test_the_scan_sees_the_run_blocks() -> None:
    total = 0
    for path in FILES:
        total += len(_run_scripts(yaml.safe_load(path.read_text(encoding="utf-8"))))
    assert total > 100, f"only {total} run blocks found; the scan is not reading the files"


def test_the_detector_flags_an_input_and_passes_an_env_reference() -> None:
    assert _violations('V="${{ inputs.version }}"') == ["inputs.version"]
    assert _violations('V="${{ github.event.inputs.workflow || \'release\' }}"')
    assert _violations('echo "${{ github.head_ref }}"') == ["github.head_ref"]
    assert _violations('echo "${{ github.event.pull_request.title }}"')
    assert _violations('V="$VERSION"') == []
    assert _violations('echo "${{ github.event.workflow_run.id }}"') == []
    assert _violations('[ "${{ github.event_name }}" = x ]') == []


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_run_block_interpolates_a_caller_supplied_value(path: Path) -> None:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    offenders = {
        where: bad for where, script in _run_scripts(doc) if (bad := _violations(script))
    }
    assert not offenders, (
        f"{path.name}: a caller-supplied expression is expanded into shell source "
        f"(CI_POLICY.md section 7, rule 4). Pass it through `env:` and quote the "
        f"variable instead: {offenders}"
    )
