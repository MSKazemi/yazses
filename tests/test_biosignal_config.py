"""`[biosignal]` config: dormant defaults, load-time validation, and `_biosignal_problems`.

The section is experimental and OFF by default (AGENTS.md rule 2). These tests pin the
defaults, the numeric bounds the generic loader enforces, and the load-time report on the
two free tables (`mode_map`, `intent_map`) that the type check cannot see. Everything is
read from a TOML file under ``tmp_path``; nothing touches the user's real configuration.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from yazses.config import (
    BiosignalConfig,
    Config,
    _biosignal_problems,
    load_config_checked,
)


def _load(tmp_path: Path, body: str):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return load_config_checked(path)


def _problems(loaded, section: str = "biosignal", key: str | None = None) -> list[str]:
    return [
        str(p) for p in loaded.problems
        if p.section == section and (key is None or p.key == key)
    ]


def _cfg(**bio) -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), **bio)
    return cfg


# --------------------------------------------------------------------------- defaults


def test_the_section_ships_off_with_no_source():
    """Dormant by default: an existing install is unchanged until the user opts in."""
    bio = Config().biosignal
    assert bio.enabled is False
    assert bio.source == ""
    assert bio.jaw_clench is False  # the likeliest to fire by mistake stays opt-in


def test_the_new_keys_have_the_documented_defaults():
    bio = BiosignalConfig()
    assert bio.ledger_autosave_seconds == 60.0
    assert bio.speech_guard is True
    assert bio.mains_hz == 50
    assert bio.calibration_file == ""
    assert bio.mode_map == {"light": "full_text", "hard": "command"}
    assert bio.intent_map == {"double_blink": "undo"}


def test_default_maps_are_not_shared_between_instances():
    a, b = BiosignalConfig(), BiosignalConfig()
    a.mode_map["light"] = "command"
    a.intent_map["jaw_clench"] = "undo"
    assert b.mode_map["light"] == "full_text"
    assert "jaw_clench" not in b.intent_map


def test_a_default_config_file_reports_no_biosignal_problem(tmp_path):
    loaded = _load(tmp_path, "")
    assert _problems(loaded) == []
    assert loaded.config.biosignal == BiosignalConfig()


def test_defaults_raise_no_problem_even_when_the_section_is_turned_on():
    """Switching the section on with nothing else set is a clean, valid configuration."""
    assert _biosignal_problems(_cfg(enabled=True)) == []


# --------------------------------------------------------------------------- loading


def test_a_full_section_loads_from_toml(tmp_path):
    loaded = _load(tmp_path, """
