"""Pitch-Contour Gestures reach the daemon (ADR-v2-103, #164 WIRE-CONTOUR-001).

Driven through the real `Daemon._on_hold_end` with the stubs `tests/test_speech_presence.py`
uses: a recorder that returns a synthetic burst, a decoder that returns a fixed transcript, a
speech detector whose verdict the test chooses. Every hum here is a synthetic harmonic tone
from `tests/synthetic_voice.py` -- the thresholds were never checked on recorded hums.

Pinned:

* off by default, and while off `yazses.contour` is never imported and both the #598 discard
  and ordinary dictation behave as before;
* on: a hum the speech detector finds no speech in gets its check *before* the #598 discard
  (owner decision 2026-10-21) and runs confirm / cancel / undo without typing;
* on: a hum that reaches the decoder is a gesture only with an empty or hum-only transcript;
* a flat hum is unmapped by default (owner decision 2026-10-21) and falls through.
"""
from __future__ import annotations

import builtins
import logging

import numpy as np
import pytest

from tests.synthetic_voice import SR, glide, hum, silence, white_noise
from yazses.audio import speech_presence
from yazses.config import Config
from yazses.contour.gesture import gesture_to_command
from yazses.core.daemon import Daemon
from yazses.platform import get_platform


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
        self.calls: list[str] = []
        self.keys: list[list[str]] = []

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, count):
        self.keys.append(["BackSpace"] * count)

    def inject_key_sequence(self, keys):
        self.keys.append(list(keys))


def _rise_fall(seconds=0.8):
    half = seconds / 2
    return lambda t: np.where(t < half, 150.0 + 150.0 * t / half, 300.0 - 150.0 * (t - half) / half)


#: Loud enough (mean |x| ~0.06) to clear the default 0.01 energy gate.
_AMP = 0.1


def _burst(f0, seconds=0.8):
    return np.concatenate([silence(0.2), hum(f0, seconds, amp=_AMP, noise=5e-4), silence(0.2)])


RISE = glide(150.0, 300.0, 0.8)
FALL = glide(300.0, 150.0, 0.8)


def _daemon(monkeypatch, audio, *, no_speech, text="", contour=True):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    cfg.contour.enabled = contour
    monkeypatch.setattr(speech_presence, "_default_detector", lambda _a, _sr: no_speech)
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _Recorder(audio)
    d._engine = _Engine(text)
    d._padding_buffer = None
    d._injector = _Injector()
    d.notes = []
    monkeypatch.setattr(d, "_notify_cmdsafety", d.notes.append)
    return d


