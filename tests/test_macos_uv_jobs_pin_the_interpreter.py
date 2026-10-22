"""A CI job that can run on macOS and installs with uv must name its Python (#424).

With no interpreter requested, uv uses the first one it discovers that satisfies
`requires-python = ">=3.11"`. On the GitHub macOS image that is Homebrew's `python3`, and
Homebrew tracks the newest CPython release. Image `macos-26-arm64` 20261013 added
`python@3.15`. From 2026-10-17 on, every macOS leg of `eye-eval-ci.yml` logged::

    Using CPython 3.15.0 interpreter at: /opt/homebrew/opt/python@3.15/bin/python3.15
    error: Distribution `onnxruntime==1.28.0 ...` can't be installed because it doesn't
    have a source distribution or wheel for the current platform
    hint: You're using CPython 3.15 (`cp315`), but `onnxruntime` (v1.28.0) only has
    wheels with the following Python ABI tags: `cp311`, `cp312`, `cp313`, `cp313t`,
    `cp314`, `cp314t`

The last green run (2026-10-15, image 20260907) had picked `python@3.14`. `test.yml`'s
macOS legs ran on the same 20261013 image and stayed green, because they pass
`python-version:` to setup-uv. That is a controlled comparison: same image, same lock,
one difference. The same failure reproduces offline with `UV_PYTHON=3.15 uv sync
--dry-run` (exit 2), and `UV_PYTHON=3.12` passes (exit 0).

The rule is scoped to macOS because that is where the system interpreter moves on its
own. The Linux legs use the distribution's `/usr/bin/python3` (3.12 on ubuntu-24.04) and
the Windows legs use the toolcache default (3.12). Both are fixed per image version, not
per Homebrew release.

Accepted pins, each seen to hold on the 3.15 image or documented by uv:

* `python-version:` on `astral-sh/setup-uv`, which exports `UV_PYTHON` (test.yml's run
  log shows "Set UV_PYTHON to 3.12");
* `UV_PYTHON` in a workflow, job or step `env`;
* a `uv python install X.Y` step. uv prefers a managed interpreter over one on `PATH`,
  and `build-macos.yml` resolved CPython 3.12.15 this way on 2026-10-18;
* `--python` on the uv command itself.

Everything here is derived from the files: the workflows are read from disk, a step that
runs a `scripts/*.sh` is checked through that script, and the "has a wheel" half reads
`uv.lock`. A hand-written list of jobs would miss the next workflow to add a macOS leg.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
LOCK = ROOT / "uv.lock"

#: The wheel-only dependency that broke. If the pinned interpreter has no macOS arm64
#: wheel for it, the pin moves the failure without removing it.
WHEEL_ONLY = ("onnxruntime",)

# A uv command that resolves or installs into an environment. `uv run --no-project` is
# left out on purpose: it runs a stdlib script and never touches the lock.
_INSTALLS = re.compile(r"\buv (sync|venv|pip install|run(?! --no-project))\b")
_SCRIPT = re.compile(r"(?:^|\s|\./)(scripts/[\w./-]+\.sh)\b")


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def can_run_on_macos(job: dict[str, Any]) -> bool:
    runs_on = " ".join(_strings(job.get("runs-on", "")))
    if "macos" in runs_on:
        return True
    if "matrix." in runs_on:
        # Conservative: any macOS label anywhere in the matrix counts as a macOS leg.
        return any("macos" in s for s in _strings((job.get("strategy") or {}).get("matrix")))
    return False


def _run_text(step: dict[str, Any], root: Path = ROOT) -> str:
    """The step's shell, plus any repository script it calls, so indirection is seen."""
    text = str(step.get("run", ""))
    for rel in _SCRIPT.findall(text):
        path = root / rel
        if path.is_file():
            text += "\n" + path.read_text(encoding="utf-8")
    return text


def installs_with_uv(job: dict[str, Any], root: Path = ROOT) -> bool:
    return any(_INSTALLS.search(_run_text(s, root)) for s in job.get("steps") or [])


