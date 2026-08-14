"""`InjectionTimeline` must be askable without being changed.

`undo()`/`redo()` mutate as they report, so asking what to do *is* doing it.
The daemon injects keystrokes between the two, and that injection can fail —
which left the history already moved on while the text was still on screen, so
the next undo targeted the wrong thing. Same defect the dictation ledger had.

`peek_undo`/`peek_redo` compute the op without mutating; the daemon commits
only after the keystrokes land.
"""
from __future__ import annotations

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.timeline.history import InjectionTimeline

# ---- the pure API -------------------------------------------------------

def test_peek_undo_does_not_change_the_timeline():
    t = InjectionTimeline()
    t.record("hello world")

    before = t.text()
    op = t.peek_undo("word")

    assert op is not None and op.backspaces > 0
    assert t.text() == before, "peek must not mutate"
    assert t.peek_undo("word").backspaces == op.backspaces, "peek must be repeatable"


def test_peek_undo_agrees_with_undo():
    """The contract that makes peek-then-commit sound."""
    for scope in ("word", "sentence", "burst", "last", "all"):
        t = InjectionTimeline()
        t.record("first sentence. second one here")

        peeked = t.peek_undo(scope)
        committed = t.undo(scope)

        assert peeked is not None and committed is not None
        assert peeked.backspaces == committed.backspaces, f"disagreed for scope={scope}"
        assert peeked.insert == committed.insert


def test_peek_redo_agrees_with_redo_and_does_not_mutate():
    t = InjectionTimeline()
    t.record("hello world")
    t.undo("word")

    peeked = t.peek_redo()
    assert peeked is not None
    assert t.peek_redo().insert == peeked.insert, "peek must be repeatable"

    committed = t.redo()
    assert committed is not None
    assert (peeked.backspaces, peeked.insert) == (committed.backspaces, committed.insert)


def test_peek_on_empty_history_is_none():
    t = InjectionTimeline()
    assert t.peek_undo() is None
    assert t.peek_redo() is None


# ---- the daemon ordering ------------------------------------------------

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
        self.key_sequences: list[list[str]] = []
        self.injected: list[str] = []
        self.fail = False

    def inject(self, text):
        self.injected.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        if self.fail:
            raise RuntimeError("injector hiccup")
        self.key_sequences.append(list(keys))


def _daemon():
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.timeline.enabled = True
    cfg.injection.continuation_window_ms = 0
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    inj = _Injector()
    d._injector = inj
    return d, inj


def _say(d, text):
    d._engine.text = text
    d._on_hold_end()


def test_failed_undo_injection_leaves_the_history_intact():
    """The regression: the text is still on screen, so the history must agree."""
    d, inj = _daemon()
    _say(d, "hello world")
    before = d._timeline.text()

    inj.fail = True
    _say(d, "undo the last word")

    assert d._timeline.text() == before, (
        "the backspaces never landed, so the timeline must still describe what "
        "is on screen"
    )


def test_successful_undo_still_advances_the_history():
    """The guard must not break the feature."""
    d, inj = _daemon()
    _say(d, "hello world")
    before = d._timeline.text()

    _say(d, "undo the last word")

    assert inj.key_sequences, "a successful undo must send backspaces"
    assert d._timeline.text() != before, "a successful undo must consume history"
