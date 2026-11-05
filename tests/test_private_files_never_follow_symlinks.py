"""``system/private_files`` must never change a mode, or write, *through* a symlink.

Before, the helpers opened by path without ``O_NOFOLLOW`` and chmod-ed by path. A symlink
``d/live.jsonl -> /some/0644/file`` was written through and the **target** became ``0600``;
``private_dir`` on a symlinked directory chmod-ed the directory it pointed at. The mode
change is now made with ``fchmod`` on the descriptor that was opened with ``O_NOFOLLOW``.

Policy, as documented in the module:

* a symlinked *file*: the write functions raise ``OSError`` (``ELOOP``) and touch nothing;
  ``ensure_private_file`` (best effort) leaves it alone;
* a symlinked *directory*: used as it is, target mode untouched;
* Windows: unchanged, no-op / plain ``Path`` calls.
"""
from __future__ import annotations

import errno
import os
import stat
import sys
from pathlib import Path

import pytest

from yazses.system import private_files as pf

posix_only = pytest.mark.skipif(
    sys.platform == "win32" or os.name != "posix",
    reason="POSIX permission bits and symlinks",
)


def _mode(p: Path) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


@pytest.fixture(params=[0o022, 0o000], ids=["umask022", "umask000"])
def umask(request):
    old = os.umask(request.param)
    try:
        yield request.param
    finally:
        os.umask(old)


def _loose_target(tmp_path: Path, mode: int = 0o644) -> Path:
    target = tmp_path / "elsewhere" / "victim.txt"
    target.parent.mkdir()
    target.write_text("original", encoding="utf-8")
    os.chmod(target, mode)
    return target


@posix_only
@pytest.mark.parametrize("writer", ["text", "append", "bytes"])
def test_a_symlinked_file_is_not_written_through_or_chmodded(tmp_path, umask, writer):
    target = _loose_target(tmp_path)
    d = pf.private_dir(tmp_path / "store")
    link = d / "live.jsonl"
    link.symlink_to(target)

    with pytest.raises(OSError) as info:
        if writer == "text":
            pf.write_private_text(link, "attacker-chosen\n")
        elif writer == "append":
            pf.write_private_text(link, "attacker-chosen\n", append=True)
        else:
            pf.write_private_bytes(link, b"attacker-chosen\n")
    assert info.value.errno == errno.ELOOP

    assert target.read_text(encoding="utf-8") == "original"
    assert _mode(target) == 0o644, "the link's target must keep its mode"


@posix_only
def test_a_dangling_symlink_does_not_create_its_target(tmp_path, umask):
    d = pf.private_dir(tmp_path / "store")
    link = d / "live.jsonl"
    ghost = tmp_path / "elsewhere" / "ghost.txt"
    ghost.parent.mkdir()
    link.symlink_to(ghost)
    with pytest.raises(OSError):
        pf.write_private_text(link, "x")
    assert not ghost.exists()


@posix_only
def test_ensure_private_file_leaves_a_symlink_and_its_target_alone(tmp_path, umask):
    target = _loose_target(tmp_path)
    link = tmp_path / "daemon.log"
    link.symlink_to(target)
    pf.ensure_private_file(link)  # best effort: must not raise
    assert _mode(target) == 0o644
    assert target.read_text(encoding="utf-8") == "original"


@posix_only
def test_ensure_private_file_does_not_create_through_a_dangling_symlink(tmp_path, umask):
    ghost = tmp_path / "ghost.txt"
    link = tmp_path / "daemon.log"
    link.symlink_to(ghost)
    pf.ensure_private_file(link)
    assert not ghost.exists()


@posix_only
def test_private_dir_on_a_symlinked_directory_does_not_chmod_the_target(tmp_path, umask):
    target = tmp_path / "bigdisk" / "yazses-data"
    target.mkdir(parents=True)
    os.chmod(target, 0o755)
    link = tmp_path / "data"
    link.symlink_to(target, target_is_directory=True)

    result = pf.private_dir(link)

    assert result == link
    assert _mode(target) == 0o755, "private_dir chmod-ed the directory the link points at"
    # ... and it is still usable as a directory: files written inside land in the target.
    pf.write_private_text(link / "a.txt", "hi")
    assert (target / "a.txt").read_text(encoding="utf-8") == "hi"
    assert _mode(target / "a.txt") == 0o600


