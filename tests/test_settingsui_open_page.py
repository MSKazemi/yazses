"""`yazses settings --page <key>` and `yazses-settings --page <key>` open on that page."""
from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from yazses.cli import app as cli_app
from yazses.config import Config
from yazses.settingsui import app as settings_app
from yazses.settingsui.pages import PAGE_KEYS, PAGES, page_from_argv, resolve_page


def test_every_page_has_a_key_that_resolves_to_itself():
    assert PAGE_KEYS == tuple(spec.key for spec in PAGES)
    assert all(resolve_page(key) == key for key in PAGE_KEYS)


def test_a_key_is_matched_whatever_its_case_or_spacing():
    assert resolve_page(" Meetings ") == "meetings"


@pytest.mark.parametrize("name", [None, "", "nonsense", "File transcription"])
def test_what_is_not_a_key_resolves_to_nothing(name):
    assert resolve_page(name) is None


@pytest.mark.parametrize(
    "argv, found",
    [
        ([], None),
        (["settings"], None),
        (["--page", "audio"], "audio"),
        (["--page=audio"], "audio"),
        (["-platform", "offscreen", "--page", "files"], "files"),
        (["--page", "audio", "--page", "files"], "files"),
        (["--page"], ""),
        (["--pages", "audio"], None),
    ],
)
def test_the_page_is_read_from_a_bare_argv(argv, found):
    assert page_from_argv(argv) == found


# ---- the CLI -------------------------------------------------------------------------


@pytest.fixture
def opened(monkeypatch):
    calls: list[str | None] = []
    monkeypatch.setattr(settings_app, "run", lambda page=None: calls.append(page))
    return calls


def test_the_cli_passes_the_page_to_the_window(opened):
    result = CliRunner().invoke(cli_app, ["settings", "--page", "meetings"])
    assert result.exit_code == 0, result.output
    assert opened == ["meetings"]


def test_without_the_option_the_window_chooses(opened):
    assert CliRunner().invoke(cli_app, ["settings"]).exit_code == 0
    assert opened == [None]


def test_an_unknown_page_is_refused_and_the_pages_are_listed(opened):
    result = CliRunner().invoke(cli_app, ["settings", "--page", "nonsense"])
    assert result.exit_code == 2
    assert opened == []
    assert "nonsense" in result.output
    assert all(key in result.output for key in PAGE_KEYS)


# ---- the window's own entry point -------------------------------------------------------


def _run(monkeypatch, argv, page=None) -> list[str]:
    """Drive the real `run()` with a stand-in window; what it was asked to do, in order."""
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    done: list[str] = []

    class _Window:
        def __init__(self, model, controller):
            self._win = None

        def open_page(self, key):
            done.append(f"open {key}")

        def show(self):
            done.append("show")

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, "exec", lambda *a: 0)
    monkeypatch.setattr(settings_app, "SettingsWindow", _Window)
    monkeypatch.setattr(settings_app, "apply_theme", lambda *a: None)
    monkeypatch.setattr("yazses.config.load_config", lambda *a, **k: Config())
    monkeypatch.setattr("sys.argv", ["yazses-settings", *argv])
    with pytest.raises(SystemExit) as exit_:
        settings_app.run(page)
    assert exit_.value.code == 0
    return done


def test_the_gui_script_opens_the_page_named_on_its_command_line(monkeypatch):
    assert _run(monkeypatch, ["--page", "audio"]) == ["open audio", "show"]


def test_a_page_passed_by_the_caller_wins(monkeypatch):
    assert _run(monkeypatch, ["--page", "audio"], page="files") == ["open files", "show"]


@pytest.mark.parametrize("argv", [[], ["--page", "nonsense"], ["--page"]])
def test_a_missing_or_unknown_page_still_opens_the_window(monkeypatch, argv):
    assert _run(monkeypatch, argv) == ["show"]


def test_the_real_window_shows_the_page_asked_for():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from yazses.settingsui.controller import SettingsController
    from yazses.settingsui.model import build_settings_model

    qapp = QApplication.instance() or QApplication([])
    cfg = Config()
    window = settings_app.SettingsWindow(
        build_settings_model(cfg), SettingsController(lambda: cfg, lambda *a: None, lambda m: [])
    )
    window._daemon_running = lambda: False  # type: ignore[method-assign]
    window._daemon_status = lambda: None  # type: ignore[method-assign]
    try:
        window.open_page("audio")
        assert window._shell.current_key() == "audio"
        window.open_page("nonsense")
        assert window._shell.current_key() == "audio"
    finally:
        window._page_timer.stop()
        window._level_timer.stop()
        window._win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qapp.processEvents()
