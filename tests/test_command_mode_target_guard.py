"""D2/D3 — command-mode handlers that TYPE must respect the no-text-target guard.

`_try_spoken_edit` backspaces and retypes; `_try_rewrite` types a rewritten
selection. Both sit in the command-mode branch, ~300 lines above the
no-text-target guard on the dictation path, so they ran unguarded: with nothing
editable focused they would have typed into whatever window did have focus.

The handlers that act on a *window* (deixis, focus) and the one that captures a
note to a pad (Ambient Scratch) are deliberately still allowed — those are the
ones that make sense precisely when no text field is focused.
"""
from __future__ import annotations

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform


class _FakeRecorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _FakeEngine:
    def __init__(self, text=""):
        self.text = text

    def transcribe(self, *args, **kwargs):
        return self.text


class _Injector:
    def __init__(self):
        self.injected: list[str] = []
        self.backspaces = 0

    def inject(self, text):
        self.injected.append(text)

    def inject_backspaces(self, count):
        self.backspaces += count

    def inject_key_sequence(self, keys):
        pass


def _daemon(*, target_ok):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = True
    cfg.commands.spoken_edit = True
    cfg.commands.spoken_edit_destructive = True
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    inj = _Injector()
    d._injector = inj
    d._state.target_ok = target_ok
    return d, inj


def _command(d, text):
    """Drive one burst with the dedicated command key held."""
    d._command_mode = True
    d._engine.text = text
    d._on_hold_end()


def test_spoken_edit_is_refused_when_there_is_no_text_target():
    """The regression: this used to backspace into another window."""
    d, inj = _daemon(target_ok=False)
    d._ledger.record("hello world")

    _command(d, "change hello to goodbye")

    assert inj.backspaces == 0, "backspaces were sent with no editable target"
    assert inj.injected == [], "text was typed with no editable target"
    assert d._ledger.last_text() == "hello world", "the ledger must not be rewritten"


def test_spoken_edit_still_applies_when_a_target_exists():
    """The guard must not disable the feature where it is legitimate."""
    d, inj = _daemon(target_ok=True)
    d._ledger.record("hello world")

    _command(d, "change hello to goodbye")

    assert inj.backspaces == len("hello world")
    assert inj.injected == ["goodbye world"]
    assert d._ledger.last_text() == "goodbye world"


def test_unknown_target_is_treated_as_usable():
    """`target_ok` is tri-state; `None` means the probe could not tell.

    Refusing on unknown would disable spoken edit on every setup without
    AT-SPI, which is a far bigger regression than the bug being fixed.
    """
    d, inj = _daemon(target_ok=None)
    d._ledger.record("hello world")

    _command(d, "change hello to goodbye")

    assert inj.injected == ["goodbye world"]


# ---- the same gap on the DICTATION path ---------------------------------
#
# "scratch that" and "undo the last word" both inject and then return, ~250
# lines above the no-text-target guard, so neither ever consulted it. The
# comment on the timeline branch — "it can never eat the user's own typing" —
# is true of WHAT it replays and silent about WHERE: if focus moved since the
# text was injected, the backspaces land on another document.


def _dictation_daemon(*, target_ok):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.revise.enabled = True
    cfg.timeline.enabled = True
    cfg.injection.continuation_window_ms = 0
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    inj = _Injector()
    d._injector = inj
    d._state.target_ok = target_ok
    return d, inj


def _dictate(d, text):
    d._engine.text = text
    d._on_hold_end()


def test_scratch_that_is_refused_when_there_is_no_text_target():
    d, inj = _dictation_daemon(target_ok=True)
    _dictate(d, "hello world")

    d._state.target_ok = False          # focus moved away
    _dictate(d, "scratch that")

    assert inj.backspaces == 0
    assert d._ledger.last_text() == "hello world", "nothing was deleted, so nothing is consumed"


def test_scratch_that_still_works_with_a_target():
    d, inj = _dictation_daemon(target_ok=True)
    _dictate(d, "hello world")
    _dictate(d, "scratch that")

    assert d._ledger.last_text() == "", "the burst must be consumed on the happy path"


def test_timeline_undo_is_refused_when_there_is_no_text_target():
    d, inj = _dictation_daemon(target_ok=True)
    _dictate(d, "hello world")
    before = d._timeline.text()

    d._state.target_ok = False
    _dictate(d, "undo the last word")

    assert d._timeline.text() == before, "history must not advance on a refused replay"


def test_timeline_undo_still_works_with_a_target():
    d, inj = _dictation_daemon(target_ok=True)
    _dictate(d, "hello world")
    before = d._timeline.text()

    _dictate(d, "undo the last word")

    assert d._timeline.text() != before, "the happy path must still replay"
