"""Acoustic Context Profiles (ADR-v2-039).

Detect the acoustic scene (quiet/café/car/meeting) and auto-switch VAD threshold + noise
suppression. The ``profiles`` module is the pure scene→policy map + hysteresis; the YAMNet/
CLAP scene tagger is lazy behind the ``acoustic`` extra. OFF by default.
"""
