"""The suite's own pytest configuration does what `pyproject.toml` says it does.

Three properties, each of which can break without a single test going red:

* **A hang is a failure.** A Windows leg once printed one test name and then nothing for
  2 h 30 m, because the test reached a real `MessageBoxW` that waits for a click. A hang
  produces no result at all, not a red one. `timeout` in `[tool.pytest.ini_options]`
  is what stops that, and it only works if pytest-timeout is loaded *and* the method
  it picks actually interrupts a blocked test on this OS. So the last test here runs a
  real hang in a child pytest and checks that it comes back as a failure.
* **Strictness is on.** A misspelt marker or an unknown config key is otherwise
  silently ignored -- `@pytest.mark.quarantined` would leave a test unquarantined with
  no error at all.
* **Every required plugin is installed everywhere the suite runs.** The FreeBSD leg
  installs test dependencies by name rather than from the `dev` group, so a plugin
  added to `required_plugins` but not to that leg's `pip install` stops its run at
  startup.
"""

from __future__ import annotations

import pathlib
import re
import signal
import subprocess
import sys
import textwrap
import time
import tomllib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _ini() -> dict:
    return _pyproject()["tool"]["pytest"]["ini_options"]


def _dist_name(requirement: str) -> str:
    return re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].strip().lower()


def test_the_strict_flags_are_on() -> None:
    ini = _ini()
    assert "--strict-markers" in ini["addopts"]
    assert "--strict-config" in ini["addopts"]
    assert ini["xfail_strict"] is True


def test_the_running_session_has_the_timeout_armed(request: pytest.FixtureRequest) -> None:
    """Read from the live config, not just the file: a `-p no:timeout` in someone's
    environment, or a plugin that failed to load, would leave the file correct and the
    run unprotected."""
    assert request.config.pluginmanager.hasplugin("timeout"), "pytest-timeout is not loaded"
    configured = float(_ini()["timeout"])
    assert configured > 0
    # `--timeout` on the command line legitimately overrides the file; zero disables it.
    live = request.config.getoption("timeout", default=None)
    live = configured if live is None else float(live)
    assert live > 0, "the per-test timeout is disabled for this run"


def test_every_required_plugin_is_a_declared_dev_dependency() -> None:
    required = {_dist_name(r) for r in _ini()["required_plugins"]}
    dev = {_dist_name(r) for r in _pyproject()["dependency-groups"]["dev"]}
    missing = sorted(required - dev)
    assert not missing, (
        f"{missing} are in required_plugins but not in the `dev` group, so a plain "
        "`uv sync` cannot start the suite."
    )


def test_every_required_plugin_is_installed_on_the_freebsd_leg() -> None:
    # Imported here, not at the top: that module scans every test file when it is
    # imported, and nothing else in this file needs it.
    from tests.test_freebsd_job_can_import_the_suite import _freebsd_scripts, _required_packages

    required = {_dist_name(r) for r in _ini()["required_plugins"]}
    installed = _required_packages(*_freebsd_scripts())
    missing = sorted(required - installed)
    assert not missing, (
        f"{missing} are in required_plugins but the freebsd job in test.yml does not "
        "install them, so pytest stops there at startup with 'Missing required "
        "plugins'. Add them to its `python -m pip install` line."
    )


#: (extra pytest args, text the output must contain, whether the run goes on to the next
#: test). The suite runs serially for contributors and with `-n auto` in CI, and
#: pytest-timeout picks SIGALRM on POSIX and a watchdog thread on Windows, so all four
#: combinations reach a real run somewhere. The thread method cannot interrupt the hung
#: thread, so it dumps every stack and exits the process. Serially, that ends the whole
#: run at the hang. Under xdist it ends one worker, which xdist reports as a crash
#: naming the test and replaces, and the run carries on, but the stack dump is lost
#: with the worker.
_HANG_RUNS = {
    "serial-signal": ([], "Timeout", True),
    "serial-thread": (["--timeout-method", "thread"], "Timeout", False),
    "xdist-signal": (["-n", "2"], "Timeout", True),
    "xdist-thread": (["-n", "2", "--timeout-method", "thread"], "crashed while running", True),
}


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    "extra, expected, carries_on", list(_HANG_RUNS.values()), ids=list(_HANG_RUNS)
)
def test_a_hung_test_comes_back_as_a_failure(
    tmp_path: pathlib.Path, extra: list[str], expected: str, carries_on: bool
) -> None:
    """Run a test that blocks for a minute under this repository's config, with the
    ceiling lowered to two seconds, and check that pytest-timeout ends it.

    The child pytest is given this repository's `pyproject.toml` with `-c`, so it runs
    the same `addopts`, `required_plugins` and timeout method the suite does. Only the
    number is overridden. The hang is a blocking wait rather than a busy loop, because
    the incident this guards against was a blocking call. A second, passing test shows
    whether the run carries on after the hang is ended.
    """
    if extra[:1] == ["-n"]:
        pytest.importorskip("xdist")
    if "thread" not in extra and not hasattr(signal, "SIGALRM"):
        # Windows: the default method there is already the thread one, covered above.
        pytest.skip("the signal method needs SIGALRM, which this OS does not have")
    hang_seconds = 60
    (tmp_path / "test_hang.py").write_text(
        textwrap.dedent(
            f"""
            import threading

            def test_blocks():
                threading.Event().wait({hang_seconds})

            def test_after_the_hang():
                pass
            """
        ),
        encoding="utf-8",
    )
    started = time.monotonic()
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "-c", str(PYPROJECT),
            "--rootdir", str(tmp_path),
            "-p", "no:cacheprovider",
            "--timeout", "2",
            *extra,
            str(tmp_path / "test_hang.py"),
        ],
        capture_output=True,
        text=True,
        timeout=hang_seconds + 30,
        cwd=tmp_path,
    )
    elapsed = time.monotonic() - started
    output = result.stdout + result.stderr
    assert result.returncode != 0, f"the hung test passed:\n{output}"
    assert expected in output, f"the run failed, but not on the timeout:\n{output}"
    if carries_on:
        assert "1 failed, 1 passed" in output, f"the run stopped at the hang:\n{output}"
    assert elapsed < hang_seconds, (
        f"the child took {elapsed:.0f}s, so the hang ran to completion instead of being "
        f"interrupted:\n{output}"
    )
