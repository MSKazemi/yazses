"""Windows: `[injection] backend` must be honoured, and pasting must be an option.

The bug these cover: dictated text arrived in Chrome correctly and in a note
application as the right *number* of characters, every one of them wrong (rows
of "?", "-" or "."). `KEYEVENTF_UNICODE` survives that trip only if the
receiving window is a Unicode window and its text service unpacks the
synthesised VK_PACKET keystroke -- Microsoft documents both conditions. Pasting
does not depend on either, but `platform/windows/__init__.py` named
`WindowsInjector` unconditionally, so `backend = "clipboard"` was read,
validated, bridged into the environment and then ignored on Windows.
"""

from __future__ import annotations

import logging

import pytest

from yazses.platform.windows import build_injector
from yazses.platform.windows.clipboard import (
    VK_CONTROL,
    VK_V,
    WindowsClipboardInjector,
    _ctrl_v_events,
)
from yazses.platform.windows.injector import KEYEVENTF_KEYUP, WindowsInjector
from yazses.platform.windows.winfo import FocusReport, language_name

#: Everything `inject.auto.apply_injection_config` writes. `yazses inject` calls
#: it, so these leak out of any test that invokes the CLI -- and conftest's env
#: guard fails the run rather than let a later test read this one's answer.
_INJECTION_ENV = ("YAZSES_INJECTOR", "YAZSES_INJECT_FALLBACK", "YAZSES_PORTAL_CONSENT")


@pytest.fixture(autouse=True)
def _clean_env():
    """Snapshot and restore explicitly: `monkeypatch.delenv(raising=False)`
    records nothing to undo for a variable that was not already set."""
    import os

    before = {name: os.environ.get(name) for name in _INJECTION_ENV}
    for name in _INJECTION_ENV:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# ---- backend selection -------------------------------------------------


def test_default_still_types():
    """Typing stays the default: clipboard-paste clobbers the clipboard."""
    assert isinstance(build_injector(), WindowsInjector)


@pytest.mark.parametrize("value", ["clipboard", "paste", "Clipboard", " CLIPBOARD "])
def test_clipboard_backend_is_honoured(monkeypatch, value):
    monkeypatch.setenv("YAZSES_INJECTOR", value)
    assert isinstance(build_injector(), WindowsClipboardInjector)


@pytest.mark.parametrize("value", ["auto", "type", "sendinput", "unicode", ""])
def test_typing_names_select_the_sendinput_backend(monkeypatch, value):
    monkeypatch.setenv("YAZSES_INJECTOR", value)
    assert isinstance(build_injector(), WindowsInjector)


def test_a_linux_only_backend_name_says_what_actually_runs(monkeypatch, caplog):
    """Substituting in silence is the failure `inject/registry.py` exists to stop."""
    monkeypatch.setenv("YAZSES_INJECTOR", "ydotool")
    with caplog.at_level(logging.WARNING):
        injector = build_injector()
    assert isinstance(injector, WindowsInjector)
    assert "ydotool" in caplog.text
    assert "clipboard" in caplog.text


# ---- the paste keystroke ----------------------------------------------


