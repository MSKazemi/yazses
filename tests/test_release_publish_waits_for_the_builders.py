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
import sys
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

# The step below runs on `ubuntu-latest`, and this harness executes its literal
# shell against stub programs it drops on PATH. That needs a POSIX shell that
# honours an extensionless executable file — which a Windows runner does not
# have, whatever `bash` resolves to there: the first run of these tests turned
# both Windows legs red with an empty stderr, because `bash` found the WSL stub.
#
# Gated on the platform rather than on probing for bash, because presence is not
# ability and a probe that half-works reports a finding about the workflow when
# what failed was the probe. The anchor below keeps this from quietly becoming a
# skip everywhere.
_POSIX = sys.platform != "win32"
_needs_posix = pytest.mark.skipif(
    not _POSIX, reason="executes the step's own /bin/sh script; the step runs on ubuntu-latest"
)


def test_the_shell_harness_is_not_skipped_on_the_platform_the_step_runs_on():
    if sys.platform.startswith(("linux", "darwin", "freebsd")):
        assert _POSIX, (
            "the execution tests below are the only ones that check what the "
            "wait DOES rather than what it says. A gate that skipped them here "
            "would leave the looping case untested on every runner."
        )


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


@_needs_posix
def test_it_stops_as_soon_as_every_run_has_completed(tmp_path):
    stdout, counter = _harness(tmp_path, 'echo completed; echo completed')
    assert "has finished" in stdout
    # Two workflows, one query each. A third call would mean it looped after
    # already having its answer.
    assert counter.read_text(encoding="utf-8").count("call") == 2, stdout


@_needs_posix
def test_a_tag_with_no_run_is_not_waited_on(tmp_path):
    stdout, counter = _harness(tmp_path, "true")
    assert "not waiting on it" in stdout
    assert counter.read_text(encoding="utf-8").count("call") == 2, stdout


@_needs_posix
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


@_needs_posix
@pytest.mark.parametrize("states", ["queued", "in_progress"])
def test_an_unfinished_state_is_never_read_as_finished(tmp_path, states):
    # Bounded by the loop, so this terminates; what matters is that it never
    # printed "has finished" for a run that was not.
    stdout, _ = _harness(tmp_path, f"echo {states}")
    assert "has finished" not in stdout, stdout


# --------------------------------------------------------------------------
# v2.44.0 and v2.45.0: the same two races, each cleared by one rerun both times
# --------------------------------------------------------------------------
#
# * Chocolatey: the asset wait passed on the .exe and .dmg, and render-chocolatey.py
#   fetched SHA256SUMS.txt 26 s before the checksums workflow uploaded it (HTTP 404).
# * Docker: the workflow's pip resolved the new version, and the pip INSIDE the build
#   container, two minutes later, still listed only the previous release.

DOCKERFILE = ROOT / "packaging" / "docker" / "Dockerfile"


def _asset_wait_run() -> str:
    return _step(PUBLISH, "wait-for-assets", "Wait for the release to carry")["run"]


def test_the_asset_wait_requires_the_checksums_file():
    run = _asset_wait_run()
    assert "SHA256SUMS.txt" in run, (
        "the Chocolatey job reads SHA256SUMS.txt from the release; the checksums "
        "workflow uploads it after the builds, so waiting for the binaries alone "
        "lets the job run first (v2.44.0, v2.45.0)"
    )


