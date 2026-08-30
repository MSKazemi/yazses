"""The two ordering guards that decide whether a tag actually ships everywhere.

Both were found by cutting v2.36.0, and both had the same shape: a wait that
looked correct, passed, and was followed within a minute by the thing it was
supposed to make safe.

* `docker.yml` polled the PEP 503 simple index with `curl`, printed "the index
  pip reads serves yazses 2.36.0", and the build failed FIFTEEN SECONDS later
  listing 2.35.0 as newest -- because a bare curl gets the HTML representation
  and pip asks for the PEP 691 JSON one, which is cached separately. That is the
  v2.24.0 failure (metadata API leads the simple index) recurring one layer down,
  so the fix is to stop approximating pip and run it.

* `publish-channels.yml` waited for two filenames and then published. The
  manifest generator also uses the arm64 Windows .exe when present and treats it
  as optional, because that leg is `continue-on-error` -- so "not built" and "not
  uploaded yet" are indistinguishable from inside the wait, and the slowest leg
  in the release lost every time.

These tests read the workflows rather than the release history, because the
release history only shows the failure on the tags where the race was lost.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCKER = ROOT / ".github" / "workflows" / "docker.yml"
PUBLISH = ROOT / ".github" / "workflows" / "publish-channels.yml"


def _steps(path: Path, job: str) -> list[dict]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc["jobs"][job]["steps"]


def _step(path: Path, job: str, prefix: str) -> dict:
    for step in _steps(path, job):
        if str(step.get("name", "")).startswith(prefix):
            return step
    raise AssertionError(f"{path.name}: no step in `{job}` named {prefix!r}")


def _index(path: Path, job: str, prefix: str) -> int:
    for i, step in enumerate(_steps(path, job)):
        if str(step.get("name", "")).startswith(prefix):
            return i
    raise AssertionError(f"{path.name}: no step in `{job}` named {prefix!r}")


# --------------------------------------------------------------------------
# docker.yml — ask pip, because pip is what fails
# --------------------------------------------------------------------------


def test_the_pypi_wait_runs_pip_rather_than_approximating_it():
    run = _step(DOCKER, "build", "Wait for PyPI")["run"]
    assert "pip download" in run, (
        "the wait must resolve the version with pip itself. Every check that is "
        "merely near pip -- the JSON metadata API (v2.24.0), the HTML simple "
        "index (v2.36.0) -- has been right while pip was wrong."
    )
    assert "pypi.org/simple" not in run, (
        "reading the simple index directly is the check that failed on v2.36.0: "
        "curl gets the HTML representation, pip asks for the PEP 691 JSON one, "
        "and the two are cached separately."
    )


def test_the_pypi_wait_proves_pip_exists_before_trusting_its_answer():
    run = _step(DOCKER, "build", "Wait for PyPI")["run"]
    assert "pip --version" in run, (
        "a runner without pip fails to resolve exactly like an unpublished "
        "release, which would block every build for a reason the log does not "
        "name. Prove pip exists first, with its own error."
    )
    assert run.index("pip --version") < run.index("pip download"), (
        "the pip-presence check has to come before the resolution loop, or the "
        "loop spends 20 minutes discovering it."
    )


def test_the_pypi_wait_does_not_let_pip_cache_a_negative():
    run = _step(DOCKER, "build", "Wait for PyPI")["run"]
    assert "--no-cache-dir" in run, (
        "pip caches index responses; without this, the first attempt's 'no such "
        "version' can be re-served for the rest of the loop and the wait never "
        "sees the release that has since published."
    )


def test_the_pypi_wait_still_runs_before_the_build():
    wait = _index(DOCKER, "build", "Wait for PyPI")
    build = _index(DOCKER, "build", "Build and push")
    assert wait < build


# --------------------------------------------------------------------------
# publish-channels.yml — wait for the producers, not for two filenames
# --------------------------------------------------------------------------


def test_the_publish_waits_for_the_producing_workflows():
    run = _step(PUBLISH, "wait-for-assets", "Wait for the artifact-producing")["run"]
    for workflow in ("build-windows.yml", "build-macos.yml"):
        assert workflow in run, f"{workflow} produces release assets and is not waited on"


def test_the_producer_wait_comes_before_the_asset_check():
    producers = _index(PUBLISH, "wait-for-assets", "Wait for the artifact-producing")
    assets = _index(PUBLISH, "wait-for-assets", "Wait for the release to carry")
    assert producers < assets, (
        "waiting for the builders after checking the assets would leave the "
        "optional arm64 .exe exactly as raced as before."
    )


def test_the_producer_wait_does_not_require_the_builders_to_succeed():
    run = _step(PUBLISH, "wait-for-assets", "Wait for the artifact-producing")["run"]
    assert "conclusion" not in run, (
        "the arm64 leg is continue-on-error. Requiring success would make a "
        "failed optional leg block the channels that never needed it -- the "
        "generator's fallback exists precisely for that case."
    )


# --------------------------------------------------------------------------
# ...and the shell actually behaves, driven against a stub `gh`
# --------------------------------------------------------------------------


def _harness(tmp_path: Path, gh_body: str) -> tuple[str, Path]:
    """Run the producer-wait shell with a stubbed `gh` and an instant `sleep`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    counter = tmp_path / "calls"
    counter.write_text("", encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        f'echo call >> "{counter}"\n'
        f"{gh_body}\n",
        encoding="utf-8",
    )
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    # `sleep` is stubbed so a loop that genuinely waits costs nothing here; a
    # real sleep would make the looping case untestable and it would go untested.
    slp = bin_dir / "sleep"
    slp.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    slp.chmod(slp.stat().st_mode | stat.S_IEXEC)

    script = tmp_path / "wait.sh"
    script.write_text(
        _step(PUBLISH, "wait-for-assets", "Wait for the artifact-producing")["run"],
        encoding="utf-8",
    )
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", TAG="v9.9.9")
    out = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env=env, timeout=60
    )
    assert out.returncode == 0, out.stderr
    return out.stdout, counter


def test_it_stops_as_soon_as_every_run_has_completed(tmp_path):
    stdout, counter = _harness(tmp_path, 'echo completed; echo completed')
    assert "has finished" in stdout
    # Two workflows, one query each. A third call would mean it looped after
    # already having its answer.
    assert counter.read_text(encoding="utf-8").count("call") == 2, stdout


def test_a_tag_with_no_run_is_not_waited_on(tmp_path):
    stdout, counter = _harness(tmp_path, "true")
    assert "not waiting on it" in stdout
    assert counter.read_text(encoding="utf-8").count("call") == 2, stdout


def test_it_keeps_waiting_while_any_run_is_unfinished(tmp_path):
    # in_progress on the first query for each workflow, completed thereafter.
    body = (
        'n=$(grep -c call "%s" 2>/dev/null || echo 0)\n'
        "if [ \"$n\" -le 1 ] || [ \"$n\" -eq 3 ]; then echo in_progress; "
        "else echo completed; fi"
    ) % (tmp_path / "calls")
    stdout, counter = _harness(tmp_path, body)
    assert "still running" in stdout, stdout
    assert "has finished" in stdout, stdout
    assert counter.read_text(encoding="utf-8").count("call") > 2, stdout


@pytest.mark.parametrize("states", ["queued", "in_progress"])
def test_an_unfinished_state_is_never_read_as_finished(tmp_path, states):
    # Bounded by the loop, so this terminates; what matters is that it never
    # printed "has finished" for a run that was not.
    stdout, _ = _harness(tmp_path, f"echo {states}")
    assert "has finished" not in stdout, stdout
