"""Read-Back Loop TTS module (spec-read-back-loop, P1).

Covers the dependency-free pieces and the dormancy/degradation contract:
sentence chunking (drives time-to-first-audio), the null backend, and the factory
that returns None when dormant / NullTtsBackend when the engine is unavailable —
so the daemon never crashes and never downloads a model unless [tts] enabled.
"""
from __future__ import annotations

from yazses.config import TtsConfig
from yazses.tts.chunking import sentence_chunks
from yazses.tts.factory import build_tts
from yazses.tts.null import NullTtsBackend

# ---- sentence_chunks (pure, no dep) ----------------------------------------

def test_chunks_split_on_sentence_punctuation():
    assert list(sentence_chunks("A. B! C?")) == ["A.", "B!", "C?"]


def test_chunks_keep_a_single_unpunctuated_sentence_whole():
    assert list(sentence_chunks("hello world")) == ["hello world"]


def test_chunks_ignore_empty_and_whitespace():
    assert list(sentence_chunks("")) == []
    assert list(sentence_chunks("   ")) == []


def test_chunks_do_not_split_decimal_or_abbreviation_runs_into_blanks():
    # Whatever the split, no empty chunks are yielded and text is preserved.
    chunks = list(sentence_chunks("Pi is 3.14 today. Done!"))
    assert all(c.strip() for c in chunks)
    assert "".join(chunks).replace(" ", "") == "Piis3.14today.Done!".replace(" ", "")


# ---- NullTtsBackend (no-op) ------------------------------------------------

def test_null_backend_is_silent_and_safe():
    nb = NullTtsBackend()
    assert nb.name == "null"
    # speak/cancel must never raise and produce no audio
    nb.speak("anything")
    nb.cancel()
    assert list(nb.synthesize("anything")) == []


# ---- build_tts factory: dormancy + degradation -----------------------------

def test_factory_returns_none_when_dormant():
    # [tts] enabled = false => fully dormant, no import attempted.
    assert build_tts(TtsConfig(enabled=False)) is None


def test_factory_returns_null_when_engine_unavailable():
    # enabled but the engine import / model is missing => NullTtsBackend
    # (degrade, don't crash). kokoro-onnx is not installed in this env.
    backend = build_tts(TtsConfig(enabled=True, engine="kokoro"))
    assert backend is not None
    assert backend.name in ("null", "kokoro")  # null when kokoro-onnx absent


def test_factory_unknown_engine_degrades_to_null():
    backend = build_tts(TtsConfig(enabled=True, engine="does-not-exist"))
    assert backend is not None
    assert backend.name == "null"


# --- barge-in ordering -------------------------------------------------------
#
# `cancel` is called from the hotkey thread while `speak` runs on a read-back
# worker, so the backend alone cannot tell a cancel aimed at what is playing from
# one aimed at an utterance that has been requested but not started. `begin` is how
# a caller that knows that ordering says so. The two assertions below are the whole
# contract, and the third is the reason `speak` still self-heals for callers that
# do not use it.

class _FakeKokoro:
    """Stands in for the loaded model; `create` returns one silent frame."""

    def __init__(self):
        self.calls = []

    def create(self, chunk, voice=None, speed=None):
        self.calls.append(chunk)
        return [0.0], 24000


def _backend():
    """A `KokoroTtsBackend` without the 340 MB model load its `__init__` performs."""
    import threading

    from yazses.tts.kokoro import KokoroTtsBackend

    b = object.__new__(KokoroTtsBackend)
    b._kokoro = _FakeKokoro()
    b._voice = "af_heart"
    b._speed = 1.0
    b._cancel = threading.Event()
    b._claimed = False
    b._claim_lock = threading.Lock()
    return b


def test_a_cancel_after_the_claim_is_not_wiped_by_speak():
    """The barge-in case: the caller claimed the utterance, then a hold cancelled it."""
    b = _backend()
    b.begin()
    b.cancel()
    assert list(b.synthesize("hello there.")) == []
    assert b._kokoro.calls == []


def test_a_cancel_before_the_claim_belongs_to_the_previous_utterance():
    """Without this, a single barge-in would silence read-back for the rest of the run."""
    b = _backend()
    b.cancel()
    b.begin()
    assert list(b.synthesize("hello there.")) != []


def test_an_unclaimed_caller_is_not_silenced_forever_by_one_cancel():
    """`synthesize` never cleared the flag at all, so after any barge-in it yielded
    nothing on every later call — silently, and for the lifetime of the process,
    since only `speak` ever cleared it."""
    b = _backend()
    b.cancel()
    assert list(b.synthesize("hello there.")) != []
