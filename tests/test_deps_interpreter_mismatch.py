"""`features enable` can install into an interpreter the daemon never loads.

Found by running Meeting Mode on a real machine (#48): the daemon came from a
`uv tool` install and `yazses` on PATH came from a checkout, so
`yazses features enable meeting` installed sherpa-onnx into the second one. The
daemon then reported the feature as unavailable and told the user to run
`yazses features enable meeting` — the command they had just run.

The check must compare **environment prefixes**, not interpreter paths: a venv's
`python` is a symlink to a shared base, so two different virtualenvs resolve to
the same real path and a `/proc/PID/exe` comparison silently never fires.
"""

from __future__ import annotations

import os
import sys
import types

from yazses.system import deps


def _lifecycle(running: bool, pid: int | None):
    return types.SimpleNamespace(is_running=lambda: running, read_pid=lambda: pid)


def test_no_daemon_means_nothing_to_warn_about():
    assert deps.daemon_interpreter_differs(_lifecycle(False, None)) is None


def test_a_daemon_with_no_pid_is_not_guessed_at():
    assert deps.daemon_interpreter_differs(_lifecycle(True, None)) is None


def test_our_own_process_is_not_reported_as_different():
    """The common case — one install — must stay silent.

    Note this test reads the host: its `argv[0]` is however the suite happened to
    be launched. It passed for a year under `uv run python -m pytest` (absolute)
    and failed the first time the suite was run as `.venv/bin/python -m pytest`
    (relative) — the bug was in the product, but only one way of invoking pytest
    could see it. `test_a_relative_argv0_is_the_same_environment` below is the
    version that does not depend on that, and is the one to trust.
    """
    import os

    assert deps.daemon_interpreter_differs(_lifecycle(True, os.getpid())) is None


def test_an_unreadable_process_is_silent_rather_than_wrong():
    assert deps.daemon_interpreter_differs(_lifecycle(True, 999_999_999)) is None


def test_the_warning_names_both_interpreters(monkeypatch, capsys):
    """A warning that does not say which is which is not actionable."""
    monkeypatch.setattr(deps, "daemon_interpreter_differs",
                        lambda *a, **k: "/opt/other/bin/python")
    monkeypatch.setattr(deps, "install_command", lambda pkgs: ["true"])
    monkeypatch.setattr(deps, "install_blocked_reason", lambda pkgs: None)

    said: list[str] = []
    deps.install_packages(["sherpa-onnx"], echo=said.append)
    text = "\n".join(said)

    assert "/opt/other/bin/python" in text
    assert sys.executable in text
    assert "pip install sherpa-onnx" in text, "must give the command that fixes it"


# --- the environment prefix, decided on strings rather than on this host --------
#
# `_env_prefix` is pure over (argv0, cwd), which is what lets these cases be
# stated exactly instead of depending on how the suite was launched.


def _abs(*parts: str) -> str:
    """An absolute path spelled the way *this host* spells one.

    `_env_prefix` returns `os.path.normpath(os.path.abspath(...))`, so on Windows it
    answers `D:\\home\\u\\proj\\.venv` where POSIX answers `/home/u/proj/.venv`.
    Both are correct and neither equals a hardcoded POSIX literal, which is what kept
    the Windows leg of CI red while Linux and macOS stayed green. Building the expected
    value from the same primitives states the intent — *this directory, joined that way*
    — instead of one platform's rendering of it.
    """
    return os.path.normpath(os.path.join(os.path.abspath(os.sep), *parts))


def test_a_relative_argv0_is_the_same_environment():
    """The regression. `.venv/bin/python` from the repo root *is* this venv.

    `dirname(dirname(".venv/bin/python"))` is `.venv`, which cannot equal an
    absolute `sys.prefix`, so every daemon started by typing a relative path was
    reported as a different interpreter — and `features enable` then told the
    user to install into `.venv/bin/python`, a path that means something
    different in every directory and nothing in most.
    """
    proj = _abs("home", "u", "proj")
    assert deps._env_prefix(os.path.join(".venv", "bin", "python"), proj) == _abs(
        "home", "u", "proj", ".venv"
    )
    assert deps._env_prefix(os.path.join(".", "venv", "bin", "python"), proj) == _abs(
        "home", "u", "proj", "venv"
    )
    assert deps._env_prefix(os.path.join("..", "other", "bin", "python"), proj) == _abs(
        "home", "u", "other"
    )


def test_an_absolute_argv0_ignores_the_working_directory():
    assert deps._env_prefix(
        _abs("opt", "yz", "bin", "python"), _abs("anywhere")
    ) == _abs("opt", "yz")


def test_a_bare_name_on_path_says_nothing_about_an_environment():
    """`python3` resolved from PATH names no prefix; guessing one would warn wrongly."""
    assert deps._env_prefix("python3", "/home/u/proj") == ""


def test_two_venvs_on_one_base_interpreter_still_differ():
    """The property the original comment protects: no symlink resolution.

    A venv's `python` is a symlink to a shared base, so `realpath` would collapse
    these two to one path and the check would never fire — which is the bug this
    whole function was written for.
    """
    a = deps._env_prefix("/home/u/a/.venv/bin/python", "/")
    b = deps._env_prefix("/home/u/b/.venv/bin/python", "/")
    assert a != b


def test_a_relative_daemon_path_is_resolved_against_the_daemons_cwd(monkeypatch):
    """End to end through /proc, with the daemon in a *different* directory.

    Resolving against our own cwd would be a plausible-looking fix that is wrong
    whenever the daemon was started somewhere else — which is the normal case.
    """
    import os

    monkeypatch.setattr(
        deps.Path, "read_bytes", lambda self: b".venv/bin/python\0-m\0yazses\0"
    )
    monkeypatch.setattr(os, "readlink", lambda path: "/srv/elsewhere")
    other = deps.daemon_interpreter_differs(_lifecycle(True, 4242))
    assert other == ".venv/bin/python", (
        "a daemon in /srv/elsewhere is genuinely a different environment from "
        f"{sys.prefix} and must be reported"
    )
