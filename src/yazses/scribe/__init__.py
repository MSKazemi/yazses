"""Ambient Meeting Scribe (ADR-v2-019).

On-device "who said what" meeting transcript with a per-speaker breakdown, distinct
from single-user dictation. This package's ``diarize`` module is the pure
labelling/formatting layer (enrolled user → "You", others → "Speaker N"); the streaming
diarization + STT backend is lazy behind the ``scribe`` extra. OFF by default.
"""
