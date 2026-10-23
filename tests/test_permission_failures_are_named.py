"""A permission denial must name the permission it actually needs.

Two defects are pinned here, both found by auditing against the rule "if it needs
a permission or hits an error, say so with a reason the user can act on".

1. `mic-permission`'s marker was the bare word "permission", and `diagnose` folds
   the exception *class name* into the matched text -- so every `PermissionError`
   matched it first. A `/dev/uinput` denial, an evdev denial and a refused portal
   consent are all `PermissionError`s, and all three sent the user to the audio
   privacy pane to fix a *typing* fault. `inject-permission` was unreachable.

2. Spoken Edit and Punch-In both erase the previous text and then retype it. The
   erase landing while the retype fails is silent data loss: the user watches the
   sentence go and nothing arrive, and the only record is a `log.debug`.
"""

from __future__ import annotations

import threading
import types

import pytest

from yazses.core.daemon import Daemon
from yazses.system.diagnosis import diagnose

# ------------------------------------------------- the classifier


@pytest.mark.parametrize(
    ("error", "where", "expected_slug"),
    [
        (PermissionError(13, "Permission denied", "/dev/uinput"), "inject", "inject-permission"),
        (
            PermissionError(13, "Permission denied", "/dev/input/event3"),
            "startup",
            "hotkey-permission",
        ),
        (
            RuntimeError(
                "Start was refused by the portal (response code 1; 1 means the "
                "user cancelled the permission dialog)"
            ),
            "inject",
            "portal-consent-denied",
        ),
        (
            RuntimeError("snap interface audio-record is not connected"),
            "capture",
            "snap-mic-interface",
        ),
        (
            RuntimeError("snap interface raw-input is not connected"),
            "startup",
            "snap-input-interface",
        ),
        (RuntimeError("Accessibility access is denied"), "startup", "macos-accessibility"),
        (RuntimeError("Input Monitoring is not granted"), "startup", "macos-input-monitoring"),
    ],
)
def test_each_permission_family_names_itself(error, where, expected_slug):
    assert diagnose(error, where=where).slug == expected_slug


@pytest.mark.parametrize(
    "error",
    [
        PermissionError(13, "Permission denied", "/dev/uinput"),
        PermissionError(13, "Permission denied", "/dev/input/event3"),
        RuntimeError("the user cancelled the permission dialog for the portal"),
    ],
)
def test_a_typing_or_hotkey_denial_is_never_called_a_microphone_problem(error):
    """The shipped bug: advice that sends someone to the wrong settings pane
    cannot work, and is worse than the generic fallback -- which at least offers
    to collect a report."""
    found = diagnose(error, where="inject")
    assert found.slug != "mic-permission"
    assert "microphone" not in found.title.lower()


def test_a_real_microphone_denial_still_reports_one():
    """Narrowing the rule must not cost the case it was written for."""
    found = diagnose(OSError("Permission denied opening microphone device"), where="capture")
    assert found.slug == "mic-permission"


def test_an_unrelated_permission_error_is_not_given_confident_advice():
    """It falls to the generic diagnosis, whose `unknown-` slug is what earns the
    'Prepare a bug report' button."""
    found = diagnose(PermissionError(13, "Permission denied", "/etc/hosts"), where="startup")
    assert found.slug.startswith("unknown-")


def test_every_permission_diagnosis_carries_a_next_step():
    """'Say the next command, not the category' -- the module's own rule."""
    for error, where in [
        (PermissionError(13, "Permission denied", "/dev/uinput"), "inject"),
        (RuntimeError("portal consent refused"), "inject"),
        (RuntimeError("snap interface raw-input is not connected"), "startup"),
        (RuntimeError("Accessibility access is denied"), "startup"),
    ]:
        assert diagnose(error, where=where).fix.strip()


# ------------------------------------------- erase-then-retype is not silent


class _Injector:
    """Types, except that `inject` fails -- the shape that erases and loses text."""

    def __init__(self):
        self.backspaced = 0

    def inject_backspaces(self, count):
        self.backspaced += count

    def inject(self, _text):
        raise RuntimeError("the injector is not available")


class _Ledger:
    def __init__(self, text):
        self._text = text
        self.replaced = None
        self.scratched = 0

    def last_text(self):
        return self._text

    def replace_last(self, text):
        self.replaced = text

    def scratch_last(self):
        self.scratched += 1
        self._text = ""
        return 0


def _daemon(reported, ledger_text="the foo is here"):
    config = types.SimpleNamespace(
        commands=types.SimpleNamespace(spoken_edit_destructive=False),
        punch_in=types.SimpleNamespace(min_score=0.5),
    )
    ledger = _Ledger(ledger_text)
    injector = _Injector()
    daemon = types.SimpleNamespace(
        _config=config,
        _ledger=ledger,
        _active_injector=lambda: injector,
        _report_failure=lambda exc, where: reported.append((str(exc), where)),
        _last_dictation_monotonic=0.0,
        _lock=threading.Lock(),
        _state=types.SimpleNamespace(last_error=None),
        notices=[],
        # Never the host clipboard: the restore fails here too, so the recovery
        # reaches the clipboard step, and a test must not overwrite the developer's.
        _rescue_to_clipboard=lambda _rescued: False,
        _log_replacement_steps=Daemon._log_replacement_steps,
    )
    daemon._notify_mic = lambda title, body, **_kw: daemon.notices.append((title, body))
    daemon._replace_last_burst = types.MethodType(Daemon._replace_last_burst, daemon)
    daemon._rewrite_undo_records = types.MethodType(Daemon._rewrite_undo_records, daemon)
    return daemon


def test_spoken_edit_tells_the_user_when_the_retype_fails():
    reported: list[tuple] = []
    daemon = _daemon(reported)
    event: dict = {}

    handled = Daemon._try_spoken_edit(daemon, "replace foo with bar", event)

    assert daemon._active_injector().backspaced > 0, "the erase is what makes this destructive"
    assert reported, "the user watched their text vanish and was told nothing"
    assert reported[0][1] == "inject"
    # And told where the words are (here: nowhere — this injector cannot even type them
    # back and the clipboard is refused), never silence.
    assert len(daemon.notices) == 1 and "could not be saved" in daemon.notices[0][0]
    # Handled: it WAS an edit command. It used to return False, and the caller then
    # filed the burst as "no command matched" — a second false statement on top of
    # the lost words.
    assert handled is True
    assert event["discard_reason"] == "spoken_edit_not_typed"


def test_spoken_edit_does_not_record_a_replacement_that_never_landed():
    """The ledger drives 'scratch that'. Recording text that was never typed would
    make the undo delete characters that are not on screen."""
    reported: list[tuple] = []
    daemon = _daemon(reported)

    Daemon._try_spoken_edit(daemon, "replace foo with bar", {})

    assert daemon._ledger.replaced is None
    # Nor may it keep counting the erased burst: what is on screen is unknown, so the
    # record is dropped and "scratch that" cannot reach past this dictation.
    assert daemon._ledger.scratched == 1
