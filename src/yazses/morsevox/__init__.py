"""Vocal Morse — two-tone timing-coded AAC (ADR-v2-105).

Decode timed vocal pulses (short/long) into text via international Morse. ``decode`` is the
pure timing classifier + decoder + adaptive calibration; ``segment`` turns a level stream into
pulses and gaps; ``mode`` decides when Morse mode starts (a long steady hum, or the spoken
"morse mode") and stops (a long silence); ``runtime`` owns the level-only microphone stream
and types what is decoded. OFF by default; experimental.
"""