@posix_only
def test_a_symlinked_parent_directory_is_not_chmodded_by_a_write(tmp_path, umask):
    target = tmp_path / "bigdisk"
    target.mkdir()
    os.chmod(target, 0o755)
    link = tmp_path / "data"
    link.symlink_to(target, target_is_directory=True)
    pf.write_private_bytes(link / "blob", b"\x00\x01")
    assert _mode(target) == 0o755
    assert _mode(target / "blob") == 0o600


@posix_only
def test_a_dangling_directory_symlink_still_raises_like_mkdir(tmp_path):
    link = tmp_path / "data"
    link.symlink_to(tmp_path / "nowhere", target_is_directory=True)
    with pytest.raises(FileExistsError):
        pf.private_dir(link)


@posix_only
def test_normal_paths_are_unchanged(tmp_path, umask):
    """The contract other modules rely on, spelled out once more here."""
    d = pf.private_dir(tmp_path / "a" / "store")
    assert _mode(d) == 0o700

    f = d / "x.bin"
    f.write_bytes(b"old")
    os.chmod(f, 0o666)
    pf.write_private_bytes(f, b"new")
    assert f.read_bytes() == b"new" and _mode(f) == 0o600

    t = d / "t.txt"
    pf.write_private_text(t, "one\n")
    pf.write_private_text(t, "two\n", append=True)
    assert t.read_text(encoding="utf-8") == "one\ntwo\n" and _mode(t) == 0o600

    pf.write_private_text(t, "fresh\n")
    assert t.read_text(encoding="utf-8") == "fresh\n"

    e = d / "e.db"
    pf.ensure_private_file(e)
    assert e.exists() and e.read_bytes() == b"" and _mode(e) == 0o600
    os.chmod(e, 0o644)
    pf.ensure_private_file(e)
    assert _mode(e) == 0o600

    os.chmod(d, 0o755)
    pf.write_private_text(t, "again\n")
    assert _mode(d) == 0o700, "the containing directory is still tightened"
    assert pf.private_dir(d) == d and _mode(d) == 0o700


@posix_only
def test_a_stricter_file_is_never_widened(tmp_path, umask):
    f = tmp_path / "strict"
    f.write_text("x", encoding="utf-8")
    os.chmod(f, 0o400)
    pf.ensure_private_file(f)
    assert _mode(f) == 0o400


@posix_only
def test_the_fallback_without_o_nofollow_still_refuses_a_symlink(tmp_path, monkeypatch):
    """A platform lacking O_NOFOLLOW has only the path check; it must still hold for chmod."""
    monkeypatch.setattr(pf, "_O_NOFOLLOW", 0)
    target = tmp_path / "bigdisk"
    target.mkdir()
    os.chmod(target, 0o755)
    link = tmp_path / "data"
    link.symlink_to(target, target_is_directory=True)
    pf.private_dir(link)
    assert _mode(target) == 0o755


def test_windows_branch_is_still_a_no_op(tmp_path, monkeypatch):
    """Off POSIX nothing is opened with O_NOFOLLOW, chmod-ed, or created by ensure_*."""
    monkeypatch.setattr(pf, "_posix", lambda: False)

    def boom(*_a, **_k):
        raise AssertionError("the Windows branch must not touch modes or descriptors")

    monkeypatch.setattr(os, "chmod", boom)
    monkeypatch.setattr(os, "open", boom)
    if hasattr(os, "fchmod"):
        monkeypatch.setattr(os, "fchmod", boom)

    d = pf.private_dir(tmp_path / "s")
    assert d.is_dir()
    pf.write_private_text(d / "a.txt", "one\n")
    pf.write_private_text(d / "a.txt", "two\n", append=True)
    pf.write_private_bytes(d / "b.bin", b"\x01")
    pf.ensure_private_file(d / "c.db")
    assert (d / "a.txt").read_text(encoding="utf-8") == "one\ntwo\n"
    assert (d / "b.bin").read_bytes() == b"\x01"
    assert not (d / "c.db").exists(), "ensure_private_file is a no-op off POSIX"
