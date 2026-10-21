"""Vocal Joystick — continuous non-speech analog control (ADR-v2-095).

Sustain vowels/pitch/loudness to drive a cursor or any 2-D control, no words. The ``control`` module
is the pure formant→direction mapping + velocity integrator; ``formants`` is the per-frame producer
(LPC F1/F2, loudness, and pitch from the shared ``audio.pitch`` YIN tracker), numpy only, so it needs
no optional extra. Not yet wired to a pointer backend. OFF by default.
"""