def interpreter_pins(workflow: dict[str, Any], job: dict[str, Any]) -> list[str]:
    """Every pinned version (or matrix expression) this job sets. Empty means unpinned."""
    pins: list[str] = []
    for env in (workflow.get("env"), job.get("env")):
        if env and "UV_PYTHON" in env:
            pins.append(str(env["UV_PYTHON"]))
    for step in job.get("steps") or []:
        if "UV_PYTHON" in (step.get("env") or {}):
            pins.append(str(step["env"]["UV_PYTHON"]))
        if "setup-uv" in str(step.get("uses", "")) and "python-version" in (step.get("with") or {}):
            pins.append(str(step["with"]["python-version"]))
        run = str(step.get("run", ""))
        pins += re.findall(r"\buv python install\s+(\S+)", run)
        pins += re.findall(r"\buv (?:sync|venv|run|pip install)\b[^\n]*?--python[ =](\S+)", run)
    return pins


def _resolve(pin: str, job: dict[str, Any]) -> list[str]:
    """`${{ matrix.KEY }}` becomes every value KEY can take on a macOS leg; a literal is itself.

    The base list crosses every runner, so all of it counts. An `include` entry that names a
    Linux or Windows runner (test.yml's 3.13 and 3.14 legs) never reaches macOS, so it is
    skipped; an entry naming no runner is kept, which errs towards checking too much.
    """
    m = re.fullmatch(r"\$\{\{\s*matrix\.([\w-]+)\s*\}\}", pin.strip())
    if not m:
        return [pin]
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    key = m.group(1)
    values = [str(v) for v in matrix.get(key) or []]
    for inc in matrix.get("include") or []:
        other_os = any(str(v).startswith(("ubuntu", "windows")) for v in inc.values())
        if key in inc and not other_os:
            values.append(str(inc[key]))
    return values


#: A concrete X.Y or X.Y.Z. A range or `3.x` floats with the image, the same as no pin.
_CONCRETE = re.compile(r"3\.\d+(\.\d+)?")


def pin_problems(workflow: dict[str, Any], job: dict[str, Any]) -> list[str]:
    """Why this job's interpreter is not pinned. An empty list means it is."""
    pins = interpreter_pins(workflow, job)
    if not pins:
        return ["names no interpreter"]
    problems: list[str] = []
    for pin in pins:
        versions = _resolve(pin, job)
        if not versions:
            problems.append(f"pins {pin!r}, which the matrix gives no value")
        problems += [f"pins {v!r}, which is not a concrete version" for v in versions if not _CONCRETE.fullmatch(v)]
    return problems