[biosignal]
enabled = true
source = "synthetic"
mains_hz = 60
emg = false
double_blink = true
jaw_clench = true
max_cancelled_per_hour = 3.5
ledger_autosave_seconds = 120
speech_guard = false
calibration_file = "/somewhere/profile.json"
mode_map = { on = "command" }
intent_map = { double_blink = "undo", jaw_clench = "redo" }
""")
    assert _problems(loaded) == []
    bio = loaded.config.biosignal
    assert bio.enabled is True
    assert bio.source == "synthetic"
    assert bio.mains_hz == 60
    assert bio.emg is False
    assert bio.jaw_clench is True
    assert bio.max_cancelled_per_hour == 3.5
    assert bio.ledger_autosave_seconds == 120.0
    assert bio.speech_guard is False
    assert bio.calibration_file == "/somewhere/profile.json"
    assert bio.mode_map == {"on": "command"}
    assert bio.intent_map == {"double_blink": "undo", "jaw_clench": "redo"}


def test_unset_keys_keep_their_defaults_when_only_some_are_given(tmp_path):
    bio = _load(tmp_path, '[biosignal]\nsource = "synthetic"\n').config.biosignal
    assert bio.source == "synthetic"
    assert bio.enabled is False
    assert bio.speech_guard is True
    assert bio.ledger_autosave_seconds == 60.0


# --------------------------------------------------------------------------- bounds


@pytest.mark.parametrize("hz", [50, 55, 60])
def test_mains_hz_accepts_its_range(tmp_path, hz):
    loaded = _load(tmp_path, f"[biosignal]\nmains_hz = {hz}\n")
    assert _problems(loaded) == []
    assert loaded.config.biosignal.mains_hz == hz


@pytest.mark.parametrize("hz", [0, 49, 61, 400])
def test_mains_hz_outside_50_to_60_falls_back_to_the_default(tmp_path, hz):
    loaded = _load(tmp_path, f"[biosignal]\nmains_hz = {hz}\n")
    assert loaded.config.biosignal.mains_hz == 50
    assert _problems(loaded, key="mains_hz")


@pytest.mark.parametrize("seconds", [5, 60, 3600])
def test_ledger_autosave_seconds_accepts_its_range(tmp_path, seconds):
    loaded = _load(tmp_path, f"[biosignal]\nledger_autosave_seconds = {seconds}\n")
    assert _problems(loaded) == []
    assert loaded.config.biosignal.ledger_autosave_seconds == float(seconds)


@pytest.mark.parametrize("seconds", [0, 4, 4.9, 3601, 86400, -1])
def test_ledger_autosave_seconds_outside_5_to_3600_falls_back_to_the_default(tmp_path, seconds):
    loaded = _load(tmp_path, f"[biosignal]\nledger_autosave_seconds = {seconds}\n")
    assert loaded.config.biosignal.ledger_autosave_seconds == 60.0
    assert _problems(loaded, key="ledger_autosave_seconds")


def test_a_negative_budget_is_refused_by_the_loader_and_replaced_by_the_default(tmp_path):
    loaded = _load(tmp_path, "[biosignal]\nmax_cancelled_per_hour = -2\n")
    assert loaded.config.biosignal.max_cancelled_per_hour == 6.0
    assert _problems(loaded, key="max_cancelled_per_hour")


def test_zero_budget_means_no_budget_and_is_valid(tmp_path):
    loaded = _load(tmp_path, "[biosignal]\nmax_cancelled_per_hour = 0\n")
    assert loaded.config.biosignal.max_cancelled_per_hour == 0.0
    assert _problems(loaded) == []


def test_a_quoted_boolean_is_used_but_reported(tmp_path):
    loaded = _load(tmp_path, '[biosignal]\nspeech_guard = "false"\n')
    assert _problems(loaded, key="speech_guard")


def test_an_unknown_key_in_the_section_is_reported_not_fatal(tmp_path):
    loaded = _load(tmp_path, "[biosignal]\nenabeld = true\n")
    assert loaded.config.biosignal.enabled is False
    assert _problems(loaded)


# --------------------------------------------------------------------------- map problems


def test_a_valid_custom_map_is_silent():
    cfg = _cfg(enabled=True, mode_map={"on": "Command", "light": " full_text "},
               intent_map={"double_blink": "undo", "jaw_clench": "scratch that"})
    assert _biosignal_problems(cfg) == []


def test_an_unknown_strength_in_mode_map_is_named():
    problems = _biosignal_problems(_cfg(enabled=True, mode_map={"medium": "command"}))
    assert [(p.section, p.key) for p in problems] == [("biosignal", "mode_map")]
    assert "'medium'" in problems[0].detail
    assert "light, hard, on" in problems[0].detail
    assert problems[0].repaired is False


def test_a_mistyped_mode_in_mode_map_is_named():
    """The `[emg] mode` failure, per entry: `comand` must not fall into the other branch."""
    problems = _biosignal_problems(_cfg(enabled=True, mode_map={"light": "comand"}))
    assert len(problems) == 1
    assert "light = 'comand'" in problems[0].detail
    assert "command, full_text" in problems[0].detail


def test_each_bad_mode_map_entry_is_its_own_problem():
    problems = _biosignal_problems(_cfg(
        enabled=True, mode_map={"light": "x", "hard": "command", "weird": "command"}))
    assert len(problems) == 2


def test_an_unknown_event_in_intent_map_is_named():
    problems = _biosignal_problems(_cfg(enabled=True, intent_map={"wink": "undo"}))
    assert [(p.section, p.key) for p in problems] == [("biosignal", "intent_map")]
    assert "'wink'" in problems[0].detail
    assert "double_blink, jaw_clench" in problems[0].detail


@pytest.mark.parametrize("phrase", ["", "   "])
def test_an_empty_command_in_intent_map_is_named(phrase):
    problems = _biosignal_problems(_cfg(enabled=True, intent_map={"double_blink": phrase}))
    assert len(problems) == 1
    assert "double_blink has an empty command" in problems[0].detail


def test_a_negative_budget_set_in_code_is_named():
    problems = _biosignal_problems(_cfg(enabled=True, max_cancelled_per_hour=-1.0))
    assert [p.key for p in problems] == ["max_cancelled_per_hour"]
    assert "negative" in problems[0].detail
    assert "0" in problems[0].detail


def test_all_detectors_off_is_reported():
    problems = _biosignal_problems(
        _cfg(enabled=True, emg=False, double_blink=False, jaw_clench=False))
    assert [p.key for p in problems] == ["emg"]
    assert "no detector runs" in problems[0].detail


@pytest.mark.parametrize("on", ["emg", "double_blink", "jaw_clench"])
def test_any_single_detector_is_enough(on):
    flags = {"emg": False, "double_blink": False, "jaw_clench": False, on: True}
    assert _biosignal_problems(_cfg(enabled=True, **flags)) == []


def test_load_reports_every_map_problem_through_the_loader(tmp_path):
    loaded = _load(tmp_path, """
