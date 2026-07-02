"""Crowd-Proof Dictation (target-speaker extraction) (ADR-v2-084).

Continuously reconstruct the enrolled voice out of overlapping babble before STT. The ``frames``
module is the pure numpy framing/reconstruction/masking plumbing; the Conv-TasNet/SSM TSE model
is deferred behind a ``crowdproof`` extra. OFF by default.
"""
