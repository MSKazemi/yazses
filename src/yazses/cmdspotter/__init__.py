"""Few-Shot Personal Command Spotter (ADR-v2-064).

Enroll a few examples of short personal commands that fire actions without a full Whisper decode.
The ``spotter`` module is the pure enrollment store + cosine dispatch; the KWS embedding encoder
is deferred behind a ``kws`` extra. Enrollment embeddings live in the encrypted corpus. OFF by
default.
"""
