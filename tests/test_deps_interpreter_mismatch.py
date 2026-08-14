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
    """The common case — one install — must stay silent."""
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
