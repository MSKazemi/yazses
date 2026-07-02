"""Gesture Chords (ADR-v2-043).

Bind multi-input chords (held key + head nod / second key / sEMG squeeze) to actions. The
``chords`` module is the pure, input-agnostic chord resolver; head-pose (MediaPipe) and sEMG
sensors are lazy behind their own extras and only feed input tokens in. OFF by default.
"""
