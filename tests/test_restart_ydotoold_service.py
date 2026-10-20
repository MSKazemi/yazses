"""The heal step: it must never report a repair that did not happen."""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yazses.inject import auto


def _cp(rc=0, err=""):
    return SimpleNamespace(returncode=rc, stderr=err, stdout="")


def test_no_systemctl_means_no_heal_available(monkeypatch):
    monkeypatch.setattr(auto.shutil, "which", lambda n: None)
    assert auto.restart_ydotoold_service() is None


def test_no_such_unit_means_no_heal_available(monkeypatch):
    monkeypatch.setattr(auto.shutil, "which", lambda n: "/usr/bin/systemctl")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _cp(rc=1))
    assert auto.restart_ydotoold_service() is None


def test_restart_that_brings_the_socket_back_reports_what_it_did(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(auto.shutil, "which", lambda n: "/usr/bin/systemctl")
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: calls.append(argv) or _cp())
    monkeypatch.setattr(auto, "find_ydotool_socket", lambda: "/tmp/.ydotool_socket")
    assert "restarted" in (auto.restart_ydotoold_service() or "")
    assert ["/usr/bin/systemctl", "--user", "restart", "ydotoold.service"] in calls


def test_a_failed_restart_raises_instead_of_claiming_success(monkeypatch):
    monkeypatch.setattr(auto.shutil, "which", lambda n: "/usr/bin/systemctl")
    answers = iter([_cp(), _cp(rc=1, err="Unit ydotoold.service is masked")])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: next(answers))
    with pytest.raises(RuntimeError, match="masked"):
        auto.restart_ydotoold_service()


def test_a_socket_that_never_returns_raises(monkeypatch):
    monkeypatch.setattr(auto.shutil, "which", lambda n: "/usr/bin/systemctl")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _cp())
    monkeypatch.setattr(auto, "find_ydotool_socket", lambda: None)
    with pytest.raises(RuntimeError, match="socket did not come back"):
        auto.restart_ydotoold_service(timeout=0.3)
