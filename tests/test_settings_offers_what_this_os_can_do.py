"""The Speech page lists only the text-injection choices, and rows, this OS acts on.

On Windows the "Text injection" box offered eight values: `auto`, `ydotool`, `type`,
`portal`, `wtype`, `xdotool`, `unicode` and `clipboard`. `platform/windows/__init__.py`
acts on two ways of getting characters into a window, typing with SendInput and pasting,
and logs "has no meaning on Windows" for anything else. So choosing `wtype` changed
nothing, and nothing in the window said so. The "Desktop portal" row below it, a Wayland
permission, was shown too.

`Platform.injection_backends` now says what an OS acts on, `None` meaning everything
(Linux, the BSDs), and the window asks it. The config loader is untouched: it still
accepts every value, so a config shared with a Linux machine keeps loading.
"""
from __future__ import annotations

import os

import pytest

from yazses.platform import windows as win_platform
from yazses.platform.base import Platform
from yazses.settingsui.controls import (
    INJECTION_BACKENDS,
    injection_backend_choices,
    portal_applies,
)

# ---- the pure choice builders ----------------------------------------------------------


def test_an_os_that_names_nothing_lists_everything():
    assert injection_backend_choices(None, "auto") == INJECTION_BACKENDS


def test_windows_lists_two_in_the_loaders_order():
    assert injection_backend_choices(("auto", "clipboard"), "auto") == ("auto", "clipboard")
    assert injection_backend_choices(("clipboard", "auto"), "auto") == ("auto", "clipboard")


def test_the_configured_value_is_kept_even_when_this_os_ignores_it():
    """A config shared with a Linux machine says `ydotool`. Dropping it from the box would
    show another value and write that one on the next Apply."""
    listed = injection_backend_choices(("auto", "clipboard"), "ydotool")
    assert listed == ("auto", "clipboard", "ydotool")


def test_a_value_the_loader_does_not_know_is_not_invented():
    assert injection_backend_choices(("auto", "clipboard"), "carrier-pigeon") == ("auto", "clipboard")


def test_the_portal_row_applies_only_where_the_portal_is_offered():
    assert portal_applies(None)
    assert portal_applies(("auto", "portal"))
    assert not portal_applies(("auto", "clipboard"))


# ---- what Windows really acts on -------------------------------------------------------


def test_every_value_windows_offers_is_one_it_acts_on():
    """Offered values must be ones `build_injector` accepts without the "no meaning" warning."""
    acted_on = win_platform._TYPE_NAMES | win_platform._CLIPBOARD_NAMES
    assert set(win_platform.INJECTION_BACKENDS) <= acted_on


def test_windows_offers_one_value_per_behaviour():
    typing = [v for v in win_platform.INJECTION_BACKENDS if v in win_platform._TYPE_NAMES]
    pasting = [v for v in win_platform.INJECTION_BACKENDS if v in win_platform._CLIPBOARD_NAMES]
    assert len(typing) == 1 and len(pasting) == 1, "two names for one behaviour is a choice that is not"


def test_every_value_windows_hides_is_an_alias_or_unknown_to_it():
    """Nothing Windows would act on differently is hidden: a hidden value either types
    anyway (an alias of `auto`) or is a Linux name it ignores."""
    for value in set(INJECTION_BACKENDS) - set(win_platform.INJECTION_BACKENDS):
        assert value not in win_platform._CLIPBOARD_NAMES, f"{value!r} pastes on Windows but is hidden"


def test_the_platform_field_defaults_to_everything():
    assert Platform.__dataclass_fields__["injection_backends"].default is None


@pytest.mark.skipif(os.name != "nt", reason="builds the real Windows bundle")
def test_the_windows_bundle_declares_its_two():
    from yazses.platform import get_platform

    assert get_platform().injection_backends == ("auto", "clipboard")


# ---- the window ------------------------------------------------------------------------

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui import app as settings_app  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class _Recorder:
    def __init__(self, cfg=None):
        self.writes: list[tuple] = []
        self.cfg = cfg if cfg is not None else Config()

    def load(self):
        return self.cfg

    def write(self, section, key, value, quote):
        self.writes.append((section, key, value, quote))

    def probe(self, modules):
        return []


def _window(qapp, monkeypatch, offered, cfg=None):
    rec = _Recorder(cfg)
    monkeypatch.setattr(settings_app, "_offered_injection_backends", lambda: offered)
    win = settings_app.SettingsWindow(
        build_settings_model(rec.cfg), SettingsController(rec.load, rec.write, rec.probe)
    )
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    return win, rec


def _items(box):
    return [box.itemText(i) for i in range(box.count())]


def test_on_windows_the_box_lists_two_and_the_portal_row_is_hidden(qapp, monkeypatch):
    win, _ = _window(qapp, monkeypatch, ("auto", "clipboard"))
    assert _items(win._backend_box) == ["auto", "clipboard"]
    assert win._consent_box.isHidden()


def test_elsewhere_the_box_and_the_portal_row_are_unchanged(qapp, monkeypatch):
    win, _ = _window(qapp, monkeypatch, None)
    assert _items(win._backend_box) == list(INJECTION_BACKENDS)
    assert not win._consent_box.isHidden()


def test_a_shared_config_value_stays_selected(qapp, monkeypatch):
    cfg = Config()
    cfg.injection.backend = "ydotool"
    win, rec = _window(qapp, monkeypatch, ("auto", "clipboard"), cfg)
    assert win._backend_box.currentText() == "ydotool"
    changed, errors = win._apply_speech()
    assert not changed and not errors and rec.writes == [], "opening the window must not rewrite it"


def test_hiding_the_portal_row_stages_nothing(qapp, monkeypatch):
    win, rec = _window(qapp, monkeypatch, ("auto", "clipboard"))
    win._apply_speech()
    assert [w for w in rec.writes if w[1] == "portal_consent"] == []


def test_choosing_clipboard_on_windows_still_writes_it(qapp, monkeypatch):
    win, rec = _window(qapp, monkeypatch, ("auto", "clipboard"))
    win._backend_box.setCurrentIndex(win._backend_box.findText("clipboard"))
    changed, errors = win._apply_speech()
    assert changed and not errors
    assert rec.writes == [("injection", "backend", "clipboard", True)]
