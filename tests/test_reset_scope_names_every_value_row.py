""""Restore defaults" left seven settings untouched without naming any of them.

The Settings window's reset confirmation ended with:

    Nothing is written until you click Apply, and your hotkey, microphone,
    vocabulary and any hand-edited settings are left alone.

That was accurate when the window held switches plus a hotkey and a microphone. It now
carries **nine** value rows, and seven — speech model, language, compute type, initial
prompt, injection backend, text-target guard, onset padding — went unnamed, covered only by
"any hand-edited settings".

They are not hand-edited. They are edited *in this window*, on the rows directly above the
button.

## Why it is worth a change rather than a shrug

Those seven are the settings most likely to have broken dictation in the first place. A
`compute_type` the CPU cannot do is reported as a missing *model*; a `language` that does
not match an `.en` checkpoint transliterates into fluent nonsense with no error; an
`injection backend` of `clipboard` is a no-op in a terminal. Someone in that state clicks
Restore defaults, clicks Apply, restarts — and is still broken, with nothing telling them
the reset never covered it.

## The guard is the point, not the sentence

Naming them today fixes today. This derives the row list from a real window, so a value row
added later fails here until it is both mapped and named — which is exactly how the
previous seven fell out: T33 added them to the window and nothing connected them to this
sentence.

Offscreen Qt, like the sibling window tests, so it runs without a display.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.help import RESET_SCOPE, reset_message  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402

#: Each value row in the window, and the words the reset scope must use for it. A row is
#: identified by its ``_<name>_baseline`` attribute, which every value row has because the
#: window has to remember what it started as.
ROW_WORDS = {
    "hotkey": ("hotkey",),
    "mic": ("microphone",),
    "model": ("speech model", "model"),
    "language": ("language",),
    "compute": ("compute type", "compute"),
    "prompt": ("initial prompt", "prompt"),
    "backend": ("injection backend", "backend"),
    "guard": ("text-target guard", "target guard"),
    "padding": ("onset padding", "padding"),
}


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def window(qapp):
    cfg = Config()

    def _writer(*_args):
        raise AssertionError("this test must never write config")

    controller = SettingsController(load_config=lambda *a, **k: cfg, writer=_writer)
    return SettingsWindow(build_settings_model(cfg), controller)


def _value_rows(window) -> set[str]:
    return {a[1:-len("_baseline")] for a in vars(window) if a.endswith("_baseline")}


def test_every_value_row_in_the_window_is_mapped(window) -> None:
    """A new value row must be added to ROW_WORDS — that is the tripwire.

    The seven missing settings got in exactly this way: added to the window with nothing
    connecting them to the reset sentence.
    """
    rows = _value_rows(window)
    assert rows, "no value rows found — the _baseline convention changed, fix this test"
    unmapped = rows - set(ROW_WORDS)
    assert not unmapped, (
        f"the Settings window grew value row(s) {sorted(unmapped)} that 'Restore defaults' "
        f"silently does not touch — name them in help.RESET_SCOPE and map them here"
    )


def test_the_reset_scope_names_every_value_row(window) -> None:
    scope = RESET_SCOPE.lower()
    missing = [
        row for row in sorted(_value_rows(window))
        if not any(word in scope for word in ROW_WORDS[row])
    ]
    assert not missing, (
        f"'Restore defaults' leaves {missing} untouched without saying so — a user who "
        f"broke one of them resets, applies, restarts and is still broken"
    )


def test_the_stale_wording_is_gone() -> None:
    """"any hand-edited settings" described rows edited in this very window."""
    assert "hand-edited" not in RESET_SCOPE


def test_the_scope_appears_in_the_confirmation_body() -> None:
    """It has to be on the dialog the user approves, not only in a constant."""
    body = reset_message([("macros", True)], {"macros": "Macros"})
    assert RESET_SCOPE in body
    assert "Apply" in body


def test_the_nothing_to_do_case_is_unchanged(window) -> None:
    """An empty diff has no scope to explain — adding it there would be noise."""
    body = reset_message([], {})
    assert "already at its default" in body
    assert RESET_SCOPE not in body


def test_the_body_still_names_the_capabilities_it_changes() -> None:
    """The original point of this dialog: never ask approval for an unseen change."""
    body = reset_message([("macros", True), ("gaze", False)],
                         {"macros": "Macros", "gaze": "Glance-Type"})
    assert "Macros" in body
    assert "Glance-Type" in body
    assert "Turn ON" in body and "Turn OFF" in body