def _asset_wait(tmp_path: Path, listings: list[str]) -> tuple[subprocess.CompletedProcess, int]:
    """Run the asset wait with a `gh` that answers each call from *listings* in turn."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "n"
    state.write_text("0", encoding="utf-8")
    answers = tmp_path / "answers"
    answers.mkdir()
    for i, text in enumerate(listings):
        (answers / str(i)).write_text(text, encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        f'n=$(cat "{state}"); echo $((n + 1)) > "{state}"\n'
        f'last=$(( $(ls "{answers}" | wc -l) - 1 ))\n'
        f'(( n > last )) && n=$last\n'
        f'cat "{answers}/$n"\n',
        encoding="utf-8",
    )
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    slp = bin_dir / "sleep"
    slp.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    slp.chmod(slp.stat().st_mode | stat.S_IEXEC)
    script = tmp_path / "assets.sh"
    script.write_text(_asset_wait_run().replace("${{ steps.resolve.outputs.version }}", "9.9.9"),
                      encoding="utf-8")
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    out = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=60)
    return out, int(state.read_text(encoding="utf-8"))


_BINARIES = "YazSes-9.9.9-windows-x64.exe\nYazSes-9.9.9-macos-arm64.dmg\n"


@_needs_posix
def test_the_asset_wait_does_not_pass_on_the_binaries_alone(tmp_path):
    # Binaries on the first two listings, the checksums only on the third: passing
    # earlier is exactly the Chocolatey 404.
    out, calls = _asset_wait(tmp_path, [_BINARIES, _BINARIES, _BINARIES + "SHA256SUMS.txt\n"])
    assert out.returncode == 0, out.stderr
    assert calls == 3, (calls, out.stdout)


@_needs_posix
def test_the_asset_wait_passes_at_once_when_everything_is_there(tmp_path):
    out, calls = _asset_wait(tmp_path, [_BINARIES + "SHA256SUMS.txt\n"])
    assert out.returncode == 0, out.stderr
    assert calls == 1, (calls, out.stdout)


def _dockerfile_pip_run() -> str:
    """The Dockerfile's `RUN` that installs yazses, exactly as Docker hands it to sh."""
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("RUN ") and "pip install" in "\n".join(_run_block(lines, i)):
            return "\n".join(_run_block(lines, i))[len("RUN "):]
    raise AssertionError("no RUN instruction installs yazses in the Dockerfile")


def _run_block(lines: list[str], start: int) -> list[str]:
    block = [lines[start]]
    while block[-1].rstrip().endswith("\\") and start + len(block) < len(lines):
        block.append(lines[start + len(block)])
    return block


def _run_pip(tmp_path: Path, behaviour: str, version: str = "9.9.9") -> tuple[int, int, str]:
    """Run the install RUN under /bin/sh with a stub `pip`; return (exit, pip calls, stdout)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    calls.write_text("", encoding="utf-8")
    pip = bin_dir / "pip"
    pip.write_text(f"#!/bin/sh\necho x >> \"{calls}\"\n{behaviour}\n", encoding="utf-8")
    pip.chmod(pip.stat().st_mode | stat.S_IEXEC)
    slp = bin_dir / "sleep"
    slp.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    slp.chmod(slp.stat().st_mode | stat.S_IEXEC)
    body = _dockerfile_pip_run().replace("/tmp/pip-install.log", str(tmp_path / "pip.log"))
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", YAZSES_VERSION=version)
    out = subprocess.run(["/bin/sh", "-c", body], capture_output=True, text=True, env=env, timeout=60)
    return out.returncode, len(calls.read_text(encoding="utf-8").split()), out.stdout + out.stderr


_NOT_YET = (
    'n=$(wc -l < "{c}"); if [ "$n" -ge {ok} ]; then echo installed; exit 0; fi; '
    "echo 'ERROR: Could not find a version that satisfies the requirement yazses==9.9.9' >&2; "
    "echo 'ERROR: No matching distribution found for yazses==9.9.9' >&2; exit 1"
)


@_needs_posix
def test_the_docker_install_retries_until_the_new_version_resolves(tmp_path):
    behaviour = _NOT_YET.format(c=tmp_path / "calls", ok=3)
    code, calls, text = _run_pip(tmp_path, behaviour)
    assert code == 0, text
    assert calls == 3, (calls, text)


@_needs_posix
def test_the_docker_install_does_not_retry_a_real_build_failure(tmp_path):
    code, calls, text = _run_pip(
        tmp_path, "echo \"error: command 'gcc' failed with exit code 1\" >&2; exit 1"
    )
    assert code != 0, text
    assert calls == 1, f"a compile error was retried {calls}x: {text}"


@_needs_posix
def test_the_docker_install_gives_up_and_fails_if_the_version_never_appears(tmp_path):
    code, calls, text = _run_pip(tmp_path, _NOT_YET.format(c=tmp_path / "calls", ok=10**6))
    assert code != 0, text
    assert calls == 20, (calls, text)


@_needs_posix
def test_the_docker_install_without_a_version_still_installs_the_latest(tmp_path):
    code, calls, text = _run_pip(tmp_path, "echo \"$@\"; exit 0", version="")
    assert code == 0 and calls == 1, text
    assert "yazses[diarization]==" not in text