@pytest.fixture
def contour_imports(monkeypatch):
    """Names of `yazses.contour*` modules that `core/daemon.py` itself imports."""
    real = builtins.__import__
    seen: list[str] = []

    def recorder(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if (globals or {}).get("__name__") == "yazses.core.daemon" and name.startswith(
            "yazses.contour"
        ):
            seen.append(name)
        return real(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", recorder)
    return seen


# ---- off by default: nothing changes -----------------------------------------------


def test_contour_is_off_by_default() -> None:
    assert Config().contour.enabled is False


def test_off_a_hum_with_no_speech_is_discarded_by_598_and_contour_never_loads(
    monkeypatch, caplog, contour_imports
) -> None:
    d = _daemon(monkeypatch, _burst(RISE), no_speech=True, contour=False)
    d._cmdsafety.hold("rm -rf build")
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        d._on_hold_end()
    assert "No speech in a" in caplog.text
    assert "Contour hum" not in caplog.text
    assert d._engine.calls == 0 and d._injector.calls == []
    assert d._cmdsafety.pending == "rm -rf build", "a disabled hum answered the held command"
    assert contour_imports == []


def test_off_dictation_types_exactly_as_before_and_contour_never_loads(
    monkeypatch, contour_imports
) -> None:
    d = _daemon(monkeypatch, _burst(FALL), no_speech=False, text="Hmm.", contour=False)
    d._on_hold_end()
    assert d._injector.calls == ["Hmm."]
    assert contour_imports == []


# ---- on: before the #598 discard ------------------------------------------------------


def test_on_a_rising_hum_with_no_speech_confirms_before_598_discards_it(
    monkeypatch, caplog
) -> None:
    d = _daemon(monkeypatch, _burst(RISE), no_speech=True)
    d._cmdsafety.hold("held words")
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        d._on_hold_end()
    assert "No speech in a" not in caplog.text, "#598 discarded the hum before contour saw it"
    assert "Contour hum confirm: done" in caplog.text
    assert d._engine.calls == 0
    assert d._cmdsafety.pending is None
    # Confirm releases the held item through the same path the spoken "confirm" uses.
    assert d._injector.calls == ["held words"]


def test_on_a_falling_hum_with_no_speech_cancels_the_held_command(monkeypatch) -> None:
    d = _daemon(monkeypatch, _burst(FALL), no_speech=True)
    d._cmdsafety.hold("rm -rf build")
    d._on_hold_end()
    assert d._cmdsafety.pending is None
    assert d._injector.calls == []
    assert any("Cancelled" in n for n in d.notes)


def test_on_a_gesture_with_nothing_held_is_a_noop_that_types_nothing(monkeypatch, caplog) -> None:
    d = _daemon(monkeypatch, _burst(RISE), no_speech=True)
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        d._on_hold_end()
    assert "Contour hum confirm: noop" in caplog.text
    assert d._injector.calls == [] and d._engine.calls == 0


@pytest.mark.parametrize("audio", [
    _burst(180.0),                          # flat: unmapped by default
    white_noise(1.0, level=0.08, seed=3),   # not voiced at all
], ids=["flat-hum", "noise"])
def test_on_a_burst_that_is_not_a_mapped_hum_is_still_discarded_by_598(
    monkeypatch, caplog, audio
) -> None:
    d = _daemon(monkeypatch, audio, no_speech=True)
    d._cmdsafety.hold("rm -rf build")
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        d._on_hold_end()
    assert "No speech in a" in caplog.text
    assert "Contour hum" not in caplog.text
    assert d._cmdsafety.pending == "rm -rf build"
    assert d._engine.calls == 0 and d._injector.calls == []


# ---- on: after decoding -----------------------------------------------------------


def test_on_a_hum_transcript_that_reached_the_decoder_is_a_gesture(monkeypatch) -> None:
    d = _daemon(monkeypatch, _burst(FALL), no_speech=False, text="Hmm.")
    d._cmdsafety.hold("rm -rf build")
    d._on_hold_end()
    assert d._engine.calls == 1
    assert d._cmdsafety.pending is None
    assert d._injector.calls == [], "the hum's transcript was typed"


def test_on_a_real_word_with_a_falling_pitch_is_dictation_not_cancel(monkeypatch) -> None:
    """A spoken "no" falls like the cancel hum; the transcript keeps it dictation."""
    d = _daemon(monkeypatch, _burst(FALL), no_speech=False, text="no")
    d._cmdsafety.hold("rm -rf build")
    d._on_hold_end()
    assert d._injector.calls == ["no"]
    assert d._cmdsafety.pending == "rm -rf build"


def test_on_a_rise_fall_hum_undoes_the_last_burst_yazses_typed(monkeypatch) -> None:
    d = _daemon(monkeypatch, _burst(_rise_fall()), no_speech=False, text="")
    d._ledger.record("hello")
    d._on_hold_end()
    assert d._injector.keys == [["BackSpace"] * 5]
    assert d._ledger.last_text() == ""
    assert d._injector.calls == []


def test_on_undo_is_refused_with_no_editable_target(monkeypatch, caplog) -> None:
    d = _daemon(monkeypatch, _burst(_rise_fall()), no_speech=True)
    d._ledger.record("hello")
    d._state.target_ok = False
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        d._on_hold_end()
    assert d._injector.keys == []
    assert d._ledger.last_text() == "hello"
    assert "Contour hum undo: not applied" in caplog.text


# ---- the default map --------------------------------------------------------------


def test_a_flat_hum_is_unmapped_by_default() -> None:
    assert gesture_to_command("flat") is None
    assert gesture_to_command("flat", profile={"flat": "repeat"}) == "repeat"


def test_the_synthetic_hums_used_here_are_the_shapes_they_claim() -> None:
    """Guards the fixtures: a green test above must not come from a mis-shaped tone."""
    from yazses.audio.pitch import track
    from yazses.contour.burst import burst_gesture

    shapes = {"rise": RISE, "fall": FALL, "rise_fall": _rise_fall(), "flat": 180.0}
    for name, f0 in shapes.items():
        assert burst_gesture(track(_burst(f0), SR)) == name


def test_on_a_stop_phrase_spelled_like_a_hum_stays_the_stop_word(monkeypatch, caplog) -> None:
    """ADR-v2-148: nothing may reinterpret a stop, so the gesture yields to it."""
    d = _daemon(monkeypatch, _burst(FALL), no_speech=False, text="Hmm hmm.")
    d._config.handsfree_safety.stop_phrase = "hmm hmm"  # a stop phrase needs two words
    d._cmdsafety.hold("rm -rf build")
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        d._on_hold_end()
    assert "Contour hum" not in caplog.text
    assert d._cmdsafety.pending == "rm -rf build"
    assert d._injector.calls == []


# ---- on: a contour failure never costs the user the burst ---------------------------
#
# `_contour_gesture` promises "never raises": with `[contour]` on, a failure inside the hum
# check must leave each hook exactly where it would be with the section off.


def _raise(*_a, **_k):
    raise RuntimeError("contour broke")


def test_on_a_failing_hum_check_before_decoding_still_lets_598_discard(
    monkeypatch, caplog
) -> None:
    from yazses.contour import wiring

    monkeypatch.setattr(wiring, "run_hum_gesture", _raise)
    d = _daemon(monkeypatch, _burst(RISE), no_speech=True)
    d._cmdsafety.hold("rm -rf build")
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        d._on_hold_end()
    assert "No speech in a" in caplog.text, "a contour failure skipped the #598 discard"
    assert "Contour hum" not in caplog.text
    assert d._cmdsafety.pending == "rm -rf build"
    assert d._engine.calls == 0 and d._injector.calls == []


def test_on_a_failing_hum_check_after_decoding_still_types_the_dictation(monkeypatch) -> None:
    from yazses.contour import wiring

    monkeypatch.setattr(wiring, "run_hum_gesture", _raise)
    d = _daemon(monkeypatch, _burst(FALL), no_speech=False, text="hello world")
    d._on_hold_end()
    assert d._engine.calls == 1
    assert d._injector.calls == ["hello world"], "a contour failure swallowed the dictation"


def test_on_a_handler_that_raises_falls_through_to_598_and_keeps_the_ledger(
    monkeypatch, caplog
) -> None:
    """`undo`'s injection fails mid-command: the burst is treated as before, nothing is lost."""
    d = _daemon(monkeypatch, _burst(_rise_fall()), no_speech=True)
    d._ledger.record("hello")
    monkeypatch.setattr(d._injector, "inject_key_sequence", _raise)
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        d._on_hold_end()
    assert "No speech in a" in caplog.text
    assert "Contour hum" not in caplog.text
    assert d._ledger.last_text() == "hello", "a failed undo popped the ledger"
    assert d._injector.calls == []
