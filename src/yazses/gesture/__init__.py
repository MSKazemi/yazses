"""Gesture Chords (ADR-v2-043, ADR-v2-147).

Bind multi-input chords (a face gesture and/or a head nod, shake or tilt) to abstract actions.
``chords`` is the pure, input-agnostic chord resolver; ``headmotion`` turns head pose into
discrete head tokens; ``sensors`` turns shared-camera samples into tokens; ``engine`` decides
when tokens form a chord and what it may do; ``runtime`` is the thin shell that leases the
camera. Heavy sensor libraries are never imported here -- they live behind the shared camera
source (the ``gaze`` extra). OFF by default, with no chord bound.
"""
