"""The `test` matrix drops macOS 3.11 on pull requests and nowhere else.

Measured on 2026-11-04 over the last 30 `test.yml` runs: 12 of 42 macOS jobs (29%) were
cancelled after about 15 minutes with no runner assigned, against 3 of 93 on Linux, 2 of
42 on Windows and 0 of 21 on arm64. Every PR launched two macOS legs (3.11 and 3.12) into
the one OS pool that is short of runners. Interpreter behaviour is covered by Linux
(3.11 to 3.14); macOS 3.12 keeps the OS coverage. So macOS 3.11 runs on pushes to main
and manual runs only (`.github/CI_POLICY.md` section 13, "macOS runner starvation").

GitHub does not allow the `matrix` context in a job-level `if:`, so one leg cannot be
skipped from outside. The `exclude` list is an expression on `github.event_name`
instead, and a leg it removes does not exist, so `ci-gate` sees a `test` job with fewer
legs rather than a skipped one. Nothing here can run GitHub's expander, so this file
re-implements the documented matrix semantics (cross product, `exclude` by partial match
on the original keys, then `include`) and renders the real expression from the real
file, offline. What it cannot prove is that GitHub accepts the expression; the first
pull-request run is that proof (see the pull request that introduced this file).
"""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TEST_YML = ROOT / ".github" / "workflows" / "test.yml"

#: The only shape this evaluator understands. A different one fails loudly, so changing
#: the expression means changing this file on purpose.
_EXCLUDE_SHAPE = re.compile(
    r"^\$\{\{\s*fromJSON\(\s*github\.event_name == 'pull_request'\s+"
    r"&&\s+'(?P<pr>\[[^']*\])'\s+\|\|\s+'(?P<other>\[[^']*\])'\s*\)\s*\}\}$"
)

EVENTS = ("pull_request", "push", "workflow_dispatch")


def rendered_exclude(exclude: Any, event_name: str) -> list[dict[str, str]]:
    """The `exclude` list GitHub would build for this event."""
    if isinstance(exclude, list):
        return exclude
    assert isinstance(exclude, str), exclude
    shape = _EXCLUDE_SHAPE.match(exclude.strip())
    assert shape, f"the exclude expression changed shape; update this evaluator: {exclude!r}"
    return json.loads(shape["pr"] if event_name == "pull_request" else shape["other"])


def expand(matrix: dict[str, Any], event_name: str) -> list[dict[str, Any]]:
    """GitHub's documented expansion: product, then `exclude`, then `include`."""
    exclude = rendered_exclude(matrix.get("exclude", []), event_name)
    include = matrix.get("include", [])
    axes = {k: v for k, v in matrix.items() if k not in ("include", "exclude")}
    combos = [dict(zip(axes, values)) for values in itertools.product(*axes.values())]
    combos = [c for c in combos if not any(all(c.get(k) == v for k, v in e.items()) for e in exclude)]
    originals = [dict(c) for c in combos]
    for entry in include:
        extended = False
        for combo, original in zip(combos, originals):
            # An include entry extends a combination only if it overwrites none of the
            # combination's original matrix values.
            if all(original[k] == v for k, v in entry.items() if k in original):
                combo.update(entry)
                extended = True
        if not extended:
            combos.append(dict(entry))
    return combos


def _matrix() -> dict[str, Any]:
    workflow = yaml.safe_load(TEST_YML.read_text(encoding="utf-8"))
    matrix: dict[str, Any] = workflow["jobs"]["test"]["strategy"]["matrix"]
    return matrix


def legs(event_name: str) -> set[tuple[str, str]]:
    return {(str(c["os"]), str(c["python-version"])) for c in expand(_matrix(), event_name)}


#: Every leg that is not macOS: it must not depend on the event.
LINUX_AND_WINDOWS = {
    ("ubuntu-latest", "3.11"),
    ("ubuntu-latest", "3.13"),
    ("ubuntu-latest", "3.14"),
    ("ubuntu-24.04-arm", "3.12"),
    ("windows-latest", "3.11"),
    ("windows-latest", "3.12"),
}
MACOS_312 = ("macos-latest", "3.12")
MACOS_311 = ("macos-latest", "3.11")


