"""Emotion / tone-aware formatting (ADR-v2-017).

Reflect paralinguistic tone (excitement, question intonation) in the dictated text
— auto ``!``/``?`` beyond the timing-only Prosody Ink. This package's ``format``
module is the pure ``(text, label, confidence) → text`` formatter (fully testable);
the SER model that produces the affect label is lazy behind the ``affect`` extra and,
when absent, yields a neutral label so the pass is a no-op. OFF by default.
"""
