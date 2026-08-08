"""SettingsController maps toggles to config writes (all I/O injected)."""
from yazses.config import Config
from yazses.settingsui.controller import SettingsController


class _Recorder:
    def __init__(self, cfg=None):
        self.cfg = cfg or Config()
        self.writes: list[tuple] = []

    def load(self):
        return self.cfg

    def write(self, section, key, value, quote):
        self.writes.append((section, key, value, quote))


def test_toggle_on_writes_on_writes_tuple():
    rec = _Recorder()
    ctrl = SettingsController(rec.load, rec.write)
    result = ctrl.toggle("streaming")  # DEFAULT_ON=False by default -> OPTIONAL, off
    assert result.ok is True
    assert result.enabled is True
    assert rec.writes == [("streaming", "enabled", "true", False)]


def test_toggle_off_writes_off_writes_tuple():
    rec = _Recorder()
    ctrl = SettingsController(rec.load, rec.write)
    result = ctrl.toggle("commands")  # DEFAULT_ON -> currently on
    assert result.ok is True
    assert result.enabled is False
    assert rec.writes == [("commands", "enabled", "false", False)]


def test_toggle_unknown_slug_errors_without_writing():
    rec = _Recorder()
    ctrl = SettingsController(rec.load, rec.write)
    result = ctrl.toggle("not-a-real-feature")
    assert result.ok is False
    assert result.error is not None
    assert rec.writes == []


def test_toggle_core_feature_errors_without_writing():
    rec = _Recorder()
    ctrl = SettingsController(rec.load, rec.write)
    result = ctrl.toggle("dictation")
    assert result.ok is False
    assert rec.writes == []


def test_toggle_unwired_feature_errors_without_writing():
    rec = _Recorder()
    ctrl = SettingsController(rec.load, rec.write)
    result = ctrl.toggle("reask")
    assert result.ok is False
    assert rec.writes == []


def test_experimental_enable_requires_confirmation():
    rec = _Recorder()
    ctrl = SettingsController(rec.load, rec.write)
    result = ctrl.toggle("cocktail")  # off by default, turning on
    assert result.ok is False
    assert result.needs_confirmation is True
    assert rec.writes == []


def test_experimental_enable_with_confirmation_writes():
    rec = _Recorder()
    ctrl = SettingsController(rec.load, rec.write)
    result = ctrl.toggle("cocktail", confirmed=True)
    assert result.ok is True
    assert result.enabled is True
    assert rec.writes == [("cocktail", "enabled", "true", False)]


def test_experimental_disable_does_not_need_confirmation():
    from dataclasses import replace

    from yazses.config import CocktailConfig

    rec = _Recorder(replace(Config(), cocktail=CocktailConfig(enabled=True)))
    ctrl = SettingsController(rec.load, rec.write)
    result = ctrl.toggle("cocktail")
    assert result.ok is True
    assert result.enabled is False
    assert rec.writes == [("cocktail", "enabled", "false", False)]


def test_string_setting_toggle_writes_quoted_values():
    rec = _Recorder()
    ctrl = SettingsController(rec.load, rec.write)
    result = ctrl.toggle("target-guard")  # DEFAULT_ON -> currently on (clipboard)
    assert result.ok is True
    assert rec.writes == [("injection", "target_guard", "off", True)]
