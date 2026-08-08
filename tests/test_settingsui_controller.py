"""SettingsController maps settings-window changes to config writes (all I/O injected)."""
from dataclasses import replace

import pytest

from yazses.config import CocktailConfig, Config, StreamingConfig
from yazses.settingsui.controller import PendingChanges, SettingsController


class _Recorder:
    def __init__(self, cfg=None, fail_on=None, missing=()):
        self.cfg = cfg or Config()
        self.writes: list[tuple] = []
        self._fail_on = fail_on  # (section, key) whose write raises
        self._missing = list(missing)

    def load(self):
        return self.cfg

    def write(self, section, key, value, quote):
        if self._fail_on == (section, key):
            raise OSError("Read-only file system")
        self.writes.append((section, key, value, quote))

    def probe(self, modules):
        return [m for m in modules if m in self._missing]


def _controller(rec):
    return SettingsController(rec.load, rec.write, rec.probe)


# --- set_enabled: the write it performs ------------------------------------


def test_enable_writes_the_on_writes_tuple():
    rec = _Recorder()
    result = _controller(rec).set_enabled("streaming", True)
    assert result.ok is True
    assert result.enabled is True
    assert rec.writes == [("streaming", "enabled", "true", False)]


def test_disable_writes_the_off_writes_tuple():
    rec = _Recorder()
    result = _controller(rec).set_enabled("commands", False)
    assert result.ok is True
    assert result.enabled is False
    assert rec.writes == [("commands", "enabled", "false", False)]


def test_string_setting_writes_quoted_values():
    rec = _Recorder()
    result = _controller(rec).set_enabled("target-guard", False)
    assert result.ok is True
    assert rec.writes == [("injection", "target_guard", "off", True)]


@pytest.mark.parametrize("slug", ["not-a-real-feature", "dictation", "reask"])
def test_unknown_core_and_unwired_slugs_error_without_writing(slug):
    """Unknown, core (no writes) and designed-but-unwired rows all refuse."""
    rec = _Recorder()
    result = _controller(rec).set_enabled(slug, True)
    assert result.ok is False
    assert result.error is not None
    assert rec.writes == []


# --- set_enabled writes the state asked for, it does not flip the config ----


def test_enable_writes_true_even_when_the_config_already_says_true():
    """The window asks for a state; a config changed under it must not invert it.

    A terminal running `yazses features enable streaming` while the window is
    open used to turn the user's "enable this" into a write of `false`.
    """
    rec = _Recorder(replace(Config(), streaming=StreamingConfig(enabled=True)))
    result = _controller(rec).set_enabled("streaming", True, confirmed=True)
    assert result.enabled is True
    assert rec.writes == [("streaming", "enabled", "true", False)]


def test_disable_writes_false_even_when_the_config_already_says_false():
    rec = _Recorder()
    result = _controller(rec).set_enabled("streaming", False)
    assert result.enabled is False
    assert rec.writes == [("streaming", "enabled", "false", False)]


# --- experimental confirmation gate ----------------------------------------


def test_experimental_enable_requires_confirmation():
    rec = _Recorder()
    result = _controller(rec).set_enabled("cocktail", True)
    assert result.ok is False
    assert result.needs_confirmation is True
    assert rec.writes == []


def test_experimental_enable_with_confirmation_writes():
    rec = _Recorder()
    result = _controller(rec).set_enabled("cocktail", True, confirmed=True)
    assert result.ok is True
    assert rec.writes == [("cocktail", "enabled", "true", False)]


def test_experimental_disable_does_not_need_confirmation():
    rec = _Recorder(replace(Config(), cocktail=CocktailConfig(enabled=True)))
    result = _controller(rec).set_enabled("cocktail", False)
    assert result.ok is True
    assert result.enabled is False
    assert rec.writes == [("cocktail", "enabled", "false", False)]


# --- a failing write is reported, never raised into Qt ----------------------


def test_failed_write_is_returned_not_raised():
    rec = _Recorder(fail_on=("streaming", "enabled"))
    result = _controller(rec).set_enabled("streaming", True)
    assert result.ok is False
    assert "Read-only file system" in (result.error or "")
    assert rec.writes == []


def test_failed_write_reports_how_many_keys_already_landed():
    """`gaze` writes two keys; a failure on the second must say the first landed."""
    rec = _Recorder(fail_on=("gaze", "route_dictation"))
    result = _controller(rec).set_enabled("gaze", True, confirmed=True)
    assert result.ok is False
    assert "1 of 2 keys were already written" in (result.error or "")


# --- missing optional dependencies are named, not silently ignored ----------


def test_enabling_reports_optional_deps_that_are_not_installed():
    """`features enable` installs these; the window must at least name them."""
    rec = _Recorder(missing=["speechbrain"])
    result = _controller(rec).set_enabled("cocktail", True, confirmed=True)
    assert result.ok is True
    assert result.missing_packages == ("speechbrain>=1.1",)


def test_no_dep_warning_when_the_modules_import():
    rec = _Recorder(missing=[])
    result = _controller(rec).set_enabled("cocktail", True, confirmed=True)
    assert result.missing_packages == ()


