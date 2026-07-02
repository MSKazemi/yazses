"""Personal Read-Back Voice (ADR-v2-042).

Read the transcript back in a clone of the user's own voice from a short enrollment. The
``clone`` module is the pure readiness/backend-selection core; the clone model is lazy behind
the ``tts`` extra. The reference embedding is biometric → encrypted-corpus only. OFF by default.
"""
