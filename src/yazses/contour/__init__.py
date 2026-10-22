"""Pitch-Contour Vocal Gestures (ADR-v2-103).

Hum a pitch shape (rise=confirm, fall=cancel, rise-fall=undo; a flat hum is unmapped) as a
word-free command grammar. The ``gesture`` module is the pure contour classifier + command
map; ``burst`` turns a finished burst into a contour with the numpy F0 tracker in
``yazses.audio.pitch`` (no optional extra); ``wiring`` is where the daemon calls in. OFF by
default.
"""
