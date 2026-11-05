"""The Persian-text checkbox must not read ON while changing nothing, without saying so.

``yazses features enable persian-normalisation`` prints a caveat when ``[stt] language`` is not
Persian: the normaliser builds nothing for another language, so the capability would read ON in
the list and change no transcript. The Settings window used to enable the same key in silence.
These tests hold the window to the CLI's honesty: the advice appears after Apply when it applies,
is absent when the language is Persian, and is read AFTER every write of that Apply, so choosing
Persian and ticking the box together does not produce a false warning.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from yazses.config import Config
from yazses.settingsui.controller import PendingChanges, SettingsController

SLUG = "persian-normalisation"


def _config(language: str) -> Config:
    base = Config()
    return dataclasses.replace(base, stt=dataclasses.replace(base.stt, language=language))


class _Rec:
    def __init__(self, language: str = "en") -> None:
        self.language = language
        self.writes: list[tuple] = []

    def load(self) -> Config:
        return _config(self.language)

    def write(self, section, key, value, quote) -> None:
        self.writes.append((section, key, value, quote))

    def probe(self, modules):
        return []


def _controller(rec: _Rec) -> SettingsController:
    return SettingsController(rec.load, rec.write, rec.probe)


# --- controller: no Qt needed -----------------------------------------------------------------


def test_the_advice_names_the_language_when_it_is_not_persian():
    advice = _controller(_Rec("en")).caveats_for([SLUG])
    assert set(advice) == {SLUG}
    assert "not Persian" in advice[SLUG]
    assert "'en'" in advice[SLUG]


def test_no_advice_when_the_language_is_persian():
    for language in ("fa", "fas", "fa-IR", "persian"):
        assert _controller(_Rec(language)).caveats_for([SLUG]) == {}, language


def test_the_window_gets_exactly_the_advice_the_cli_prints_and_none_for_nothing():
    from yazses.system.features import enable_caveat

    controller = _controller(_Rec("en"))
    assert controller.caveats_for([]) == {}
    cfg = _config("en")
    for slug in ("streaming", "cocktail", "dictation"):
        expected = enable_caveat(slug, cfg)
        assert controller.caveats_for([slug]) == ({slug: expected} if expected else {}), slug


def test_an_unreadable_config_yields_no_advice_instead_of_failing_apply():
    def boom() -> Config:
        raise OSError("config.toml is locked")

    controller = SettingsController(boom, _Rec().write, _Rec().probe)
    assert controller.caveats_for([SLUG]) == {}


def test_apply_reports_only_the_slugs_it_turned_on():
    rec = _Rec("en")
    controller = _controller(rec)
    pending = PendingChanges({SLUG: False})
    pending.stage(SLUG, True)
    on = controller.apply(pending)
    assert on.enabled == [SLUG]
    assert on.caveats == {}  # the window fills these in once every write has landed

    off_pending = PendingChanges({SLUG: True})
    off_pending.stage(SLUG, False)
    off = controller.apply(off_pending)
    assert off.applied == 1
    assert off.enabled == []


# --- the real window: Apply -> summary line ---------------------------------------------------

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _window(qapp, rec: _Rec) -> SettingsWindow:
    win = SettingsWindow(build_settings_model(rec.load()), _controller(rec))
    # No modal dialog and no host daemon: either would hang a headless run.
    win._confirm_experimental = lambda row: True  # type: ignore[method-assign]
    win._warn = lambda title, body: None  # type: ignore[method-assign]
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    win._confirm_restart = lambda: False  # type: ignore[method-assign]
    win._run_restart = lambda: (False, "not in a test")  # type: ignore[method-assign]
    return win


def test_ticking_the_box_with_a_non_persian_language_says_it_changes_nothing(qapp):
    rec = _Rec("en")
    win = _window(qapp, rec)
    win._checkboxes[SLUG].setChecked(True)
    win._on_apply()
    assert ("stt", "persian_normalisation", "true", False) in rec.writes
    assert "changes nothing you dictate" in win._hint.text()


def test_ticking_the_box_with_persian_selected_adds_no_warning(qapp):
    rec = _Rec("fa")
    win = _window(qapp, rec)
    win._checkboxes[SLUG].setChecked(True)
    win._on_apply()
    assert ("stt", "persian_normalisation", "true", False) in rec.writes
    assert "Heads up" not in win._hint.text()
    assert "changes nothing" not in win._hint.text()


def test_the_advice_is_read_after_the_writes_so_a_language_chosen_in_the_same_apply_counts(qapp):
    """The config on disk says 'en' before Apply; the Speech page writes 'fa' during it."""
    rec = _Rec("en")
    win = _window(qapp, rec)
    real_apply_speech = win._apply_speech

    def apply_speech_that_lands_persian(**kwargs):
        rec.language = "fa"  # what writing [stt] language = "fa" does to the file
        return real_apply_speech(**kwargs)

    win._apply_speech = apply_speech_that_lands_persian  # type: ignore[method-assign]
    win._checkboxes[SLUG].setChecked(True)
    win._on_apply()
    assert "changes nothing" not in win._hint.text()