def test_the_expander_reproduces_the_pre_change_matrix() -> None:
    """Anchor the re-implementation: with nothing excluded but the baseline leg, the
    matrix is the eight legs it was before this change (test-linux runs the ninth)."""
    matrix = dict(_matrix())
    matrix["exclude"] = [{"os": "ubuntu-latest", "python-version": "3.12"}]
    rendered = {(str(c["os"]), str(c["python-version"])) for c in expand(matrix, "push")}
    assert rendered == LINUX_AND_WINDOWS | {MACOS_311, MACOS_312}


def test_a_pull_request_runs_macos_312_and_not_macos_311() -> None:
    pr = legs("pull_request")
    assert MACOS_312 in pr
    assert MACOS_311 not in pr
    assert {leg for leg in pr if leg[0] == "macos-latest"} == {MACOS_312}


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_main_and_manual_runs_run_both_macos_legs(event: str) -> None:
    assert {MACOS_311, MACOS_312} <= legs(event)


@pytest.mark.parametrize("event", EVENTS)
def test_every_linux_and_windows_leg_is_the_same_on_every_event(event: str) -> None:
    rendered = {leg for leg in legs(event) if leg[0] != "macos-latest"}
    assert rendered == LINUX_AND_WINDOWS


@pytest.mark.parametrize("event", EVENTS)
def test_the_baseline_leg_is_never_in_the_matrix(event: str) -> None:
    """`test-linux` runs ubuntu-latest / 3.12 on every PR; a second copy would double it."""
    assert ("ubuntu-latest", "3.12") not in legs(event)


def test_the_only_difference_between_events_is_macos_311() -> None:
    assert legs("push") - legs("pull_request") == {MACOS_311}
    assert legs("pull_request") <= legs("push")


def test_the_python_floor_is_still_proved_on_every_pull_request() -> None:
    """requires-python is >=3.11: dropping macOS 3.11 must leave 3.11 tested on a PR."""
    assert ("ubuntu-latest", "3.11") in legs("pull_request")
    assert ("windows-latest", "3.11") in legs("pull_request")


def test_no_macos_leg_is_allowed_to_fail() -> None:
    """The fix is to demand less of the starved pool, not to excuse its failures."""
    workflow = yaml.safe_load(TEST_YML.read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["test"]["strategy"]["matrix"]
    assert workflow["jobs"]["test"]["continue-on-error"] == "${{ matrix.experimental == true }}"
    for event in EVENTS:
        for combo in expand(matrix, event):
            if combo["os"].startswith("macos"):
                assert "experimental" not in combo, combo
    assert not any("macos" in str(e) for e in matrix.get("include", []))


def test_ci_gate_knows_nothing_about_which_legs_exist() -> None:
    """A leg that does not exist leaves `needs.test.result` at success when the rest pass;
    the gate must stay free of any per-leg or per-OS rule so a leg that does exist and
    fails or is cancelled still fails the job and so the gate."""
    workflow = yaml.safe_load(TEST_YML.read_text(encoding="utf-8"))
    gate = workflow["jobs"]["ci-gate"]
    script = gate["steps"][0]["run"]
    assert "macos" not in script.lower()
    assert "3.11" not in script
    assert "matrix" not in script
    assert "continue-on-error" not in gate
    assert gate["if"] == "always()"
    assert "test" in gate["needs"]


def test_the_job_names_of_the_remaining_legs_are_unchanged() -> None:
    """Branch rules, CI telemetry and docs may name `test (macos-latest, 3.12)`."""
    workflow = yaml.safe_load(TEST_YML.read_text(encoding="utf-8"))
    assert "name" not in workflow["jobs"]["test"], "the default name is `test (<os>, <python>)`"
    assert workflow["jobs"]["test-linux"]["name"] == "test (${{ matrix.os }}, ${{ matrix.python-version }})"
    assert list(_matrix())[:2] == ["os", "python-version"], "axis order sets the leg names"
