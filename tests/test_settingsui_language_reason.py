"""The Speech page says why the Language box is greyed, and the claim is checked in code.

An exact language profile owns the speech language: the box is disabled and, once the
profile's preview has run, shows the profile's ``speech_language``. The reason line is
shown only in that state, so a greyed box no longer looks broken. Under Custom / advanced
the box is editable and the line is hidden.

The controller is wired to the real preview (``prepare_language_change``) on a temporary
config, with no network and no model download, as the app does. The check reads the
profile registry, so the wording is not measured against itself.
Skipped without PySide6; runs offscreen.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.config import load_config  # noqa: E402
from yazses.language import list_profiles  # noqa: E402
from yazses.language.service import prepare_language_change  # noqa: E402
from yazses.settingsui.app import LANGUAGE_REASON, SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.language_view import CUSTOM_LABEL  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def make_window(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[stt]\nengine = "faster-whisper"\nmodel = "base.en"\nlanguage = "en"\n'
        'chinese_script = ""\n',
        encoding="utf-8",
    )

    def preview(profile, *, model=None):
        return prepare_language_change(
            path, profile, model=model,
            missing_modules_fn=lambda _mods: [],
            blocked_probe=lambda _packages: None,
            cache_probe=lambda _model: True,
        )

    def build(qapp):
        controller = SettingsController(
            load_config=lambda: load_config(path),
            writer=lambda *_a: None,
            language_previewer=preview,
        )
        win = SettingsWindow(build_settings_model(load_config(path)), controller)
        win._daemon_running = lambda: False  # type: ignore[method-assign]
        win._daemon_status = lambda: None  # type: ignore[method-assign]
        win.show()
        return win

    return build


def _reason_shown(win) -> bool:
    return not win._language_reason.isHidden()


def test_a_profile_greys_the_language_box_and_says_why(qapp, make_window):
    win = make_window(qapp)
    win._profile_box.setCurrentIndex(win._profile_box.findData("en"))
    assert win._language_box.isEnabled() is False
    assert _reason_shown(win)
    assert win._language_reason.text() == LANGUAGE_REASON


def test_custom_makes_the_box_editable_and_hides_the_reason(qapp, make_window):
    win = make_window(qapp)
    win._profile_box.setCurrentIndex(win._profile_box.findData("en"))
    win._profile_box.setCurrentIndex(win._profile_box.findData(""))
    assert win._profile_box.currentText() == CUSTOM_LABEL
    assert win._language_box.isEnabled()
    assert not _reason_shown(win)


@pytest.mark.parametrize("profile", list_profiles(), ids=lambda p: p.id)
def test_the_greyed_box_shows_what_the_profile_actually_sets(qapp, make_window, profile):
    """The reason says the profile sets the language: check it against the registry."""
    win = make_window(qapp)
    win._profile_box.setCurrentIndex(win._profile_box.findData(profile.id))
    assert win._language_box.isEnabled() is False
    assert win._language_box.currentData() == profile.speech_language
    assert _reason_shown(win)


def test_a_window_that_opens_on_a_profile_shows_the_reason(qapp, make_window):
    win = make_window(qapp)
    assert win._profile_box.currentData() == "en"
    assert win._language_box.isEnabled() is False
    assert _reason_shown(win)