def macos_uv_jobs() -> list[tuple[str, str, dict[str, Any], dict[str, Any]]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in (workflow.get("jobs") or {}).items():
            if can_run_on_macos(job) and installs_with_uv(job):
                found.append((path.name, name, workflow, job))
    return found


def _macos_arm64_cp_tags(package: str) -> set[str]:
    text = LOCK.read_text(encoding="utf-8")
    stem = package.replace("-", "_")
    return set(re.findall(rf"{stem}-[^\"/-]+-(cp3\d+)-cp3\d+-macosx_[\w.]+_arm64\.whl", text))


JOBS = macos_uv_jobs()


def test_the_scan_finds_the_jobs_it_exists_for() -> None:
    # A guard that iterates is green on an empty collection, so the collection is checked.
    names = {(f, j) for f, j, _, _ in JOBS}
    assert ("eye-eval-ci.yml", "evaluate") in names
    assert ("test.yml", "test") in names
    # Seen only through scripts/build-macos.sh, whose `uv sync` is not in the YAML.
    assert ("macos-smoke.yml", "smoke") in names


@pytest.mark.parametrize(("wf", "name"), [(f, j) for f, j, _, _ in JOBS])
def test_every_macos_job_that_installs_with_uv_pins_its_interpreter(wf: str, name: str) -> None:
    _, _, workflow, job = next(item for item in JOBS if item[:2] == (wf, name))
    assert pin_problems(workflow, job) == [], (
        f"{wf}::{name} can run on macOS and installs with uv, so uv would take the image's "
        "Homebrew python3, which tracks the newest CPython. Give setup-uv a concrete "
        "`python-version:` as test.yml does"
    )


@pytest.mark.parametrize("package", WHEEL_ONLY)
def test_every_pinned_macos_interpreter_has_a_locked_wheel(package: str) -> None:
    tags = _macos_arm64_cp_tags(package)
    assert tags, f"no locked macOS arm64 wheel for {package}; the regex no longer matches uv.lock"
    for wf, name, workflow, job in JOBS:
        for pin in interpreter_pins(workflow, job):
            for version in _resolve(pin, job):
                cp = "cp" + "".join(version.split(".")[:2])
                assert cp in tags, f"{wf}::{name} pins {version}, but {package} locks no {cp} macOS wheel"


# --- the guard can fail -----------------------------------------------------------------


_SETUP_UV = {"uses": "astral-sh/setup-uv@0000000000000000000000000000000000000000"}


def _job(*steps: dict[str, Any], runs_on: str = "${{ matrix.os }}") -> dict[str, Any]:
    return {
        "runs-on": runs_on,
        "strategy": {"matrix": {"os": ["ubuntu-latest", "macos-latest", "windows-latest"]}},
        "steps": list(steps),
    }


def test_the_eye_eval_job_as_it_was_on_main_is_flagged() -> None:
    job = _job(_SETUP_UV, {"run": "uv sync"})
    assert can_run_on_macos(job) and installs_with_uv(job)
    assert pin_problems({}, job) == ["names no interpreter"]


def test_each_accepted_pin_is_recognised() -> None:
    pinned_uv = {**_SETUP_UV, "with": {"python-version": "3.12"}}
    assert interpreter_pins({}, _job(pinned_uv, {"run": "uv sync"})) == ["3.12"]
    assert interpreter_pins({"env": {"UV_PYTHON": "3.12"}}, _job({"run": "uv sync"})) == ["3.12"]
    assert interpreter_pins({}, _job({"run": "uv python install 3.12"}, {"run": "uv sync"})) == ["3.12"]
    assert interpreter_pins({}, _job({"run": "uv sync --python 3.12"})) == ["3.12"]


def test_a_matrix_expression_resolves_to_every_value_it_can_take() -> None:
    job = _job()
    job["strategy"]["matrix"]["python-version"] = ["3.11", "3.12"]
    job["strategy"]["matrix"]["include"] = [
        {"os": "ubuntu-latest", "python-version": "3.15"},  # never on macOS: skipped
        {"os": "macos-15-intel", "python-version": "3.13"},
    ]
    assert _resolve("${{ matrix.python-version }}", job) == ["3.11", "3.12", "3.13"]


def test_a_linux_only_job_and_a_stdlib_only_run_are_not_flagged() -> None:
    assert not can_run_on_macos(_job(runs_on="ubuntu-latest"))
    assert not installs_with_uv(_job({"run": "uv run --no-project python scripts/x.py"}))


def test_a_script_that_syncs_is_seen_through(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "build.sh").write_text("set -e\nuv sync --no-dev\n", encoding="utf-8")
    assert installs_with_uv(_job({"run": "./scripts/build.sh"}), root=tmp_path)
    assert not installs_with_uv(_job({"run": "./scripts/missing.sh"}), root=tmp_path)


@pytest.mark.parametrize("floating", ["3.x", ">=3.11", "3"])
def test_a_floating_pin_is_refused(floating: str) -> None:
    job = _job({**_SETUP_UV, "with": {"python-version": floating}}, {"run": "uv sync"})
    assert pin_problems({}, job) == [f"pins {floating!r}, which is not a concrete version"]


def test_a_matrix_pin_with_no_value_is_refused() -> None:
    job = _job({**_SETUP_UV, "with": {"python-version": "${{ matrix.python }}"}}, {"run": "uv sync"})
    assert pin_problems({}, job) == ["pins '${{ matrix.python }}', which the matrix gives no value"]
