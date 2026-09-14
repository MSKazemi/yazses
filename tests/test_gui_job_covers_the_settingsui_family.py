"""The GUI (Qt) job must cover every settings-window test file.

The job exists because PySide6 is not a base dependency, so every Qt test in the
suite is skipped by the ordinary job and the settings window's tests had never
executed anywhere. It selected its files by a hand-written list of nine names.
A tenth was added and joined nothing -- its Qt cases would have run only where
PySide6 is absent, which is to say nowhere.

A set that has to be remembered is the defect. The job now globs the family, and
this test holds that true: it fails if the glob is replaced by a list again, or
if a settings-window file is written outside the naming the glob derives from.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/test.yml"
FAMILY_GLOB = "tests/test_settingsui_*.py"


@pytest.fixture(scope="module")
def gui_run_step() -> str:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    gui = jobs["gui"]
    for step in gui["steps"]:
        run = step.get("run", "")
        if "pytest" in run and "gui-tests.txt" in run:
            return run
    raise AssertionError("the GUI job has no step that runs pytest")


def test_the_job_selects_the_family_by_glob(gui_run_step: str) -> None:
    assert FAMILY_GLOB in gui_run_step, (
        f"the GUI job must select the settings-window tests with {FAMILY_GLOB!r}. "
        "A hand-written list silently stops covering the next file added."
    )


def test_no_settingsui_file_is_named_individually(gui_run_step: str) -> None:
    """A leftover explicit name is how a list grows back.

    Comment lines are stripped first. The step's comment names the file whose
    omission prompted this, and matching prose would fail on the explanation
    rather than on a real selection -- the same cry-wolf trap the store-listing
    denylist hit.
    """
    invocation = "\n".join(
        line for line in gui_run_step.splitlines() if not line.strip().startswith("#")
    )
    named = re.findall(r"tests/test_settingsui_[a-z_]+\.py", invocation)
    assert not named, f"remove these; the glob already covers them: {named}"


def test_the_glob_actually_matches_something() -> None:
    """A guard that iterates is green on an empty collection."""
    matched = sorted(ROOT.glob(FAMILY_GLOB))
    assert len(matched) >= 10, f"only {len(matched)} files matched {FAMILY_GLOB}"


def test_the_snap_banner_test_is_inside_the_family() -> None:
    """The file whose omission prompted all this must be covered by the glob."""
    assert (ROOT / "tests/test_settingsui_snap_banner.py").is_file()
    assert (ROOT / "tests/test_settingsui_snap_banner.py") in set(ROOT.glob(FAMILY_GLOB))


def test_the_job_still_fails_on_a_silent_skip() -> None:
    """The anti-skip check is the reason the job means anything; keep it."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "No Qt test may be silently skipped" in text
    assert 'grep -q "^SKIPPED" gui-tests.txt' in text


def test_the_job_still_proves_pyside6_is_importable() -> None:
    """Without this the Qt tests skip and the job passes green having tested nothing."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "PySide6 must actually be importable" in text
