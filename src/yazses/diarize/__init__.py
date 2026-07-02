"""Diarized Conversation Capture with Rename-by-Voice (ADR-v2-074).

Capture a live multi-speaker conversation as attributed Markdown, renameable by voice. The
``labels`` module is the pure label map + rename grammar + renderer; the pyannote diarizer is
deferred behind a ``diarize`` extra. OFF by default.
"""
