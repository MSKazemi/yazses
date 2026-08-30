"""`require_git()` must name git's own complaint, and must not be satisfiable by a lie.

The guard it protects exists because of a real run: the advisory FreeBSD leg produced
twenty failures and four collection errors, every one of them phrased as a finding about
this repository -- files "tracked but not published", a helper "now referenced from []"
-- from a git that exited 128 before looking at anything. The cause appeared in none of
the twenty messages, because `capture_output=True` had captured it and `check=True`
discarded everything but the exit code.

So the property under test is not "require_git detects a broken git". It is "the failure
carries the sentence git printed", because that sentence is the entire difference between
a fifteen-minute diagnosis and a fifteen-hour one.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from tests import gitprobe


@pytest.fixture(autouse=True)
def _forget_the_probe():
    """The probe is `lru_cache`d -- it answers the same question for twenty callers in
    one session and must not pay for it twenty times. That cache is shared state, so it
    is cleared on both sides of every test here, or the first test to run would decide
    the result of the rest."""
    gitprobe._probe.cache_clear()
    yield
    gitprobe._probe.cache_clear()


def _break_git(
    monkeypatch: pytest.MonkeyPatch,
    directory: pathlib.Path,
    message: str,
    code: int,
) -> None:
    """Make `git` fail the way it failed on FreeBSD: exit *code*, print *message*.

    Two mechanisms, because Windows cannot run the good one.

    Everywhere else this writes an executable `git` first on PATH, which exercises the
    real chain -- PATH lookup, process start, exit status, stderr -- rather than the
    test's own double. That is what the first version of this file did on every
    platform, and it turned both Windows legs red: a `#!/bin/sh` file named `git` is
    not executable there, and `subprocess.run(["git", ...])` reaches `CreateProcess`,
    which appends `.exe` to an extensionless name and does not consult `PATHEXT` -- so
    a `git.cmd` shim is not found either. The stub was simply absent, the probe
    correctly reported "no git on PATH", and the assertion about git's *stderr* had
    nothing to assert against.

    So on Windows the failure is injected at `subprocess.run` instead. That covers
    less: it proves the message is built from what git said, not that the process
    machinery behaves as expected. The half it does cover is the half these tests are
    about, and the POSIX legs -- including the FreeBSD one this whole guard exists for
    -- still run the real thing.
    """
    if sys.platform != "win32":
        shim = directory / "git"
        body = "#!/bin/sh\n"
        if message:
            body += f"echo '{message}' >&2\n"
        body += f"exit {code}\n"
        shim.write_text(body, encoding="utf-8")
        shim.chmod(0o755)
        monkeypatch.setenv("PATH", str(directory))
        return

    real = subprocess.run

    def fake(cmd, *args, **kwargs):  # noqa: ANN001, ANN202 - mirrors subprocess.run
        if cmd and cmd[0] == "git":
            return subprocess.CompletedProcess(cmd, code, stdout="", stderr=message)
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(gitprobe.subprocess, "run", fake)


def test_a_working_git_is_not_reported_as_a_problem() -> None:
    """Without this the guard could be a `raise` and every assertion above it would
    still 'pass' in the sense of never being reached."""
    if shutil.which("git") is None:  # pragma: no cover - git is present in CI
        pytest.skip("no git on PATH, so the positive direction cannot be exercised")
    gitprobe.require_git()


def test_a_git_that_exits_nonzero_fails_and_quotes_what_git_said(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _break_git(monkeypatch, tmp_path, "fatal: detected dubious ownership in repository", 128)
    with pytest.raises(AssertionError) as caught:
        gitprobe.require_git()
    message = str(caught.value)
    assert "detected dubious ownership" in message, (
        f"the failure did not carry git's own words, which is the whole point: {message}"
    )
    assert "128" in message


def test_a_git_that_is_absent_is_named_as_absent(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The FreeBSD image shipped without git at all before this leg installed it, and
    that produced `FileNotFoundError` inside twenty unrelated guards. It is a different
    cause from a git that runs and refuses, so it gets a different sentence."""
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(AssertionError) as caught:
        gitprobe.require_git()
    assert "no `git` on PATH" in str(caught.value)


def test_a_silent_failure_still_produces_a_message(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A git that fails and prints nothing is the case where a naive implementation
    formats an empty string into its message and says nothing at all."""
    _break_git(monkeypatch, tmp_path, "", 129)
    with pytest.raises(AssertionError) as caught:
        gitprobe.require_git()
    assert "129" in str(caught.value)
    assert "<it printed nothing>" in str(caught.value)


def test_the_guarded_tests_fail_rather_than_skip_when_git_cannot_run(
    tmp_path: pathlib.Path,
) -> None:
    """A skip would be the tempting fix and is the wrong one.

    `test_no_private_path_is_tracked` is what stands between a private marketing tree
    and a public repository. If a broken git turned it into a skip, a run with no
    private-tier guard at all would report green -- which is the state where the guard
    is most needed and least present. So this asserts the *policy*, not just the
    plumbing: an environment problem must stop the build, not quietly reduce it.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # A child process cannot inherit a monkeypatched `subprocess.run`, so this one has
    # to break git through the environment. On Windows an executable stub is not
    # available (see `_break_git`), so git is made *absent* instead of *refusing* --
    # a different cause reaching the same code path, which is the right substitution
    # here because the property under test is what the guard does about a git that
    # cannot answer, not which way it failed to answer.
    expected = "no `git` on PATH"
    if sys.platform != "win32":
        shim = bindir / "git"
        shim.write_text("#!/bin/sh\necho 'fatal: not a git repository' >&2\nexit 128\n",
                        encoding="utf-8")
        shim.chmod(0o755)
        expected = "not a git repository"
    # PATH is the stub directory *plus* the interpreter's own, and nothing else: the
    # stub must shadow the real git, and the child must still be able to find python.
    child = _inherited_env()
    child["PATH"] = os.pathsep.join([str(bindir), str(pathlib.Path(sys.executable).parent)])
    child["HOME"] = str(tmp_path)
    done = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/test_private_tiers_stay_private.py::test_no_private_path_is_tracked",
            "-q", "--no-header", "-p", "no:cacheprovider",
        ],
        cwd=gitprobe.ROOT,
        capture_output=True,
        text=True,
        env=child,
        timeout=300,
    )
    assert done.returncode != 0, (
        "a broken git left the private-tier guard reporting success:\n" + done.stdout
    )
    assert "skipped" not in done.stdout.split("=")[-1], (
        "the private-tier guard skipped instead of failing:\n" + done.stdout
    )
    assert expected in done.stdout, (
        "the failure did not reach the caller naming why git could not answer:\n"
        + done.stdout
    )


def _inherited_env() -> dict[str, str]:
    """The few variables the child genuinely needs. Deliberately not `os.environ` --
    the point of the child is that its PATH is controlled, and copying the parent's
    environment wholesale is how a real git finds its way back in."""
    keep = (
        "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "TMPDIR", "VIRTUAL_ENV",
        "PYTHONPATH", "LANG", "COMSPEC", "PATHEXT", "USERPROFILE",
    )
    return {k: v for k, v in os.environ.items() if k in keep}
