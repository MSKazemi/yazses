"""A transcript that only repeats the decoder's own prompt is never typed unheard (#598).

The speech-presence check (``tests/test_speech_presence.py``) drops a no-speech burst
before decode, but it is skipped in Whisper / Dysfluency-Friendly / sotto-voce mode, can
be switched off, and fails open when the detector cannot run. In each of those cases the
decoder can still answer non-speech with "The app is called YazSes.", so a second,
text-level check catches the echo -- and it acts only when the audio was *not* positively
found to hold speech, so a user who says the sentence still gets it typed.
"""
from __future__ import annotations

import numpy as np
import pytest

from yazses.audio import speech_presence
from yazses.audio.device_monitor import CAPTURE_DOUBTING_DISCARDS
from yazses.audio.speech_presence import speech_verdict
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.stt.vocabulary import BUILTIN_PROMPT, is_prompt_echo, merge_initial_prompt

# ---- the pure rule -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The app is called YazSes.",
        "the app is called yazses",
        "THE APP IS CALLED YAZSES!",
        "  The app, is called -- YazSes...  ",
        "The app is called YazS.",       # cut short mid-token (measured, #598)
        "The app is called YazSeses.",   # the coined name stuttered (measured on Windows)
        "is called YazSes.",              # a contiguous fragment
        "The app is",
    ],
)
def test_an_echo_of_the_builtin_prompt_is_recognised(text) -> None:
    assert is_prompt_echo(text, merge_initial_prompt(None)) is True


@pytest.mark.parametrize(
    "text",
    [
        "YazSes.",                                  # the name alone
        "Open YazSes settings.",
        "The app is called YazSes and it works offline.",
        "I think the app is called YazSes.",
        "called YazSes",                            # two words: below the minimum
        "The app called YazSes.",                   # not contiguous
        "Please send the report today.",
        "",
    ],
)
def test_ordinary_dictation_containing_the_name_is_not_an_echo(text) -> None:
    assert is_prompt_echo(text, merge_initial_prompt(None)) is False


def test_a_span_of_a_personal_vocabulary_is_an_echo() -> None:
    prompt = merge_initial_prompt("Ydotool, Mohsen, Wayland.")
    assert is_prompt_echo("Ydotool, Mohsen, Wayland.", prompt) is True
    assert is_prompt_echo("Wayland.", prompt) is False


def test_no_prompt_means_no_echo() -> None:
    assert is_prompt_echo("The app is called YazSes.", None) is False


@pytest.mark.parametrize(
    "answer,expected",
    [(True, True), (False, False), (None, None), ("yes", None)],
)
def test_the_verdict_is_tri_state(answer, expected) -> None:
    assert speech_verdict(np.zeros(10), 16000, detector=lambda a, sr: answer) is expected


def test_a_raising_detector_is_unknown_not_speech() -> None:
    def boom(_a, _sr):
        raise RuntimeError("no onnx")

    assert speech_verdict(np.zeros(10), 16000, detector=boom) is None


def test_the_discard_is_classified_as_doubting_the_capture() -> None:
    assert "prompt_echo" in CAPTURE_DOUBTING_DISCARDS


# ---- the daemon --------------------------------------------------------------------


class _Recorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _Engine:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def transcribe(self, *_a, **_k):
        self.calls += 1
        return self.text

    def transcribe_words(self, *_a, **_k):
        self.calls += 1
        return self.text, []


class _Injector:
    def __init__(self):
        self.calls = []

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        pass


def _daemon(monkeypatch, *, verdict, text, configure=lambda cfg: None):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    configure(cfg)
    monkeypatch.setattr(speech_presence, "_default_detector", lambda _a, _sr: verdict)
    d = Daemon(config=cfg, platform=get_platform())
    # Loud enough to clear the 0.01 energy gate, as a fan or a key click does.
    d._recorder = _Recorder(np.full(16000, 0.05, dtype="float32"))
    d._engine = _Engine(text)
    d._padding_buffer = None
    d._injector = _Injector()
    return d


@pytest.mark.parametrize("echo", [BUILTIN_PROMPT, "the app is called yazs", "The app is called YazSeses!"])
def test_an_echo_is_not_typed_when_the_detector_cannot_run(monkeypatch, echo) -> None:
    d = _daemon(monkeypatch, verdict=None, text=echo)
    d._on_hold_end()
    assert d._injector.calls == []


@pytest.mark.parametrize(
    "configure",
    [
        lambda cfg: setattr(cfg.accessibility, "speech_presence_check", False),
        lambda cfg: setattr(cfg.accessibility, "dysfluency_friendly", True),
    ],
    ids=["check_off", "dysfluency_friendly_exempt"],
)
def test_an_echo_is_not_typed_when_the_check_did_not_run(monkeypatch, configure) -> None:
    # The detector would say "no speech", but it is never asked: the echo check still holds.
    d = _daemon(monkeypatch, verdict=True, text=BUILTIN_PROMPT, configure=configure)
    d._on_hold_end()
    assert d._engine.calls == 1
    assert d._injector.calls == []


def test_the_sentence_is_typed_when_speech_was_heard(monkeypatch) -> None:
    d = _daemon(monkeypatch, verdict=False, text=BUILTIN_PROMPT)
    d._on_hold_end()
    assert d._injector.calls == [BUILTIN_PROMPT]


def test_dictation_containing_the_name_is_typed_without_a_verdict(monkeypatch) -> None:
    d = _daemon(monkeypatch, verdict=None, text="Open YazSes settings.")
    d._on_hold_end()
    assert d._injector.calls == ["Open YazSes settings."]


def test_a_silent_burst_is_never_decoded(monkeypatch) -> None:
    d = _daemon(monkeypatch, verdict=True, text=BUILTIN_PROMPT)
    d._on_hold_end()
    assert d._engine.calls == 0
    assert d._injector.calls == []


def test_the_echo_discard_logs_no_text(monkeypatch, caplog) -> None:
    import logging

    d = _daemon(monkeypatch, verdict=None, text=BUILTIN_PROMPT)
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        d._on_hold_end()
    assert "Prompt echo" in caplog.text
    assert BUILTIN_PROMPT not in caplog.text
