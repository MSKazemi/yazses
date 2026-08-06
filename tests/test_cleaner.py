import numpy as np

from yazses.audio.vad import is_silent
from yazses.postprocess.cleaner import clean_text

# --- text cleaner ---

def test_strips_leading_trailing_whitespace():
    assert clean_text("  hello world  ") == "hello world"


def test_removes_blank_audio_artefact():
    assert clean_text("[BLANK_AUDIO]") == ""


def test_removes_leading_ellipsis():
    assert clean_text("... hello") == "hello"


def test_removes_leading_period():
    assert clean_text(". hello") == "hello"


def test_empty_string_returns_empty():
    assert clean_text("") == ""


def test_normal_text_is_unchanged():
    assert clean_text("Hello, how are you?") == "Hello, how are you?"


def test_strips_whitespace_around_artefact():
    assert clean_text("  [BLANK_AUDIO]  ") == ""


# --- VAD ---

def test_silence_detected_for_near_zero_audio():
    audio = np.zeros(16000, dtype="float32")
    assert is_silent(audio) is True


def test_speech_not_silent():
    rng = np.random.default_rng(42)
    audio = rng.uniform(-0.5, 0.5, 16000).astype("float32")
    assert is_silent(audio) is False


def test_empty_audio_is_silent():
    assert is_silent(np.array([], dtype="float32")) is True
