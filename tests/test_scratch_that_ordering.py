"""D1 — "scratch that" must not drop the burst until the backspaces land.

`DictationLedger.scratch_last()` *pops* as it reports, so asking it for the
count is itself the undo. The daemon used to ask first and inject second, which
meant a failed injection left the ledger believing the burst was gone while its
text was still on screen — and the *next* "scratch that" then deleted the burst
before it, text the user never asked to remove. Compounding, and silent,
because `_on_hold_end`'s outer handler swallows the exception.

Drives the real `_on_hold_end`, in the style of
`tests/test_continuation_spacing_daemon.py`.
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
    """Records injections; can be told to fail the backspace sequence."""

    def __init__(self):
        self.calls: list[str] = []
        self.key_sequences: list[list[str]] = []
        self.fail_key_sequence = False

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        if self.fail_key_sequence:
            raise RuntimeError("injector hiccup")
        self.key_sequences.append(list(keys))


def _daemon():
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.revise.enabled = True
    # Off so the counts in these tests are the burst itself. A later burst
    # otherwise gets a leading continuation space and the ledger records the
    # *prefixed* text — correct, but it obscures what is being asserted here.
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


def test_scratch_that_backspaces_the_last_burst():
    """The happy path still works — the fix must not break the feature."""
    d, inj = _daemon()
    _say(d, "hello world")
    _say(d, "scratch that")

    assert inj.key_sequences == [["BackSpace"] * len("hello world")]
    assert len(d._ledger) == 0, "a successful scratch must consume the burst"


def test_failed_scratch_keeps_the_burst_in_the_ledger():
    """The regression. Without the fix the ledger has already dropped the burst.

    The text is still on screen because the backspaces never landed, so the
    ledger must still describe it — otherwise the next scratch targets the
    wrong burst.
    """
    d, inj = _daemon()
    _say(d, "hello world")

    inj.fail_key_sequence = True
    _say(d, "scratch that")

    assert len(d._ledger) == 1, (
        "the injection failed, so the burst is still on screen and must still "
        "be in the ledger"
    )
    assert d._ledger.last_text() == "hello world"


def test_a_retry_after_a_failed_scratch_targets_the_same_burst():
    """The compounding failure, stated end to end.

    Before the fix the retry deleted the *previous* burst — text the user never
    asked to remove.
    """
    d, inj = _daemon()
    _say(d, "first burst")
    _say(d, "hello world")

    inj.fail_key_sequence = True
    _say(d, "scratch that")          # fails

    inj.fail_key_sequence = False
    _say(d, "scratch that")          # retry

    assert inj.key_sequences == [["BackSpace"] * len("hello world")], (
        "the retry must delete the burst the user meant, not the one before it"
    )
    assert d._ledger.last_text() == "first burst", "the earlier burst must survive"
