"""Streaming partials must be taken back when a burst does not type (#796).

With ``[streaming] enabled`` the hold start types live partial text before any
gate has seen the utterance. Every path out of ``_on_hold_end`` that consumes the
burst without typing it has to cancel those partials, or they stay in the editor
and a later commit types the staged buffer on top of them (duplicated text).

Injected fakes only: fake recorder, fake stream engine, mock injector. This does
NOT prove anything about a real editor or a real display server.
"""

from __future__ import annotations

import numpy as np
import pytest

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.inject.streaming import StreamingInjector
from yazses.platform import get_platform

PARTIAL = "hello "


class _Rec:
    has_clip = True
    stream_interrupted = False
    device = None

    def stop(self):
        t = np.arange(16000) / 16000
        return (0.3 * np.sin(2 * np.pi * 220 * t)).astype("float32")


class _Eng:
    def __init__(self, text: str) -> None:
        self._text = text

    def commit(self):
        return self._text

    def request_stop(self):
        pass


def _daemon(mocker, *, staged: bool = False, text: str = "hello world"):
    cfg = Config()
    cfg.streaming.enabled = True
    cfg.staged.enabled = staged
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _Rec()
    d._engine = mocker.MagicMock()
    d._engine.transcribe.return_value = text
    d._injector = mocker.MagicMock(name="injector")
    d._stream_engine = _Eng(text)
    d._padding_buffer = None
    d._corpus = mocker.MagicMock()
    d._notify_mic = mocker.MagicMock()
    d._maybe_retune_threshold = mocker.MagicMock()
    d._notify_staged = mocker.MagicMock()
    si = StreamingInjector(d._injector)
    si.inject_partial(PARTIAL)  # a live partial is already in the editor
    d._stream_injector = si
    return d


def _partials_taken_back(d) -> None:
    d._injector.inject_backspaces.assert_called_once_with(len(PARTIAL))


# ---- staged x streaming ------------------------------------------------------


def test_staged_burst_takes_back_the_typed_partials(mocker):
    d = _daemon(mocker, staged=True)
    d._on_hold_end()
    assert d._staged.chunks, "the burst should have reached the staged buffer"
    _partials_taken_back(d)


@pytest.mark.parametrize("text", ["take that back", "discard that"])
def test_staged_undo_and_discard_take_back_the_typed_partials(mocker, text):
    d = _daemon(mocker, staged=True, text=text)
    d._config.staged.spoken_commit = True
    d._on_hold_end()
    _partials_taken_back(d)


def test_an_empty_staged_commit_takes_back_the_typed_partials(mocker):
    d = _daemon(mocker, staged=True, text="commit that")
    d._config.staged.spoken_commit = True
    d._on_hold_end()
    assert not d._staged.chunks
    _partials_taken_back(d)


def test_a_full_staged_buffer_takes_back_the_typed_partials(mocker):
    d = _daemon(mocker, staged=True)
    d._config.staged.max_chunks = 1
    d._staged.stage("earlier burst")
    d._on_hold_end()
    _partials_taken_back(d)


def test_a_staged_commit_still_types_the_text(mocker):
    """No regression: a real commit selects the partials and types the buffer over them."""
    d = _daemon(mocker, staged=True, text="commit that")
    d._config.staged.spoken_commit = True
    d._staged.stage("buffered words")
    d._on_hold_end()
    d._injector.inject_key_sequence.assert_called_once_with(["shift+Left"] * len(PARTIAL))
    d._injector.inject_backspaces.assert_not_called()
    typed = [c.args[0] for c in d._injector.inject.call_args_list]
    assert any("buffered words" in t for t in typed)


def test_ordinary_dictation_without_staged_leaves_the_text_typed(mocker):
    d = _daemon(mocker, staged=False)
    d._on_hold_end()
    d._injector.inject_key_sequence.assert_called()
    typed = [c.args[0] for c in d._injector.inject.call_args_list]
    assert any("world" in t for t in typed)


# ---- the four other early returns in the dictation branch --------------------


def _hold_gate(d, mocker, gate: str):
    setattr(d, gate, mocker.MagicMock(return_value=None))


def test_cmdsafety_hold_takes_back_the_typed_partials(mocker):
    d = _daemon(mocker)
    d._config.cmdsafety.enabled = True
    _hold_gate(d, mocker, "_cmdsafety_gate")
    d._on_hold_end()
    d._cmdsafety_gate.assert_called_once()
    _partials_taken_back(d)


def test_checkdigit_hold_takes_back_the_typed_partials(mocker):
    d = _daemon(mocker)
    d._config.checkdigit.enabled = True
    _hold_gate(d, mocker, "_checkdigit_gate")
    d._on_hold_end()
    d._checkdigit_gate.assert_called_once()
    _partials_taken_back(d)


def test_reask_takes_back_the_typed_partials(mocker):
    d = _daemon(mocker)
    d._config.reask.enabled = True
    _hold_gate(d, mocker, "_reask_gate")
    d._on_hold_end()
    d._reask_gate.assert_called_once()
    _partials_taken_back(d)


def test_mic_answer_takes_back_the_typed_partials(mocker):
    d = _daemon(mocker)
    d._config.audio.voice_answer = True
    _hold_gate(d, mocker, "_mic_answer_gate")
    d._on_hold_end()
    d._mic_answer_gate.assert_called_once()
    _partials_taken_back(d)


# ---- the branch that landed with the device-lost fix -------------------------


def test_device_lost_takes_back_the_typed_partials(mocker):
    d = _daemon(mocker)
    d._recorder.stream_interrupted = True
    d._earcon = mocker.MagicMock()
    d._on_hold_end()
    _partials_taken_back(d)
    d._engine.transcribe.assert_not_called()
