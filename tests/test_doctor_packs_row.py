"""`yazses doctor`'s **Add-ons** row (ADR-028, owner answer to question 4).

The per-user uninstaller deletes the running user's ``packs\\`` folder; an all-users
uninstall runs as the administrator and cannot reach the users' folders. So doctor names
``yazses packs remove --all`` and what it frees in exactly two cases — add-ons this copy
never loads, and an all-users install while this user has add-ons — and says nothing
otherwise. Everything is faked: a pack tree in ``tmp_path``, a fake launcher, no Windows.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from tests.packs_fixtures import FakeRuntime, base, build_pack
from yazses.packs.context import PackContext
from yazses.packs.layout import PackLayout
from yazses.packs.manage import DiskUse, disk_use
from yazses.packs.policy import Capability
from yazses.system import doctor
from yazses.system.doctor import packs_row

THIS = "b-" + "a" * 12
OTHER = "b-" + "b" * 12


def _write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _ctx(data: Path, *, index: bool = True) -> PackContext:
    pack = build_pack(data.parent / "src" / "p.yazpack")
    return PackContext(
        runtime=FakeRuntime(), layout=PackLayout.under(data), frozen=index,
        capability=Capability(True),
        index=pack.index() if index else None, base=base() if index else None,
    )


# ---- the pure row ---------------------------------------------------------------------

def test_no_add_ons_and_a_per_user_install_is_no_row() -> None:
    assert packs_row(DiskUse(0, 0, 0), "user") is None
    assert packs_row(DiskUse(None, 0, 0), "unknown") is None


def test_this_builds_add_ons_alone_on_a_per_user_install_is_no_row() -> None:
    """The per-user uninstaller removes them; nothing to say."""
    assert packs_row(DiskUse(45_000_000, 0, 0), "user") is None


def test_another_builds_add_ons_warn_and_name_remove_all_with_the_size() -> None:
    row = packs_row(DiskUse(0, 45_000_000, 0), "user")
    assert row is not None
    label, status, detail = row
    assert (label, status) == ("Add-ons", "WARN")
    assert "45 MB of add-ons are not used by this copy" in detail
    assert "yazses packs remove --all" in detail and "frees 45 MB" in detail
    assert "reinstall" not in detail, "nothing of this build's is removed, so no reinstall"


def test_when_this_build_has_add_ons_too_the_row_says_remove_all_takes_them() -> None:
    _, _, detail = packs_row(DiskUse(20_000_000, 45_000_000, 0), "user")
    assert "frees 65 MB" in detail
    assert "including this build's 20 MB" in detail
    assert "yazses packs install <name>" in detail


def test_unfinished_install_leftovers_count_as_unused() -> None:
    row = packs_row(DiskUse(0, 0, 3_000_000), "user")
    assert row is not None and row[1] == "WARN" and "3.0 MB" in row[2]


def test_an_unknown_build_never_calls_anything_unused() -> None:
    """A source checkout shares the data folder with the frozen app: it cannot tell which
    build is current, so it must not tell anyone to delete the app's add-ons."""
    assert packs_row(DiskUse(None, 45_000_000, 3_000_000), "user") is None


def test_an_all_users_install_with_add_ons_names_the_command_before_uninstalling() -> None:
    row = packs_row(DiskUse(45_000_000, 0, 0), "machine")
    assert row is not None
    label, status, detail = row
    assert (label, status) == ("Add-ons", "OK"), "a statement, not a problem"
    assert "installed for all users" in detail
    assert "cannot remove your add-ons" in detail
    assert "yazses packs remove --all" in detail and "frees 45 MB for you" in detail


def test_an_all_users_install_without_add_ons_is_no_row() -> None:
    assert packs_row(DiskUse(0, 0, 0), "machine") is None


def test_both_facts_share_one_row_and_warn() -> None:
    _, status, detail = packs_row(DiskUse(20_000_000, 45_000_000, 0), "machine")
    assert status == "WARN"
    assert "not used by this copy" in detail and "installed for all users" in detail


