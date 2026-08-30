"""A step that pins a package must not be undone by the step after it.

`uv run` synchronises the project environment against `uv.lock` *before* it runs the
command. That is almost always what you want, and it is exactly wrong immediately
after a deliberate downgrade: the pin is silently reverted and the command then runs
against the version the pin existed to avoid.

`.github/workflows/heavy-extras.yml` was written to prove that the remedy this project
prints to its users actually works. `voiceprint/factory.py` catches resemblyzer's
`ModuleNotFoundError` and tells the reader, in those words, to
``pip install "setuptools<81"`` -- because `resemblyzer` imports `webrtcvad`, whose
first line is `import pkg_resources`, which setuptools removed in 81.0.0. So the job
pinned `setuptools<81` and then imported `resemblyzer` to show the advice was good.

Three bare `uv run` invocations followed that pin, and each of them put setuptools
back to the locked 84.0.0 before running. Measured rather than reasoned about, in a
throwaway project pinned to `packaging<25`::

    uv pip install "packaging<25"
    uv run --no-sync python -c "import packaging; print(packaging.__version__)"  -> 24.2
    uv run          python -c "import packaging; print(packaging.__version__)"  -> 26.3
                                                    ("Uninstalled 1 package ...")

and confirmed against the real dependency, with the shared virtualenv left alone by
installing to a `--target` directory and putting it first on `PYTHONPATH`::

    setuptools 84.0.0  -> from resemblyzer import VoiceEncoder
                          ModuleNotFoundError: No module named 'pkg_resources'
    setuptools 80.10.2 -> resemblyzer ok

So the job could not have passed, whatever the state of the dependency: the pin was
gone by the time the import ran. Nobody had seen it, because the workflow is weekly
and had not yet reached a Monday -- which is the part worth keeping in mind. A job
that runs rarely is a job whose breakage is discovered late, so the cheap guard is the
one that reads the file rather than the one that waits for the schedule.

The check below is deliberately derived rather than a list: it scans *every* workflow
for the pattern, so the next place someone pins a version in CI is covered on the day
it is written rather than after the same afternoon of debugging.

`--frozen` is accepted alongside `--no-sync`; it also stops `uv run` from touching the
environment, and refusing it would be a guard enforcing a spelling rather than a
property.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

WORKFLOWS = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"

#: The workflow this guard was written for. Named only so its *vacuity* can be
#: checked -- the scan itself never looks at this name.
NEEDS_A_PIN = "heavy-extras.yml"

_PIN = re.compile(r"\buv pip install\b")
_UV_RUN = re.compile(r"\buv run\b")
_SAFE = ("--no-sync", "--frozen")


def _violations(doc: dict) -> list[tuple[str, str, str]]:
    """`uv run` lines that follow a `uv pip install` in the same job, unprotected."""
    found: list[tuple[str, str, str]] = []
    for job_name, job in (doc.get("jobs") or {}).items():
        pinned = False
        for step in (job or {}).get("steps") or []:
            run = (step or {}).get("run") or ""
            if pinned:
                for line in run.splitlines():
                    if _UV_RUN.search(line) and not any(f in line for f in _SAFE):
                        found.append((job_name, (step or {}).get("name", "?"), line.strip()))
            # Checked *after* the scan so a step cannot be judged against its own pin.
            if _PIN.search(run):
                pinned = True
    return found


def _workflows() -> list[pathlib.Path]:
    return sorted(p for p in WORKFLOWS.iterdir() if p.suffix in {".yml", ".yaml"})


def test_no_workflow_undoes_its_own_pin_with_a_bare_uv_run() -> None:
    bad: list[str] = []
    for path in _workflows():
        for job, step, line in _violations(yaml.safe_load(path.read_text(encoding="utf-8"))):
            bad.append(f"{path.name} :: job {job} :: step {step!r}\n      {line}")
    assert not bad, (
        "a `uv run` follows a `uv pip install` without `--no-sync`, so it re-syncs the\n"
        "environment against uv.lock and reverts the pin before running anything:\n\n  "
        + "\n  ".join(bad)
    )


def test_the_scanner_would_actually_notice() -> None:
    """Without this the guard above passes on any repository, including one where the
    bug is present and the parse quietly returned nothing."""
    doc = yaml.safe_load(
        """
jobs:
  demo:
    steps:
      - run: uv sync
      - run: uv pip install "setuptools<81"
      - run: uv run python -c "import resemblyzer"
"""
    )
    assert _violations(doc) == [("demo", "?", 'uv run python -c "import resemblyzer"')]


@pytest.mark.parametrize("flag", ["--no-sync", "--frozen"])
def test_either_protecting_flag_is_accepted(flag: str) -> None:
    doc = yaml.safe_load(
        f"""
jobs:
  demo:
    steps:
      - run: uv pip install "setuptools<81"
      - run: uv run {flag} python -c "import resemblyzer"
"""
    )
    assert _violations(doc) == []


def test_a_pin_is_not_judged_against_itself() -> None:
    """A single step that pins and then runs in the same script is the one case the
    ordering cannot resolve, and flagging it would be a false positive that teaches
    people to work around the guard."""
    doc = yaml.safe_load(
        """
jobs:
  demo:
    steps:
      - run: |
          uv pip install "setuptools<81"
          uv run python -c "import resemblyzer"
"""
    )
    assert _violations(doc) == []


def test_the_workflow_this_was_written_for_still_pins_and_still_runs() -> None:
    """The vacuity anchor. If `heavy-extras.yml` ever stops pinning, or stops running
    anything afterwards, the scan above still passes while proving nothing -- so say so
    here rather than letting the suite go quietly green."""
    doc = yaml.safe_load((WORKFLOWS / NEEDS_A_PIN).read_text(encoding="utf-8"))
    steps = [s for j in (doc.get("jobs") or {}).values() for s in (j or {}).get("steps") or []]
    runs = [(s or {}).get("run") or "" for s in steps]
    pins = [i for i, r in enumerate(runs) if _PIN.search(r)]
    assert pins, f"{NEEDS_A_PIN} no longer pins anything; this guard now checks nothing"
    after = [r for r in runs[pins[0] + 1 :] if _UV_RUN.search(r)]
    assert after, (
        f"{NEEDS_A_PIN} pins a version and then never runs `uv run`; the guard above is "
        "no longer exercised by any real file"
    )


def test_the_reason_is_written_down_beside_the_flag() -> None:
    """A lone `--no-sync` reads like noise and gets tidied away. The explanation is
    what stops that, so it is part of the fix rather than decoration."""
    text = (WORKFLOWS / NEEDS_A_PIN).read_text(encoding="utf-8")
    assert "--no-sync" in text
    assert "re-syncs" in text, (
        "the `--no-sync` flags in heavy-extras.yml are no longer explained; whoever "
        "removes them next will have nothing telling them why the job goes red"
    )
