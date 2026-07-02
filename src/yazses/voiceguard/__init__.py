"""Continuous voice-biometric gate + anti-spoof (ADR-v2-018).

Only drive the keyboard when the live speaker matches the enrolled user and the audio
isn't synthetic/replayed. This package's ``gate`` module is the pure admission
decision; the ECAPA speaker match (reuse the encrypted voiceprint, ADR-012) and the
anti-spoof model are lazy behind the ``voiceguard`` extra. EXPERIMENTAL, OFF by default.
"""