def test_ctrl_v_is_pressed_and_released_in_order():
    """A stuck Ctrl is worse than a failed paste, so assert the whole sequence."""
    assert _ctrl_v_events() == [
        (VK_CONTROL, 0),
        (VK_V, 0),
        (VK_V, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    ]


def test_paste_uses_real_virtual_keys_not_a_unicode_packet():
    """The point of this backend: no KEYEVENTF_UNICODE anywhere in the keystroke."""
    from yazses.platform.windows.injector import KEYEVENTF_UNICODE

    assert all(flags & KEYEVENTF_UNICODE == 0 for _, flags in _ctrl_v_events())


def test_clipboard_injector_delegates_keys_to_the_sendinput_backend(monkeypatch):
    """Backspaces and key combos already went out as virtual keys and were fine."""
    seen: dict[str, object] = {}
    injector = WindowsClipboardInjector()
    monkeypatch.setattr(
        injector._keys, "inject_backspaces", lambda n: seen.__setitem__("bs", n)
    )
    monkeypatch.setattr(
        injector._keys, "inject_key_sequence", lambda k: seen.__setitem__("keys", k)
    )
    injector.inject_backspaces(3)
    injector.inject_key_sequence(["ctrl+a"])
    assert seen == {"bs": 3, "keys": ["ctrl+a"]}


def test_empty_text_touches_nothing(monkeypatch):
    """An empty burst must not open the clipboard, let alone overwrite it."""
    monkeypatch.setattr(
        "yazses.platform.windows.clipboard._load_clipboard_user32",
        lambda: pytest.fail("clipboard opened for empty text"),
    )
    WindowsClipboardInjector().inject("")


# ---- the diagnostic ----------------------------------------------------


def test_an_ansi_window_is_named_as_the_cause():
    report = FocusReport(
        hwnd=1, title="Untitled - Notes", window_class="Notepad",
        focus_hwnd=2, focus_class="Edit", focus_is_unicode=False,
        keyboard_layout=0x04090409, language="en-US",
    )
    text = "\n".join(report.lines())
    assert report.ansi_window
    assert "ANSI" in text and 'backend = "clipboard"' in text


def test_a_unicode_window_rules_ansi_out_without_declaring_success():
    report = FocusReport(
        hwnd=1, title="x", window_class="Chrome_WidgetWin_1",
        focus_hwnd=1, focus_class="Chrome_WidgetWin_1", focus_is_unicode=True,
        keyboard_layout=0x04090409, language="en-US",
    )
    text = "\n".join(report.lines())
    assert not report.ansi_window
    assert "VK_PACKET" in text


def test_an_unreadable_control_gives_no_verdict():
    """An unrun probe must never become a finding (inject/registry.py's rule)."""
    report = FocusReport(
        hwnd=1, title="x", window_class="X", focus_hwnd=1, focus_class="X",
        focus_is_unicode=None, keyboard_layout=0, language="langid 0x0000",
    )
    text = "\n".join(report.lines())
    assert "no verdict" in text
    assert 'backend = "clipboard"' not in text


@pytest.mark.parametrize(
    ("hkl", "expected"),
    [(0x04090409, "en-US"), (0x04290429, "fa-IR (Persian)"), (0x00000000, "langid 0x0000")],
)
def test_layout_language_is_read_from_the_low_word(hkl, expected):
    assert language_name(hkl) == expected


# ---- `yazses inject` as a test instrument ------------------------------


def _invoke_inject(monkeypatch, tmp_path, argv, *, config: str = ""):
    """Run `yazses inject ...` with a throwaway config and a recording injector."""
    import types

    from typer.testing import CliRunner

    from yazses import cli

    cfg = tmp_path / "config.toml"
    cfg.write_text(config, encoding="utf-8")
    injected: list[str] = []
    monkeypatch.setattr(
        cli,
        "get_platform",
        lambda: types.SimpleNamespace(
            default_hotkey="right_ctrl",
            paths=types.SimpleNamespace(config_file=cfg),
            injector_factory=lambda: types.SimpleNamespace(
                inject=injected.append, backend_name="FakeInjector"
            ),
        ),
    )
    return CliRunner().invoke(cli.app, argv), injected


def test_inject_without_delay_still_types_immediately(monkeypatch, tmp_path):
    result, injected = _invoke_inject(monkeypatch, tmp_path, ["inject", "hello"])
    assert result.exit_code == 0, result.output
    assert injected == ["hello"]


def test_delay_is_waited_out_before_injecting(monkeypatch, tmp_path):
    """The whole point: focus the app under test, then have the text arrive there.

    Asserted on the ordering, not the wall clock -- a test that really slept for
    five seconds would be paid for on every run of the suite.
    """
    events: list[str] = []
    monkeypatch.setattr("time.sleep", lambda s: events.append(f"slept {s}"))
    result, injected = _invoke_inject(
        monkeypatch, tmp_path, ["inject", "--delay", "5", "hello"]
    )
    assert result.exit_code == 0, result.output
    assert events == ["slept 5.0"]
    assert injected == ["hello"]
    assert "Focus the window" in result.output


def test_delay_accepts_the_short_flag(monkeypatch, tmp_path):
    monkeypatch.setattr("time.sleep", lambda s: None)
    result, injected = _invoke_inject(monkeypatch, tmp_path, ["inject", "-d", "2", "hi"])
    assert result.exit_code == 0, result.output
    assert injected == ["hi"]


def test_a_negative_delay_is_refused(monkeypatch, tmp_path):
    """Not a silent 0: a mistyped flag should say so rather than look like success."""
    result, injected = _invoke_inject(monkeypatch, tmp_path, ["inject", "-d", "-1", "hi"])
    assert result.exit_code != 0
    assert injected == []


def test_diagnose_off_windows_says_so_instead_of_printing_nothing(monkeypatch, tmp_path):
    result, injected = _invoke_inject(
        monkeypatch, tmp_path, ["inject", "--diagnose", "hello"]
    )
    assert result.exit_code == 0, result.output
    assert "Windows windows only" in result.output
    assert injected == ["hello"]


def test_diagnose_renders_the_report_when_the_probe_answers(monkeypatch, tmp_path):
    from yazses.platform.windows import winfo

    monkeypatch.setattr(winfo, "available", lambda: True)
    monkeypatch.setattr(
        winfo,
        "read_focus",
        lambda: FocusReport(
            hwnd=1, title="Untitled - Notes", window_class="Notepad",
            focus_hwnd=2, focus_class="Edit", focus_is_unicode=False,
            keyboard_layout=0x04090409, language="en-US",
        ),
    )
    result, injected = _invoke_inject(
        monkeypatch, tmp_path, ["inject", "--diagnose", "hello"]
    )
    assert result.exit_code == 0, result.output
    assert "Untitled - Notes" in result.output
    assert "ANSI" in result.output
    assert injected == ["hello"]


def test_diagnose_reports_no_foreground_window_rather_than_crashing(monkeypatch, tmp_path):
    from yazses.platform.windows import winfo

    monkeypatch.setattr(winfo, "available", lambda: True)
    monkeypatch.setattr(winfo, "read_focus", lambda: None)
    result, injected = _invoke_inject(
        monkeypatch, tmp_path, ["inject", "--diagnose", "hello"]
    )
    assert result.exit_code == 0, result.output
    assert "could not be determined" in result.output
    assert injected == ["hello"]
