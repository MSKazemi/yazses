"""Tests for config type-checking and repair.

The governing rule is availability: no config file may prevent the daemon from starting.
Every case below asserts both halves of that — the daemon still gets a usable config, *and*
the user is told what was wrong.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from yazses.config import AccessibilityConfig, load_config, load_config_checked
from yazses.configcheck import ConfigProblem, build_section, coerce_value


@dataclass
class Sample:
    name: str = "x"
    count: int = 3
    ratio: float = 0.5
    on: bool = False
    tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    maybe: str | None = None


def _build(raw):
    problems: list[ConfigProblem] = []
    return build_section(Sample, raw, "sample", problems), problems


# --- the bug that took dictation down (issue #52) -----------------------------------


def test_quoted_number_is_repaired_not_fatal():
    """`vad_threshold = "0.004"` used to load fine and then break every burst."""
    cfg, problems = _build({"ratio": "0.004"})

    assert cfg.ratio == pytest.approx(0.004)
    assert isinstance(cfg.ratio, float), "must be a real float, not a string"
    assert any(p.key == "ratio" and p.repaired for p in problems)


def test_quoted_bool_is_repaired():
    for raw, expected in [("true", True), ("False", False), ("yes", True), ("off", False)]:
        cfg, problems = _build({"on": raw})
        assert cfg.on is expected, raw
        assert any(p.repaired for p in problems)


def test_unknown_key_is_dropped_rather_than_aborting_the_load():
    """A typo'd key used to raise TypeError and take the whole daemon with it."""
    cfg, problems = _build({"nmae": "typo", "name": "kept"})

    assert cfg.name == "kept"
    assert any(p.key == "nmae" and not p.repaired for p in problems)


def test_uncoercible_value_falls_back_to_the_default():
    cfg, problems = _build({"count": "not a number"})

    assert cfg.count == 3, "must fall back to the field default"
    assert any(p.key == "count" and not p.repaired for p in problems)


def test_bool_is_not_treated_as_an_int():
    """`isinstance(True, int)` is True in Python; `count = true` is still a mistake."""
    cfg, problems = _build({"count": True})

    assert cfg.count == 3
    assert any(p.key == "count" and not p.repaired for p in problems)


def test_int_field_rejects_a_fractional_float_but_accepts_a_whole_one():
    whole, whole_problems = _build({"count": 7.0})
    assert whole.count == 7 and isinstance(whole.count, int)
    assert any(p.repaired for p in whole_problems)

    frac, frac_problems = _build({"count": 7.5})
    assert frac.count == 3, "7.5 is not a whole number — take the default"
    assert any(not p.repaired for p in frac_problems)


def test_lists_and_dicts_survive_and_wrong_shapes_do_not_crash():
    ok, _ = _build({"tags": ["a", "b"], "extra": {"k": "v"}})
    assert ok.tags == ["a", "b"] and ok.extra == {"k": "v"}

    bad, problems = _build({"tags": "not-a-list"})
    assert bad.tags == []
    assert any(p.key == "tags" and not p.repaired for p in problems)


def test_optional_field_accepts_none():
    cfg, problems = _build({"maybe": None})
    assert cfg.maybe is None
    assert not [p for p in problems if p.key == "maybe"]


def test_a_section_that_is_not_a_table_is_ignored():
    problems: list[ConfigProblem] = []
    cfg = build_section(Sample, "oops", "sample", problems)

    assert cfg.name == "x", "defaults, not an exception"
    assert problems and not problems[0].repaired


def test_coerce_value_reports_what_it_repaired():
    ok, value, note = coerce_value("0.25", float)
    assert ok and value == pytest.approx(0.25) and note


# --- end to end, through the real loader -------------------------------------------


def test_a_thoroughly_broken_file_still_yields_a_working_config(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[accessibility]\nvad_threshold = "0.004"\n\n'
        '[hotkey]\nkey = "right_ctrl"\nhold_threshold_ms = "500"\n\n'
        '[streaming]\nenabled = "false"\n\n'
        "[audio]\nvad_treshold = 0.01\n\n"
        "[nosuchsection]\nenabled = true\n"
    )

    loaded = load_config_checked(path)

    # The settings that matter survived, with the right types.
    assert loaded.config.accessibility.vad_threshold == pytest.approx(0.004)
    assert isinstance(loaded.config.accessibility.vad_threshold, float)
    assert loaded.config.hotkey.key == "right_ctrl"
    assert loaded.config.hotkey.hold_threshold_ms == 500
    assert loaded.config.streaming.enabled is False
    # And every fault was reported.
    reported = {(p.section, p.key) for p in loaded.problems}
    assert ("audio", "vad_treshold") in reported
    assert ("nosuchsection", "") in reported


def test_unparseable_toml_starts_on_defaults_instead_of_raising(tmp_path: Path):
    """A syntax error must not mean "no dictation today"."""
    path = tmp_path / "config.toml"
    path.write_text("[hotkey\nkey = broken")

    loaded = load_config_checked(path)

    assert loaded.config.hotkey.key == "auto", "fell back to defaults"
    assert loaded.problems, "and said why"


def test_missing_file_is_valid_and_silent(tmp_path: Path):
    loaded = load_config_checked(tmp_path / "absent.toml")

    assert loaded.problems == []
    assert loaded.path is None


def test_load_config_never_raises_and_keeps_its_signature(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[accessibility]\nvad_threshold = "nonsense"\n')

    cfg = load_config(path)

    assert cfg.accessibility.vad_threshold == 0.01, "documented default"


# ---- nan and inf are floats, and a type check waves them through -------------


@pytest.mark.parametrize("literal", ["nan", "inf", "-inf", '"nan"', '"inf"'])
def test_a_non_finite_threshold_falls_back_and_is_reported(tmp_path, literal):
    """`vad_threshold = inf` used to load cleanly and break dictation completely.

    The silence gate is `mean(|audio|) < threshold`, so infinity discards every
    burst and nothing is ever typed; NaN makes the comparison false forever and the
    gate stops gating. Both are floats, so the type check passed them, `doctor`
    reported no config problem, and the user had a daemon that looked healthy and
    transcribed nothing.

    This module's promise is a working daemon *and* a ConfigProblem — never a silent
    oddity — so the fallback matters as much as the report.
    """
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(f"[accessibility]\nvad_threshold = {literal}\n", encoding="utf-8")

    result = load_config_checked(cfg_file)
    value = result.config.accessibility.vad_threshold

    assert math.isfinite(value), f"{literal} reached the silence gate as {value!r}"
    assert value == AccessibilityConfig().vad_threshold, "did not fall back to the default"
    assert result.problems, f"{literal} was accepted without a word"


def test_ordinary_numbers_are_untouched(tmp_path):
    """The guard must not cost the normal case anything."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[accessibility]\nvad_threshold = 0.004\n", encoding="utf-8")
    result = load_config_checked(cfg_file)
    assert result.config.accessibility.vad_threshold == 0.004
    assert not result.problems


def test_a_quoted_number_still_repairs(tmp_path):
    """`"0.004"` -> 0.004 is the documented repair and must survive the new check."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[accessibility]\nvad_threshold = "0.004"\n', encoding="utf-8")
    result = load_config_checked(cfg_file)
    assert result.config.accessibility.vad_threshold == 0.004
    assert result.problems, "a repaired value should still be reported at the source"