def test_no_dep_warning_when_disabling():
    rec = _Recorder(missing=["speechbrain"])
    result = _controller(rec).set_enabled("cocktail", False)
    assert result.missing_packages == ()


# --- environments that can never install the deps (a snap) -----------------


def test_enabling_is_refused_without_writing_when_deps_can_never_install():
    """Inside a snap the files are read-only, so naming the packages and writing
    the config anyway would leave the setting reading "on" with nothing able to
    honour it — and point at a `features enable` that refuses for the same
    reason. Refuse before the write instead."""
    rec = _Recorder(missing=["speechbrain"])
    ctrl = SettingsController(
        rec.load, rec.write, rec.probe, blocked_probe=lambda pkgs: "this is a snap"
    )
    result = ctrl.set_enabled("cocktail", True, confirmed=True)
    assert result.ok is False
    assert "this is a snap" in (result.error or "")
    assert rec.writes == [], "config was written for a setting that can never work"


def test_a_bundled_dependency_still_enables_in_a_locked_environment():
    """The gate must be precise: the snap bundles the libraries for several
    capabilities, and those must still toggle normally."""
    rec = _Recorder(missing=[])  # deps import fine — they are bundled
    ctrl = SettingsController(
        rec.load, rec.write, rec.probe, blocked_probe=lambda pkgs: "would be blocked"
    )
    result = ctrl.set_enabled("cocktail", True, confirmed=True)
    assert result.ok is True
    assert rec.writes


def test_disabling_is_never_blocked():
    """Turning something OFF installs nothing, so a locked environment must not
    trap a user with a setting they cannot switch back."""
    rec = _Recorder(missing=["speechbrain"])
    ctrl = SettingsController(
        rec.load, rec.write, rec.probe, blocked_probe=lambda pkgs: "this is a snap"
    )
    result = ctrl.set_enabled("cocktail", False)
    assert result.ok is True
    assert rec.writes


# --- PendingChanges (pure staging) -----------------------------------------


def test_staging_a_row_back_to_its_baseline_stages_nothing():
    pending = PendingChanges({"a": False})
    pending.stage("a", True)
    assert pending.items() == [("a", True)]
    pending.stage("a", False)
    assert pending.items() == []
    assert len(pending) == 0


def test_confirmation_is_spent_when_the_row_returns_to_its_baseline():
    pending = PendingChanges({"cocktail": False})
    pending.stage("cocktail", True)
    pending.confirm("cocktail")
    assert pending.is_confirmed("cocktail") is True
    pending.stage("cocktail", False)  # unchecked again
    assert pending.is_confirmed("cocktail") is False


def test_settle_makes_the_applied_state_the_new_baseline():
    pending = PendingChanges({"a": False})
    pending.stage("a", True)
    pending.settle("a", True)
    assert pending.items() == []
    assert pending.baseline("a") is True
    pending.stage("a", True)  # already there now
    assert pending.items() == []


# --- apply(): what lands, what stays staged --------------------------------


def test_apply_settles_successful_rows_and_counts_them():
    rec = _Recorder()
    pending = PendingChanges({"streaming": False, "commands": True})
    pending.stage("streaming", True)
    pending.stage("commands", False)

    report = _controller(rec).apply(pending)

    assert report.applied == 2
    assert report.ok is True
    assert len(pending) == 0
    assert pending.baseline("streaming") is True
    assert pending.baseline("commands") is False
    assert sorted(rec.writes) == [
        ("commands", "enabled", "false", False),
        ("streaming", "enabled", "true", False),
    ]


def test_apply_keeps_failed_rows_staged_and_reports_them():
    """A failed write must never be reported as applied, nor silently dropped."""
    rec = _Recorder(fail_on=("streaming", "enabled"))
    pending = PendingChanges({"streaming": False, "commands": True})
    pending.stage("streaming", True)
    pending.stage("commands", False)

    report = _controller(rec).apply(pending)

    assert report.applied == 1
    assert report.ok is False
    assert len(report.errors) == 1
    assert "streaming" in report.errors[0]
    assert pending.items() == [("streaming", True)]  # retryable
    assert pending.baseline("streaming") is False  # not claimed as applied


def test_apply_reports_an_unconfirmed_experimental_row_without_writing():
    rec = _Recorder()
    pending = PendingChanges({"cocktail": False})
    pending.stage("cocktail", True)  # staged, never confirmed

    report = _controller(rec).apply(pending)

    assert report.applied == 0
    assert report.unconfirmed == ["cocktail"]
    assert rec.writes == []
    assert pending.items() == [("cocktail", True)]


def test_apply_passes_the_confirmation_through():
    rec = _Recorder()
    pending = PendingChanges({"cocktail": False})
    pending.stage("cocktail", True)
    pending.confirm("cocktail")

    report = _controller(rec).apply(pending)

    assert report.applied == 1
    assert rec.writes == [("cocktail", "enabled", "true", False)]


def test_apply_collects_missing_packages_per_slug():
    rec = _Recorder(missing=["speechbrain"])
    pending = PendingChanges({"cocktail": False})
    pending.stage("cocktail", True)
    pending.confirm("cocktail")

    report = _controller(rec).apply(pending)

    assert report.missing_packages == {"cocktail": ("speechbrain>=1.1",)}
