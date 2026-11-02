"""`[residency] latency_keep_alive_s` (ADR-029): the default, the TOML table, bad values.

The key is read by the same loader as `[stt] idle_unload_s`, so these tests pin the
behaviour the loader gives any magnitude: a default of 0 (never release, unchanged
behaviour), a negative or non-integer value repaired to the default with a named problem,
and an unknown key inside the table ignored with a named problem. Nothing here loads a
model or touches the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yazses.config import Config, ResidencyConfig, load_config_checked


def _load(tmp_path: Path, body: str):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return load_config_checked(path)


def _residency_problems(loaded) -> list[str]:
    return [str(p) for p in loaded.problems if p.section.startswith("residency")]


def test_the_default_is_zero_so_an_install_that_never_set_it_is_unchanged() -> None:
    assert Config().residency.latency_keep_alive_s == 0
    assert ResidencyConfig().latency_keep_alive_s == 0


def test_the_residency_table_is_a_field_of_config() -> None:
    assert isinstance(Config().residency, ResidencyConfig)


def test_a_positive_keep_alive_loads_from_the_residency_table(tmp_path: Path) -> None:
    loaded = _load(tmp_path, "[residency]\nlatency_keep_alive_s = 600\n")
    assert loaded.problems == []
    assert loaded.config.residency.latency_keep_alive_s == 600


def test_zero_loads_clean_and_means_never_release(tmp_path: Path) -> None:
    loaded = _load(tmp_path, "[residency]\nlatency_keep_alive_s = 0\n")
    assert loaded.problems == []
    assert loaded.config.residency.latency_keep_alive_s == 0


def test_a_negative_keep_alive_is_repaired_to_the_default_with_a_named_problem(tmp_path: Path) -> None:
    loaded = _load(tmp_path, "[residency]\nlatency_keep_alive_s = -5\n")
    assert loaded.config.residency.latency_keep_alive_s == 0
    (problem,) = _residency_problems(loaded)
    assert "latency_keep_alive_s" in problem and "negative" in problem


def test_a_non_integer_keep_alive_is_repaired_to_the_default(tmp_path: Path) -> None:
    loaded = _load(tmp_path, '[residency]\nlatency_keep_alive_s = "ten minutes"\n')
    assert loaded.config.residency.latency_keep_alive_s == 0
    assert _residency_problems(loaded), "a string where an integer belongs must be reported"


def test_an_unknown_key_in_the_table_is_ignored_and_named(tmp_path: Path) -> None:
    loaded = _load(tmp_path, "[residency]\nlatency_keep_alive_s = 60\nbogus = 1\n")
    assert loaded.config.residency.latency_keep_alive_s == 60
    (problem,) = _residency_problems(loaded)
    assert "bogus" in problem and "not a known setting" in problem


def test_an_unknown_table_is_still_ignored_at_top_level(tmp_path: Path) -> None:
    loaded = _load(tmp_path, "[residency_typo]\nlatency_keep_alive_s = 60\n")
    assert loaded.config.residency.latency_keep_alive_s == 0
    assert any("residency_typo" in str(p) for p in loaded.problems)


@pytest.mark.parametrize("value", [1, 600, 86400])
def test_positive_integers_are_accepted(tmp_path: Path, value: int) -> None:
    loaded = _load(tmp_path, f"[residency]\nlatency_keep_alive_s = {value}\n")
    assert loaded.problems == []
    assert loaded.config.residency.latency_keep_alive_s == value
