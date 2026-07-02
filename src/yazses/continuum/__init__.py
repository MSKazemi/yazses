"""Accessibility Continuum (ADR-v2-012).

Opt-in capabilities for effortful/quiet speech: Whisper/Low-Effort Mode (lower the
VAD threshold so whispered dictation isn't gated as silence), Semantic Capture
(meaning-not-words, reuses the LLM-cleanup path), and adaptive pacing. Pure
threshold/pacing math here; heavy paths (LLM) stay opt-in. OFF by default.
"""
