"""ADR-028 §6: the on-disk layout stays under Windows' MAX_PATH at the worst-case
%LOCALAPPDATA% length, and two build ids sharing a 12-hex prefix get different folders."""
from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from yazses.packs.layout import (
    MAX_PACK_NAME,
    MAX_PACK_RELPATH,
    MAX_PATH,
    WORST_CASE_DATA_DIR_LEN,
    PackLayout,
    budget_problems,
    build_dir_name,
)

A = "sha256:" + "0123456789ab" + "c" * 52
B = "sha256:" + "0123456789ab" + "d" * 52   # same first 12 hex digits


def test_the_budget_holds_at_the_worst_case_data_dir() -> None:
    assert budget_problems(WORST_CASE_DATA_DIR_LEN) == []


def test_the_budget_check_bites_on_a_longer_data_dir() -> None:
    """Guard the guard: a data dir long enough must be reported."""
    assert budget_problems(WORST_CASE_DATA_DIR_LEN + 60)


def test_the_worst_case_data_dir_is_what_windows_can_produce() -> None:
    """``C:\\Users\\<20-char user>.<15-char domain>\\AppData\\Local\\yazses``."""
    worst = PureWindowsPath("C:/Users") / ("u" * 20 + "." + "d" * 15) / "AppData/Local/yazses"
    assert len(str(worst)) <= WORST_CASE_DATA_DIR_LEN


def test_a_real_worst_case_path_fits() -> None:
    data = PureWindowsPath("C:/Users") / ("u" * 20 + "." + "d" * 15) / "AppData/Local/yazses"
    path = (data / "packs" / (build_dir_name(A, {}) + "-9") / ("n" * MAX_PACK_NAME)
            / ("x" * MAX_PACK_RELPATH))
    assert len(str(path)) < MAX_PATH


def test_build_dir_is_the_first_12_hex_digits() -> None:
    assert build_dir_name(A, {}) == "b-0123456789ab"
    assert build_dir_name(A, {"b-0123456789ab": A}) == "b-0123456789ab"


def test_a_prefix_collision_gets_its_own_folder() -> None:
    claimed = {"b-0123456789ab": A}
    assert build_dir_name(B, claimed) == "b-0123456789ab-2"
    claimed["b-0123456789ab-2"] = B
    assert build_dir_name(B, claimed) == "b-0123456789ab-2"
    assert build_dir_name(A, claimed) == "b-0123456789ab"


@pytest.mark.parametrize("bad", ["", "sha256:xyz", "0123", "sha256:" + "A" * 64])
def test_a_malformed_build_id_is_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        build_dir_name(bad, {})


def test_layout_paths_sit_under_data_dir_packs(tmp_path: Path) -> None:
    lay = PackLayout.under(tmp_path)
    assert lay.root == tmp_path / "packs"
    assert lay.state_file == tmp_path / "packs" / "state.json"
    assert lay.lock("parakeet") == tmp_path / "packs" / "parakeet.lock"
    assert lay.pack_dir("b-0123456789ab", "parakeet").parent.name == "b-0123456789ab"
    assert lay.staging_dir("parakeet", "abcd1234").name == "parakeet.abcd1234"
    assert not lay.root.exists(), "the layout is pure and must not create anything"


def test_the_name_rule_and_the_budget_agree() -> None:
    """`manifest._NAME_RE` and `MAX_PACK_NAME` are two statements of one limit."""
    from yazses.packs.manifest import _NAME_RE

    assert _NAME_RE.match("a" * MAX_PACK_NAME)
    assert not _NAME_RE.match("a" * (MAX_PACK_NAME + 1))
