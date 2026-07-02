"""Vocal Joystick (ADR-v2-095) + Earcon Feedback (ADR-v2-096) — pure cores."""
from __future__ import annotations

from yazses.earcon.tones import ToneSpec, earcon_for, render_earcon
from yazses.vocaljoystick.control import (
    ControlEvent,
    VocalJoystick,
    vocal_control_vector,
    vowel_to_direction,
)


# ---- vocal joystick --------------------------------------------------------

def test_vowel_to_direction():
    assert vowel_to_direction((300, 2300)) == "nw"   # close + front → up-left
    assert vowel_to_direction((800, 900)) == "se"    # open + back → down-right
    assert vowel_to_direction((300, 1500)) == "up"   # close, centred F2
    assert vowel_to_direction((800, 1500)) == "down"
    assert vowel_to_direction((550, 1500)) is None   # deadzone centre


def test_vocal_control_vector():
    assert vocal_control_vector("right", 1.0, max_speed=20.0) == (20.0, 0.0)
    assert vocal_control_vector("up", 0.5, max_speed=20.0) == (0.0, -10.0)
    assert vocal_control_vector(None, 1.0) == (0.0, 0.0)
    assert vocal_control_vector("left", 5.0, max_speed=20.0) == (-20.0, 0.0)  # loudness clamped to 1


def test_vocal_joystick_move_idle_click():
    j = VocalJoystick(max_speed=10.0, click_pitch=250.0, click_jump=30.0)
    assert j.feed("right", 1.0, 120.0) == ControlEvent("move", 10.0, 0.0)
    assert j.position() == (10.0, 0.0)
    assert j.feed(None, 1.0, 120.0) == ControlEvent("idle", 0.0, 0.0)
    # sharp upward pitch jump past threshold → click, no move
    assert j.feed("right", 1.0, 300.0).kind == "click"
    assert j.position() == (10.0, 0.0)


# ---- earcon ----------------------------------------------------------------

def test_earcon_for():
    assert earcon_for("recording_start")[0] == ToneSpec(660, 90)
    assert earcon_for("unknown_event") == earcon_for("idle")
    assert earcon_for("command_done", confidence=0.2)[0].envelope == "buzz"  # low conf overrides


def test_render_earcon_shapes():
    wave = render_earcon(earcon_for("recording_start"), fs=8000)
    assert wave.shape[0] == int(8000 * 90 / 1000) + int(8000 * 110 / 1000)
    assert abs(float(wave.max())) <= 1.0
    buzz = render_earcon(earcon_for("error"), fs=8000)
    assert buzz.shape[0] > 0
    assert render_earcon([], fs=8000).shape[0] == 0
    assert render_earcon([ToneSpec(440, 0)], fs=8000).shape[0] == 0   # zero-length skipped


def test_envelope_zero_length_guard():
    from yazses.earcon.tones import _envelope
    assert _envelope("linear", 0).shape[0] == 0
    assert _envelope("buzz", 4).shape[0] == 4


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "vocaljoystick" in slugs and "earcon" in slugs
    assert Config().vocaljoystick.enabled is False and Config().earcon.enabled is False
