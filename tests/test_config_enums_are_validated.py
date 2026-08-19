"""A misspelled `off` left the guard on, and nothing said so.

`configcheck` repairs what it can and reports every decision as a `ConfigProblem`, and
`yazses doctor` renders that as *"Config validity: every setting is a usable value"*. But
coercion only checked **types**, and every one of these is a `str` field, so a typo was
stored verbatim and reported nothing:

    [injection] backend      = "clipbaord"
    [injection] target_guard = "of"

What happened next depended on the key, and was invisible either way. No branch matches
`clipbaord`, so the auto path runs while the user believes they forced the clipboard. And
the daemon tests `target_guard != "off"` — so a misspelled `off` leaves the no-text-target
guard **enabled**, which is the opposite of what was asked.

The second is what decided this was worth fixing. Getting a feature you switched off is a
different class of wrong from getting a fallback you did not choose.

## Only closed sets

`[stt] compute_type` is a property of the CPU, `[stt] language` is open, and a model name is
whatever is downloadable. Guessing at those would reject valid configs, which is worse than
accepting an invalid one — so the table holds only settings whose documented values are
genuinely a closed set.

## One table, not two

The Settings window already had its own copy of both lists. Two copies of a closed set
disagree the first time one is extended, at which point the window offers a value the loader
throws away, or refuses one it accepts. `controls.py` now derives from
`configcheck.enum_values`, and the direction is right: the GUI depends on the loader, never
the reverse.
"""

from __future__ import annotations

import pytest

from yazses.config import load_config_checked
from yazses.configcheck import enum_values


def _load(tmp_path, body: str):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return load_config_checked(path)


@pytest.mark.parametrize(
    "key,bad,default",
    [
        ("backend", "clipbaord", "auto"),
        ("backend", "nonsense", "auto"),
        ("target_guard", "of", "clipboard"),
        ("target_guard", "warnn", "clipboard"),
    ],
)
def test_a_typo_falls_back_and_is_reported(tmp_path, key, bad, default) -> None:
    result = _load(tmp_path, f'[injection]\n{key} = "{bad}"\n')
    assert getattr(result.config.injection, key) == default, (
        f"{bad!r} was stored verbatim; the daemon would act on it"
    )
    assert any(p.key == key for p in result.problems), (
        f"{bad!r} was rejected silently — `doctor` still reports the config as valid"
    )


def test_the_misspelled_off_is_the_case_that_matters(tmp_path) -> None:
    """A feature you switched off staying on is worse than an unchosen fallback.

    The daemon builds the target detector when `target_guard != "off"`, so any value it
    does not recognise keeps the guard running.
    """
    result = _load(tmp_path, '[injection]\ntarget_guard = "of"\n')
    assert result.config.injection.target_guard != "of"
    problem = next(p for p in result.problems if p.key == "target_guard")
    assert "off" in str(problem), "the message must name the value the user meant"


@pytest.mark.parametrize("value", ["auto", "type", "clipboard", "wtype"])
def test_every_documented_backend_is_accepted(value: str) -> None:
    """The expensive direction: a table that rejected a real value breaks working configs."""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        path.write_text(f'[injection]\nbackend = "{value}"\n', encoding="utf-8")
        result = load_config_checked(path)
    assert result.config.injection.backend == value
    assert not result.problems


@pytest.mark.parametrize("value", ["clipboard", "warn", "off"])
def test_every_documented_target_guard_is_accepted(tmp_path, value: str) -> None:
    result = _load(tmp_path, f'[injection]\ntarget_guard = "{value}"\n')
    assert result.config.injection.target_guard == value
    assert not result.problems


def test_open_ended_settings_are_not_in_the_table() -> None:
    """Guessing at these would reject valid configs, which is the worse failure."""
    for section, key in (
        ("stt", "compute_type"),   # a property of the CPU
        ("stt", "language"),       # open set
        ("stt", "model"),          # whatever is downloadable
        ("stt", "initial_prompt"),
    ):
        assert enum_values(section, key) is None, (
            f"[{section}] {key} is not a closed set — pinning one would reject configs "
            f"that work"
        )


def test_the_settings_window_uses_the_same_table() -> None:
    """Two copies of a closed set disagree the first time one is extended."""
    from yazses.settingsui.controls import INJECTION_BACKENDS, TARGET_GUARDS

    assert tuple(INJECTION_BACKENDS) == enum_values("injection", "backend")
    assert tuple(v for _label, v in TARGET_GUARDS) == enum_values(
        "injection", "target_guard"
    )


def test_the_dependency_points_the_right_way() -> None:
    """The GUI may depend on the loader; the loader must never depend on the GUI."""
    import inspect

    from yazses import configcheck

    assert "settingsui" not in inspect.getsource(configcheck)


def test_an_unknown_key_is_still_reported_separately(tmp_path) -> None:
    """The pre-existing behaviour, so the new branch has not swallowed it."""
    result = _load(tmp_path, '[injection]\nnot_a_setting = "x"\n')
    assert any("not a known setting" in str(p) for p in result.problems)
