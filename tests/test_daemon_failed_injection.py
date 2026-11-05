"""A dictation the injector could not type must not be recorded as typed, nor go quiet.

Three things were wrong when `injector.inject()` raised after the transcript existed:

* `event["injected"]` had been set to True *before* the call, so the learning corpus
  recorded a typed sentence and the edit watcher was told to read back text that was
  never typed;
* the notice went through the 300 s per-fault silence, so only the first lost sentence
  was ever announced -- the second and third vanished without a word;
* the notice did not say the words were lost.

The clipboard is deliberately not part of this: copying lost text there overwrites what
the user had copied, and is an owner decision.
"""

from __future__ import annotations

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform


class _Rec:
    def stop(self):
        return np.full(16000, 0.5, dtype="float32")


class _Eng:
    def transcribe(self, *a, **k):
        return "hello world"


class _BrokenInjector:
    def inject(self, text):
        raise OSError("ydotoold: connect: no such file")

    def inject_backspaces(self, n):
        pass

    def inject_key_sequence(self, k):
        pass


class _WorkingInjector:
    def __init__(self):
        self.typed = []

    def inject(self, text):
        self.typed.append(text)

    def inject_backspaces(self, n):
        pass

    def inject_key_sequence(self, k):
        pass


def _daemon(injector):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder, d._engine, d._padding_buffer, d._injector = _Rec(), _Eng(), None, injector
    return d


def test_a_failed_injection_is_not_recorded_as_injected(mocker, sandbox_paths):
    mocker.patch("yazses.system.notify.notify")
    d = _daemon(_BrokenInjector())
    d._edit_watcher = mocker.MagicMock()
    d._corpus = mocker.MagicMock()
    d._on_hold_end()
    event = d._corpus.write.call_args[0][0]
    assert not event.get("injected"), f"corpus event says injected={event.get('injected')!r}"
    assert event.get("discard_reason") == "inject_failed"
    d._edit_watcher.watch.assert_not_called()


def test_control_a_successful_injection_is_recorded_and_watched(mocker, sandbox_paths):
    mocker.patch("yazses.system.notify.notify")
    inj = _WorkingInjector()
    d = _daemon(inj)
    d._edit_watcher = mocker.MagicMock()
    d._corpus = mocker.MagicMock()
    d._on_hold_end()
    event = d._corpus.write.call_args[0][0]
    assert event.get("injected") is True
    assert not event.get("discard_reason")
    assert inj.typed, "the control did not type anything"
    d._edit_watcher.watch.assert_called_once()


def test_each_lost_dictation_is_announced_and_says_it_was_not_typed(mocker, sandbox_paths):
    toasts = mocker.patch("yazses.system.notify.notify")
    d = _daemon(_BrokenInjector())
    for _ in range(3):
        d._on_hold_end()
    assert toasts.call_count == 3, f"{toasts.call_count} toast(s) for 3 lost dictations"
    for call in toasts.call_args_list:
        assert "not typed" in call.args[1], call.args


def test_the_outcome_gauge_counts_a_lost_dictation_as_not_typed(mocker, sandbox_paths):
    mocker.patch("yazses.system.notify.notify")
    d = _daemon(_BrokenInjector())
    d._on_hold_end()
    data = d._outcomes.as_dict()
    assert data["dictation_total"] == 1
    assert data["dictation_typed"] == 0, data
    assert data["counts"] == {"inject_failed": 1}, data


def test_a_failure_that_lost_nothing_keeps_the_300_second_silence(mocker, sandbox_paths):
    toasts = mocker.patch("yazses.system.notify.notify")
    d = _daemon(_WorkingInjector())
    for _ in range(3):
        d._report_failure(OSError("boom"), "capture")
    assert toasts.call_count == 1


def test_the_failed_injection_does_not_copy_the_text_to_the_clipboard(mocker, sandbox_paths):
    """The owner has not decided whether lost words may overwrite the clipboard."""
    mocker.patch("yazses.system.notify.notify")
    clip = mocker.patch("yazses.system.clipboard.set_clipboard", return_value=True)
    d = _daemon(_BrokenInjector())
    d._on_hold_end()
    clip.assert_not_called()


# ---- the notice must not claim more than the code knows ---------------------------------

_LONG = "First clause here, second clause there. Third clause."


class _EngLong:
    def transcribe(self, *a, **k):
        return _LONG


class _FailsOnTheSecondCall(_WorkingInjector):
    """Types the first clause, then breaks: some of the text IS on screen."""

    def inject(self, text):
        if self.typed:
            raise OSError("ydotoold: connect: no such file")
        super().inject(text)


def _paced_daemon(injector):
    d = _daemon(injector)
    d._engine = _EngLong()
    d._config.srpace.enabled = True
    d._config.srpace.wpm = 100000.0  # real schedule, tiny delays: the test only needs 2+ chunks
    return d


def test_a_paced_burst_that_failed_after_its_first_clause_does_not_claim_nothing_was_typed(
    mocker, sandbox_paths
):
    toasts = mocker.patch("yazses.system.notify.notify")
    inj = _FailsOnTheSecondCall()
    d = _paced_daemon(inj)
    d._on_hold_end()
    assert inj.typed, "precondition: the first clause must have been typed"
    body = toasts.call_args.args[1]
    assert "may not have been fully typed" in body, body
    assert "was not typed" not in body, body


def test_a_paced_burst_that_failed_on_its_first_clause_says_nothing_was_typed(
    mocker, sandbox_paths
):
    toasts = mocker.patch("yazses.system.notify.notify")
    d = _paced_daemon(_BrokenInjector())
    d._on_hold_end()
    body = toasts.call_args.args[1]
    assert "What you just said was not typed." in body, body


def test_a_streaming_commit_failure_does_not_claim_nothing_was_typed(mocker, sandbox_paths):
    toasts = mocker.patch("yazses.system.notify.notify")
    d = _daemon(_WorkingInjector())
    d._config.streaming.enabled = True
    d._stream_engine = mocker.MagicMock()
    d._stream_engine.commit.return_value = _LONG  # the streaming decoder's final text
    stream = mocker.MagicMock()
    stream.commit.side_effect = OSError("ydotoold: connect: no such file")
    d._stream_injector = stream
    d._on_hold_end()
    assert stream.commit.called, "precondition: the streaming commit path must have run"
    body = toasts.call_args.args[1]
    assert "may not have been fully typed" in body, body
    assert "was not typed" not in body, body


def test_a_plain_injection_failure_still_uses_the_absolute_wording(mocker, sandbox_paths):
    toasts = mocker.patch("yazses.system.notify.notify")
    d = _daemon(_BrokenInjector())
    d._on_hold_end()
    assert "What you just said was not typed." in toasts.call_args.args[1]