[biosignal]
enabled = true
mode_map = { light = "x", bogus = "command" }
intent_map = { foo = "undo" }
emg = false
double_blink = false
""")
    messages = _problems(loaded)
    assert len(messages) == 4
    assert any("not a mode" in m for m in messages)
    assert any("not a squeeze strength" in m for m in messages)
    assert any("not an event" in m for m in messages)
    assert any("no detector runs" in m for m in messages)


# --------------------------------------------------------------------------- silent when off


def test_every_problem_is_silent_while_the_section_is_disabled():
    cfg = _cfg(enabled=False, mode_map={"x": "y"}, intent_map={"wink": ""},
               max_cancelled_per_hour=-5.0, emg=False, double_blink=False, jaw_clench=False)
    cfg.activation.enabled = True
    cfg.activation.confirm_threshold = 7.0
    assert _biosignal_problems(cfg) == []


def test_a_disabled_section_with_garbage_loads_without_biosignal_problems(tmp_path):
    loaded = _load(tmp_path, """
[biosignal]
mode_map = { x = "y" }
intent_map = { wink = "" }
emg = false
double_blink = false
[activation]
enabled = true
confirm_threshold = 0.2
reject_floor = 0.8
""")
    assert _problems(loaded) == []
    assert _problems(loaded, section="activation") == []


# --------------------------------------------------------------------------- [activation]


def _with_activation(confirm: float, floor: float, *, enabled: bool = True,
                     biosignal_on: bool = True) -> Config:
    cfg = _cfg(enabled=biosignal_on)
    cfg.activation.enabled = enabled
    cfg.activation.confirm_threshold = confirm
    cfg.activation.reject_floor = floor
    return cfg


def test_sane_activation_thresholds_are_silent():
    assert _biosignal_problems(_with_activation(0.9, 0.5)) == []
    assert _biosignal_problems(_with_activation(0.7, 0.7)) == []  # equal is allowed
    assert _biosignal_problems(_with_activation(1.0, 0.0)) == []  # the edges are valid


def test_a_floor_above_the_threshold_is_reported_when_activation_is_on():
    problems = _biosignal_problems(_with_activation(0.4, 0.6))
    assert [(p.section, p.key) for p in problems] == [("activation", "reject_floor")]
    assert "0.6" in problems[0].detail and "0.4" in problems[0].detail
    assert "0.90 / 0.50" in problems[0].detail


@pytest.mark.parametrize("confirm,floor", [(1.4, 0.5), (0.9, -0.1), (2.0, 3.0), (-1.0, -2.0)])
def test_thresholds_outside_0_to_1_are_reported_when_activation_is_on(confirm, floor):
    problems = _biosignal_problems(_with_activation(confirm, floor))
    assert [(p.section, p.key) for p in problems] == [("activation", "confirm_threshold")]
    assert "between 0 and 1" in problems[0].detail


def test_bad_activation_thresholds_are_silent_while_activation_is_off():
    assert _biosignal_problems(_with_activation(0.4, 0.6, enabled=False)) == []
    assert _biosignal_problems(_with_activation(9.0, -9.0, enabled=False)) == []


def test_activation_thresholds_are_not_judged_by_this_check_when_biosignal_is_off():
    assert _biosignal_problems(_with_activation(0.4, 0.6, biosignal_on=False)) == []


def test_the_activation_problem_reaches_the_loader(tmp_path):
    loaded = _load(tmp_path, """
[biosignal]
enabled = true
[activation]
enabled = true
confirm_threshold = 0.3
reject_floor = 0.6
""")
    assert len(_problems(loaded, section="activation", key="reject_floor")) == 1


def test_the_check_never_raises_on_hostile_values():
    """A map check must never be what stops the daemon starting."""
    cfg = _cfg(enabled=True)
    cfg.biosignal.mode_map = None  # type: ignore[assignment]
    assert _biosignal_problems(cfg) == []

    cfg = _cfg(enabled=True)
    cfg.biosignal.max_cancelled_per_hour = "lots"  # type: ignore[assignment]
    assert isinstance(_biosignal_problems(cfg), list)


def test_the_problem_check_does_not_import_the_biosignal_package(monkeypatch):
    """Reads plain data only: a config that never sets the section pays nothing.

    An import spy rather than a `sys.modules` look, so the answer does not depend on what
    an earlier test in the same process already imported.
    """
    import builtins

    requested: list[str] = []
    real_import = builtins.__import__

    def spy(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name.split(".")[:2] == ["yazses", "biosignal"]:
            requested.append(name)
        elif level == 0 and name == "yazses" and "biosignal" in (fromlist or ()):
            requested.append("yazses.biosignal")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", spy)
    _biosignal_problems(_cfg(enabled=True, mode_map={"light": "bad"},
                             intent_map={"wink": ""}, max_cancelled_per_hour=-1.0))
    assert requested == []
