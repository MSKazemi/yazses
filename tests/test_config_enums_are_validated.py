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


# --- why the table is small -------------------------------------------------
#
# Eight further settings are closed sets and are deliberately NOT validated. Each already
# fails safe: an unrecognised value disables the feature or falls back to the
# always-available implementation, and logs what happened. That is the opposite of
# `target_guard`, where a misspelling turned a guard ON. These pin that property, so if
# one of them starts falling back to something ENABLED, the exclusion stops being
# justified and this file says so.


def test_an_unknown_gaze_backend_disables_gaze_rather_than_picking_one(monkeypatch) -> None:
    """Fail-safe: the camera stays off.

    The backends are stubbed so construction SUCCEEDS. Without that this proves nothing:
    `build_gaze` catches a construction failure and returns None, so on any machine
    without the `gaze` extra the assertion passes whatever the unknown-name branch does.
    A first version of this test did exactly that and survived a sabotage that made the
    unknown branch return a working backend.
    """
    import sys
    import types

    from yazses.config import Config
    from yazses.gaze.factory import build_gaze

    for name, cls in (("mediapipe_backend", "MediapipeGazeBackend"), ("l2cs", "L2csGazeBackend")):
        module = types.ModuleType(f"yazses.gaze.{name}")
        setattr(module, cls, lambda _config: "A WORKING BACKEND")
        monkeypatch.setitem(sys.modules, f"yazses.gaze.{name}", module)

    cfg = Config()
    cfg.gaze.enabled = True
    cfg.gaze.backend = "mediapipe"
    assert build_gaze(cfg.gaze) == "A WORKING BACKEND", (
        "the stub did not take effect — this test would prove nothing"
    )

    cfg.gaze.backend = "medipipe"
    assert build_gaze(cfg.gaze) is None, (
        "an unrecognised gaze backend now enables a webcam; it belongs in _ENUMS"
    )


def test_an_unknown_meeting_vad_backend_still_returns_a_working_gate() -> None:
    """Fail-safe the other way: meetings must not stop detecting speech over a typo."""
    from yazses.config import Config
    from yazses.meeting.vad import build_is_silent

    cfg = Config().meeting
    cfg.vad_backend = "silaro"
    assert callable(build_is_silent(cfg, 0.01))


def test_an_unknown_stt_engine_falls_back_and_says_so() -> None:
    """Asserted on the source: constructing an engine downloads a model.

    The factory's own docstring promises a fallback "with an honest log line saying
    exactly what happened", which is why this key is not in the table.
    """
    import inspect

    from yazses.stt import factory

    source = inspect.getsource(factory)
    assert "falling back to faster-whisper" in source


def test_the_excluded_sets_are_recorded_where_the_table_is() -> None:
    """So the next person does not redo this sweep, or add them carelessly."""
    import inspect

    from yazses import configcheck

    note = inspect.getsource(configcheck)
    for key in ("[gaze] backend", "[stt] engine", "[meeting] vad_backend",
                "[cocktail] mode"):
        assert key in note, f"{key} is no longer recorded where the table is"


def test_the_note_does_not_call_an_enforced_setting_deliberately_absent() -> None:
    """The exclusion note went stale, and staleness here is not cosmetic.

    It listed eight settings as deliberately outside `_ENUMS` "because each one already
    fails safe and says so". Three had since been added to the table, and of the five
    that really were absent, only three had the fail-safe property asserted anywhere.
    Reading the two nobody had checked found the claim false both times: `[emg] mode`
    switched to the *opposite* mode on a typo rather than disabling anything, and
    `[gaze] zones` / `[polyglot] lid` have no consumer at all to fail safely.

    A justification that names a setting the table now enforces is evidence the whole
    justification was not re-read, so this pins the cheap half mechanically.
    """
    import inspect

    from yazses import configcheck

    note = inspect.getsource(configcheck).split("_ENUMS: dict")[0]
    assert 'absent, because each one\n#: already fails safe and says so' not in note, (
        "the exclusion note has regained the sentence that went stale: it listed "
        "eight settings as deliberately outside _ENUMS on a fail-safe claim, while "
        "three of them were already in the table and two had no consumer at all. If "
        "settings are excluded again, name the ones excluded *today* and say which "
        "test asserts the fail-safe behaviour for each."
    )
    #: The two that really are excluded must each have that assertion, by name.
    for key, pinning in (("[cocktail] mode", None),
                         ("[meeting] vad_backend",
                          "test_an_unknown_meeting_vad_backend_still_returns_a_working_gate")):
        assert key in note, f"{key} is no longer recorded as a deliberate exclusion"
        if pinning:
            assert pinning in open(__file__, encoding="utf-8").read(), (
                f"{key} is excluded from _ENUMS on a fail-safe claim that nothing "
                "asserts any more"
            )
