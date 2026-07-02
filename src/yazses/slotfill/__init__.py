"""Structured Form / Slot-Filling Dictation (ADR-v2-063).

Speak naturally once and fill a named-field template. The ``fill`` module is the pure schema
matcher; the SpeechLLM for freeform utterance→slot mapping is deferred behind a ``slotfill``
extra. OFF by default.
"""
