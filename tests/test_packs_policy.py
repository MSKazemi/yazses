"""ADR-028 §4a-§6 numbers and choices: disk space, deadline, size ceiling, capability,
garbage collection with rollback, and quarantine versus stale."""
from __future__ import annotations

import pytest

from yazses.packs.manifest import IndexEntry
from yazses.packs.policy import (
    BASE_DEADLINE_S,
    PACK_INSTALL_METHODS,
    PACK_MAX_BYTES,
    capability,
    deadline_s,
    disk_problem,
    disposition,
    gc_plan,
    max_download_bytes,
    required_free_bytes,
    size_problem,
)


def _entry(size: int = 1_000_000, unpacked: int = 3_000_000) -> IndexEntry:
    return IndexEntry("parakeet", "a", "c" * 64, size, unpacked, 1, ("stt-parakeet",))


def test_disk_space_is_archive_plus_tree_plus_ten_percent() -> None:
    entry = _entry(1_000_000, 3_000_000)
    assert required_free_bytes(entry) == 4_400_000
    assert disk_problem(entry, 4_400_000) is None
    problem = disk_problem(entry, 4_399_999)
    assert problem and "4.4 MB free" in problem
    assert disk_problem(entry, None) is None, "unknown free space is not a refusal"


def test_the_deadline_grows_with_size_but_never_below_the_installer_one() -> None:
    from yazses.system.installer_update import DOWNLOAD_DEADLINE_S

    assert BASE_DEADLINE_S == DOWNLOAD_DEADLINE_S
    assert deadline_s(1_000) == BASE_DEADLINE_S
    assert deadline_s(220_000_000) == 220_000_000 / 50_000


def test_the_size_ceiling_is_under_githubs_two_gib_and_is_enforced() -> None:
    assert PACK_MAX_BYTES < 2 * (1 << 30)
    assert size_problem(_entry(PACK_MAX_BYTES)) is None
    assert size_problem(_entry(PACK_MAX_BYTES + 1))
    assert max_download_bytes(_entry(5)) == 5, "the index's exact size, not a default cap"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({}, "ok"),
        ({"frozen": False}, "not-frozen"),
        ({"runtime_supported": False}, "unsupported"),
        ({"profile_can_add_packs": False}, "unsupported"),
        ({"install_method": "choco"}, "method"),
        ({"install_method": "scoop"}, "method"),
        ({"elevated": True}, "elevated"),
    ],
)
def test_capability(kwargs, code) -> None:
    args = dict(frozen=True, runtime_supported=True, profile_can_add_packs=True,
                profile_label="the Windows installer", install_method="windows-installer",
                elevated=False)
    args.update(kwargs)
    cap = capability(**args)
    assert cap.code == code
    assert cap.ok == (code == "ok")
    assert cap.ok or cap.reason


def test_phase_one_allows_only_the_installer_channel() -> None:
    """Chocolatey and Scoop join only after their checklist items pass (spec Phase 2)."""
    assert PACK_INSTALL_METHODS == frozenset({"windows-installer"})


@pytest.mark.parametrize(
    ("status", "complete", "damaged", "action"),
    [
        ("ok", True, False, "mount"),
        ("ok", False, False, "skip"),
        ("stale", True, False, "stale"),
        ("refused", True, False, "quarantine"),
        ("ok", True, True, "quarantine"),
        (None, True, False, "quarantine"),
    ],
)
def test_quarantine_versus_stale(status, complete, damaged, action) -> None:
    assert disposition(status, complete=complete, damaged=damaged) == action


def test_gc_keeps_the_previous_build_until_the_new_one_started_ok() -> None:
    builds = {"b-old": 1.0, "b-prev": 5.0, "b-new": 9.0}
    before = gc_plan(builds, "b-new", started_ok=False)
    assert set(before.keep) == {"b-new", "b-prev"} and before.delete == ("b-old",)
    after = gc_plan(builds, "b-new", started_ok=True)
    assert after.keep == ("b-new",) and set(after.delete) == {"b-old", "b-prev"}


def test_gc_on_rollback_keeps_the_relaunched_old_builds_packs() -> None:
    """A failed update relaunches the old version: its build is then `current`, and the
    newer build's tree (if any) is what may go."""
    plan = gc_plan({"b-old": 1.0, "b-new": 9.0}, "b-old", started_ok=False)
    assert "b-old" in plan.keep
