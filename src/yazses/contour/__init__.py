"""Pitch-Contour Vocal Gestures (ADR-v2-103).

Hum a pitch shape (rise=confirm, fall=cancel, rise-fall=undo, flat=repeat) as a word-free command
grammar. The ``gesture`` module is the pure contour classifier + command map; ``burst`` turns a
finished burst into a contour with the numpy F0 tracker in ``yazses.audio.pitch`` (no optional
extra). Not wired yet; OFF by default.
"""
