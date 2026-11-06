"""`yazses doctor`'s "multiple yazses on PATH" row must count only runnable copies.

At 8a72bbc6 ``_yazses_paths_on_path`` accepted any ``Path.exists()`` hit, so:

* a *directory* named ``yazses`` under a PATH entry (a source checkout below ``.`` or
  ``~/src``) and a non-executable leftover file were each reported as an install, and
  doctor printed a false "multiple yazses on PATH" WARN; and
* a PATH entry whose ``stat`` raised ``PermissionError`` propagated out of
  ``run_doctor`` (the call is unguarded), taking the whole report down.

The real lookup ``shutil.which`` uses -- a regular file with the execute bit -- is the
contract these tests pin. Real files in ``tmp_path``; no host state is read.
"""

from __future__ import annotations

import os
import pathlib
import stat
import sys

import pytest

from yazses.system import doctor

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX execute bits; the diagnostic is Linux-only"
)


def _executable(path: pathlib.Path) -> pathlib.Path:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@posix_only
def test_a_directory_named_yazses_is_not_an_install(tmp_path, monkeypatch):
    real_bin = tmp_path / "bin"
    real_bin.mkdir()
    real = _executable(real_bin / "yazses")
    checkout_parent = tmp_path / "src"
    (checkout_parent / "yazses").mkdir(parents=True)  # a git clone, not a program
    monkeypatch.setenv("PATH", os.pathsep.join([str(checkout_parent), str(real_bin)]))

    assert doctor._yazses_paths_on_path() == [str(real.resolve())]


@posix_only
def test_a_non_executable_file_is_not_an_install(tmp_path, monkeypatch):
    real_bin = tmp_path / "bin"
    real_bin.mkdir()
    real = _executable(real_bin / "yazses")
    stale = tmp_path / "stale"
    stale.mkdir()
    leftover = stale / "yazses"
    leftover.write_text("not a program\n", encoding="utf-8")
    leftover.chmod(0o644)
    monkeypatch.setenv("PATH", os.pathsep.join([str(stale), str(real_bin)]))

    assert doctor._yazses_paths_on_path() == [str(real.resolve())]


@posix_only
def test_an_unreadable_path_entry_is_skipped_not_raised(tmp_path, monkeypatch):
    real_bin = tmp_path / "bin"
    real_bin.mkdir()
    real = _executable(real_bin / "yazses")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked_candidate = str(locked / "yazses")

    # Simulate EACCES deterministically (a real chmod 000 is bypassed under root).
    def _deny(original):
        def probe(self, *args, **kwargs):
            if str(self) == locked_candidate:
                raise PermissionError(13, "Permission denied", locked_candidate)
            return original(self, *args, **kwargs)
        return probe

    monkeypatch.setattr(pathlib.Path, "exists", _deny(pathlib.Path.exists))
    monkeypatch.setattr(pathlib.Path, "is_file", _deny(pathlib.Path.is_file))
    monkeypatch.setattr(pathlib.Path, "stat", _deny(pathlib.Path.stat))
    monkeypatch.setenv("PATH", os.pathsep.join([str(locked), str(real_bin)]))

    assert doctor._yazses_paths_on_path() == [str(real.resolve())]


@posix_only
def test_install_row_silent_when_only_one_copy_can_run(tmp_path, monkeypatch):
    real_bin = tmp_path / "bin"
    real_bin.mkdir()
    _executable(real_bin / "yazses")
    checkout_parent = tmp_path / "src"
    (checkout_parent / "yazses").mkdir(parents=True)
    monkeypatch.setenv("PATH", os.pathsep.join([str(checkout_parent), str(real_bin)]))
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    monkeypatch.setattr(doctor, "_systemd_execstart", lambda: None)

    rows = doctor._install_consistency_checks()

    assert not [r for r in rows if r[0] == "Install"], rows


@posix_only
def test_two_runnable_copies_still_warn(tmp_path, monkeypatch):
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    _executable(first / "yazses")
    _executable(second / "yazses")
    monkeypatch.setenv("PATH", os.pathsep.join([str(first), str(second)]))

    assert len(doctor._yazses_paths_on_path()) == 2