# ---- measuring the folder -------------------------------------------------------------

def test_disk_use_splits_this_build_other_builds_and_leftovers(tmp_path) -> None:
    data = tmp_path / "data"
    root = data / "packs"
    _write(root / THIS / "parakeet" / "a.bin", 1000)
    _write(root / OTHER / "parakeet" / "a.bin", 300)
    _write(root / OTHER / "diarization" / "deep" / "b.bin", 200)
    _write(root / "staging" / "parakeet.x" / "c.bin", 40)
    _write(root / "downloads" / "p.yazpack.part", 7)
    _write(root / "state.json", 5)
    _write(root / "unrelated" / "d.bin", 999)
    use = disk_use(_ctx(data))
    assert use == DiskUse(1000, 500, 47)
    assert use.total == 1547 and use.unused == 547


def test_disk_use_without_an_index_knows_no_current_build(tmp_path) -> None:
    data = tmp_path / "data"
    _write(data / "packs" / THIS / "parakeet" / "a.bin", 1000)
    use = disk_use(_ctx(data, index=False))
    assert use.this_build is None and use.other_builds == 1000 and use.unused == 0


def test_disk_use_of_a_missing_folder_is_zero(tmp_path) -> None:
    assert disk_use(_ctx(tmp_path / "data")) == DiskUse(0, 0, 0)


# ---- the gathering half ---------------------------------------------------------------

@pytest.fixture
def gathered(monkeypatch, tmp_path):
    data = tmp_path / "data"
    monkeypatch.setattr("yazses.platform.factory.get_pack_paths",
                        lambda: types.SimpleNamespace(data_dir=data))
    ctx = _ctx(data)
    monkeypatch.setattr("yazses.packs.context.load_context", lambda **k: ctx)
    return data


def _platform(scope: str | Exception | None):
    if scope is None:
        return types.SimpleNamespace(update_launcher=None)

    def install_scope():
        if isinstance(scope, Exception):
            raise scope
        return scope

    return types.SimpleNamespace(
        update_launcher=types.SimpleNamespace(install_scope=install_scope))


def test_no_pack_folder_is_no_row_and_no_context_is_loaded(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("yazses.platform.factory.get_pack_paths",
                        lambda: types.SimpleNamespace(data_dir=tmp_path / "none"))

    def boom(**_k):
        raise AssertionError("load_context ran with no pack folder")

    monkeypatch.setattr("yazses.packs.context.load_context", boom)
    assert doctor._packs_check(_platform("machine")) is None


def test_the_check_reads_the_scope_from_the_update_launcher(gathered) -> None:
    _write(gathered / "packs" / THIS / "parakeet" / "a.bin", 2_000_000)
    row = doctor._packs_check(_platform("machine"))
    assert row is not None and "installed for all users" in row[2]
    assert doctor._packs_check(_platform("user")) is None


def test_a_failing_launcher_only_drops_the_all_users_sentence(gathered) -> None:
    _write(gathered / "packs" / OTHER / "parakeet" / "a.bin", 2_000_000)
    row = doctor._packs_check(_platform(OSError("registry")))
    assert row is not None and row[1] == "WARN"
    assert "installed for all users" not in row[2]
    assert doctor._packs_check(_platform(None)) == row


def test_a_fault_while_gathering_never_takes_doctor_down(monkeypatch, gathered) -> None:
    (gathered / "packs").mkdir(parents=True)

    def boom(**_k):
        raise RuntimeError("nope")

    monkeypatch.setattr("yazses.packs.context.load_context", boom)
    assert doctor._packs_check(_platform("machine")) is None


def test_run_doctor_prints_the_row(sandbox_paths, monkeypatch, capsys) -> None:
    """Wired into the real report, not only defined."""
    row = ("Add-ons", "WARN", "45 MB of add-ons are not used by this copy")
    monkeypatch.setattr(doctor, "_packs_check", lambda platform: row)
    try:
        doctor.run_doctor(check_mic=False)
    except SystemExit:
        pass
    assert "Add-ons" in capsys.readouterr().out
